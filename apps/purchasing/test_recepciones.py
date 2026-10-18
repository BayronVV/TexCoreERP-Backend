"""Recepción de mercancía: contra una orden aprobada (parcial y completa) y suelta, tolerancia, atomicidad, permisos y costos."""
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.inventory.models import Movimiento
from apps.inventory.tests import client_for, make_user, today

from .models import OrdenCompra, Recepcion, RecepcionLinea
from .test_ordenes_compra import PurchasingBase


class ReceiveBase(PurchasingBase):
    def setUp(self):
        super().setUp()
        self.receipts_url = reverse("compras_recepciones")

    def receipt_body(self, order, rows, **extra):
        body = {"orden": order["id"], "documento": "REM-1001", "lineas": rows}
        body.update(extra)
        return body

    def receive(self, body, client=None):
        return (client or self.store).post(self.receipts_url, body, format="json")

    def received(self, body, client=None):
        response = self.receive(body, client)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def row(self, order, index, quantity, lote="L-001", **extra):
        row = {"linea": order["lineas"][index]["id"], "cantidad": str(quantity), "lote": lote}
        row.update(extra)
        return row

    def order_state(self, order):
        return OrdenCompra.objects.get(pk=order["id"]).estado

    def counts(self):
        return Recepcion.objects.count(), RecepcionLinea.objects.count(), Movimiento.objects.count()

    def stocks(self):
        self.refresh(self.tela, self.cierre, self.boton)
        return self.tela.stock_actual, self.cierre.stock_actual, self.boton.stock_actual


