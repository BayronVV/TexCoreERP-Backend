"""Crea proveedores y catálogo de ejemplo para desarrollo. Es idempotente.

    python manage.py seed_inventario

Crea lo que falte (por NIT y por nombre/categoría) y, en productos que ya existen, solo
completa datos vacíos (ancho útil, composición, color). No toca existencias ni nada que
ya tenga valor. Los productos nuevos reciben un ingreso inicial para que el kardex explique
su saldo.
"""
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.inventory import catalog, services
from apps.inventory.models import Movimiento, Producto, Proveedor

# (NIT, razón social, categoría, contacto, teléfono, correo, ciudad, dirección)
SUPPLIERS = [
    ("890.900.001-4", "Coltejer Denim & Colors", catalog.CAT_FABRIC, "Claudia Morales", "315 678 1234",
     "cmorales@coltejer.com.co", "Cúcuta", "Zona Industrial La Fría"),
    ("890.900.123-1", "Fabricato Textil S.A.", catalog.CAT_FABRIC, "Guillermo Restrepo", "310 455 8899",
     "ventas@fabricato.com", "Medellín", "Km 2 Vía Medellín - Bello"),
    ("890.100.234-5", "Hilos Coats Cadena Colombia", catalog.CAT_THREAD, "Jorge Quintero", "312 789 4561",
     "servicioalcliente@coatscadena.com", "Bogotá", "Av. Américas 45-20"),
    ("860.001.234-9", "Corporación Cierres Eka Ltda.", catalog.CAT_ZIPPER, "Hernán Botero", "320 987 6543",
     "pedidos@eka-cierres.com", "Bogotá", "Calle 15 # 24-80"),
    ("900.234.567-8", "Herrajes & Botones Andinos S.A.S.", catalog.CAT_BUTTON, "Milena Jaimes", "318 444 5566",
     "ventas@herrajesandinos.com", "Cali", "Carrera 8 # 12-30"),
    ("900.789.012-3", "Marquillas & Empaques Jacron Tex", catalog.CAT_LABEL, "Diana Cárdenas", "313 222 3344",
     "diana@jacrontex.com", "Medellín", "Calle 50 # 40-15"),
]

# (nombre, categoría, unidad, saldo inicial, mínimo, ancho útil, color, composición)
PRODUCTS = [
    ("Tela denim 12 oz", catalog.CAT_FABRIC, "m", "1200", "300", "1.55", "Azul índigo", "98% algodón / 2% elastano"),
    ("Denim rígido negro 14 oz", catalog.CAT_FABRIC, "m", "800", "200", "1.65", "Negro", "100% algodón"),
    ("Hilo poliéster", catalog.CAT_THREAD, "kg", "40", "10", None, "Azul", "100% poliéster"),
    ("Cierre metálico", catalog.CAT_ZIPPER, "unidad", "600", "150", None, "Níquel", ""),
    ("Botón metálico", catalog.CAT_BUTTON, "unidad", "900", "200", None, "Cobre envejecido", ""),
    ("Remache", catalog.CAT_BUTTON, "unidad", "1500", "400", None, "Cobre", ""),
    ("Etiqueta de marca", catalog.CAT_LABEL, "unidad", "700", "200", None, "", ""),
    ("Pantalón genérico", catalog.CAT_GENERIC, "unidad", "0", "0", None, "", ""),
    ("MOD-SKINNY 5 BOTONES V2", catalog.CAT_FINISHED, "unidad", "0", "0", None, "", ""),
]


class Command(BaseCommand):
    help = "Crea proveedores y catálogo de ejemplo para desarrollo (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")

        new_suppliers = 0
        for nit, name, category, contact, phone, email, city, address in SUPPLIERS:
            body, _ = services.normalize_nit(nit)
            if Proveedor.objects.filter(nit=body).exists():
                continue
            services.save_supplier(
                nit=nit, razon_social=name, categoria=category, contacto=contact, telefono=phone,
                correo=email, ciudad=city, direccion=address,
            )
            new_suppliers += 1

        new_products = 0
        for name, category, unit, stock, minimum, width, color, composition in PRODUCTS:
            existing = Producto.objects.filter(categoria=category, nombre__iexact=name).first()
            if existing:
                self._fill_blanks(existing, width, color, composition)
                continue
            product = services.create_product(
                nombre=name, categoria=category, unidad=unit, stock_minimo=Decimal(minimum),
                ancho_util=Decimal(width) if width else None, color=color, composicion=composition,
            )
            if Decimal(stock) > 0:
                Movimiento.objects.create(
                    producto=product, tipo=catalog.ENTRY, motivo=catalog.REASON_PURCHASE,
                    cantidad=Decimal(stock), stock_antes=0, stock_despues=Decimal(stock),
                    fecha=timezone.localdate(), proveedor_nombre="Saldo inicial de desarrollo", lote="INICIAL",
                )
                product.stock_actual = Decimal(stock)
                product.save(update_fields=["stock_actual", "updated_at"])
            new_products += 1
        self.stdout.write(self.style.SUCCESS(f"Proveedores creados: {new_suppliers}. Productos creados: {new_products}."))

    @staticmethod
    def _fill_blanks(product, width, color, composition):
        changed = []
        if width and product.ancho_util is None:
            product.ancho_util = Decimal(width)
            changed.append("ancho_util")
        if color and not product.color:
            product.color = color
            changed.append("color")
        if composition and not product.composicion:
            product.composicion = composition
            changed.append("composicion")
        if changed:
            product.save(update_fields=changed + ["updated_at"])
