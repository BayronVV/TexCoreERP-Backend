"""Pruebas de HU 7.7 (TE-177): filtros combinables, paginación (>200), devoluciones por vendedor, fechas inválidas y cero N+1."""
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.testing import client_for, make_user
from apps.finished.models import MovimientoTerminado
from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Movimiento, Producto
from apps.sales.models import FacturaVenta
from apps.sales.test_ventas import SalesBase
from apps.shipping import catalog as shipping_catalog
from apps.shipping.models import Guia


class FiltrosPaginacionYDevolucionesTests(SalesBase):
    """Cubre los escenarios de aceptación de TE-177 en todos los listados y en el tablero gerencial."""

    def test_escenario1_filtros_combinados_en_facturas(self):
        other_seller_user = make_user("vendedor2_177@t.co", "VENDEDOR", first_name="Laura", last_name="Méndez")
        other_seller = client_for(other_seller_user)
        seller_user = FacturaVenta.objects.create if False else self.wholesale  # solo referencia visual

        inv_match = self.sell([(self.v30, 1, 0)], customer=self.wholesale).json()
        inv_wrong_client = self.sell([(self.v30, 1, 0)], customer=self.retail).json()
        inv_wrong_seller = self.sell([(self.v32, 1, 0)], customer=self.wholesale, client=other_seller).json()
        inv_old_date = self.sell([(self.v32, 1, 0)], customer=self.wholesale).json()

        today = timezone.localdate()
        old_day = today - timedelta(days=20)
        FacturaVenta.objects.filter(pk=inv_old_date["id"]).update(fecha=old_day)
        FacturaVenta.objects.filter(pk=inv_match["id"]).update(fecha=today)

        self.assertIsNotNone(seller_user)
        match_obj = FacturaVenta.objects.get(pk=inv_match["id"])
        res = self.seller.get(
            reverse("ventas_facturas"),
            {
                "vendedor": match_obj.vendedor_id,
                "cliente": self.wholesale.id,
                "desde": (today - timedelta(days=1)).isoformat(),
                "hasta": today.isoformat(),
                "referencia": self.ref["id"],
                "page": 1,
                "page_size": 25,
            },
        )
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual([r["id"] for r in body["results"]], [inv_match["id"]])
        self.assertNotIn(inv_wrong_client["id"], [r["id"] for r in body["results"]])
        self.assertNotIn(inv_wrong_seller["id"], [r["id"] for r in body["results"]])
        self.assertNotIn(inv_old_date["id"], [r["id"] for r in body["results"]])

    def test_escenario2_paginacion_mayor_a_200_movimientos_y_retrocompatibilidad(self):
        user = make_user("pag_177@t.co", "ALMACENISTA")
        today = timezone.localdate()
        product = Producto.objects.order_by("id").first()
        self.assertIsNotNone(product)
        base_moves = [
            Movimiento(
                producto=product,
                tipo="INGRESO",
                motivo=inventory_catalog.REASON_PURCHASE,
                cantidad=Decimal("1.00"),
                stock_antes=Decimal("100.00"),
                stock_despues=Decimal("101.00"),
                fecha=today,
                lote=f"LOT-PAG-{i:03d}",
                registrado_por=user,
            )
            for i in range(215)
        ]
        Movimiento.objects.bulk_create(base_moves)
        total_expected = Movimiento.objects.count()
        self.assertGreaterEqual(total_expected, 215)

        url = reverse("inventario_movimientos")
        collected_ids = []
        page = 1
        while True:
            res = self.viewer.get(url, {"page": page, "page_size": 50})
            self.assertEqual(res.status_code, 200, res.content)
            payload = res.json()
            self.assertEqual(payload["count"], total_expected)
            self.assertEqual(payload["page"], page)
            self.assertEqual(payload["page_size"], 50)
            collected_ids.extend(row["id"] for row in payload["results"])
            if payload["next"] is None:
                break
            page = payload["next"]

        self.assertEqual(len(collected_ids), total_expected)
        self.assertEqual(len(set(collected_ids)), total_expected)

        # Retrocompatibilidad: sin ?page= sigue devolviendo un arreglo JSON plano
        legacy = self.viewer.get(url)
        self.assertEqual(legacy.status_code, 200)
        self.assertIsInstance(legacy.json(), list)

    def test_escenario3_devoluciones_por_vendedor_y_filtros_tablero(self):
        seller_b_user = make_user("vendedor_b_177@t.co", "VENDEDOR", first_name="Camilo", last_name="Rojas")
        seller_b = client_for(seller_b_user)

        # Factura 1 con 2 líneas del vendedor principal: flete $12.000 NO debe duplicarse por línea
        inv1 = self.sell([(self.v30, 1, 0), (self.v32, 1, 0)], customer=self.wholesale).json()
        inv2 = self.sell([(self.v34, 1, 0)], customer=self.retail).json()
        inv3 = self.sell([(self.v30, 1, 0)], customer=self.wholesale, client=seller_b).json()

        f1 = FacturaVenta.objects.get(pk=inv1["id"])
        f2 = FacturaVenta.objects.get(pk=inv2["id"])
        f3 = FacturaVenta.objects.get(pk=inv3["id"])

        Guia.objects.create(
            factura=f1,
            transportadora="INTERRAPIDISIMO",
            numero_guia="GUIA-DEV-1",
            estado=shipping_catalog.RETURNED,
            vigente=True,
            flete_vendedor=12_000,
        )
        Guia.objects.create(
            factura=f2,
            transportadora="INTERRAPIDISIMO",
            numero_guia="GUIA-DEV-2",
            estado=shipping_catalog.RETURNED,
            vigente=True,
            flete_vendedor=9_000,
        )
        Guia.objects.create(
            factura=f3,
            transportadora="ENVIA",
            numero_guia="GUIA-DEV-3",
            estado=shipping_catalog.RETURNED,
            vigente=True,
            flete_vendedor=7_000,
        )
        # Reconciliar o mantener transportadora en FacturaVenta para consistencia de ventas
        FacturaVenta.objects.filter(pk__in=(f1.id, f2.id)).update(transportadora="INTERRAPIDISIMO")
        FacturaVenta.objects.filter(pk=f3.id).update(transportadora="ENVIA")

        res_all = self.manager.get(reverse("reportes-gerencial"))
        self.assertEqual(res_all.status_code, 200, res_all.content)
        data_all = res_all.json()
        self.assertEqual(data_all["kpis"]["devoluciones_guias"], 3)
        self.assertEqual(data_all["kpis"]["flete_devoluciones_total"], 28_000)

        by_seller = {row["vendedor_id"]: row for row in data_all["devoluciones_por_vendedor"]}
        self.assertEqual(by_seller[f1.vendedor_id]["guias_devueltas"], 2)
        self.assertEqual(by_seller[f1.vendedor_id]["flete_vendedor"], 21_000)
        self.assertEqual(by_seller[seller_b_user.id]["guias_devueltas"], 1)
        self.assertEqual(by_seller[seller_b_user.id]["flete_vendedor"], 7_000)

        # Filtro combinado por vendedor y transportadora en el tablero
        res_filtered = self.manager.get(
            reverse("reportes-gerencial"),
            {"vendedor": f1.vendedor_id, "transportadora": "INTERRAPIDISIMO", "referencia": self.ref["id"]},
        )
        self.assertEqual(res_filtered.status_code, 200, res_filtered.content)
        filtered = res_filtered.json()
        self.assertEqual(filtered["kpis"]["facturas_emitidas"], 2)
        self.assertEqual(filtered["kpis"]["devoluciones_guias"], 2)
        self.assertEqual(filtered["kpis"]["flete_devoluciones_total"], 21_000)
        self.assertEqual(len(filtered["devoluciones_por_vendedor"]), 1)
        self.assertEqual(filtered["devoluciones_por_vendedor"][0]["flete_vendedor"], 21_000)

    def test_escenario4_filtros_invalidos_responden_400_y_no_500(self):
        endpoints = [
            reverse("reportes-gerencial"),
            reverse("ventas_facturas"),
            reverse("envios_guias"),
            reverse("produccion_ordenes"),
            reverse("produccion_lotes"),
            reverse("produccion_monitor"),
            reverse("calidad_inspecciones"),
            reverse("inventario_movimientos"),
            reverse("terminado_movimientos"),
        ]
        for url in endpoints:
            bad_date = self.admin.get(url, {"desde": "2026-13-45"})
            self.assertEqual(bad_date.status_code, 400, f"{url} -> {bad_date.status_code}: {bad_date.content}")

            inverted = self.admin.get(url, {"desde": "2026-12-10", "hasta": "2026-12-01"})
            self.assertEqual(inverted.status_code, 400, f"{url} -> {inverted.status_code}: {inverted.content}")

        # Parámetros de paginación o IDs inválidos también responden 400
        bad_page = self.admin.get(reverse("ventas_facturas"), {"page": "0"})
        self.assertEqual(bad_page.status_code, 400)
        bad_seller = self.manager.get(reverse("reportes-gerencial"), {"vendedor": "abc"})
        self.assertEqual(bad_seller.status_code, 400)

    def test_escenario5_permisos_reportes_y_metadatos_con_vendedores(self):
        self.assertEqual(self.seller.get(reverse("reportes-gerencial")).status_code, 403)
        self.assertEqual(self.seller.get(reverse("reportes-metadatos")).status_code, 403)

        rep_meta = self.manager.get(reverse("reportes-metadatos")).json()
        self.assertTrue(len(rep_meta["vendedores"]) >= 1)
        self.assertTrue(len(rep_meta["transportadoras"]) >= 1)

        sales_meta = self.seller.get(reverse("ventas_metadatos")).json()
        self.assertTrue(len(sales_meta["vendedores"]) >= 1)

        ship_meta = self.seller.get(reverse("envios_metadatos")).json()
        self.assertTrue(len(ship_meta["vendedores"]) >= 1)

    def test_filtros_combinables_en_guias_ordenes_lotes_inspecciones_y_movimientos(self):
        inv = self.sell([(self.v30, 1, 0)], customer=self.wholesale).json()
        f = FacturaVenta.objects.get(pk=inv["id"])
        Guia.objects.create(
            factura=f,
            transportadora="INTERRAPIDISIMO",
            numero_guia="GUIA-FILTRO-1",
            estado=shipping_catalog.IN_TRANSIT,
            vigente=True,
        )
        # Guías filtradas por cliente + vendedor + transportadora + referencia + estado
        g_res = self.seller.get(
            reverse("envios_guias"),
            {
                "cliente": self.wholesale.id,
                "vendedor": f.vendedor_id,
                "transportadora": "INTERRAPIDISIMO",
                "referencia": self.ref["id"],
                "estado": shipping_catalog.IN_TRANSIT,
                "page": 1,
            },
        )
        self.assertEqual(g_res.status_code, 200, g_res.content)
        self.assertEqual(g_res.json()["count"], 1)

        # Órdenes de producción y Lotes
        o_res = self.admin.get(
            reverse("produccion_ordenes"),
            {"referencia": self.ref["id"], "lote": self.lot1.codigo, "page": 1},
        )
        self.assertEqual(o_res.status_code, 200, o_res.content)
        self.assertEqual(o_res.json()["count"], 1)

        l_res = self.admin.get(
            reverse("produccion_lotes"),
            {"referencia": self.ref["id"], "lote": self.lot1.codigo, "estado": "PLANEADA", "paginado": "1"},
        )
        self.assertEqual(l_res.status_code, 200, l_res.content)
        self.assertEqual(l_res.json()["count"], 1)
        self.assertEqual(l_res.json()["results"][0]["codigo"], self.lot1.codigo)

        # Monitor con filtro textual y fecha
        m_res = self.admin.get(reverse("produccion_monitor"), {"q": self.lot1.codigo})
        self.assertEqual(m_res.status_code, 200, m_res.content)

        # Inspecciones con estado CON_MARRAS y referencia
        i_res = self.admin.get(
            reverse("calidad_inspecciones"),
            {"referencia": self.ref["id"], "estado": "CON_MARRAS", "page": 1},
        )
        self.assertEqual(i_res.status_code, 200, i_res.content)
        self.assertEqual(i_res.json()["count"], 1)

        # Movimientos producto terminado filtrados por cliente, vendedor y tipo
        self.assertTrue(MovimientoTerminado.objects.exists())
        mt_res = self.seller.get(
            reverse("terminado_movimientos"),
            {
                "tipo": "SALIDA_VENTA",
                "referencia": self.ref["id"],
                "cliente": self.wholesale.id,
                "vendedor": f.vendedor_id,
                "page": 1,
            },
        )
        self.assertEqual(mt_res.status_code, 200, mt_res.content)
        self.assertEqual(mt_res.json()["count"], 1)

    def test_listados_paginados_con_consultas_acotadas_sin_n_mas_1(self):
        for _ in range(4):
            inv = self.sell([(self.v30, 1, 0)], customer=self.wholesale).json()
            f = FacturaVenta.objects.get(pk=inv["id"])
            Guia.objects.create(
                factura=f,
                transportadora="INTERRAPIDISIMO",
                numero_guia=f"G-N1-{f.id}",
                estado=shipping_catalog.PENDING,
                vigente=True,
            )

        urls = [
            reverse("ventas_facturas"),
            reverse("envios_guias"),
            reverse("produccion_ordenes"),
            reverse("produccion_lotes"),
            reverse("calidad_inspecciones"),
            reverse("inventario_movimientos"),
            reverse("terminado_movimientos"),
        ]
        for url in urls:
            self.admin.get(url, {"page": 1, "page_size": 1})
            with CaptureQueriesContext(connection) as q_small:
                r1 = self.admin.get(url, {"page": 1, "page_size": 1})
            with CaptureQueriesContext(connection) as q_large:
                r2 = self.admin.get(url, {"page": 1, "page_size": 4})
            self.assertEqual(r1.status_code, 200, f"{url}: {r1.content}")
            self.assertEqual(r2.status_code, 200, f"{url}: {r2.content}")
            self.assertEqual(
                len(q_small),
                len(q_large),
                f"Posible N+1 en {url}: page_size=1 usó {len(q_small)} queries vs {len(q_large)} para page_size=4",
            )
