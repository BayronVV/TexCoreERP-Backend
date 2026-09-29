"""Crea el catálogo mínimo de inventario para desarrollo. Es idempotente.

    python manage.py seed_inventario

Solo crea productos que no existan (por nombre y tipo) y les registra un
ingreso inicial para que el kardex explique el saldo. No toca los existentes.
"""
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.inventory import catalog, services
from apps.inventory.models import Movimiento, Producto

# (nombre, tipo, unidad, saldo inicial, mínimo)
CATALOG = [
    ("Tela denim 12 oz", catalog.RAW_MATERIAL, "m", "1200", "300"),
    ("Hilo poliéster", catalog.RAW_MATERIAL, "kg", "40", "10"),
    ("Cierre metálico", catalog.SUPPLY, "unidad", "600", "150"),
    ("Botón metálico", catalog.SUPPLY, "unidad", "900", "200"),
    ("Remache", catalog.SUPPLY, "unidad", "1500", "400"),
    ("Etiqueta de marca", catalog.SUPPLY, "unidad", "700", "200"),
    ("Pantalón genérico", catalog.GENERIC_PANTS, "unidad", "0", "0"),
    ("MOD-SKINNY 5 BOTONES V2", catalog.FINISHED_PANTS, "unidad", "0", "0"),
]


class Command(BaseCommand):
    help = "Crea productos de ejemplo para desarrollo (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        created = 0
        for name, kind, unit, stock, minimum in CATALOG:
            if Producto.objects.filter(tipo=kind, nombre__iexact=name).exists():
                continue
            product = services.create_product(nombre=name, tipo=kind, unidad=unit, stock_minimo=Decimal(minimum))
            if Decimal(stock) > 0:
                Movimiento.objects.create(
                    producto=product, tipo=catalog.ENTRY, motivo=catalog.REASON_PURCHASE,
                    cantidad=Decimal(stock), stock_antes=0, stock_despues=Decimal(stock),
                    fecha=timezone.localdate(), proveedor="Saldo inicial de desarrollo", lote="INICIAL",
                )
                product.stock_actual = Decimal(stock)
                product.save(update_fields=["stock_actual", "updated_at"])
            created += 1
        self.stdout.write(self.style.SUCCESS(f"Productos creados: {created}."))
