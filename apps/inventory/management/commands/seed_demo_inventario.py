"""Datos de demostración del inventario: proveedores, catálogo con fotos, compras y órdenes.

    python manage.py seed_inventario          # base mínima (opcional, este comando la incluye)
    python manage.py seed_demo_inventario     # catálogo completo e historial conectado

Todo pasa por las mismas reglas que usa la aplicación (`services`), así que el kardex, los
saldos, las alertas y las órdenes quedan coherentes entre sí: cada producto nuevo recibe
compras de uno o varios proveedores de su categoría, y varias órdenes de producción y
lavandería consumen esos insumos y devuelven pantalones al inventario. Es idempotente: lo que
ya existe no se vuelve a crear. Solo funciona con DJANGO_DEBUG=true.
"""
import struct
import zlib
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.inventory import catalog, services
from apps.inventory.models import Movimiento, OrdenSalida, Producto, Proveedor

T, H, C, B, E, Q, O = (
    catalog.CAT_FABRIC, catalog.CAT_THREAD, catalog.CAT_ZIPPER, catalog.CAT_BUTTON,
    catalog.CAT_LABEL, catalog.CAT_CHEMICAL, catalog.CAT_OTHER,
)
G, F = catalog.CAT_GENERIC, catalog.CAT_FINISHED

# NIT, razón social, categoría, contacto, teléfono, correo, ciudad, dirección
SUPPLIERS = [
    ("900.412.778-3", "Denim Andino S.A.S.", T, "Paola Jiménez", "601 555 0142", "ventas@denimandino.co", "Bogotá", "Zona Industrial Puente Aranda"),
    ("890.205.611-9", "Tejidos Santander Ltda.", T, "Luis Carreño", "607 555 0178", "comercial@tejidossantander.co", "Bucaramanga", "Parque Industrial Girón"),
    ("900.318.445-6", "Hilazas del Norte S.A.S.", H, "Sandra Peñaranda", "607 555 0120", "pedidos@hilazasnorte.co", "Cúcuta", "Av. 6 # 12-40"),
    ("901.044.236-1", "Cierres Industriales Rayo S.A.S.", C, "Andrés Patiño", "604 555 0190", "ventas@cierresrayo.co", "Medellín", "Carrera 52 # 30-18"),
    ("901.122.905-4", "Remaches y Broches del Valle", B, "Martha Ocampo", "602 555 0166", "info@brochesdelvalle.co", "Cali", "Calle 25 # 8-42"),
    ("900.667.210-8", "Etiquetas Gráficas Norte", E, "Camilo Duarte", "604 555 0133", "diseno@etiquetasnorte.co", "Medellín", "Calle 10 # 43-70"),
    ("890.981.347-2", "Químicos Textiles del Oriente S.A.S.", Q, "Rosa Villamizar", "607 555 0155", "ventas@quimicosoriente.co", "Cúcuta", "Zona Industrial La Fría"),
    ("900.508.119-7", "Insumos Confección Total", O, "Jairo Mendoza", "601 555 0111", "contacto@insumostotal.co", "Bogotá", "Carrera 30 # 17-25"),
]

# Claves cortas de proveedor (por NIT, sin puntos) para no repetir nombres largos abajo.
COLTEJER, FABRICATO, COATS, EKA, HERRAJES, JACRON = "890900001", "890900123", "890100234", "860001234", "900234567", "900789012"
ANDINO, SANTANDER, NORTE, RAYO, VALLE, GRAFICAS, QUIMICOS, TOTAL = (
    "900412778", "890205611", "900318445", "901044236", "901122905", "900667210", "890981347", "900508119",
)

