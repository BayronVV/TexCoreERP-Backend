"""El BPMN publicado es verificable contra el código (TE-188).

- Cada tarea automatizada (de usuario o de servicio) del diagrama general tiene su fila: caso de uso, endpoint y prueba. El endpoint
  existe en las rutas de la API y la prueba existe y lo ejercita. La misma tabla está en `docs/procesos-bpmn.md`.
- Las tareas manuales no están en la tabla (ocurren fuera de TexCore) y los terceros son participantes externos con flujos de mensaje.
- Cada compuerta exclusiva con varias salidas tiene una salida por defecto y condición en las demás; las excepciones están modeladas.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import get_resolver

BASE = Path(settings.BASE_DIR)
BPMN = BASE / "docs" / "bpmn" / "texcore-proceso.bpmn"
DOC = BASE / "docs" / "procesos-bpmn.md"
NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}

# tarea del BPMN → (caso de uso, nombre de la ruta de la API, módulo de prueba)
ACTIVITIES = {
    "T1": ("CU-05b", "compras_ordenes", "apps/purchasing/test_ordenes_compra.py"),
    "T2": ("CU-05b", "compras_orden_aprobar", "apps/purchasing/test_ordenes_compra.py"),
    "T3": ("CU-05b", "compras_recepciones", "apps/purchasing/test_recepciones.py"),
    "S1": ("CU-05", "compras_recepciones", "apps/purchasing/test_recepciones.py"),
    "T4": ("CU-06", "referencias", "apps/references/tests.py"),
    "T5": ("CU-06", "referencia_ficha", "apps/references/test_ficha.py"),
    "T6": ("CU-07", "produccion_simulacion", "apps/production/tests.py"),
    "T7": ("CU-07", "produccion_simulacion", "apps/production/tests.py"),
    "T8": ("CU-08", "produccion_ordenes", "apps/production/test_ordenes.py"),
    "S2": ("CU-08", "produccion_ordenes", "apps/production/test_ordenes.py"),
    "T9": ("CU-10", "produccion_lote_asignar", "apps/production/test_recursos.py"),
    "T10": ("CU-09", "produccion_lote_accion", "apps/production/test_tiempos.py"),
    "T11": ("CU-11", "produccion_monitor", "apps/production/test_monitor.py"),
    "T12": ("CU-13", "lavanderia_remisiones", "apps/core/test_e2e_sustentacion.py"),
    "T14": ("CU-14", "lavanderia_recepciones", "apps/core/test_e2e_sustentacion.py"),
    "S4": ("CU-14", "lavanderia_recepciones", "apps/core/test_e2e_sustentacion.py"),
    "S5": ("CU-14", "lavanderia_recepciones", "apps/core/test_e2e_sustentacion.py"),
    "S6": ("CU-14", "lavanderia_recepciones", "apps/core/test_e2e_sustentacion.py"),
    "T15": ("CU-15", "calidad_inspecciones", "apps/quality/test_calidad.py"),
    "T16": ("CU-16", "terminado_ingresos", "apps/finished/test_terminado.py"),
    "S8": ("CU-16", "terminado_ingresos", "apps/finished/test_terminado.py"),
    "T17": ("CU-16", "terminado_ajustes", "apps/finished/test_ajustes.py"),
    "T19": ("CU-17", "ventas_facturas", "apps/sales/test_ventas.py"),
    "S10": ("CU-17", "ventas_factura_pdf", "apps/sales/test_ventas.py"),
    "T21": ("CU-18", "envios_relaciones", "apps/shipping/test_envios.py"),
    "S11": ("CU-18", "envios_relaciones", "apps/shipping/test_envios.py"),
    "T23": ("CU-18", "envios_guia_rastrear", "apps/shipping/test_rastreo.py"),
    "S12": ("CU-18", "envios_guia_rastrear", "apps/shipping/test_rastreo.py"),
    "T24": ("CU-19", "ventas_factura_conciliar", "apps/shipping/test_cartera_guias.py"),
    "S13": ("CU-19", "ventas_factura_conciliar", "apps/shipping/test_cartera_guias.py"),
    "T27": ("CU-19", "envios_guia_devolucion", "apps/shipping/test_cartera_guias.py"),
    "S14": ("CU-19", "envios_guia_devolucion", "apps/shipping/test_cartera_guias.py"),
    "T25": ("CU-20", "reportes-gerencial", "apps/reports/test_reportes.py"),
}


def routes():
    """Nombre de cada ruta → su patrón (`api/...`)."""
    found = {}

    def walk(resolver, prefix=""):
        for pattern in resolver.url_patterns:
            if hasattr(pattern, "url_patterns"):
                walk(pattern, prefix + str(pattern.pattern))
            elif pattern.name:
                found[pattern.name] = prefix + str(pattern.pattern)

    walk(get_resolver())
    return found


class BpmnVerificableTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = ET.parse(BPMN).getroot()
        cls.process = cls.root.find("bpmn:process", NS)

    def tasks(self, tag):
        return {node.get("id"): node.get("name") for node in self.process.findall(f"bpmn:{tag}", NS)}

    def test_cada_tarea_automatizada_tiene_su_fila_y_ninguna_sobra(self):
        automated = self.tasks("userTask") | self.tasks("serviceTask")
        self.assertEqual(set(ACTIVITIES), set(automated))
        self.assertFalse(set(ACTIVITIES) & set(self.tasks("manualTask")))

    def test_el_endpoint_existe_y_la_prueba_lo_ejercita(self):
        api = routes()
        for task, (_, route, test_module) in ACTIVITIES.items():
            with self.subTest(task=task):
                self.assertIn(route, api, f"{task}: la ruta {route} no existe")
                path = BASE / test_module
                self.assertTrue(path.exists(), f"{task}: no existe {test_module}")
                source = path.read_text(encoding="utf-8")
                fixed = re.sub(r"<[^>]+>.*$", "", api[route]).removeprefix("api/").rstrip("/")  # parte fija de la ruta
                prefix, _, action = route.rpartition("_")
                by_action = bool(prefix) and f'"{action}"' in source and f"{prefix}_" in source  # reverse(f"compras_orden_{action}")
                self.assertTrue(
                    f'"{route}"' in source or f"'{route}'" in source or fixed in source or by_action,
                    f"{task}: {test_module} no ejercita {route} ({api[route]})",
                )

    def test_la_tabla_de_la_documentacion_coincide(self):
        doc = DOC.read_text(encoding="utf-8")
        api = routes()
        for task, (use_case, route, test_module) in ACTIVITIES.items():
            with self.subTest(task=task):
                row = next((line for line in doc.splitlines() if line.startswith(f"| {task} |")), None)
                self.assertIsNotNone(row, f"falta la fila de {task} en procesos-bpmn.md")
                for value in (use_case, f"/{api[route]}", test_module):
                    self.assertIn(value, row)

    def test_las_compuertas_tienen_condicion_y_salida_por_defecto(self):
        flows = {flow.get("id"): flow for flow in self.process.findall("bpmn:sequenceFlow", NS)}
        for gateway in self.process.findall("bpmn:exclusiveGateway", NS):
            outgoing = [flows[ref.text] for ref in gateway.findall("bpmn:outgoing", NS)]
            if len(outgoing) < 2:
                continue
            with self.subTest(gateway=gateway.get("id")):
                default = gateway.get("default")
                self.assertIn(default, {flow.get("id") for flow in outgoing})
                for flow in outgoing:
                    has_condition = flow.find("bpmn:conditionExpression", NS) is not None
                    self.assertEqual(has_condition, flow.get("id") != default, flow.get("id"))

    def test_los_terceros_son_participantes_externos_con_mensajes(self):
        collaboration = self.root.find("bpmn:collaboration", NS)
        externals = {p.get("id") for p in collaboration.findall("bpmn:participant", NS) if p.get("processRef") is None}
        self.assertEqual(externals, {"P_LAV", "P_TRA"})
        messages = collaboration.findall("bpmn:messageFlow", NS)
        for external in externals:
            self.assertTrue(any(external in (m.get("sourceRef"), m.get("targetRef")) for m in messages), external)
        self.assertFalse([lane.get("name") for lane in self.process.iter(f"{{{NS['bpmn']}}}lane") if "tercero" in lane.get("name")])

    def test_las_excepciones_estan_modeladas(self):
        names = {node.get("name") for node in self.process.iter() if node.get("name")}
        boundary = self.process.find("bpmn:boundaryEvent", NS)
        self.assertEqual(boundary.get("attachedToRef"), "S4")  # el cotejo de la lavandería que no cuadra
        self.assertIsNotNone(boundary.find("bpmn:errorEventDefinition", NS))
        for expected in ("Con novedad o en tránsito: volver a consultar", "Recaudo pendiente: la factura sigue por cobrar",
                         "Devuelta", "Devolución registrada", "¿Hay merma o dañadas?"):
            self.assertIn(expected, names)
