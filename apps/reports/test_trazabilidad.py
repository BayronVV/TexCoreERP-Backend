"""Trazabilidad de punta a punta (HU 7.6, TE-176): tramos, permisos por bloque, búsqueda, consultas fijas y solo lectura."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.testing import client_for, make_user
from apps.finished import catalog as finished_catalog
from apps.production.models import AsignacionEtapa, Lote, Operario
from apps.quality.models import Inspeccion
from apps.sales import catalog as sales_catalog
from apps.sales.models import FacturaVenta
from apps.shipping import catalog as shipping_catalog
from apps.shipping.models import EventoGuia, Guia, RelacionDespacho

from .trazabilidad import reconcile

ROLES = ("ADMIN", "GERENTE", "ALMACENISTA", "PRODUCCION", "SECRETARIA", "VENDEDOR", "TERMINACION")
NO_ACCESS = {"acceso": False}


def lot_url(code):
    return reverse("trazabilidad-lote", args=[code])


def invoice_url(number):
    return reverse("trazabilidad-factura", args=[number])


def steps(data):
    return {row["paso"]: row for row in data["conciliacion"]}


@override_settings(DEBUG=False)
class TraceTests(TestCase):
    """Sobre la siembra de demostración completa: un lote ingresado, uno a medio camino y ventas en todos los estados."""

    @classmethod
    def setUpTestData(cls):
        cls.users = {role: make_user(f"traza-{role.lower()}@t.co", role) for role in ROLES}
        cls.pending = make_user("traza-pending@t.co")
        call_command("seed_demo_completo", "--permitir-produccion", stdout=StringIO())
        cls.done = Lote.objects.filter(ingresos_terminado__isnull=False).order_by("id").first()
        cls.halfway = (
            Lote.objects.filter(recepciones_lavado__isnull=False, inspecciones__isnull=True).order_by("id").first()
        )
        cls.paid = FacturaVenta.objects.filter(estado_cobro=sales_catalog.COLLECT_PAID).first()
        cls.returned = FacturaVenta.objects.filter(estado_cobro=sales_catalog.COLLECT_RETURNED).first()

    def setUp(self):
        self.manager = client_for(self.users["GERENTE"])
        self.seller = client_for(self.users["VENDEDOR"])

    # ------------------------------------------------------------------ escenario 1: recorrido completo de un lote
    def test_lote_completo_cuadra_de_un_paso_al_siguiente(self):
        data = self.manager.get(lot_url(self.done.codigo)).json()
        for block in ("referencia", "orden", "materiales", "etapas", "lavanderia", "calidad", "ingreso"):
            self.assertTrue(data[block]["acceso"], block)
        self.assertEqual(data["orden"]["cantidad_lote"], self.done.cantidad)
        self.assertTrue(data["etapas"]["items"])
        self.assertTrue(data["materiales"]["lineas"])
        self.assertTrue(data["lavanderia"]["remisiones"] and data["lavanderia"]["recepciones"])

        inspection = Inspeccion.objects.get(lote=self.done)
        rows = steps(data)
        self.assertEqual([row["paso"] for row in data["conciliacion"]], ["PLANIFICADO", "ENVIADO", "RECIBIDO", "APTAS", "INGRESADO"])
        self.assertEqual(rows["PLANIFICADO"]["cantidad"], self.done.cantidad)
        self.assertEqual(rows["APTAS"]["cantidad"], inspection.aptas)
        self.assertEqual(rows["INGRESADO"]["cantidad"], inspection.aptas)
        self.assertEqual(rows["INGRESADO"]["diferencia"], 0)
        self.assertEqual(rows["APTAS"]["justificada"], min(rows["APTAS"]["diferencia"], inspection.marras))
        for row in data["conciliacion"]:
            self.assertFalse(row["pendiente"], row["paso"])
            if "diferencia" in row:
                self.assertEqual(row["diferencia"], row["justificada"] + row["sin_justificar"])
        self.assertEqual(data["calidad"]["inspeccion"]["aptas"], inspection.aptas)
        self.assertEqual(sum(d["cantidad"] for d in data["calidad"]["inspeccion"]["defectos"]), inspection.marras)

    # ------------------------------------------------------------------ escenario 2: lote a medio camino
    def test_lote_a_medio_camino_deja_pendientes_los_pasos_siguientes(self):
        rows = steps(self.manager.get(lot_url(self.halfway.codigo)).json())
        self.assertIsNotNone(rows["RECIBIDO"]["cantidad"])
        self.assertTrue(rows["APTAS"]["pendiente"])
        self.assertTrue(rows["INGRESADO"]["pendiente"])
        self.assertNotIn("diferencia", rows["APTAS"])

    def test_lote_sin_lavanderia_aun(self):
        planned = Lote.objects.filter(remisiones_lavado__isnull=True).order_by("id").first()
        data = self.manager.get(lot_url(planned.codigo)).json()
        self.assertEqual(data["lavanderia"]["remisiones"], [])
        self.assertIsNone(data["calidad"]["inspeccion"])
        self.assertTrue(steps(data)["ENVIADO"]["pendiente"])

    def test_diferencia_sin_justificar(self):
        rows = reconcile([
            ("A", "a", True, 30, None),
            ("B", "b", True, 30, None),
            ("C", "c", True, 26, 3),
            ("D", "d", False, None, None),
            ("E", "e", True, 20, None),
        ])
        self.assertEqual((rows[2]["diferencia"], rows[2]["justificada"], rows[2]["sin_justificar"]), (4, 3, 1))
        self.assertEqual(rows[2]["porcentaje"], 13.3)
        self.assertEqual(rows[3], {"paso": "D", "etiqueta": "d", "acceso": False})
        self.assertNotIn("diferencia", rows[4])  # el paso anterior no es visible: no se compara contra él

    # ------------------------------------------------------------------ escenario 3: recorrido de una venta
    def test_factura_entregada_y_pagada(self):
        data = self.manager.get(invoice_url(self.paid.numero)).json()
        self.assertTrue(all(data[b]["acceso"] for b in ("venta", "existencias", "envio", "cobro")))
        self.assertIn(finished_catalog.SALE_EXIT, [m["tipo"] for m in data["existencias"]["movimientos"]])
        guide = data["envio"]["guias"][0]
        self.assertTrue(guide["vigente"])
        self.assertEqual(guide["estado"], shipping_catalog.DELIVERED)
        self.assertTrue(guide["eventos"])
        self.assertEqual(data["cobro"]["estado_cobro"], sales_catalog.COLLECT_PAID)
        self.assertTrue(data["cobro"]["movimientos"])
        self.assertEqual(len(data["existencias"]["lotes_de_origen"]), self.paid.lineas.count())
        for row in data["existencias"]["lotes_de_origen"]:
            self.assertGreaterEqual(row["total_lotes"], len(row["lotes"]))
            for lot in row["lotes"]:
                self.assertLessEqual(lot["fecha"], self.paid.fecha.isoformat())

    def test_factura_devuelta_muestra_el_reingreso(self):
        data = self.manager.get(invoice_url(self.returned.numero)).json()
        kinds = [m["tipo"] for m in data["existencias"]["movimientos"]]
        self.assertIn(finished_catalog.SALE_EXIT, kinds)
        self.assertIn(finished_catalog.SALE_RETURN, kinds)
        self.assertEqual(data["cobro"]["estado_cobro"], sales_catalog.COLLECT_RETURNED)
        self.assertEqual(data["envio"]["guias"][0]["estado"], shipping_catalog.RETURNED)

    # ------------------------------------------------------------------ escenario 4: permisos por bloque
    def test_vendedor_ve_ventas_envios_y_existencias_y_no_produccion(self):
        invoice = self.seller.get(invoice_url(self.paid.numero)).json()
        self.assertTrue(all(invoice[b]["acceso"] for b in ("venta", "existencias", "envio", "cobro")))

        lot = self.seller.get(lot_url(self.done.codigo)).json()
        for block in ("orden", "materiales", "etapas", "lavanderia", "calidad"):
            self.assertEqual(lot[block], NO_ACCESS, block)
        self.assertTrue(lot["ingreso"]["acceso"])
        self.assertTrue(lot["referencia"]["acceso"])
        self.assertEqual(lot["referencia"]["ficha"], NO_ACCESS)
        for row in lot["conciliacion"][:4]:
            self.assertEqual(set(row), {"paso", "etiqueta", "acceso"})
            self.assertFalse(row["acceso"])

    def test_almacenista_ve_materiales_y_compras_pero_no_produccion(self):
        data = client_for(self.users["ALMACENISTA"]).get(lot_url(self.done.codigo)).json()
        self.assertEqual(data["orden"], NO_ACCESS)
        self.assertTrue(data["materiales"]["acceso"])
        self.assertTrue(all(line["compras_previas"]["acceso"] for line in data["materiales"]["lineas"]))
        self.assertEqual(data["ingreso"], NO_ACCESS)

    def test_terminacion_solo_ve_calidad(self):
        data = client_for(self.users["TERMINACION"]).get(lot_url(self.done.codigo)).json()
        self.assertTrue(data["calidad"]["acceso"])
        for block in ("referencia", "orden", "materiales", "etapas", "lavanderia", "ingreso"):
            self.assertEqual(data[block], NO_ACCESS, block)
        invoice = client_for(self.users["TERMINACION"]).get(invoice_url(self.paid.numero)).json()
        for block in ("venta", "existencias", "envio", "cobro"):
            self.assertEqual(invoice[block], NO_ACCESS, block)

    def test_sin_ningun_permiso_de_consulta_no_entra(self):
        client = client_for(self.pending)
        self.assertEqual(client.get(lot_url(self.done.codigo)).status_code, 403)
        self.assertEqual(client.get(invoice_url(self.paid.numero)).status_code, 403)
        self.assertEqual(client.get(reverse("trazabilidad-buscar"), {"codigo": "FV-0001"}).status_code, 403)

    # ------------------------------------------------------------------ escenario 5: búsqueda única
    def search(self, code):
        response = self.manager.get(reverse("trazabilidad-buscar"), {"codigo": code})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_busqueda_por_cada_tipo_de_codigo(self):
        self.assertEqual(self.search(self.done.codigo.lower()), {"tipo": "lote", "codigo": self.done.codigo})
        self.assertEqual(self.search(self.paid.numero), {"tipo": "factura", "codigo": self.paid.numero})
        order = self.search(self.done.orden.codigo)
        self.assertEqual(order["tipo"], "orden")
        self.assertEqual([o["codigo"] for o in order["opciones"]], list(self.done.orden.lotes.order_by("numero").values_list("codigo", flat=True)))
        inspection = Inspeccion.objects.get(lote=self.done)
        self.assertEqual(self.search(inspection.codigo), {"tipo": "lote", "codigo": self.done.codigo})
        entry = self.done.ingresos_terminado.first()
        self.assertEqual(self.search(entry.codigo)["codigo"], self.done.codigo)
        guide = Guia.objects.filter(factura=self.paid, vigente=True).first()
        self.assertEqual(self.search(guide.numero_guia), {"tipo": "factura", "codigo": self.paid.numero})
        dispatch = RelacionDespacho.objects.filter(guias__isnull=False).first()
        found = self.search(dispatch.codigo)
        self.assertEqual(found["tipo"], "relacion")
        self.assertTrue(all(o["tipo"] == "factura" for o in found["opciones"]))

    def test_codigo_que_no_existe(self):
        self.assertEqual(self.search("NO-EXISTE-99"), {"tipo": None, "codigo": "NO-EXISTE-99"})
        self.assertEqual(self.search("  "), {"tipo": None, "codigo": ""})
        self.assertEqual(self.manager.get(lot_url("NO-EXISTE")).status_code, 404)
        self.assertEqual(self.manager.get(invoice_url("FV-9999")).status_code, 404)

    # ------------------------------------------------------------------ consultas fijas y solo lectura
    def count_queries(self, url):
        client = client_for(get_user_model().objects.get(pk=self.users["GERENTE"].pk))  # sin permisos en caché
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(client.get(url).status_code, 200)
        return ctx.captured_queries

    def test_las_consultas_no_crecen_con_las_filas(self):
        first = self.count_queries(invoice_url(self.paid.numero))
        before = len(first)
        guide = Guia.objects.filter(factura=self.paid, vigente=True).first()
        for number in range(8):
            EventoGuia.objects.create(guia=guide, estado_antes=guide.estado, estado_despues=guide.estado, nota=f"Nota {number}")
        after = self.count_queries(invoice_url(self.paid.numero))
        self.assertEqual(len(after), before, " ||| ".join(q["sql"][:120] for q in after))

        lot_queries = len(self.count_queries(lot_url(self.done.codigo)))
        self.assertLessEqual(lot_queries, 25)
        stage = self.done.etapas.first()
        for number in range(5):
            worker = Operario.objects.create(codigo=f"OPT-{number}", nombres=f"Operario {number}")
            AsignacionEtapa.objects.create(etapa_lote=stage, operario=worker, inicio_at=timezone.now(), fin_at=timezone.now())
        self.assertEqual(len(self.count_queries(lot_url(self.done.codigo))), lot_queries)

    def test_solo_lectura(self):
        for url in (lot_url(self.done.codigo), invoice_url(self.paid.numero), invoice_url(self.returned.numero)):
            for query in self.count_queries(url):
                self.assertFalse(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")), query["sql"])
        for method in ("post", "put", "patch", "delete"):
            self.assertIn(getattr(self.manager, method)(lot_url(self.done.codigo)).status_code, (403, 405))
