"""Pruebas del generador del MER en notación de Chen (`generar_mer`)."""
import re

from django.test import SimpleTestCase

from apps.core.management.commands import generar_mer as mer
from apps.core.management.commands.generar_erd import Command as ErdCommand, MODULES, module_of, project_models


class GenerarMerTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.models = project_models()
        cls.dots = mer.all_dots(cls.models)
        cls.general = cls.dots["mer-general"]

    def test_es_determinista(self):
        self.assertEqual(self.dots, mer.all_dots(project_models()))

    def test_cada_modelo_es_entidad_o_rombo_nm(self):
        self.assertEqual(len(self.models), 54)
        for model in self.models:
            node = f"r_{model.__name__}" if mer.is_associative(model) else f"e_{model.__name__}"
            self.assertRegex(self.general, rf"(?m)^\s+{node} \[",f"{model.__name__} no aparece en el MER general")

    def test_toda_fk_de_negocio_tiene_nombre_curado(self):
        sin_nombre = []
        for model in self.models:
            if mer.is_associative(model):
                continue
            for field, target in mer.business_foreign_keys(model, self.models):
                if mer.is_associative(target):
                    continue
                if (model.__name__, field.name) not in mer.RELATION_NAMES:
                    sin_nombre.append((model.__name__, field.name))
        self.assertEqual(sin_nombre, [], "FK sin nombre curado en RELATION_NAMES")

    def test_no_hay_nombres_curados_huerfanos(self):
        reales = {(m.__name__, f.name) for m in self.models if not mer.is_associative(m)
                  for f, _t in mer.business_foreign_keys(m, self.models)}
        self.assertEqual(set(mer.RELATION_NAMES) - reales, set())

    def test_entidades_debiles_con_doble_borde(self):
        for name in mer.WEAK:
            self.assertRegex(self.general, rf"e_{name} \[[^\]]*peripheries=2")
        self.assertNotRegex(self.general, r"e_Lote \[[^\]]*peripheries=2")
        # relación identificadora con rombo de doble borde
        self.assertRegex(self.general, r"r_DetalleVenta_factura \[shape=diamond[^\]]*peripheries=2")
        self.assertNotRegex(self.general, r"r_FacturaVenta_cliente \[shape=diamond[^\]]*peripheries=2")

    def test_cardinalidades(self):
        rels = {r["id"]: r for r in mer.relations(self.models)}
        self.assertEqual(rels["r_FacturaVenta_cliente"]["ends"], [("Cliente", "1"), ("FacturaVenta", "N")])
        self.assertEqual(rels["r_OrdenProduccion_orden_salida"]["ends"], [("OrdenSalida", "1"), ("OrdenProduccion", "1")])
        self.assertEqual(rels["r_RolePermission"]["kind"], "nm")
        self.assertEqual({c for _e, c in rels["r_RolePermission"]["ends"]}, {"N", "M"})
        self.assertEqual(rels["r_RemisionLote"]["attrs"][0], "cantidad")

    def test_sin_relaciones_hacia_usuario_fuera_de_seguridad(self):
        for rel in mer.relations(self.models):
            if rel["owner"] != "CustomUser":
                for entity, _c in rel["ends"]:
                    if entity == "CustomUser":
                        self.assertEqual(module_of(next(m for m in self.models if m.__name__ == rel["owner"])), "seguridad")

    def test_atributos_principales(self):
        for model in self.models:
            attrs = mer.main_attributes(model)
            self.assertLessEqual(len(attrs), mer.MAX_ATTRS)
            self.assertTrue(attrs[0][1], f"{model.__name__}: la llave primaria va primero y subrayada")
            for name, _key in attrs:
                self.assertNotIn(name, {"created_at", "updated_at", "deleted_at"})
        self.assertIn("<U>id</U>", self.dots["mer-ventas"])

    def test_mer_general_con_atributos_principales(self):
        dot = self.dots["mer-general-atributos"]
        self.assertEqual(len(re.findall(r"(?m)^\s+a_\S+ \[shape=ellipse", dot)), 199)  # llave + hasta 3 atributos por entidad
        for model in self.models:
            if not mer.is_associative(model):
                self.assertRegex(dot, rf"(?m)^\s+a_{model.__name__}_id \[", f"{model.__name__} sin su llave")
        por_entidad = {}
        for dueno in re.findall(r"(?m)^\s+(\S+)\s+--\s+a_\S+ \[", dot):
            por_entidad[dueno] = por_entidad.get(dueno, 0) + 1
        self.assertLessEqual(max(por_entidad.values()), 4)
        self.assertNotIn("sin atributos", self.dots["mer-general"].lower())

    def test_una_figura_por_modulo_y_dot_valido(self):
        nombres = set(self.dots)
        self.assertIn("mer-general", nombres)
        for key, _title, _labels in MODULES:
            self.assertTrue(any(n == f"mer-{key}" or n.startswith(f"mer-{key}-") for n in nombres), key)
        self.assertIn("mer-produccion-fabricacion", nombres)
        self.assertIn("mer-produccion-lavanderia", nombres)
        for name, dot in self.dots.items():
            self.assertTrue(dot.startswith("// layout: neato\ngraph "), name)
            self.assertTrue(dot.rstrip().endswith("}"), name)
            self.assertEqual(dot.count("{") , dot.count("}"), f"{name}: llaves desbalanceadas")
            nodos = set(re.findall(r"^\s+(\w+) \[", dot, re.M))
            for a, b in re.findall(r"^\s+(\w+) -- (\w+)", dot, re.M):
                self.assertIn(a, nodos, f"{name}: arista a nodo inexistente {a}")
                self.assertIn(b, nodos, f"{name}: arista a nodo inexistente {b}")

    def test_modulo_marca_externas_en_gris(self):
        self.assertIn("e_Producto", self.dots["mer-compras"])
        self.assertRegex(self.dots["mer-compras"], r"e_Producto \[[^\]]*#e5e7eb")

    def test_documento_incluye_seccion_chen(self):
        text = ErdCommand().render(self.models)
        self.assertLess(text.index("## Modelo entidad-relación (notación de Chen)"), text.index("## Mapa de módulos"))
        self.assertIn("img/mer-general.svg", text)
        self.assertIn("img/mer-produccion-lavanderia.svg", text)
        self.assertIn("esquema físico", text)
