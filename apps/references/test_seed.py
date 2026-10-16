"""Comando `seed_demo_referencias`: datos de demostración coherentes con las reglas de la HU 3.1."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.inventory.tests import make_user
from apps.references.management.commands.seed_demo_referencias import (
    REFERENCES,
    jean_image,
)

from . import catalog
from .models import ImagenReferencia, Referencia, Variante


def seed():
    out = StringIO()
    call_command("seed_demo_referencias", stdout=out)
    return out.getvalue()


@override_settings(DEBUG=True)
class SeedDemoReferenciasTests(TestCase):
    def setUp(self):
        self.boss = make_user("produccion@t.co", "PRODUCCION")

    def test_crea_todas_las_referencias_con_codigos_consecutivos(self):
        self.assertIn(f"Referencias nuevas: {len(REFERENCES)}", seed())
        codes = list(Referencia.objects.order_by("id").values_list("codigo", flat=True))
        self.assertEqual(codes, [f"REF-{n:04d}" for n in range(1, len(REFERENCES) + 1)])

    def test_hay_referencias_en_los_tres_estados(self):
        seed()
        by_state = {state: Referencia.objects.filter(estado=state).count() for state, _ in catalog.STATES}
        self.assertEqual(by_state, {catalog.DRAFT: 2, catalog.ACTIVE: 4, catalog.DISCONTINUED: 1})

    def test_cumple_las_reglas_de_estado(self):
        seed()
        for reference in Referencia.objects.filter(estado__in=[catalog.ACTIVE, catalog.DISCONTINUED]):
            self.assertTrue(reference.variantes.exists(), reference.nombre)
            self.assertTrue(reference.imagenes.exists(), reference.nombre)
        incomplete = Referencia.objects.get(nombre="Wide leg gris ceniza")  # borrador sin tallas ni colores
        self.assertFalse(incomplete.variantes.exists())
        self.assertTrue(incomplete.imagenes.exists())
        self.assertFalse(Referencia.objects.get(nombre="Bootcut azul medio").imagenes.exists())

    def test_cada_referencia_tiene_una_sola_imagen_principal(self):
        seed()
        for reference in Referencia.objects.filter(imagenes__isnull=False).distinct():
            self.assertEqual(reference.imagenes.filter(principal=True).count(), 1, reference.nombre)
        self.assertEqual(ImagenReferencia.objects.count(), 9)

    def test_las_variantes_son_el_producto_de_tallas_por_colores(self):
        seed()
        clasico = Referencia.objects.get(nombre="Clásico 5 bolsillos frosteado")
        self.assertEqual(clasico.variantes.count(), 6 * 2)
        self.assertEqual(Variante.objects.filter(referencia__nombre="Skinny negro stretch").count(), 4)

    def test_las_imagenes_son_png_validos(self):
        seed()
        for image in ImagenReferencia.objects.all():
            self.assertEqual(image.tipo, "image/png")
            self.assertEqual(bytes(image.imagen)[:8], b"\x89PNG\r\n\x1a\n")
        self.assertNotEqual(jean_image("Azul medio"), jean_image("Azul medio", back=True))

    def test_es_idempotente(self):
        seed()
        self.assertIn("Referencias nuevas: 0", seed())
        self.assertEqual(Referencia.objects.count(), len(REFERENCES))
        self.assertEqual(ImagenReferencia.objects.count(), 9)

    def test_no_repite_una_referencia_que_ya_existe(self):
        from . import services

        services.create_reference(
            user=self.boss, data={"nombre": "skinny NEGRO stretch", "ajuste": "SKINNY"}, variants=[],
        )
        self.assertIn(f"Referencias nuevas: {len(REFERENCES) - 1}", seed())
        self.assertEqual(Referencia.objects.filter(nombre__iexact="Skinny negro stretch").count(), 1)

    def test_la_crea_a_nombre_de_un_usuario_de_produccion(self):
        make_user("admin@t.co", "ADMIN")
        seed()
        self.assertEqual(set(Referencia.objects.values_list("creado_por__email", flat=True)), {"produccion@t.co"})

    def test_sin_usuarios_falla_con_un_mensaje_claro(self):
        self.boss.delete()
        with self.assertRaisesMessage(CommandError, "No hay usuarios"):
            seed()
        self.assertEqual(Referencia.objects.count(), 0)


class SeedDemoReferenciasGuardTests(TestCase):
    @override_settings(DEBUG=False)
    def test_no_corre_fuera_de_modo_debug(self):
        make_user("produccion@t.co", "PRODUCCION")
        with self.assertRaisesMessage(CommandError, "DJANGO_DEBUG=true"):
            seed()
        self.assertEqual(Referencia.objects.count(), 0)
