"""Catálogo de defectos y lotes de demostración para la inspección de calidad (HU 6.1).

    python manage.py seed_demo_calidad     # requiere antes seed_demo_produccion (órdenes y lotes en planta)

Crea los defectos típicos de un jean (costura, tono, mancha, medida, botón o remache) y devuelve de lavandería dos lotes de
las órdenes de demostración con las mismas reglas de la aplicación (`create_laundry_remission` y `create_laundry_reception`):
el primero queda **inspeccionado** (con marras de dos defectos) y el segundo **pendiente**, para inspeccionarlo en vivo.
Usa un proveedor de lavandería y una receta existentes (o los crea si faltan). Es idempotente: no repite defectos, y los
lotes de demostración se reconocen por el texto de sus observaciones. Solo con DJANGO_DEBUG=true.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Proveedor
from apps.production import catalog as production_catalog
from apps.production.models import Lote, RecepcionLavanderia, RecetaLavado, RemisionLavanderia
from apps.production.recepcion_services import create_laundry_reception
from apps.production.remisiones_services import create_laundry_remission

from ... import services
from ...models import Inspeccion, TipoDefecto

DEFECTS = [
    ("Costura floja o puntada saltada", "Costura abierta, floja o con puntadas saltadas", True),
    ("Botón o remache mal puesto", "Botón o remache suelto, torcido o faltante", True),
    ("Mancha removible", "Mancha superficial que sale con un nuevo lavado o limpieza", True),
    ("Hilos sueltos o sin rematar", "Hilos sobrantes que se cortan o rematan", True),
    ("Variación de tono", "Diferencia de tono dentro de la prenda o frente al estándar", False),
    ("Mancha permanente", "Mancha de químico, grasa u óxido que no se puede quitar", False),
    ("Rotura o desgaste de tela", "Rotura, desgarro o desgaste excesivo de la tela", False),
    ("Medida fuera de tolerancia", "Encogimiento o medida fuera de la tolerancia de la ficha", False),
]
MARKER = "Remisión de demostración de calidad"
DEMO_LOTS = 2  # el primero se inspecciona y el segundo queda pendiente


class Command(BaseCommand):
    """Comando de gestión: siembra defectos y lotes devueltos de lavandería (solo con `DJANGO_DEBUG=true`)."""
    help = "Crea defectos típicos y dos lotes devueltos de lavandería, uno inspeccionado y otro pendiente (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        users = get_user_model().objects.filter(is_active=True)
        operator = users.filter(role_id="PRODUCCION").first() or users.first()
        if operator is None:
            raise CommandError("No hay usuarios: crea uno primero (por ejemplo con seed_admin).")
        inspector = users.filter(role_id="TERMINACION").first() or operator

        defects = self._defects()
        lots = self._returned_lots(operator)
        inspected = self._inspect_first(lots, inspector, defects)
        self.stdout.write(self.style.SUCCESS(
            f"Defectos nuevos: {defects['nuevos']}. Lotes devueltos de lavandería: {len(lots['nuevos'])}. Inspecciones nuevas: {inspected}."
        ))

    def _defects(self):
        by_name, created = {}, 0
        for name, description, fixable in DEFECTS:
            defect = TipoDefecto.objects.filter(nombre__iexact=name).first()
            if defect is None:
                defect = services.create_defect(nombre=name, descripcion=description, corregible=fixable)
                created += 1
            by_name[name] = defect
        return {"por_nombre": by_name, "nuevos": created}

    def _provider_and_recipe(self):
        provider = Proveedor.objects.filter(categoria=inventory_catalog.CAT_LAUNDRY).first()
        if provider is None:
            provider = Proveedor.objects.create(
                nit="900543210", nit_dv="4", razon_social="Lavandería Industrial El Cóndor S.A.S.", categoria=inventory_catalog.CAT_LAUNDRY,
                contacto="Gustavo Mejía", telefono="3114567890", ciudad="Itagüí", direccion="Zona Industrial",
            )
        recipe = RecetaLavado.objects.first() or RecetaLavado.objects.create(codigo="REC-DEMO-01", nombre="Stone wash medio", duracion_horas=24)
        return provider, recipe

    def _returned_lots(self, operator):
        """Envía a lavandería y recibe de vuelta hasta dos lotes en planta; los ya sembrados se reconocen por la remisión."""
        done = list(RemisionLavanderia.all_objects.filter(observaciones=MARKER).order_by("id"))
        lots = [
            row.lotes_detalle.first().lote for row in done
            if row.lotes_detalle.exists() and not self._annulled(row.lotes_detalle.first().lote)
        ]
        created = []
        if len(lots) >= DEMO_LOTS:
            return {"todos": lots, "nuevos": created}
        provider, recipe = self._provider_and_recipe()
        candidates = (
            Lote.objects.filter(estado_inventario=production_catalog.LOT_INV_INTERNAL, cantidad__gte=10)
            .exclude(orden__orden_salida__estado=inventory_catalog.STATUS_CANCELLED).exclude(recepciones_lavado__isnull=False).exclude(pk__in=[lot.pk for lot in lots]).order_by("orden_id", "numero")
        )
        today = timezone.localdate()
        for lot in candidates:
            if len(lots) + len(created) >= DEMO_LOTS:
                break
            try:
                remission = create_laundry_remission(
                    user=operator, lavanderia_id=provider.id, fecha_emision=today, transportador_nombre="Transportes Aburrá",
                    vehiculo_placa="DEM-123", tulas_bultos=1, peso_kg=20, observaciones=MARKER,
                    lotes_seleccionados=[{"lote_id": lot.id, "cantidad": lot.cantidad, "receta_id": recipe.codigo, "instrucciones_especiales": ""}],
                )
                row = RemisionLavanderia.objects.get(codigo=remission["codigo"]).lotes_detalle.first()
                create_laundry_reception(
                    user=operator, remision_id=row.remision_id, fecha_recepcion=today, observaciones="Recepción de demostración de calidad",
                    lotes_recibidos=[{
                        "remision_lote_id": row.id, "cantidad_recibida_conforme": lot.cantidad - 1, "cantidad_merma": 1,
                        "motivo_merma": "Extravío en tinas", "cantidad_danada": 0, "costo_unitario_prenda": "30000.00",
                    }],
                )
            except ValidationError as error:
                self.stdout.write(f"No se devolvió {lot.codigo}: {error.detail}")
                continue
            created.append(Lote.objects.get(pk=lot.pk))
        if not lots and not created:
            self.stdout.write("No hay lotes en planta de 10 prendas o más: corre antes seed_demo_produccion.")
        return {"todos": lots + created, "nuevos": created}

    @staticmethod
    def _annulled(lot):
        return lot.orden.orden_salida.estado == inventory_catalog.STATUS_CANCELLED

    def _inspect_first(self, lots, inspector, defects):
        """Inspecciona el primer lote devuelto con marras de dos defectos; el siguiente queda pendiente."""
        if not lots["todos"]:
            return 0
        lot = lots["todos"][0]
        if Inspeccion.objects.filter(lote=lot).exists():
            return 0
        received = RecepcionLavanderia.objects.filter(lotes_detalle__lote=lot).first().lotes_detalle.get(lote=lot).cantidad_recibida_conforme
        seams, stains = 2, 1
        if received <= seams + stains:
            return 0
        names = list(defects["por_nombre"])
        services.register_inspection(
            user=inspector, lote_id=lot.id, aptas=received - seams - stains, observaciones="Inspección de demostración",
            defectos=[
                {"defecto": defects["por_nombre"][names[0]].id, "cantidad": seams, "nota": "Pretina y bolsillo trasero"},
                {"defecto": defects["por_nombre"][names[5]].id, "cantidad": stains, "nota": ""},
            ],
        )
        return 1
