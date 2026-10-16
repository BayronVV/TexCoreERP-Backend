"""Datos de demostración del catálogo de referencias de jean (HU 3.1).

    python manage.py seed_demo_referencias

Crea referencias en los tres estados (borrador, activa y descontinuada) con tallas, colores y
fotos del prototipo (frente y espalda). Si el catálogo de inventario de demostración ya existe
(`seed_demo_inventario`), también arma la ficha técnica de consumo por unidad de las referencias activas. Todo pasa por las mismas reglas que usa la aplicación
(`services`), así que el código REF-0001, la imagen principal y las validaciones de estado son
las reales. Es idempotente: una referencia con el mismo nombre no se vuelve a crear. Solo
funciona con DJANGO_DEBUG=true.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from apps.inventory.management.commands.seed_demo_inventario import SWATCHES, png, shade
from apps.inventory.models import Producto
from apps.references import catalog, fichas, services
from apps.references.models import Referencia

NUMERIC = ["28", "30", "32", "34", "36", "38"]
SMALL = ["28", "30", "32", "34"]

# nombre, ajuste, descripción, tallas, colores, imágenes, estado final
REFERENCES = [
    ("Clásico 5 bolsillos frosteado", "RECTO", "Tiro medio, tela rígida de 14 oz con lavado frosteado.",
     NUMERIC, ["Azul índigo", "Azul frosteado"], ["Azul frosteado", "Azul frosteado"], catalog.ACTIVE),
    ("Skinny negro stretch", "SKINNY", "Tiro medio, tela stretch de 11 oz con elastano.",
     SMALL, ["Negro profundo"], ["Negro profundo", "Negro profundo"], catalog.ACTIVE),
    ("Mom vintage tiro alto", "MOM", "Tiro alto, pierna holgada y bota recta.",
     ["26", "28", "30", "32"], ["Azul medio", "Azul claro"], ["Azul claro", "Azul claro"], catalog.ACTIVE),
    ("Slim blanco roto", "SLIM", "Tela de 9 oz, corte ajustado en tono blanco roto.",
     SMALL, ["Blanco roto"], ["Blanco roto"], catalog.ACTIVE),
    ("Bootcut azul medio", "BOOTCUT", "Pierna ligeramente acampanada. Pendiente de definir la foto final.",
     ["30", "32", "34"], ["Azul medio"], [], catalog.DRAFT),
    ("Wide leg gris ceniza", "WIDE_LEG", "Prototipo en revisión: faltan las tallas y los colores definitivos.",
     [], [], ["Gris ceniza"], catalog.DRAFT),
    ("Jogger caqui", "JOGGER", "Referencia de la colección anterior, ya no se fabrica.",
     ["S", "M", "L"], ["Caqui arena"], ["Caqui arena"], catalog.DISCONTINUED),
]


# nombre de la referencia -> (lavado, notas, [(material del catálogo, cantidad por prenda, merma %)]).
# Son consumos de demostración, orientativos para un jean de adulto.
SHEETS = {
    "Clásico 5 bolsillos frosteado": ("STONE_WASH", "Costura de seguridad en los costados y pespunte doble en los tiros.", [
        ("Denim rígido índigo 14 oz", "1.4", "8"), ("Hilo poliéster 40/2 azul índigo", "0.02", "10"),
        ("Cierre metálico 18 cm níquel", "1", "0"), ("Botón metálico 17 mm níquel", "1", "0"),
        ("Remache cobre 9 mm", "5", "0")]),
    "Skinny negro stretch": ("ENZIMATICO", "Tela stretch: considerar el encogimiento en lavandería.", [
        ("Denim negro stretch 11 oz", "1.5", "8"), ("Hilo poliéster 40/2 negro", "0.02", "10"),
        ("Cierre de nylon 16 cm negro", "1", "0"), ("Botón a presión 15 mm negro mate", "1", "0"),
        ("Remache níquel 9 mm", "5", "0")]),
    "Mom vintage tiro alto": ("LEJIA", "", [
        ("Denim stretch azul medio 10 oz", "1.6", "8"), ("Hilo poliéster 40/2 azul índigo", "0.02", "10"),
        ("Cierre metálico 18 cm níquel", "1", "0"), ("Botón metálico 17 mm níquel", "1", "0")]),
    "Slim blanco roto": ("OTRO", "", [
        ("Denim blanco roto 9 oz", "1.4", "8"), ("Hilo algodón 20/3 crudo", "0.015", "10"),
        ("Hilo poliéster naranja (puntada decorativa)", "0.01", "10"),
        ("Cierre metálico 15 cm latón antiguo", "1", "0")]),
}


def jean_image(color, back=False):
    """Silueta sintética de un jean (frente o espalda): pretina, dos piernas y bolsillos.
    El lienzo es 3:2, igual que la miniatura del catálogo, para que no se recorte.
    """
    w, h = 320, 240
    center = w // 2
    base = SWATCHES.get(color) or (62, 101, 168)

    def pixel(x, y):
        taper = max(0, y - 40) * 0.05  # las piernas se afinan hacia abajo
        in_body = 14 <= y <= 226 and 108 + taper <= x <= 212 - taper
        if not in_body:
            return (240, 241, 245)
        if y < 38:  # pretina
            return shade(base, 0.8)
        if y > 90 and abs(x - center) < 2:  # entrepierna
            return shade(base, 0.55)
        if abs(x - center) < 1:  # costura central
            return shade(base, 0.7)
        if back and 46 < y < 86 and (118 < x < 150 or 170 < x < 202):  # bolsillos traseros
            edge = y < 50 or y > 82 or x < 122 or 146 < x < 154 or 166 < x < 174 or x > 198
            return shade(base, 1.2 if edge else 0.95)
        if not back and 40 < y < 78 and (112 < x < 140 or 180 < x < 208):  # bolsillos delanteros
            return shade(base, 0.82)
        return shade(base, 1.1 if (x + y) % 7 < 2 else 1.0)  # sarga

    return png(w, h, pixel)


class Command(BaseCommand):
    help = "Carga referencias de jean de demostración (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        user = self._operator()
        created = 0
        for name, fit, description, sizes, colors, images, final_state in REFERENCES:
            if Referencia.objects.filter(nombre__iexact=name).exists():
                continue
            variants = [{"talla": size, "color": color} for size in sizes for color in colors]
            reference = services.create_reference(
                user=user, data={"nombre": name, "ajuste": fit, "descripcion": description}, variants=variants,
            )
            if images:
                uploads = [
                    SimpleUploadedFile(f"{reference.codigo}-{'espalda' if index else 'frente'}.png",
                                       jean_image(color, back=bool(index)), "image/png")
                    for index, color in enumerate(images)
                ]
                services.add_images(reference, uploads)
            if final_state != catalog.DRAFT:
                services.change_state(reference, catalog.ACTIVE)
            if final_state == catalog.DISCONTINUED:
                services.change_state(reference, catalog.DISCONTINUED)
            created += 1
        sheets = self._sheets(user)
        self.stdout.write(self.style.SUCCESS(
            f"Referencias nuevas: {created} (de {len(REFERENCES)} de demostración). Fichas técnicas nuevas: {sheets}."
        ))

    @staticmethod
    def _sheets(user):
        """Arma las fichas que faltan. Si falta algún material del catálogo, esa ficha se omite entera."""
        by_name = {p.nombre.casefold(): p for p in Producto.objects.all()}
        created = 0
        for name, (wash, notes, materials) in SHEETS.items():
            reference = Referencia.objects.filter(nombre__iexact=name).first()
            if reference is None or reference.fichas.exists():
                continue
            if any(material.casefold() not in by_name for material, _, _ in materials):
                continue
            lines = [
                {"producto": by_name[material.casefold()].id, "cantidad": quantity, "merma": waste}
                for material, quantity, waste in materials
            ]
            fichas.save_ficha(user=user, reference=reference, data={"lavado": wash, "notas": notes}, lines=lines)
            created += 1
        return created

    @staticmethod
    def _operator():
        users = get_user_model().objects.filter(is_active=True)
        user = users.filter(role_id="PRODUCCION").first() or users.filter(role_id="ADMIN").first() or users.first()
        if user is None:
            raise CommandError("No hay usuarios: crea uno primero (por ejemplo con seed_admin).")
        return user
