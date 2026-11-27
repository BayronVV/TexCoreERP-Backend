"""Pruebas del módulo de reportes gerenciales: vistas SQL materializadas, filtros avanzados y permisos."""
from unittest import mock

from django.db import DatabaseError
from django.urls import reverse

from apps.core.testing import client_for, make_user
from apps.sales import catalog as sales_catalog
from apps.sales.test_ventas import SalesBase
from apps.users.models import ModulePermission, Role

from .models import VistaProduccionOrden, VistaVentasReferencia
from .services import clear_views_dirty, mark_views_dirty, refresh_materialized_views


class ReportesGerencialesTests(SalesBase):
    """Verifica las vistas SQL analíticas y el endpoint de reportes gerenciales sobre datos de producción y ventas."""

    def setUp(self):
        super().setUp()
        # Emitimos dos ventas para poblar la vista de ventas por referencia
        self.invoice1 = self.sell([(self.v30, 3, 10)], customer=self.wholesale).json()
        self.invoice2 = self.sell([(self.v32, 2, 0)], customer=self.retail).json()

    def test_vistas_sql_analiticas_contienen_produccion_y_ventas(self):
        refresh_materialized_views()
        prod_rows = list(VistaProduccionOrden.objects.all())
        self.assertEqual(len(prod_rows), 1)
        self.assertEqual(prod_rows[0].referencia_id, self.ref["id"])
        self.assertEqual(prod_rows[0].prendas_aptas, 90)
        self.assertEqual(prod_rows[0].prendas_marras, 5)

        sales_rows = list(VistaVentasReferencia.objects.all())
        self.assertEqual(len(sales_rows), 2)
        self.assertEqual(sum(r.unidades for r in sales_rows), 5)

    def test_metadatos_devuelve_catalogos_para_filtros(self):
        res = self.manager.get(reverse("reportes-metadatos"))
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertTrue(len(data["tipos_jean"]) > 0)
        self.assertTrue(len(data["estados_orden"]) > 0)
        self.assertTrue(len(data["estados_cobro"]) > 0)
        self.assertTrue(any(r["id"] == self.ref["id"] for r in data["referencias"]))

    def test_reporte_gerencial_consolida_kpis_produccion_y_ventas(self):
        res = self.manager.get(reverse("reportes-gerencial"))
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()

        kpis = body["kpis"]
        self.assertEqual(kpis["total_ordenes"], 1)
        self.assertEqual(kpis["prendas_aptas"], 90)
        self.assertEqual(kpis["prendas_marras"], 5)
        self.assertEqual(kpis["facturas_emitidas"], 2)
        self.assertEqual(kpis["unidades_vendidas"], 5)
        self.assertEqual(kpis["ingresos_totales"], self.invoice1["total"] + self.invoice2["total"])

        self.assertEqual(len(body["ordenes_produccion"]), 1)
        self.assertEqual(len(body["ventas_por_referencia"]), 1)
        self.assertEqual(body["ventas_por_referencia"][0]["unidades_vendidas"], 5)
        self.assertEqual(len(body["consolidado_tipo_jean"]), 1)

    def test_filtros_avanzados_por_tipo_jean_estado_orden_y_rango_fechas(self):
        # Filtrar por un tipo de jean distinto al de la referencia activa devuelve cero registros
        res_empty = self.manager.get(reverse("reportes-gerencial"), {"tipo_jean": "JOGGER"})
        self.assertEqual(res_empty.status_code, 200)
        self.assertEqual(res_empty.json()["kpis"]["total_ordenes"], 0)
        self.assertEqual(res_empty.json()["kpis"]["unidades_vendidas"], 0)

        # Filtrar por el ajuste real de la referencia devuelve los datos completos
        ajuste_real = self.ref["ajuste"]
        res_match = self.manager.get(reverse("reportes-gerencial"), {"tipo_jean": ajuste_real})
        self.assertEqual(res_match.status_code, 200)
        self.assertEqual(res_match.json()["kpis"]["total_ordenes"], 1)
        self.assertEqual(res_match.json()["kpis"]["unidades_vendidas"], 5)

        # Filtrar por estado de orden ANULADA excluye la orden actual
        res_anulada = self.manager.get(reverse("reportes-gerencial"), {"estado_orden": "ANULADA"})
        self.assertEqual(res_anulada.status_code, 200)
        self.assertEqual(len(res_anulada.json()["ordenes_produccion"]), 0)

        # Filtrar por rango de fechas futuro excluye todo
        res_futuro = self.manager.get(reverse("reportes-gerencial"), {"desde": "2099-01-01", "hasta": "2099-12-31"})
        self.assertEqual(res_futuro.status_code, 200)
        self.assertEqual(res_futuro.json()["kpis"]["total_ordenes"], 0)
        self.assertEqual(res_futuro.json()["kpis"]["unidades_vendidas"], 0)

    def test_filtro_estado_cobro_y_conciliacion_en_reporte(self):
        # Conciliamos la primera factura como PAGADO
        conciliar_url = reverse("ventas_factura_conciliar", args=[self.invoice1["id"]])
        self.manager.post(conciliar_url, {"nota": "Entregada en mano y pagada en efectivo"}, format="json")

        res_pagadas = self.manager.get(reverse("reportes-gerencial"), {"estado_cobro": sales_catalog.COLLECT_PAID})
        self.assertEqual(res_pagadas.status_code, 200)
        body = res_pagadas.json()
        self.assertEqual(body["kpis"]["facturas_emitidas"], 1)
        self.assertEqual(body["kpis"]["unidades_vendidas"], 3)
        self.assertEqual(body["kpis"]["recaudado_periodo"], self.invoice1["total"])

    def test_permisos_solo_gerente_y_admin_acceden_a_reportes(self):
        # Vendedor no tiene reportes.ver
        res_seller = self.seller.get(reverse("reportes-gerencial"))
        self.assertEqual(res_seller.status_code, 403)

        # Refrescar vistas permitido para gerente
        res_refresh = self.manager.post(reverse("reportes-refrescar"))
        self.assertEqual(res_refresh.status_code, 200)
        self.assertIn("refreshed", res_refresh.json())

    def test_refrescar_las_vistas_exige_gestion_y_no_basta_con_consultar(self):
        role = Role.objects.create(code="CONSULTOR", name="Consultor")
        role.permissions.set(ModulePermission.objects.filter(code="reportes.ver"))
        reader = client_for(make_user("consultor@t.co", "CONSULTOR"))
        reader_res = reader.get(reverse("reportes-gerencial"))
        self.assertEqual(reader_res.status_code, 200)  # consulta: sí
        self.assertIsNone(reader_res.json()["kpis"]["saldo_financiero_empresa"])  # sin ventas.conciliar no ve la caja
        denied = reader.post(reverse("reportes-refrescar"))
        self.assertEqual(denied.status_code, 403)  # refrescar: no, solo con reportes.gestionar

        self.manager.post(
            reverse("ventas_factura_conciliar", args=[self.invoice1["id"]]),
            {"nota": "Entregada en mano y pagada en efectivo"},
            format="json",
        )
        manager_res = self.manager.get(reverse("reportes-gerencial"))
        self.assertEqual(manager_res.status_code, 200)
        self.assertEqual(manager_res.json()["kpis"]["saldo_financiero_empresa"], self.invoice1["total"])
        self.assertEqual(self.manager.post(reverse("reportes-refrescar")).status_code, 200)

    def test_fechas_y_referencia_invalidas_responden_400_con_mensaje(self):
        url = reverse("reportes-gerencial")
        bad_desde = self.manager.get(url, {"desde": "abc"})
        self.assertEqual(bad_desde.status_code, 400)
        self.assertIn("desde", bad_desde.json())

        bad_hasta = self.manager.get(url, {"hasta": "2026-99-99"})
        self.assertEqual(bad_hasta.status_code, 400)
        self.assertIn("hasta", bad_hasta.json())

        inverted = self.manager.get(url, {"desde": "2026-12-31", "hasta": "2026-01-01"})
        self.assertEqual(inverted.status_code, 400)
        self.assertIn("posterior", str(inverted.json()["desde"][0]))

        bad_ref = self.manager.get(url, {"referencia": "no-es-id"})
        self.assertEqual(bad_ref.status_code, 400)
        self.assertIn("referencia", bad_ref.json())

    def test_abrir_reporte_dos_veces_seguidas_no_refresca_dos_veces(self):
        clear_views_dirty()
        url = reverse("reportes-gerencial")
        with mock.patch("apps.reports.services.refresh_materialized_views", wraps=refresh_materialized_views) as refresh_spy:
            first = self.manager.get(url)
            second = self.manager.get(url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(refresh_spy.call_count, 0)

        mark_views_dirty()
        with mock.patch("apps.reports.services.refresh_materialized_views", wraps=refresh_materialized_views) as refresh_spy:
            after_change = self.manager.get(url)
            repeated = self.manager.get(url)
        self.assertEqual(after_change.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(refresh_spy.call_count, 1)

    def test_error_al_refrescar_vistas_responde_503_controlado(self):
        with mock.patch("apps.reports.services.refresh_materialized_views", side_effect=DatabaseError("fallo simulado")):
            response = self.manager.post(reverse("reportes-refrescar"))
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["refreshed"])
        self.assertIn("No fue posible actualizar", response.json()["detail"])