class RecibirContraOrdenTests(ReceiveBase):
    def test_recepcion_parcial_suma_al_stock_y_deja_la_orden_parcial(self):
        order = self.approved()  # 100 m de tela y 50 cierres
        receipt = self.received(self.receipt_body(order, [self.row(order, 0, 60, "L-A", costo_unitario="18000")]))
        self.assertEqual((receipt["codigo"], receipt["orden_codigo"], receipt["orden_estado"]), ("RC-0001", "OC-0001", "RECIBIDA_PARCIAL"))
        self.assertEqual((receipt["proveedor_nombre"], receipt["documento"]), ("Textiles SA", "REM-1001"))
        self.assertEqual(self.stocks()[0], Decimal("1060"))
        self.assertEqual(self.order_state(order), "RECIBIDA_PARCIAL")
        line = self.store.get(self.order_url(order["id"])).json()["lineas"][0]
        self.assertEqual((line["cantidad_recibida"], line["pendiente"], line["completa"]), ("60.00", "40.00", False))

    def test_el_kardex_y_el_costo_promedio_salen_del_ingreso(self):
        order = self.approved()
        self.received(self.receipt_body(order, [self.row(order, 0, 100, "L-A", costo_unitario="20000")]))
        movement = Movimiento.objects.get(producto=self.tela, tipo="INGRESO")
        self.assertEqual((movement.motivo, movement.orden_compra, movement.lote), ("COMPRA", "OC-0001", "L-A"))
        self.assertEqual((movement.proveedor_id, movement.costo_unitario, movement.stock_antes, movement.stock_despues),
                         (self.supplier.id, Decimal("20000"), Decimal("1000"), Decimal("1100")))
        self.assertIn("RC-0001", movement.observaciones)
        self.assertIn("REM-1001", movement.observaciones)
        self.refresh(self.tela)
        self.assertEqual(self.tela.costo_promedio, Decimal("20000.0000"))  # la tela del almacén no tenía costo: manda el de la compra
        link = RecepcionLinea.objects.get()
        self.assertEqual((link.movimiento_id, link.costo_unitario, link.lote), (movement.id, Decimal("20000"), "L-A"))

    def test_sin_costo_el_promedio_no_cambia(self):
        order = self.approved()
        self.received(self.receipt_body(order, [self.row(order, 1, 10)]))
        self.refresh(self.cierre)
        self.assertEqual(self.cierre.costo_promedio, Decimal(0))
        self.assertIsNone(RecepcionLinea.objects.get().costo_unitario)

    def test_la_segunda_recepcion_completa_la_orden(self):
        order = self.approved()
        self.received(self.receipt_body(order, [self.row(order, 0, 60, "L-A")]))
        second = self.received(self.receipt_body(order, [self.row(order, 0, 40, "L-B"), self.row(order, 1, 50, "L-C")], documento="REM-1002"))
        self.assertEqual((second["codigo"], second["orden_estado"]), ("RC-0002", "RECIBIDA"))
        self.assertEqual(self.order_state(order), "RECIBIDA")
        self.assertEqual(self.stocks()[:2], (Decimal("1100"), Decimal("550")))
        detail = self.store.get(self.order_url(order["id"])).json()
        self.assertEqual([line["completa"] for line in detail["lineas"]], [True, True])
        self.assertEqual([r["codigo"] for r in detail["recepciones"]], ["RC-0001", "RC-0002"])

    def test_varias_filas_en_una_recepcion_son_una_sola_entrega(self):
        order = self.approved()
        receipt = self.received(self.receipt_body(order, [self.row(order, 0, 30, "L-A"), self.row(order, 1, 20, "L-B")]))
        self.assertEqual(len(receipt["lineas"]), 2)
        self.assertEqual(self.counts(), (1, 2, 2))
        self.assertEqual({row["lote"] for row in receipt["lineas"]}, {"L-A", "L-B"})

    def test_un_mismo_producto_en_dos_lotes(self):
        order = self.approved()
        receipt = self.received(self.receipt_body(order, [self.row(order, 0, 40, "L-A"), self.row(order, 0, 60, "L-B")]))
        self.assertEqual(sorted(row["lote"] for row in receipt["lineas"]), ["L-A", "L-B"])
        self.assertEqual(self.stocks()[0], Decimal("1100"))
        self.assertEqual(Movimiento.objects.filter(producto=self.tela, tipo="INGRESO").count(), 2)

    def test_listado_y_filtro_por_orden(self):
        first, second = self.approved(), self.approved()
        self.received(self.receipt_body(first, [self.row(first, 0, 10)]))
        self.received(self.receipt_body(second, [self.row(second, 0, 10)], documento="REM-2"))
        listed = self.manager.get(self.receipts_url).json()
        self.assertEqual([r["codigo"] for r in listed], ["RC-0002", "RC-0001"])
        self.assertEqual([r["codigo"] for r in self.manager.get(self.receipts_url, {"orden": first["id"]}).json()], ["RC-0001"])
        self.assertEqual(len(self.manager.get(self.receipts_url, {"proveedor": self.supplier.id}).json()), 2)
        self.assertEqual(self.manager.get(self.receipts_url, {"orden": "x"}).status_code, 400)

    def test_la_orden_se_puede_cerrar_a_mano_con_una_recepcion_parcial(self):
        order = self.approved()
        self.received(self.receipt_body(order, [self.row(order, 0, 60)]))
        closed = self.close(order["id"], "El proveedor no tiene más tela")
        self.assertEqual(closed.status_code, 200, closed.content)
        self.assertEqual((closed.json()["estado"], closed.json()["motivo_cierre"]), ("CERRADA", "El proveedor no tiene más tela"))
        self.assertEqual(self.cancel(order["id"]).status_code, 400)  # con recepciones ya no se cancela
        again = self.receive(self.receipt_body(order, [self.row(order, 0, 5)], documento="REM-X"))
        self.assertEqual(again.status_code, 400)
        self.assertIn("cerrada", str(again.json()))


