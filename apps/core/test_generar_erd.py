"""Pruebas del generador del modelo de datos (`generar_erd`)."""
from django.test import SimpleTestCase

from apps.core.management.commands.generar_erd import Command, MODULES, project_models, report_views


class GenerarErdTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.models = project_models()
        cls.text = Command().render(cls.models)

    def test_incluye_todas_las_tablas(self):
        self.assertEqual(len(self.models), 54)
        for model in self.models:
            self.assertIn(f"### {model.__name__} (`{model._meta.db_table}`)", self.text)

    def test_es_determinista(self):
        self.assertEqual(self.text, Command().render(project_models()))

    def test_tres_niveles_de_lectura(self):
        for heading in ("## Mapa general", "## Diagramas por módulo", "## Diagrama entidad-relación completo", "## Tablas"):
            self.assertIn(heading, self.text)
        for _key, title, _labels in MODULES:
            self.assertIn(f"### {title}", self.text)

    def test_modulos_nuevos_del_sprint_3(self):
        for title in ("Calidad", "Producto terminado", "Ventas y cartera", "Envíos"):
            self.assertIn(f"### {title}", self.text)
        for entity in ("Inspeccion", "StockTerminado", "FacturaVenta", "Guia"):
            self.assertIn(f"    {entity} {{", self.text)

    def test_vistas_de_reportes(self):
        self.assertIn("## Vistas materializadas de reportes", self.text)
        views = {v["name"]: v for v in report_views(self.models)}
        self.assertEqual(set(views), {"reportes_mv_produccion_ordenes", "reportes_mv_ventas_referencias"})
        self.assertEqual(len(views["reportes_mv_produccion_ordenes"]["columns"]), 14)
        self.assertEqual(len(views["reportes_mv_ventas_referencias"]["columns"]), 22)
        self.assertIn("| `estado_cobro` |", self.text)

    def test_referencia_imagenes(self):
        self.assertIn("img/mapa-general.svg", self.text)
        self.assertIn("img/modulo-calidad.svg", self.text)
