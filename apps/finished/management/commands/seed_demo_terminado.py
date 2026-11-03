"""Ingreso de producto terminado de demostración (HU 6.2).

    python manage.py seed_demo_terminado     # requiere antes seed_demo_calidad (una inspección de demostración)

Ingresa al inventario final las aptas de la inspección de demostración de calidad con las mismas reglas de la aplicación
(`services.register_entry`): las reparte entre las tallas del lote (o, si el lote no trae desglose, entre las primeras
variantes de su referencia) y deja el movimiento en el libro. La inspección de otros lotes queda sin ingresar para hacerlo en
vivo. Es idempotente: una inspección ya ingresada no se repite. Solo con DJANGO_DEBUG=true.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from apps.production.models import LoteTalla
from apps.quality.models import Inspeccion
from apps.references.models import Variante

from ... import services
from ...models import IngresoTerminado

MARKER = "Ingreso de demostración"
SPREAD = 3  # tallas entre las que se reparten las aptas cuando el lote no trae desglose


class Command(BaseCommand):
    """Comando de gestión: ingresa al inventario final las aptas de la inspección de demostración (solo con `DJANGO_DEBUG=true`)."""
    help = "Ingresa al inventario final las aptas de la inspección de demostración de calidad (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        users = get_user_model().objects.filter(is_active=True)
        clerk = users.filter(role_id="SECRETARIA").first() or users.filter(role_id="ADMIN").first() or users.first()
        if clerk is None:
            raise CommandError("No hay usuarios: crea uno primero (por ejemplo con seed_admin).")
        pending = services.pending_entries().filter(observaciones="Inspección de demostración")
        created = 0
        for inspection in pending:
            created += self._enter(inspection, clerk)
        if not pending and not IngresoTerminado.objects.filter(observaciones=MARKER).exists():
            self.stdout.write("No hay una inspección de demostración por ingresar: corre antes seed_demo_calidad.")
        self.stdout.write(self.style.SUCCESS(f"Ingresos nuevos de producto terminado: {created}."))

    def _enter(self, inspection, clerk):
        lot = inspection.lote
        planned = list(LoteTalla.objects.filter(lote=lot).order_by("id"))
        variants = [row.variante_id for row in planned] or list(
            Variante.objects.filter(referencia_id=lot.orden.referencia_id).order_by("id").values_list("id", flat=True)[:SPREAD]
        )
        if not variants:
            self.stdout.write(f"La referencia de {lot.codigo} no tiene variantes: no se ingresó.")
            return 0
        share, extra = divmod(inspection.aptas, len(variants))
        lines = [
            {"variante": variant_id, "cantidad": share + (1 if index < extra else 0)} for index, variant_id in enumerate(variants)
            if share + (1 if index < extra else 0) > 0
        ]
        try:
            services.register_entry(
                user=clerk, inspeccion_id=inspection.id, lineas=lines, ubicacion="Estante demostración", observaciones=MARKER,
            )
        except ValidationError as error:
            self.stdout.write(f"No se ingresó {inspection.codigo}: {error.detail}")
            return 0
        return 1
