"""Guías de envío de demostración (HU 7.2).

    python manage.py seed_demo_envios     # idempotente; solo con DJANGO_DEBUG=true; requiere antes seed_demo_ventas y stock de producto terminado

Deja la demo lista **sin llamar a Track123 ni gastar cuota**:
- Las tres guías reales de Interrapidísimo del PO (700187211301, 700180879081, 700200165317) quedan ENTREGADAS con la respuesta real de la
  transportadora guardada (`fixtures/track123_entregadas.json`). Si las facturas demo de la HU 7.3 traen guías ficticias, se reemplazan.
- Guías **sintéticas** (marcadas como tales) para ver todo el semáforo: una por despachar, dos en tránsito en la relación RD, una con novedad,
  una devuelta con su flete y una factura sin guía. Además deja historial de cartera: una guía entregada y cobrada (suma al saldo financiero)
  y una devolución ya registrada (reingresa el stock).
"""
import json
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.finished.models import StockTerminado
from apps.sales import catalog as sales_catalog
from apps.sales import invoicing
from apps.sales.models import Cliente, FacturaVenta, PrecioReferencia

from ... import catalog, services, tracking
from ...models import Guia

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "track123_entregadas.json"
REAL = ["700187211301", "700180879081", "700200165317"]
FAKE_FROM_SALES_SEED = {"70001829102", "0284719283", "GUIA-CUC-991"}  # las ficticias de la siembra de la HU 7.3
NAMESPACE = uuid.UUID("5f4dcc3b-5aa7-4c3e-9f33-7a1d9b2e0a11")


def token(label):
    return uuid.uuid5(NAMESPACE, f"seed-envios-{label}")