# nombre, categoría, unidad, mínimo, ancho útil, color, composición, [(proveedor, cantidad, lote, días atrás)]
PRODUCTS = [
    # Telas
    ("Denim rígido índigo 14 oz", T, "m", 400, "1.55", "Azul índigo intenso", "100% algodón",
     [(COLTEJER, 1500, "L-2609-A1", 25), (ANDINO, 800, "L-2609-B4", 12)]),
    ("Denim stretch azul medio 10 oz", T, "m", 300, "1.60", "Azul medio", "98% algodón / 2% elastano",
     [(FABRICATO, 1200, "L-2609-F2", 22)]),
    ("Denim negro stretch 11 oz", T, "m", 300, "1.57", "Negro profundo", "96% algodón / 3% poliéster / 1% elastano",
     [(SANTANDER, 900, "L-2609-S7", 20), (COLTEJER, 400, "L-2610-A2", 5)]),
    ("Denim gris ceniza 12 oz", T, "m", 200, "1.55", "Gris ceniza", "100% algodón",
     [(ANDINO, 600, "L-2609-B9", 18)]),
    ("Denim azul claro lavado 8 oz", T, "m", 250, "1.50", "Azul claro", "80% algodón / 20% poliéster",
     [(SANTANDER, 700, "L-2609-S3", 15)]),
    ("Denim blanco roto 9 oz", T, "m", 150, "1.60", "Blanco roto", "100% algodón",
     [(FABRICATO, 160, "L-2609-F8", 10)]),
    ("Drill caqui 8 oz", T, "m", 150, "1.60", "Caqui arena", "97% algodón / 3% elastano",
     [(ANDINO, 500, "L-2609-B2", 14)]),
    ("Denim índigo 12 oz (rollo de 50 m)", T, "rollo", 6, "1.58", "Azul índigo", "100% algodón",
     [(COLTEJER, 24, "R-2609-C5", 9), (SANTANDER, 12, "R-2609-S1", 4)]),
    # Hilos
    ("Hilo poliéster 40/2 azul índigo", H, "kg", 8, None, "Azul índigo", "100% poliéster",
     [(COATS, 30, "H-2609-01", 24), (NORTE, 18, "H-2609-N3", 11)]),
    ("Hilo poliéster 40/2 negro", H, "kg", 8, None, "Negro", "100% poliéster",
     [(COATS, 25, "H-2609-02", 24)]),
    ("Hilo algodón 20/3 crudo", H, "kg", 6, None, "Crudo", "100% algodón",
     [(NORTE, 20, "H-2609-N8", 13)]),
    ("Hilo poliéster naranja (puntada decorativa)", H, "kg", 5, None, "Naranja", "100% poliéster",
     [(COATS, 6, "H-2609-07", 16)]),
    # Cierres
    ("Cierre metálico 18 cm níquel", C, "unidad", 300, None, "Níquel", "",
     [(EKA, 1200, "C-2609-E1", 23), (RAYO, 600, "C-2609-R2", 8)]),
    ("Cierre metálico 15 cm latón antiguo", C, "unidad", 200, None, "Latón antiguo", "",
     [(RAYO, 800, "C-2609-R5", 17)]),
    ("Cierre de nylon 16 cm negro", C, "unidad", 200, None, "Negro", "",
     [(EKA, 700, "C-2609-E6", 19)]),
    ("Cierre de nylon en caja de 100 (negro)", C, "caja", 4, None, "Negro", "",
     [(RAYO, 12, "C-2609-R9", 6)]),
    # Botones y remaches
    ("Botón metálico 17 mm níquel", B, "unidad", 400, None, "Níquel brillante", "",
     [(HERRAJES, 2000, "B-2609-H1", 21), (VALLE, 1000, "B-2609-V3", 9)]),
    ("Botón metálico 20 mm cobre envejecido", B, "unidad", 300, None, "Cobre envejecido", "",
     [(VALLE, 1500, "B-2609-V5", 16)]),
    ("Botón a presión 15 mm negro mate", B, "unidad", 300, None, "Negro mate", "",
     [(HERRAJES, 900, "B-2609-H7", 14)]),
    ("Remache cobre 9 mm", B, "unidad", 800, None, "Cobre", "",
     [(HERRAJES, 4000, "B-2609-H2", 21), (VALLE, 2500, "B-2609-V6", 7)]),
    ("Remache níquel 9 mm", B, "unidad", 800, None, "Níquel", "",
     [(VALLE, 3000, "B-2609-V8", 12)]),
    # Etiquetas y empaque
    ("Etiqueta tejida de marca", E, "unidad", 500, None, "Azul y blanco", "",
     [(JACRON, 2500, "E-2609-J1", 20), (GRAFICAS, 1500, "E-2609-G4", 6)]),
    ("Marquilla de talla (caja de 500)", E, "caja", 3, None, "Blanco", "",
     [(GRAFICAS, 10, "E-2609-G2", 10)]),
    ("Bolsa plástica de empaque 35x50", E, "unidad", 400, None, "Transparente", "",
     [(JACRON, 1800, "E-2609-J5", 15)]),
    ("Parche de cuero de marca", E, "unidad", 300, None, "Café natural", "", []),  # sin compras: agotado
    # Químicos
    ("Suavizante enzimático", Q, "kg", 20, None, "Crema", "",
     [(QUIMICOS, 120, "Q-2609-01", 13)]),
    ("Permanganato de potasio", Q, "kg", 10, None, "Violeta", "",
     [(QUIMICOS, 40, "Q-2609-02", 13)]),
    ("Hipoclorito de sodio", Q, "l", 30, None, "Transparente", "",
     [(QUIMICOS, 200, "Q-2609-03", 8)]),
    # Otros insumos
    ("Cinta de refuerzo 10 mm", O, "m", 300, None, "Blanco", "",
     [(TOTAL, 2000, "O-2609-T1", 18)]),
    ("Hang tag de cartón", O, "unidad", 500, None, "Kraft", "",
     [(GRAFICAS, 3000, "O-2609-G1", 9)]),
    # Pantalones (sin compras: entran al cerrar órdenes)
    ("Pantalón genérico rígido", G, "unidad", 0, None, "", "", []),
    ("Pantalón genérico stretch", G, "unidad", 0, None, "", "", []),
    ("REF-1427 Clásico 5 bolsillos frosteado", F, "unidad", 30, None, "Azul frosteado", "", []),
    ("REF-G41 Recto azul claro lavado", F, "unidad", 30, None, "Azul claro", "", []),
    ("REF-N22 Skinny negro stretch", F, "unidad", 30, None, "Negro", "", []),
]

