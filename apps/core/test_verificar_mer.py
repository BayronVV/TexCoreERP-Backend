"""El modelo de datos publicado coincide con el esquema que crean las migraciones (TE-188).

Corre en SQLite con la suite y en PostgreSQL en el job de la integración continua. Para la sustentación:
`python manage.py test apps.core.test_verificar_mer` o, contra una base real, `python manage.py verificar_mer`.
"""
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import models
from django.test import TestCase

from apps.core import mer_check
from apps.core.management.commands.generar_erd import schema_version
from apps.inventory.models import Producto


class VerificarMerTests(TestCase):
    def test_el_modelo_coincide_con_la_base(self):
        self.assertEqual(mer_check.compare(), [])

    def test_el_comando_lo_confirma(self):
        out = StringIO()
        call_command("verificar_mer", stdout=out)
        self.assertIn("El modelo de datos coincide con la base", out.getvalue())

    def test_detecta_una_restriccion_que_falta_en_la_base(self):
        fake = models.UniqueConstraint(fields=["nombre"], name="uq_producto_inexistente")
        with mock.patch.object(Producto._meta, "constraints", [*Producto._meta.constraints, fake]):
            problems = mer_check.compare()
            with self.assertRaises(CommandError):
                call_command("verificar_mer", stdout=StringIO())
        self.assertEqual(problems, ["inventario_producto: falta la restricción uq_producto_inexistente (unique)."])

    def test_detecta_nulabilidad_distinta(self):
        field = Producto._meta.get_field("nombre")
        with mock.patch.object(field, "null", True):
            problems = mer_check.compare()
        self.assertIn("inventario_producto.nombre: en la base no acepta nulos y el modelo dice lo contrario.", problems)

    def test_la_pagina_del_modelo_es_de_la_version_actual_del_esquema(self):
        page = (Path(settings.BASE_DIR) / "docs" / "modelo-de-datos.md").read_text(encoding="utf-8")
        self.assertIn(f"> Esquema de las migraciones: {schema_version()}.", page)
        self.assertRegex(page, r"> Generado el \d{4}-\d{2}-\d{2} desde el commit `[0-9a-f]{7}`\.")