class Command(BaseCommand):
    """Comando de gestión: guías de demostración con el semáforo completo (solo con `DJANGO_DEBUG=true`)."""
    help = "Registra guías de demostración: las 3 reales entregadas (sin gastar cuota) y otras sintéticas para ver el semáforo (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        User = get_user_model()
        seller = User.objects.filter(is_active=True, role_id="VENDEDOR").first() or User.objects.filter(is_active=True).first()
        storekeeper = User.objects.filter(is_active=True, role_id="ALMACENISTA").first() or seller
        if seller is None:
            raise CommandError("No hay usuarios: crea uno primero (por ejemplo con seed_admin).")
        clients = list(Cliente.objects.filter(activo=True).order_by("id"))
        variants = list(
            StockTerminado.objects.filter(cantidad__gte=2, variante__referencia__in=PrecioReferencia.objects.values("referencia"))
            .select_related("variante").order_by("-cantidad", "variante_id")
        )
        if not clients or not variants:
            raise CommandError("Faltan clientes, precios o stock de producto terminado: corre antes seed_demo_ventas y deja stock en Producto Terminado.")
        results = json.loads(FIXTURE.read_text(encoding="utf-8"))["guias"]
        counter = {"n": 0}

        def invoice(label, carrier="", number=""):
            """Emite una factura de demostración; con el mismo `label` repite sin duplicar."""
            counter["n"] += 1
            existing = FacturaVenta.objects.filter(observaciones=f"Demo envíos: {label}").first()
            if existing:
                return existing
            stock = variants[counter["n"] % len(variants)]
            customer = clients[counter["n"] % len(clients)]
            return invoicing.issue_invoice(
                user=seller, cliente=customer.id, lineas=[{"variante": stock.variante_id, "cantidad": 1, "descuento_pct": 0}], token=token(label),
                transportadora=carrier, numero_guia=number, observaciones=f"Demo envíos: {label}",
            )

        # 1) Las tres guías reales, ENTREGADAS con su respuesta guardada.
        legacy = list(FacturaVenta.objects.filter(numero_guia__in=FAKE_FROM_SALES_SEED).order_by("id"))
        made = 0
        for index, number in enumerate(REAL):
            if Guia.objects.filter(transportadora="INTERRAPIDISIMO", numero_guia=number, vigente=True).exists():
                guide = Guia.objects.get(transportadora="INTERRAPIDISIMO", numero_guia=number, vigente=True)
            else:
                target = legacy[index] if index < len(legacy) else invoice(f"real-{number}")
                if target.estado_cobro != sales_catalog.COLLECT_PENDING or target.estado != sales_catalog.STATUS_ISSUED:
                    continue
                guide = services.assign_guide_to(target, "INTERRAPIDISIMO", number, seller)
                made += 1
            result = next((r for r in results if r["trackNo"] == number), None)
            if result and guide.estado == catalog.PENDING:
                now = timezone.now()
                guide.rastreo_registrado, guide.rastreo_sintetico = True, False
                guide.rastreo_estado, guide.rastreo_subestado = result.get("transitStatus", ""), result.get("transitSubStatus", "") or ""
                guide.rastreo_respuesta, guide.rastreo_consultado_en = result, now
                guide.rastreo_proxima_consulta = now + timedelta(minutes=settings.TRACK123_COOLDOWN_MINUTES)
                guide.save()
                when = tracking.parse_time(result.get("deliveredTime"))
                services.advance_to(guide, catalog.DELIVERED, tracking.describe(result), catalog.ORIGIN_TRACK123, None, when)

        # 2) Guías sintéticas para ver el semáforo completo.
        def synthetic(label, number, carrier="ENVIA"):
            existing = Guia.objects.filter(numero_guia=number, vigente=True).first()
            if existing:
                return existing
            guide = services.assign_guide_to(invoice(label), carrier, number, seller)
            guide.rastreo_sintetico = True
            guide.save(update_fields=["rastreo_sintetico", "updated_at"])
            return guide

        pending = synthetic("por-despachar", "ENV-DEMO-0001")
        a, b = synthetic("en-transito-1", "ENV-DEMO-0002"), synthetic("en-transito-2", "ENV-DEMO-0003")
        incident, returned = synthetic("novedad", "OTR-DEMO-0004", "OTRA"), synthetic("devuelta", "OTR-DEMO-0005", "OTRA")
        if a.estado == catalog.PENDING and b.estado == catalog.PENDING:
            services.create_dispatch(user=storekeeper, carrier="ENVIA", guide_ids=[a.id, b.id], token=token("rd-envia"), responsible="Bodega",
                                     notes="Recogida de la tarde")
        if incident.estado == catalog.PENDING and returned.estado == catalog.PENDING:
            services.create_dispatch(user=storekeeper, carrier="OTRA", guide_ids=[incident.id, returned.id], token=token("rd-otra"), responsible="Bodega")
        incident.refresh_from_db()
        returned.refresh_from_db()
        if incident.estado == catalog.IN_TRANSIT:
            services.change_state(guide_id=incident.id, new_state=catalog.INCIDENT, note="Dirección errada: la transportadora no localiza al cliente", user=storekeeper)
        if returned.estado == catalog.IN_TRANSIT:
            services.change_state(guide_id=returned.id, new_state=catalog.RETURNED, note="El destinatario rechazó el paquete", user=storekeeper)
            services.register_freight(guide_id=returned.id, value=12_000, user=storekeeper)

        # 3) Historial de cartera: una guía entregada y cobrada (suma al saldo) y una devolución ya registrada (reingresa el stock).
        paid = synthetic("pagada", "ENV-DEMO-0006")
        if paid.estado == catalog.PENDING:
            services.advance_to(paid, catalog.DELIVERED, "Entregada y recaudada (demostración)", catalog.ORIGIN_MANUAL, storekeeper)
        if paid.factura.estado_cobro == sales_catalog.COLLECT_PENDING:
            invoicing.reconcile_collection(user=seller, factura_id=paid.factura_id, nuevo_estado=sales_catalog.COLLECT_PAID, observaciones="Giro de la transportadora (demostración)")
        back = synthetic("devolucion-registrada", "OTR-DEMO-0007", "OTRA")
        if back.estado == catalog.PENDING:
            services.advance_to(back, catalog.RETURNED, "El cliente no recibió el pedido (demostración)", catalog.ORIGIN_MANUAL, storekeeper)
            services.register_freight(guide_id=back.id, value=9_000, user=storekeeper)
        back.refresh_from_db()
        if back.factura.estado_cobro == sales_catalog.COLLECT_PENDING:
            services.return_to_stock(guide_id=back.id, user=storekeeper)

        # 4) Una factura sin guía, para ver la cola «por despachar / sin guía».
        invoice("sin-guia")
        self.stdout.write(self.style.SUCCESS(
            f"Guías reales asignadas: {made}. Guías sintéticas por despachar: {pending.estado == catalog.PENDING}. Facturas sin guía: {services.invoices_without_guide().count()}."
        ))