class TolerianciaTests(ReceiveBase):
    def test_se_puede_recibir_hasta_el_cinco_por_ciento_de_mas(self):
        order = self.approved([{"producto": self.tela.id, "cantidad": "100"}])
        self.received(self.receipt_body(order, [self.row(order, 0, 105)]))  # 100 + 5 %
        self.assertEqual(self.order_state(order), "RECIBIDA")
        self.assertEqual(self.stocks()[0], Decimal("1105"))

    def test_mas_del_cinco_por_ciento_se_rechaza(self):
        order = self.approved([{"producto": self.tela.id, "cantidad": "100"}])
        before = self.counts()
        response = self.receive(self.receipt_body(order, [self.row(order, 0, "105.01")]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Fila 1", response.json()["lineas"][0])
        self.assertIn("hasta 105 m", response.json()["lineas"][0])
        self.assertEqual((self.counts(), self.stocks()[0]), (before, Decimal("1000")))

    def test_la_tolerancia_es_sobre_lo_pendiente_y_acumula_entre_filas(self):
        order = self.approved([{"producto": self.tela.id, "cantidad": "100"}, {"producto": self.cierre.id, "cantidad": "10"}])
        # 60 + 50 = 110 supera el máximo (105) aunque cada fila por separado cabe.
        self.assertEqual(self.receive(self.receipt_body(order, [self.row(order, 0, 60), self.row(order, 0, 50, "L-B")])).status_code, 400)
        self.assertEqual(self.receive(self.receipt_body(order, [self.row(order, 0, 60), self.row(order, 0, 45, "L-B")])).status_code, 201)

    def test_lo_ya_recibido_cuenta_para_el_maximo(self):
        order = self.approved([{"producto": self.tela.id, "cantidad": "100"}, {"producto": self.cierre.id, "cantidad": "10"}])
        self.received(self.receipt_body(order, [self.row(order, 0, 100)]))  # tela completa; la orden sigue parcial por el cierre
        self.assertEqual(self.order_state(order), "RECIBIDA_PARCIAL")
        response = self.receive(self.receipt_body(order, [self.row(order, 0, 1, "L-B")], documento="REM-2"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("faltan 0 m", response.json()["lineas"][0])

    def test_una_unidad_entera_redondea_el_maximo_hacia_abajo(self):
        order = self.approved([{"producto": self.cierre.id, "cantidad": "10"}])  # 10 + 5 % = 10,5 → 10 unidades enteras
        self.assertEqual(self.receive(self.receipt_body(order, [self.row(order, 0, 11)])).status_code, 400)
        self.assertEqual(self.receive(self.receipt_body(order, [self.row(order, 0, 10)])).status_code, 201)


class AtomicidadTests(ReceiveBase):
    def test_si_una_fila_falla_no_queda_ninguna(self):
        order = self.approved()
        before, stocks = self.counts(), self.stocks()
        rows = [self.row(order, 0, 30, "L-A"), self.row(order, 1, 10, "")]  # la segunda no trae lote
        response = self.receive(self.receipt_body(order, rows))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Fila 2", response.json()["lineas"][0])
        self.assertIn("lote", response.json()["lineas"][0])
        self.assertEqual((self.counts(), self.stocks()), (before, stocks))
        self.assertEqual(self.order_state(order), "APROBADA")

    def test_un_costo_invalido_en_la_ultima_fila_deshace_todo(self):
        order = self.approved()
        before, stocks = self.counts(), self.stocks()
        rows = [self.row(order, 0, 30, "L-A", costo_unitario="18000"), self.row(order, 1, 10, "L-B", costo_unitario="-5")]
        response = self.receive(self.receipt_body(order, rows))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Fila 2", response.json()["lineas"][0])
        self.assertEqual((self.counts(), self.stocks()), (before, stocks))
        self.refresh(self.tela)
        self.assertEqual(self.tela.costo_promedio, Decimal(0))  # el costo de la primera fila tampoco quedó

    def test_el_consecutivo_no_salta_cuando_se_rechaza(self):
        order = self.approved()
        self.receive(self.receipt_body(order, [self.row(order, 0, 30, "")]))
        self.assertEqual(self.received(self.receipt_body(order, [self.row(order, 0, 30)]))["codigo"], "RC-0001")


class ReglasDeLaOrdenTests(ReceiveBase):
    def test_solo_se_recibe_contra_una_orden_aprobada(self):
        draft = self.placed()
        for order, state in ((draft, "borrador"),):
            response = self.receive(self.receipt_body(order, [self.row(order, 0, 5)]))
            self.assertEqual(response.status_code, 400)
            self.assertIn(state, str(response.json()["orden"]))
        cancelled = self.approved()
        self.cancel(cancelled["id"])
        self.assertEqual(self.receive(self.receipt_body(cancelled, [self.row(cancelled, 0, 5)])).status_code, 400)
        done = self.approved([{"producto": self.tela.id, "cantidad": "10"}])
        self.received(self.receipt_body(done, [self.row(done, 0, 10)]))
        response = self.receive(self.receipt_body(done, [self.row(done, 0, 1)], documento="REM-9"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("recibida", str(response.json()["orden"]))
        self.assertEqual(Recepcion.objects.count(), 1)

    def test_quien_creo_la_orden_no_la_recibe(self):
        admin = client_for(make_user("admin_r@t.co", "ADMIN"))  # tiene ambos permisos: el de compras y el de inventario
        order = self.placed(client=admin)
        self.approve(order["id"])
        response = self.receive(self.receipt_body(order, [self.row(order, 0, 5)]), client=admin)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Quien creó la orden", str(response.json()["orden"]))
        self.assertEqual(self.receive(self.receipt_body(order, [self.row(order, 0, 5)])).status_code, 201)  # el almacenista, sí

    def test_orden_inexistente(self):
        response = self.receive({"orden": 99999, "documento": "R", "lineas": [{"linea": 1, "cantidad": "1", "lote": "L"}]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("orden", response.json())

    def test_las_filas_deben_ser_lineas_de_la_orden(self):
        order, other = self.approved(), self.approved()
        foreign = self.row(other, 0, 5)  # línea de otra orden
        for row, text in (
            (foreign, "indica una línea de la orden OC-0001"),
            ({"cantidad": "5", "lote": "L"}, "indica una línea"),
            ({"linea": 99999, "cantidad": "5", "lote": "L"}, "indica una línea"),
            ({"producto": self.tela.id, "cantidad": "5", "lote": "L"}, "indica una línea"),
        ):
            response = self.receive(self.receipt_body(order, [row]))
            self.assertEqual(response.status_code, 400, row)
            self.assertIn(text, response.json()["lineas"][0])
        self.assertEqual(Recepcion.objects.count(), 0)

    def test_la_fecha_no_puede_ser_futura_ni_anterior_a_la_orden(self):
        order = self.approved()
        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.assertEqual(self.receive(self.receipt_body(order, [self.row(order, 0, 5)], fecha=future)).status_code, 400)
        old = self.placed(fecha=(timezone.localdate() - timedelta(days=2)).isoformat())
        self.approve(old["id"])
        before = (timezone.localdate() - timedelta(days=5)).isoformat()
        response = self.receive(self.receipt_body(old, [self.row(old, 0, 5)], fecha=before))
        self.assertEqual(response.status_code, 400)
        self.assertIn("anterior a la fecha de la orden", str(response.json()))

    def test_valida_documento_cantidad_y_filas(self):
        order = self.approved()
        for body, field in (
            (self.receipt_body(order, [self.row(order, 0, 5)], documento=""), "documento"),
            (self.receipt_body(order, [self.row(order, 0, 5)], documento="   "), "documento"),
            (self.receipt_body(order, []), "lineas"),
            (self.receipt_body(order, "tela"), "lineas"),
            (self.receipt_body(order, [self.row(order, 0, 0)]), "lineas"),
            (self.receipt_body(order, [self.row(order, 0, "abc")]), "lineas"),
            (self.receipt_body(order, [self.row(order, 1, "2.5")]), "lineas"),  # el cierre es unidad entera
            (self.receipt_body(order, ["fila"]), "lineas"),
        ):
            response = self.receive(body)
            self.assertEqual(response.status_code, 400, (body, response.content))
            self.assertIn(field, response.json())
        self.assertEqual(Recepcion.objects.count(), 0)


class RecepcionSueltaTests(ReceiveBase):
    def loose(self, rows, **extra):
        body = {"proveedor": self.supplier.id, "documento": "FAC-77", "lineas": rows}
        body.update(extra)
        return body

    def test_varios_productos_de_un_proveedor_sin_orden(self):
        rows = [
            {"producto": self.tela.id, "cantidad": "20", "lote": "L-1", "costo_unitario": "19000"},
            {"producto": self.cierre.id, "cantidad": "100", "lote": "L-2"},
            {"producto": self.boton.id, "cantidad": "40", "lote": "L-3"},
        ]
        receipt = self.received(self.loose(rows))
        self.assertEqual((receipt["codigo"], receipt["orden"], receipt["orden_codigo"], receipt["orden_estado"]), ("RC-0001", None, None, None))
        self.assertEqual(len(receipt["lineas"]), 3)
        self.assertEqual(self.stocks(), (Decimal("1020"), Decimal("600"), Decimal("340")))
        self.assertEqual(Movimiento.objects.filter(orden_compra="", motivo="COMPRA").count(), 3)
        self.refresh(self.tela)
        self.assertEqual(self.tela.costo_promedio, Decimal("19000.0000"))

    def test_exige_proveedor_y_solo_materia_prima_o_insumos(self):
        row = {"producto": self.tela.id, "cantidad": "5", "lote": "L"}
        self.assertEqual(self.receive({"documento": "F", "lineas": [row]}).status_code, 400)
        self.assertEqual(self.receive(self.loose([row], proveedor=99999)).status_code, 400)
        generic = {"producto": self.generico.id, "cantidad": "5", "lote": "L"}
        response = self.receive(self.loose([generic]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("no se compra", response.json()["lineas"][0])
        self.assertEqual(Recepcion.objects.count(), 0)

    def test_una_fila_sin_producto_o_con_linea(self):
        for row, text in (
            ({"cantidad": "5", "lote": "L"}, "indica el producto"),
            ({"producto": self.tela.id, "linea": 1, "cantidad": "5", "lote": "L"}, "sin orden no lleva línea"),
            ({"producto": 99999, "cantidad": "5", "lote": "L"}, "no existe"),
        ):
            response = self.receive(self.loose([row]))
            self.assertEqual(response.status_code, 400, row)
            self.assertIn(text, str(response.json()))

    def test_el_producto_repetido_con_dos_lotes_es_valido(self):
        rows = [{"producto": self.tela.id, "cantidad": "10", "lote": "L-1"}, {"producto": self.tela.id, "cantidad": "15", "lote": "L-2"}]
        self.assertEqual(len(self.received(self.loose(rows))["lineas"]), 2)
        self.assertEqual(self.stocks()[0], Decimal("1025"))

    def test_el_proveedor_archivado_se_rechaza(self):
        self.supplier.delete()
        response = self.receive(self.loose([{"producto": self.tela.id, "cantidad": "5", "lote": "L"}]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("proveedor", response.json())


class PermisosDeRecepcionTests(ReceiveBase):
    def test_solo_el_almacenista_recibe(self):
        order = self.approved()
        body = self.receipt_body(order, [self.row(order, 0, 5)])
        self.assertEqual(self.client.post(self.receipts_url, body, format="json").status_code, 401)
        for client in (self.producer, self.manager, client_for(make_user("vendedor_r@t.co", "VENDEDOR"))):
            self.assertEqual(self.receive(body, client).status_code, 403)
        self.assertEqual(Recepcion.objects.count(), 0)
        self.assertEqual(self.receive(body).status_code, 201)

    def test_quien_puede_ver_las_recepciones(self):
        for client in (self.producer, self.manager, self.store):
            self.assertEqual(client.get(self.receipts_url).status_code, 200)
        self.assertEqual(self.client.get(self.receipts_url).status_code, 401)
        self.assertEqual(client_for(make_user("vendedor_l@t.co", "VENDEDOR")).get(self.receipts_url).status_code, 403)


class RegresionDelIngresoTests(ReceiveBase):
    def test_el_ingreso_suelto_de_un_producto_sigue_funcionando(self):
        body = {"producto": self.tela.id, "cantidad": "50", "fecha": today(), "proveedor": self.supplier.id, "orden_compra": "OC-LIBRE", "lote": "L-9"}
        response = self.store.post(reverse("inventario_ingresos"), body, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.stocks()[0], Decimal("1050"))
        self.assertEqual(Recepcion.objects.count(), 0)  # no pasa por compras
