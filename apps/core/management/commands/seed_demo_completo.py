"""Siembra de demostración completa: deja datos de trabajo en todos los módulos.

    python manage.py seed_demo_completo                            # desarrollo (DJANGO_DEBUG=true)
    python manage.py seed_demo_completo --permitir-produccion      # contra la base de producción (datos SIMULADOS de la demostración)

Encadena, en el orden en que dependen unos de otros, los comandos `seed_demo_*` de cada módulo:
inventario → producción → recursos → tarifas → compras → calidad → producto terminado → stock por talla y color → ventas → envíos.
Es idempotente: un módulo que ya tiene datos se salta (sin duplicarlos) y los pasos que se pueden repetir (stock, ventas, envíos) solo
completan lo que falta. Al final imprime cuántos registros tiene cada módulo y falla si alguno quedó vacío.

Los comandos `seed_demo_*` se niegan a correr con DJANGO_DEBUG=false a propósito. Aquí la bandera `--permitir-produccion` lo permite solo
durante esta corrida, y solo para este comando: la base de la demostración es la misma de desarrollo y producción y sus datos son simulados.
No borra nada ni toca usuarios, roles ni permisos. En Render se puede disparar sola al arrancar con SEED_DEMO_ON_DEPLOY=true (ver
docs/despliegue-render.md).
"""
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings


def _model(path):
    module, name = path.rsplit(".", 1)
    return getattr(__import__(module, fromlist=[name]), name)


# (módulo, comando, modelo que indica que el módulo ya tiene datos, ¿saltar si ya los tiene?)
STEPS = [
    ("Inventario", "seed_demo_inventario", "apps.inventory.models.Producto", True),
    ("Producción", "seed_demo_produccion", "apps.production.models.OrdenProduccion", True),
    ("Recursos", "seed_demo_recursos", "apps.production.models.Operario", True),
    ("Tarifas de mano de obra", "seed_demo_tarifas", "apps.production.models.TarifaManoObra", True),
    ("Compras", "seed_demo_compras", "apps.purchasing.models.OrdenCompra", True),
    ("Calidad", "seed_demo_calidad", "apps.quality.models.TipoDefecto", True),
    ("Producto terminado", "seed_demo_terminado", "apps.finished.models.IngresoTerminado", True),
    ("Stock por talla y color", "seed_demo_stock", "apps.finished.models.StockTerminado", False),
    ("Ventas", "seed_demo_ventas", "apps.sales.models.PrecioReferencia", False),
    ("Envíos", "seed_demo_envios", "apps.shipping.models.Guia", False),
]

# módulo → modelo que cuenta sus datos, para el informe final
REPORT = [
    ("Usuarios activos", "apps.users.models.CustomUser"),
    ("Productos de inventario", "apps.inventory.models.Producto"),
    ("Referencias de jean", "apps.references.models.Referencia"),
    ("Órdenes de producción", "apps.production.models.OrdenProduccion"),
    ("Lotes", "apps.production.models.Lote"),
    ("Operarios", "apps.production.models.Operario"),
    ("Tarifas de mano de obra", "apps.production.models.TarifaManoObra"),
    ("Remisiones de lavandería", "apps.production.models.RemisionLavanderia"),
    ("Órdenes de compra", "apps.purchasing.models.OrdenCompra"),
    ("Inspecciones de calidad", "apps.quality.models.Inspeccion"),
    ("Movimientos de producto terminado", "apps.finished.models.MovimientoTerminado"),
    ("Clientes", "apps.sales.models.Cliente"),
    ("Facturas", "apps.sales.models.FacturaVenta"),
    ("Movimientos de cartera", "apps.sales.models.MovimientoCartera"),
    ("Guías de envío", "apps.shipping.models.Guia"),
    ("Relaciones de despacho", "apps.shipping.models.RelacionDespacho"),
]


class Command(BaseCommand):
    """Comando de gestión: siembra de demostración de todos los módulos (con `DJANGO_DEBUG=true` o `--permitir-produccion`)."""
    help = "Deja datos de demostración en todos los módulos, en orden y sin duplicar."

    def add_arguments(self, parser):
        parser.add_argument("--permitir-produccion", action="store_true", help="Permite correr con DJANGO_DEBUG=false (datos simulados).")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["permitir_produccion"]:
            raise CommandError("Con DJANGO_DEBUG=false hay que pasar --permitir-produccion: es la siembra de datos SIMULADOS de la demostración.")
        with override_settings(DEBUG=True):  # los seed_demo_* exigen DEBUG; el permiso vale solo durante esta corrida
            for module, command, probe, skip_if_filled in STEPS:
                if skip_if_filled and _model(probe).objects.exists():
                    self.stdout.write(f"  · {module}: ya tiene datos, se salta.")
                    continue
                self.stdout.write(f"  → {module} ({command})")
                call_command(command, stdout=self.stdout)
        self.stdout.write("Datos por módulo:")
        empty = []
        for label, path in REPORT:
            manager = _model(path).objects
            count = manager.filter(is_active=True).count() if label == "Usuarios activos" else manager.count()
            self.stdout.write(f"  {label}: {count}")
            if count == 0:
                empty.append(label)
        if empty:
            raise CommandError("Quedaron módulos sin datos: " + ", ".join(empty))
        self.stdout.write(self.style.SUCCESS("Todos los módulos tienen datos de demostración."))
