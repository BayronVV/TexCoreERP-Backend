"""Clientes y precios de demostración para ventas (HU 7.1).

    python manage.py seed_demo_ventas     # idempotente; solo con DJANGO_DEBUG=true

Registra cuatro clientes de distintos tipos y el costo de fábrica y los precios (antes de IVA) de las referencias de demostración,
con margen consistente: mayorista ≈ costo × 1,45 y detal ≈ costo × 1,90. Son valores de demostración: el Gerente los corrige en la
pantalla de precios. No crea facturas, para hacerlas en vivo. Una referencia que ya tiene precio no se toca.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory.services import next_code
from apps.references.models import Referencia

from ... import catalog
from ...models import Cliente, PrecioReferencia

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
        self.stdout.write(self.style.SUCCESS(f"Clientes nuevos: {clients}. Referencias con precio nuevo: {priced}."))
