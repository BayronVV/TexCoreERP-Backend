"""Órdenes de producción de demostración (HU 4.2): con lotes y tallas por lote, sobre las referencias demo.

    python manage.py seed_demo_produccion     # requiere antes seed_demo_inventario (catálogo, stock y referencias)

Pasa por la misma regla que usa la aplicación (`services.create_production_order`), así que descuenta el material de
la ficha y deja el kardex coherente. Es idempotente: una orden ya sembrada no se repite (se reconoce por su
observación). Si el stock no alcanza o falta la ficha, la orden se omite en lugar de fallar. Solo con DJANGO_DEBUG=true.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.inventory.models import OrdenSalida, Producto
from apps.references.models import Referencia, Variante

from ... import services

# `lotes`: (prendas del lote, cuántas de las primeras variantes de la referencia lleva). La cantidad se reparte en
# partes casi iguales entre esas variantes; `None` deja el lote sin tallas.
ORDERS = [
    {
        "key": "OPL-DEMO-CLASICO", "referencia": "Clásico 5 bolsillos frosteado", "resultado": "Pantalón genérico rígido",
        "prendas": 80, "dias": 3, "responsable": "Marta Ruiz (producción)",
        "lotes": [(30, 3), (30, 2), (20, None)],
    },
    {
        "key": "OPL-DEMO-MOM", "referencia": "Mom vintage tiro alto", "resultado": "Pantalón genérico stretch",
        "prendas": 40, "dias": 1, "responsable": "Jorge Santos (corte)",
        "lotes": [(25, 2), (15, None)],
    },
]


def spread(quantity, parts):
    """Reparte `quantity` en `parts` cantidades casi iguales que suman justo `quantity` (el resto, a las primeras)."""
    base, extra = divmod(quantity, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


class Command(BaseCommand):
    help = "Crea órdenes de producción de demostración con lotes y tallas (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        users = get_user_model().objects.filter(is_active=True)
        user = users.filter(role_id="PRODUCCION").first() or users.first()
        if user is None:
            raise CommandError("No hay usuarios: crea uno primero (por ejemplo con seed_admin).")
        created = sum(self._order(user, spec) for spec in ORDERS)
        self.stdout.write(self.style.SUCCESS(f"Órdenes de producción nuevas: {created}."))

    def _order(self, user, spec):
        marker = f"Orden de demostración {spec['key']}"
        if OrdenSalida.objects.filter(observaciones=marker).exists():
            return 0
        reference = Referencia.objects.filter(nombre__iexact=spec["referencia"]).first()
        result = next((p for p in Producto.objects.all() if p.nombre.casefold() == spec["resultado"].casefold()), None)
        if reference is None or result is None:
            self.stdout.write(f"Omitida {spec['key']}: falta la referencia o el pantalón genérico (corre seed_demo_inventario).")
            return 0
        variants = list(Variante.objects.filter(referencia=reference).order_by("id"))
        lots = []
        for size, sizes_count in spec["lotes"]:
            lot = {"cantidad": size}
            if sizes_count and len(variants) >= sizes_count:
                amounts = spread(size, sizes_count)
                lot["tallas"] = [{"variante": variants[i].id, "cantidad": amounts[i]} for i in range(sizes_count)]
            lots.append(lot)
        try:
            services.create_production_order(
                user=user, referencia_id=reference.id, cantidad=spec["prendas"], producto_resultado_id=result.id,
                lotes=lots, fecha_salida=timezone.localdate() - timedelta(days=spec["dias"]),
                responsable=spec["responsable"], observaciones=marker,
            )
        except ValidationError as error:
            first = next(iter(error.detail.values()))
            self.stdout.write(f"Omitida {spec['key']}: {first[0] if isinstance(first, list) else first}")
            return 0
        return 1