# Colores de la foto de referencia (RGB) por producto; lo que no esté aquí usa el de su categoría.
SWATCHES = {
    "Azul índigo intenso": (30, 48, 105), "Azul índigo": (36, 58, 120), "Azul medio": (62, 101, 168),
    "Negro profundo": (30, 32, 38), "Negro": (34, 34, 38), "Gris ceniza": (139, 143, 150),
    "Azul claro": (142, 178, 214), "Blanco roto": (236, 232, 221), "Caqui arena": (196, 174, 130),
    "Crudo": (225, 214, 190), "Naranja": (232, 131, 38), "Níquel": (176, 182, 190),
    "Latón antiguo": (166, 136, 70), "Níquel brillante": (192, 198, 206), "Cobre envejecido": (150, 98, 66),
    "Negro mate": (46, 46, 50), "Cobre": (184, 115, 51), "Azul y blanco": (70, 110, 190), "Blanco": (244, 244, 244),
    "Transparente": (205, 226, 236), "Café natural": (139, 94, 60), "Crema": (238, 226, 196), "Violeta": (104, 40, 130),
    "Kraft": (196, 160, 112), "Azul frosteado": (120, 156, 204),
}


def png(width, height, pixel):
    """PNG RGB sin dependencias: `pixel(x, y)` devuelve la tupla (r, g, b)."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(pixel(x, y))

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b"")


def shade(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def reference_image(category, color):
    """Foto de referencia sintética: sarga para telas, hilos, círculo para botones, dientes para cierres."""
    w, h = 320, 240
    base = SWATCHES.get(color) or (120, 140, 170)
    if category == T:  # sarga diagonal de denim
        return png(w, h, lambda x, y: shade(base, 1.12 if (x + y) % 6 < 2 else (0.94 if (x - y) % 11 == 0 else 1.0)))
    if category == H:  # hilos en líneas
        return png(w, h, lambda x, y: shade(base, 1.15 if y % 8 < 3 else 0.88))
    if category == B:  # botón: disco con borde
        cx, cy, r = w // 2, h // 2, 70
        return png(w, h, lambda x, y: shade(base, 1.2 if abs(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 - r) < 5
                                            else (1.0 if (x - cx) ** 2 + (y - cy) ** 2 < r * r else 0.35)))
    if category == C:  # cierre: dientes verticales
        return png(w, h, lambda x, y: shade(base, 1.15 if abs(x - w // 2) < 28 and y % 14 < 7 else 0.4))
    if category in (E, O):  # etiqueta: rectángulo con franja
        return png(w, h, lambda x, y: shade(base, 1.0 if 40 < x < w - 40 and 50 < y < h - 50 and not 110 < y < 124 else 0.55))
    return png(w, h, lambda x, y: shade(base, 1.0 - 0.25 * (y / h)))  # químicos, pantalones: degradado


# Órdenes de demostración. Cada una usa productos del catálogo por nombre y deja datos vivos:
# completada, en proceso y anulada, para ver el flujo completo conectado.
ORDERS = [
    {
        "key": "FT-1427-A", "tipo": catalog.ORDER_PRODUCTION, "dias": 10, "responsable": "Marta Ruiz (producción)",
        "resultado": "Pantalón genérico rígido", "prendas": 150, "recibe": (148, 6),
        "lineas": [("Denim rígido índigo 14 oz", 420), ("Hilo poliéster 40/2 azul índigo", 3),
                   ("Cierre metálico 18 cm níquel", 150), ("Botón metálico 17 mm níquel", 150),
                   ("Remache cobre 9 mm", 600)],
    },
    {
        "key": "FT-1431-B", "tipo": catalog.ORDER_PRODUCTION, "dias": 7, "responsable": "Marta Ruiz (producción)",
        "resultado": "Pantalón genérico stretch", "prendas": 200, "recibe": (196, 3),
        "lineas": [("Denim negro stretch 11 oz", 560), ("Hilo poliéster 40/2 negro", 4),
                   ("Cierre de nylon 16 cm negro", 200), ("Botón a presión 15 mm negro mate", 200),
                   ("Remache níquel 9 mm", 800)],
    },
    {
        "key": "FT-1436-C", "tipo": catalog.ORDER_PRODUCTION, "dias": 3, "responsable": "Jorge Santos (corte)",
        "resultado": "Pantalón genérico rígido", "prendas": 90, "recibe": None,  # queda en proceso
        "lineas": [("Denim blanco roto 9 oz", 130), ("Hilo algodón 20/3 crudo", 2), ("Hilo poliéster naranja (puntada decorativa)", 2),
                   ("Cierre metálico 15 cm latón antiguo", 90)],
    },
    {
        "key": "REF-1427-LV1", "tipo": catalog.ORDER_LAUNDRY, "dias": 6, "responsable": "Lavandería Sol del Norte",
        "destino": "Lavandería Sol del Norte", "resultado": "REF-1427 Clásico 5 bolsillos frosteado", "recibe": (97, 1),
        "lineas": [("Pantalón genérico rígido", 100), ("Suavizante enzimático", 12), ("Permanganato de potasio", 4),
                   ("Etiqueta tejida de marca", 100)],
    },
    {
        "key": "REF-N22-LV2", "tipo": catalog.ORDER_LAUNDRY, "dias": 2, "responsable": "Lavandería Sol del Norte",
        "destino": "Lavandería Sol del Norte", "resultado": "REF-N22 Skinny negro stretch", "recibe": None,
        "lineas": [("Pantalón genérico stretch", 120), ("Hipoclorito de sodio", 25), ("Etiqueta tejida de marca", 120),
                   ("Hang tag de cartón", 120)],
    },
    {
        "key": "FT-1440-X", "tipo": catalog.ORDER_PRODUCTION, "dias": 1, "responsable": "Jorge Santos (corte)",
        "resultado": "Pantalón genérico rígido", "prendas": 20, "anular": "Orden duplicada: se registró dos veces por error",
        "lineas": [("Drill caqui 8 oz", 40), ("Cierre metálico 15 cm latón antiguo", 20)],
    },
]


class Command(BaseCommand):
    help = "Carga un catálogo, proveedores y movimientos de demostración (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        user = self._operator()
        call_command("seed_inventario", verbosity=0)  # base mínima, por si la base está vacía
        today = timezone.localdate()

        suppliers = self._suppliers()
        created = self._products(user, suppliers, today)
        orders = self._orders(user, today)
        self.stdout.write(self.style.SUCCESS(
            f"Productos nuevos: {created['products']} · compras registradas: {created['entries']} · "
            f"imágenes: {created['images']} · órdenes nuevas: {orders}."
        ))

    @staticmethod
    def _operator():
        users = get_user_model().objects
        user = users.filter(role_id="ALMACENISTA", is_active=True).first() or users.filter(is_active=True).first()
        if user is None:
            raise CommandError("No hay usuarios: crea uno primero (por ejemplo con seed_admin).")
        return user

    def _suppliers(self):
        for nit, name, category, contact, phone, email, city, address in SUPPLIERS:
            body, _ = services.normalize_nit(nit)
            if not Proveedor.objects.filter(nit=body).exists():
                services.save_supplier(
                    nit=nit, razon_social=name, categoria=category, contacto=contact, telefono=phone,
                    correo=email, ciudad=city, direccion=address,
                )
        return {supplier.nit: supplier for supplier in Proveedor.objects.all()}

    def _products(self, user, suppliers, today):
        counts = {"products": 0, "entries": 0, "images": 0}
        for name, category, unit, minimum, width, color, composition, purchases in PRODUCTS:
            product = next(
                (p for p in Producto.objects.filter(categoria=category) if p.nombre.casefold() == name.casefold()), None
            )
            if product is None:
                product = services.create_product(
                    nombre=name, categoria=category, unidad=unit, stock_minimo=Decimal(minimum),
                    ancho_util=Decimal(width) if width else None, color=color, composicion=composition,
                )
                counts["products"] += 1
            if not product.tiene_imagen:
                data = reference_image(category, color)
                services.set_product_image(product, SimpleUploadedFile("demo.png", data, "image/png"))
                counts["images"] += 1
            if purchases and not Movimiento.objects.filter(producto=product).exists():
                for nit, quantity, lot, days in purchases:
                    services.register_entry(
                        user=user, producto_id=product.id, cantidad=quantity, fecha=today - timedelta(days=days),
                        proveedor_id=suppliers[nit].id, lote=lot, orden_compra=f"OC-{lot[-4:]}",
                        observaciones="Compra de demostración",
                    )
                    counts["entries"] += 1
        return counts

    def _orders(self, user, today):
        created = 0
        by_name = {p.nombre.casefold(): p for p in Producto.objects.all()}
        for spec in ORDERS:
            if OrdenSalida.objects.filter(ficha_tecnica=spec["key"]).exists():
                continue
            lines = [
                {"producto": by_name[name.casefold()].id, "cantidad": quantity}
                for name, quantity in spec["lineas"]
            ]
            order = services.create_order(
                user=user, tipo=spec["tipo"], fecha_salida=today - timedelta(days=spec["dias"]),
                responsable=spec["responsable"], ficha_tecnica=spec["key"],
                producto_resultado_id=by_name[spec["resultado"].casefold()].id, lineas=lines,
                destino=spec.get("destino", ""), cantidad_prendas=spec.get("prendas"),
                observaciones="Orden de demostración",
            )
            created += 1
            if spec.get("recibe"):
                quantity, days_back = spec["recibe"]
                services.register_entry(
                    user=user, producto_id=order.producto_resultado_id, cantidad=quantity,
                    fecha=today - timedelta(days=days_back), orden_id=order.id,
                    observaciones="Recepción de demostración",
                )
            if spec.get("anular"):
                services.cancel_order(user=user, order_id=order.id, motivo=spec["anular"])
        return created
