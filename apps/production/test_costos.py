"""
Pruebas del motor de costos, tarifas de mano de obra y liquidación de órdenes (HU 4.6, TE-129 y TE-130).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.inventory import catalog as inventory_catalog
from apps.inventory.tests import client_for, make_user

from . import catalog, costing
from .models import EtapaLote, Lote, OrdenProduccion, TarifaManoObra
from .test_ordenes import OrderBase


class CostingPureFunctionsTests(OrderBase):
    """Pruebas unitarias de las funciones puras de costing.py."""

    def test_costo_etapa_cero_segundos(self):
        cost, sin_tarifa = costing.calculate_stage_cost(0, Decimal("250.0000"))
        self.assertEqual(cost, Decimal("0.00"))
        self.assertFalse(sin_tarifa)

    def test_costo_etapa_sin_tarifa_con_segundos(self):
        cost, sin_tarifa = costing.calculate_stage_cost(3300, None)
        self.assertEqual(cost, Decimal("0.00"))
        self.assertTrue(sin_tarifa)

    def test_costo_etapa_con_tarifa_y_segundos(self):
        # 3300 s = 55 minutos. 55 * 250 = 13750.00
        cost, sin_tarifa = costing.calculate_stage_cost(3300, Decimal("250.0000"))
        self.assertEqual(cost, Decimal("13750.00"))
        self.assertFalse(sin_tarifa)

    def test_costo_etapa_redondeo_al_final(self):
        # 100 s = 1.66666... min * 350.5000 = 584.1666... -> 584.17
        cost, sin_tarifa = costing.calculate_stage_cost(100, Decimal("350.5000"))
        self.assertEqual(cost, Decimal("584.17"))
        self.assertFalse(sin_tarifa)

    def test_costo_material_sin_costo_unitario(self):
        cost, sin_costo = costing.calculate_material_line_cost(Decimal("120.96"), None)
        self.assertEqual(cost, Decimal("0.00"))
        self.assertTrue(sin_costo)

    def test_costo_material_con_costo_unitario(self):
        cost, sin_costo = costing.calculate_material_line_cost(Decimal("100.00"), Decimal("18500.2500"))
        self.assertEqual(cost, Decimal("1850025.00"))
        self.assertFalse(sin_costo)

    def test_buscar_tarifa_vigente_por_fecha(self):
        d1 = date(2026, 1, 1)
        d2 = date(2026, 6, 1)
        r1 = TarifaManoObra(etapa=catalog.STAGE_CUTTING, costo_minuto=Decimal("200.0000"), vigente_desde=d1)
        r2 = TarifaManoObra(etapa=catalog.STAGE_CUTTING, costo_minuto=Decimal("250.0000"), vigente_desde=d2)
        rates = [r2, r1]

        # Antes de d1: ninguna
        self.assertIsNone(costing.find_applicable_rate(catalog.STAGE_CUTTING, date(2025, 12, 31), rates))
        # Entre d1 y d2: r1
        self.assertEqual(costing.find_applicable_rate(catalog.STAGE_CUTTING, date(2026, 3, 15), rates), r1)
        # En d2 y posterior: r2
        self.assertEqual(costing.find_applicable_rate(catalog.STAGE_CUTTING, date(2026, 6, 1), rates), r2)
        self.assertEqual(costing.find_applicable_rate(catalog.STAGE_CUTTING, date(2026, 10, 1), rates), r2)


class TarifasEndpointsTests(OrderBase):
    """Endpoints de consulta y creación de vigencias de tarifas de mano de obra (TE-129)."""

    def setUp(self):
        super().setUp()
        self.tarifas_url = reverse("produccion_tarifas")
        self.viewer = client_for(make_user("gerente_tarifas@t.co", "GERENTE"))
        self.manager = self.api  # Rol PRODUCCION tiene produccion.gestionar y produccion.ver
        self.unauthorized = client_for(make_user("almacen_tarifas@t.co", "ALMACENISTA"))

    def test_permisos_tarifas(self):
        # Anónimo 401
        self.assertEqual(self.client.get(self.tarifas_url).status_code, 401)
        self.assertEqual(self.client.post(self.tarifas_url, {}).status_code, 401)

        # Sin permisos 403
        self.assertEqual(self.unauthorized.get(self.tarifas_url).status_code, 403)
        self.assertEqual(self.unauthorized.post(self.tarifas_url, {"etapa": "CORTE", "costo_minuto": "250.0000"}).status_code, 403)

        # Viewer (GERENTE) puede GET pero no POST (403)
        self.assertEqual(self.viewer.get(self.tarifas_url).status_code, 200)
        self.assertEqual(self.viewer.post(self.tarifas_url, {"etapa": "CORTE", "costo_minuto": "250.0000"}).status_code, 403)

        # Manager (PRODUCCION) puede GET y POST
        res = self.manager.post(self.tarifas_url, {"etapa": "CORTE", "costo_minuto": "250.0000"})
        self.assertEqual(res.status_code, 201)

    def test_crear_y_listar_tarifas(self):
        res = self.manager.post(self.tarifas_url, {
            "etapa": catalog.STAGE_CUTTING,
            "costo_minuto": "275.5000",
            "vigente_desde": "2026-09-01",
        })
        self.assertEqual(res.status_code, 201)
        body = res.json()
        self.assertEqual(body["etapa"], catalog.STAGE_CUTTING)
        self.assertEqual(body["etapa_nombre"], "Corte")
        self.assertEqual(body["costo_minuto"], "275.5000")
        self.assertEqual(body["vigente_desde"], "2026-09-01")

        # Listar
        list_res = self.viewer.get(self.tarifas_url)
        self.assertEqual(list_res.status_code, 200)
        items = list_res.json()
        self.assertTrue(any(t["costo_minuto"] == "275.5000" for t in items))

    def test_vigente_desde_por_defecto_es_hoy(self):
        res = self.manager.post(self.tarifas_url, {
            "etapa": catalog.STAGE_SEWING,
            "costo_minuto": "320.0000",
        })
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["vigente_desde"], str(timezone.localdate()))

    def test_valida_costo_minuto_positivo(self):
        for bad in ("0", "-10", "abc"):
            res = self.manager.post(self.tarifas_url, {"etapa": catalog.STAGE_CUTTING, "costo_minuto": bad})
            self.assertEqual(res.status_code, 400)


class CostosEndpointTests(OrderBase):
    """Endpoint GET /api/produccion/ordenes/<id>/costos/ (TE-130)."""

    def setUp(self):
        super().setUp()
        self.viewer = client_for(make_user("gerente_costos@t.co", "GERENTE"))
        self.manager = self.api  # PRODUCCION
        self.unauthorized = client_for(make_user("almacen_costos@t.co", "ALMACENISTA"))

        # Fijar costo unitario a los materiales de la prueba
        self.tela.costo_promedio = Decimal("18500.0000")
        self.tela.save()
        self.boton.costo_promedio = Decimal("650.0000")
        self.boton.save()
        self.cierre.costo_promedio = Decimal("1200.0000")
        self.cierre.save()

        # Crear tarifas
        today = timezone.localdate()
        TarifaManoObra.objects.create(etapa=catalog.STAGE_CUTTING, costo_minuto=Decimal("250.0000"), vigente_desde=today)
        TarifaManoObra.objects.create(etapa=catalog.STAGE_SEWING, costo_minuto=Decimal("350.0000"), vigente_desde=today)
        TarifaManoObra.objects.create(etapa=catalog.STAGE_FINISHING, costo_minuto=Decimal("200.0000"), vigente_desde=today)


    def test_permisos_endpoint_costos(self):
        order_dict = self.placed(10)
        url = reverse("produccion_orden_costos", kwargs={"pk": order_dict["id"]})

        # Anónimo 401
        self.assertEqual(self.client.get(url).status_code, 401)
        # Con produccion.ver 200
        self.assertEqual(self.viewer.get(url).status_code, 200)

    def test_orden_inexistente_responde_404(self):
        url = reverse("produccion_orden_costos", kwargs={"pk": 999999})
        self.assertEqual(self.viewer.get(url).status_code, 404)

    def test_formato_exacto_respuesta_costos(self):
        # Crear orden con 2 lotes (60 y 40 prendas = 100 prendas)
        order_dict = self.placed(100, lots=[{"cantidad": 60}, {"cantidad": 40}])
        order_id = order_dict["id"]

        # Avanzar tiempos en el primer lote (lote 1: Corte 3300 s)
        lote_1_id = order_dict["lotes"][0]["id"]
        etapa_corte = EtapaLote.objects.get(lote_id=lote_1_id, etapa=catalog.STAGE_CUTTING)
        etapa_corte.acumulado_s = 3300
        etapa_corte.estado = catalog.STAGE_DONE
        etapa_corte.fin_at = timezone.now()
        etapa_corte.save()

        url = reverse("produccion_orden_costos", kwargs={"pk": order_id})
        res = self.viewer.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Validar claves principales
        self.assertIn("orden", data)
        self.assertIn("completo", data)
        self.assertIn("advertencias", data)
        self.assertIn("materiales", data)
        self.assertIn("mano_obra", data)
        self.assertIn("totales", data)
        self.assertIn("distribucion", data)

        # Orden info
        orden_info = data["orden"]
        self.assertEqual(orden_info["id"], order_id)
        self.assertEqual(orden_info["cantidad"], 100)
        self.assertFalse(orden_info["anulada"])

        # Materiales
        mat = data["materiales"]
        self.assertIn("lineas", mat)
        self.assertIn("total", mat)
        self.assertTrue(len(mat["lineas"]) >= 3)
        self.assertTrue(data["completo"])
        self.assertEqual(data["advertencias"], [])

        # Mano de obra por lote
        mo = data["mano_obra"]
        self.assertEqual(len(mo["por_lote"]), 2)
        l0 = mo["por_lote"][0]
        self.assertEqual(l0["cantidad"], 60)
        # El corte del primer lote tuvo 3300 s = 55 min * 250 = 13750.00
        etapa_corte_json = next(e for e in l0["etapas"] if e["etapa"] == catalog.STAGE_CUTTING)
        self.assertEqual(etapa_corte_json["segundos_netos"], 3300)
        self.assertEqual(etapa_corte_json["tarifa_minuto"], "250.0000")
        self.assertEqual(etapa_corte_json["costo"], "13750.00")
        self.assertFalse(etapa_corte_json["sin_tarifa"])
        self.assertFalse(etapa_corte_json["provisional"])

        # Prorrateo de materiales: lote 1 lleva 60% de materiales
        mat_total = Decimal(mat["total"])
        l0_mat = Decimal(l0["materiales_asignados"])
        self.assertEqual(l0_mat, (mat_total * Decimal("60") / Decimal("100")).quantize(Decimal("0.01")))

        # Totales
        totales = data["totales"]
        self.assertEqual(totales["materiales"], mat["total"])
        self.assertEqual(totales["mano_obra"], mo["total"])
        gran_total = Decimal(mat["total"]) + Decimal(mo["total"])
        self.assertEqual(Decimal(totales["total"]), gran_total)
        self.assertEqual(Decimal(totales["costo_por_prenda"]), (gran_total / Decimal("100")).quantize(Decimal("0.01")))

    def test_incompleto_cuando_falta_tarifa_o_costo_material(self):
        # Material sin costo (0 = desconocido)
        self.boton.costo_promedio = Decimal("0.0000")
        self.boton.save()

        # Eliminar tarifa de corte
        TarifaManoObra.objects.filter(etapa=catalog.STAGE_CUTTING).delete()

        order_dict = self.placed(50)
        lote_id = order_dict["lotes"][0]["id"]
        etapa = EtapaLote.objects.get(lote_id=lote_id, etapa=catalog.STAGE_CUTTING)
        etapa.acumulado_s = 600  # 10 min
        etapa.estado = catalog.STAGE_DONE
        etapa.fin_at = timezone.now()
        etapa.save()

        url = reverse("produccion_orden_costos", kwargs={"pk": order_dict["id"]})
        res = self.viewer.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertFalse(data["completo"])
        self.assertTrue(any("Falta la tarifa de la etapa Corte" in w for w in data["advertencias"]))
        self.assertTrue(any("El material Botón" in w and "no tiene costo" in w for w in data["advertencias"]))

    def test_orden_anulada_devuelve_costos_en_cero(self):
        order_dict = self.placed(10)
        order_id = order_dict["id"]

        # Anular la orden
        anular_url = reverse("produccion_orden_anular", kwargs={"pk": order_id})
        self.manager.post(anular_url, {"motivo": "Cancelada por error de pedido"})

        url = reverse("produccion_orden_costos", kwargs={"pk": order_id})
        res = self.viewer.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertTrue(data["orden"]["anulada"])
        self.assertEqual(data["totales"]["total"], "0.00")
        self.assertEqual(data["totales"]["materiales"], "0.00")
        self.assertEqual(data["totales"]["mano_obra"], "0.00")
        self.assertEqual(data["distribucion"]["materiales_pct"], "0.00")
        self.assertEqual(data["distribucion"]["mano_obra_pct"], "0.00")

    def test_eficiencia_consultas_no_crece_con_lotes(self):
        """Verifica que el número de consultas SQL no escala con la cantidad de lotes."""
        order_1 = self.placed(30, lots=[{"cantidad": 30}])
        order_3 = self.placed(90, lots=[{"cantidad": 30}, {"cantidad": 30}, {"cantidad": 30}])

        url_1 = reverse("produccion_orden_costos", kwargs={"pk": order_1["id"]})
        url_3 = reverse("produccion_orden_costos", kwargs={"pk": order_3["id"]})

        # Calentar autenticación/permisos del usuario
        self.viewer.get(url_1)

        with CaptureQueriesContext(connection) as ctx_1:
            self.viewer.get(url_1)
        q1 = len(ctx_1.captured_queries)

        with CaptureQueriesContext(connection) as ctx_3:
            self.viewer.get(url_3)
        q3 = len(ctx_3.captured_queries)

        # La consulta no debe escalar con el número de lotes
        self.assertEqual(q1, q3)
