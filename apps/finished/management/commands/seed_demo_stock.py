"""Stock inicial de producto terminado de demostración, por talla y color.

    python manage.py seed_demo_stock     # idempotente; solo con DJANGO_DEBUG=true

Deja entre 12 y 20 unidades en cada talla y color de las referencias activas, para poder vender en la demostración. Pasa por la misma
regla de la aplicación que el ajuste manual (HU 6.3): una corrección por referencia con motivo «Sobrante o hallazgo», que deja su
comprobante `AJT` y su movimiento en el libro. Solo sube las variantes que están por debajo de su meta: lo que ya tiene más, no se toca.
"""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from apps.references import catalog as reference_catalog
from apps.references.models import Referencia, Variante

from ... import adjustments
from ...models import StockTerminado

NOTE = "Inventario inicial de demostración: unidades por talla y color para la demo de ventas."


def target(variant_id):
    """Meta de unidades por variante: entre 12 y 20, repartida de forma estable."""
    return 12 + (variant_id * 7) % 9


class Command(BaseCommand):
    """Comando de gestión: siembra el stock inicial por talla y color (solo con `DJANGO_DEBUG=true`)."""
    help = "Deja unidades en cada talla y color de las referencias activas mediante ajustes (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        users = get_user_model().objects.filter(is_active=True)
        clerk = users.filter(role_id="SECRETARIA").first() or users.filter(role_id="ADMIN").first() or users.first()
        if clerk is None:
            raise CommandError("No hay usuarios: crea uno primero (por ejemplo con seed_admin).")
        references = adjusted = 0
        for reference in Referencia.objects.filter(estado=reference_catalog.ACTIVE).order_by("codigo"):
            lines = []
            for variant in Variante.objects.filter(referencia=reference).order_by("id"):
                before = StockTerminado.objects.filter(variante=variant).values_list("cantidad", flat=True).first() or 0
                if target(variant.id) > before:
                    lines.append({"variante": variant.id, "esperado": before, "contado": target(variant.id)})
            if not lines:
                continue
            try:
                adjustments.adjust_stock(user=clerk, motivo="SOBRANTE", observacion=NOTE, lineas=lines, token=uuid.uuid4())
            except ValidationError as error:
                self.stdout.write(f"No se ajustó {reference.codigo}: {error.detail}")
                continue
            references += 1
            adjusted += len(lines)
        self.stdout.write(self.style.SUCCESS(f"Referencias con stock nuevo: {references}. Tallas y colores ajustados: {adjusted}."))
