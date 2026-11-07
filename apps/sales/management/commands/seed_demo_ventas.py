"""Clientes y precios de demostración para ventas (HU 7.1).

    python manage.py seed_demo_ventas     # idempotente; solo con DJANGO_DEBUG=true

Registra cuatro clientes de distintos tipos y el costo de fábrica y los precios (antes de IVA) de las referencias de demostración,
con margen consistente: mayorista ≈ costo × 1,45 y detal ≈ costo × 1,90. Son valores de demostración: el Gerente los corrige en la
pantalla de precios. No crea facturas, para hacerlas en vivo. Una referencia que ya tiene precio no se toca.
"""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.finished.models import StockTerminado
from apps.inventory.services import next_code
from apps.references.models import Referencia

from ... import catalog, invoicing
from ...models import Cliente, FacturaVenta, PrecioReferencia, SaldoFinanciero

# código de la referencia → (costo de fábrica, precio mayorista, precio detal)
PRICES = {
    "REF-0012": (47_000, 68_000, 89_900),
    "REF-0009": (50_000, 72_500, 94_900),
    "REF-0010": (53_000, 77_000, 99_900),
    "REF-0011": (53_000, 77_000, 99_900),
    "REF-0001": (50_000, 72_500, 94_900),
}

CLIENTS = [
    ("NIT", "900123456", "7", "Distribuciones El Jean S.A.S.", catalog.CLIENT_DISTRIBUTOR, "Bogotá", "Carrera 15 # 45-20", "3105551234"),
    ("NIT", "901234567", "1", "Moda Joven Medellín", catalog.CLIENT_WHOLESALE, "Medellín", "Calle 52 # 48-10", "3115559876"),
    ("NIT", "900765432", "4", "Boutique La 10", catalog.CLIENT_WHOLESALE, "Cali", "Avenida 6N # 23-45", "3125554321"),
    ("CC", "1032456789", "", "Carolina Pérez", catalog.CLIENT_DETAL, "Cúcuta", "Avenida 5 # 12-30", "3135556789"),
]


class Command(BaseCommand):
    """Comando de gestión: registra clientes y precios de demostración (solo con `DJANGO_DEBUG=true`)."""
    help = "Registra clientes y precios de demostración para ventas (solo con DJANGO_DEBUG=true)."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        clients = 0
        for kind, number, dv, name, client_type, city, address, phone in CLIENTS:
            if Cliente.objects.filter(tipo_documento=kind, documento=number).exists():
                continue
            Cliente.objects.create(
                codigo=next_code(catalog.CLIENT_PREFIX), tipo_documento=kind, documento=number, dv=dv, nombre=name, tipo=client_type,
                ciudad=city, direccion=address, telefono=phone,
            )
            clients += 1
        priced = 0
        for code, (cost, wholesale, retail) in PRICES.items():
            reference = Referencia.objects.filter(codigo=code).first()
            if reference is None or PrecioReferencia.objects.filter(referencia=reference).exists():
                continue
            PrecioReferencia.objects.create(referencia=reference, costo_fabrica=cost, precio_mayorista=wholesale, precio_detal=retail)
            priced += 1

        invoices_count = 0
        if FacturaVenta.objects.count() == 0:
            User = get_user_model()
            seller = User.objects.filter(role__name="Vendedor").first() or User.objects.first()
            stocks = list(StockTerminado.objects.filter(variante__referencia__codigo="REF-0001", cantidad__gte=5).select_related("variante")[:3])
            if stocks and len(stocks) >= 2:
                v1, v2 = stocks[0].variante, stocks[1].variante
                c1 = Cliente.objects.filter(tipo=catalog.CLIENT_WHOLESALE).first()
                c2 = Cliente.objects.filter(tipo=catalog.CLIENT_DISTRIBUTOR).first()
                c3 = Cliente.objects.filter(tipo=catalog.CLIENT_DETAL).first()

                if c1 and v1:
                    invoicing.issue_invoice(
                        user=seller, cliente=c1.id,
                        lineas=[{"variante": v1.id, "cantidad": 2, "descuento_pct": 5}],
                        transportadora="INTERRAPIDISIMO", numero_guia="70001829102",
                        observaciones="Despacho urgente a Medellín", token=uuid.uuid4(),
                    )
                    invoices_count += 1

                if c2 and v2:
                    invoicing.issue_invoice(
                        user=seller, cliente=c2.id,
                        lineas=[{"variante": v2.id, "cantidad": 3, "descuento_pct": 10}],
                        transportadora="ENVIA", numero_guia="0284719283",
                        observaciones="Envío contraentrega a bodega central", token=uuid.uuid4(),
                    )
                    invoices_count += 1

                if c3 and v1:
                    invoicing.issue_invoice(
                        user=seller, cliente=c3.id,
                        lineas=[{"variante": v1.id, "cantidad": 1, "descuento_pct": 0}],
                        transportadora="OTRA", numero_guia="GUIA-CUC-991",
                        observaciones="Entrega local en tienda", token=uuid.uuid4(),
                    )
                    invoices_count += 1

        SaldoFinanciero.objects.get_or_create(nombre="Caja General", defaults={"saldo_actual": 0})
        self.stdout.write(self.style.SUCCESS(f"Clientes nuevos: {clients}. Referencias con precio nuevo: {priced}. Facturas demo creadas: {invoices_count}."))
