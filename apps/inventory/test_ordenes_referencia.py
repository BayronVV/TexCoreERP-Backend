"""Órdenes de salida sobre una referencia de jean (HU 3.2): la referencia reemplaza al texto libre `ficha_tecnica`."""
from decimal import Decimal

from django.urls import reverse

from apps.references import catalog as reference_catalog
from apps.references.models import Referencia

from .models import Movimiento, OrdenSalida
from .tests import InventoryBase, client_for, make_user


class OrderReferenceTests(InventoryBase):
    def setUp(self):
        super().setUp()
        self.generico.stock_actual = Decimal("100")  # la lavandería envía pantalones genéricos ya fabricados
        self.generico.save()

    def other_reference(self, state=reference_catalog.ACTIVE, **extra):
        return Referencia.objects.create(
            codigo=extra.pop("codigo", "REF-0002"), nombre=extra.pop("nombre", "Mom vintage"), ajuste="MOM",
            estado=state, **extra,
        )

    def test_la_orden_guarda_la_referencia_y_usa_su_codigo_como_lote(self):
        response = self.production_order()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["referencia"], self.referencia.id)
        self.assertEqual((body["referencia_codigo"], body["referencia_nombre"]), ("REF-0001", "Skinny 5 bolsillos"))
        self.assertEqual(body["ficha_tecnica"], "REF-0001")
        order = OrdenSalida.objects.get(pk=body["id"])
        self.assertEqual(order.referencia_id, self.referencia.id)
        self.assertEqual({m.lote for m in Movimiento.objects.filter(orden=order)}, {"REF-0001"})

    def test_la_lavanderia_tambien_se_hace_sobre_una_referencia(self):
        response = self.laundry_order()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["referencia_codigo"], "REF-0001")

    def test_el_texto_libre_de_ficha_tecnica_ya_no_se_usa(self):
        response = self.production_order(ficha_tecnica="FT-ESCRITA-A-MANO")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["ficha_tecnica"], "REF-0001")

    def test_la_referencia_es_obligatoria(self):
        for make in (self.production_order, self.laundry_order):
            body = make(referencia=None)
            self.assertEqual(body.status_code, 400)
            self.assertIn("referencia", body.json())
        self.assertEqual(OrdenSalida.objects.count(), 0)

    def test_la_referencia_debe_existir(self):
        response = self.production_order(referencia=99999)
        self.assertEqual(response.status_code, 400)
        self.assertIn("no existe o no está activa", response.json()["referencia"][0])

    def test_solo_referencias_activas(self):
        for state in (reference_catalog.DRAFT, reference_catalog.DISCONTINUED):
            other = self.other_reference(state=state, codigo=f"REF-1{state[:2]}", nombre=f"En {state}")
            for make in (self.production_order, self.laundry_order):
                response = make(referencia=other.id)
                self.assertEqual(response.status_code, 400, (state, response.content))
                self.assertIn("referencia", response.json())
        self.assertEqual(OrdenSalida.objects.count(), 0)

    def test_una_referencia_archivada_no_sirve(self):
        other = self.other_reference()
        other.delete()
        self.assertEqual(self.production_order(referencia=other.id).status_code, 400)

    def test_produccion_exige_que_la_referencia_tenga_ficha(self):
        sin_ficha = self.other_reference()
        response = self.production_order(referencia=sin_ficha.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("no tiene ficha técnica", response.json()["referencia"][0])
        self.assertEqual(OrdenSalida.objects.count(), 0)
        self.assertEqual(self.laundry_order(referencia=sin_ficha.id).status_code, 201)  # lavandería no la necesita

    def test_produccion_exige_la_cantidad_de_prendas(self):
        for bad in (None, "", 0, "-5", "1.5", "abc"):
            response = self.production_order(cantidad_prendas=bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("cantidad_prendas", response.json())
        self.assertEqual(OrdenSalida.objects.count(), 0)
        order = self.production_order(cantidad_prendas=250).json()
        self.assertEqual(Decimal(order["cantidad_prendas"]), Decimal("250"))

    def test_una_orden_rechazada_no_toca_el_stock_ni_gasta_codigo(self):
        self.production_order(referencia=99999)
        self.refresh(self.tela, self.cierre)
        self.assertEqual((self.tela.stock_actual, self.cierre.stock_actual), (Decimal("1000"), Decimal("500")))
        self.assertEqual(self.production_order().json()["codigo"], "OP-0001")

    def test_filtra_las_ordenes_por_referencia(self):
        self.production_order()
        other = self.other_reference()
        self.laundry_order(referencia=other.id)
        listed = self.api.get(reverse("inventario_ordenes"), {"referencia": self.referencia.id}).json()
        self.assertEqual([o["tipo"] for o in listed], ["PRODUCCION"])
        self.assertEqual(self.api.get(reverse("inventario_ordenes"), {"referencia": "abc"}).status_code, 400)

    def test_las_ordenes_antiguas_siguen_mostrandose(self):
        old = OrdenSalida.objects.create(
            codigo="OP-0099", tipo="PRODUCCION", fecha_salida="2026-09-20", responsable="Marta",
            ficha_tecnica="FT-1427-A", producto_resultado=self.generico,
        )
        body = self.api.get(reverse("inventario_orden", args=[old.id])).json()
        self.assertEqual((body["referencia"], body["referencia_codigo"], body["referencia_nombre"]), (None, "", ""))
        self.assertEqual(body["ficha_tecnica"], "FT-1427-A")

    def test_el_ingreso_de_una_orden_hereda_el_lote_de_la_referencia(self):
        order = self.production_order().json()
        response = self.api.post(reverse("inventario_ingresos"), {
            "producto": self.generico.id, "cantidad": "95", "fecha": order["fecha_salida"], "orden": order["id"],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["lote"], "REF-0001")

    def test_flujo_completo_ficha_consumo_y_orden(self):
        """Lo que hace el formulario: pide el consumo de N prendas y crea la orden con esa cesta."""
        consumo = self.api.get(reverse("ficha_consumo", args=[self.referencia.id]), {"cantidad": 100})
        self.assertEqual(consumo.status_code, 200, consumo.content)
        data = consumo.json()
        self.assertTrue(data["viable"])
        lines = [{"producto": row["producto"], "cantidad": row["requerido"]} for row in data["lineas"]]
        response = self.production_order(lineas=lines, cantidad_prendas=data["cantidad"])
        self.assertEqual(response.status_code, 201, response.content)
        required = {row["producto"]: Decimal(row["requerido"]) for row in data["lineas"]}
        self.refresh(self.tela, self.cierre, self.boton)
        self.assertEqual(self.tela.stock_actual, Decimal("1000") - required[self.tela.id])  # 165 m con la merma
        self.assertEqual(self.cierre.stock_actual, Decimal("400"))
        self.assertEqual(self.boton.stock_actual, Decimal("200"))

    def test_el_faltante_que_anuncia_el_consumo_lo_confirma_la_orden(self):
        data = self.api.get(reverse("ficha_consumo", args=[self.referencia.id]), {"cantidad": 400}).json()
        self.assertFalse(data["viable"])  # hacen falta 400 botones y hay 300
        lines = [{"producto": row["producto"], "cantidad": row["requerido"]} for row in data["lineas"]]
        response = self.production_order(lineas=lines, cantidad_prendas=400)
        self.assertEqual(response.status_code, 400)
        missing = {int(row["producto"]) for row in response.json()["faltantes"]}
        self.assertEqual(missing, {row["producto"] for row in data["faltantes"]})
        self.refresh(self.boton)
        self.assertEqual(self.boton.stock_actual, Decimal("300"))  # nada se descontó


class ReferenceWithOpenOrdersTests(InventoryBase):
    def setUp(self):
        super().setUp()
        self.boss = client_for(make_user("produccion@t.co", "PRODUCCION"))
        self.url = reverse("referencia", args=[self.referencia.id])

    def discontinue(self):
        self.referencia.estado = reference_catalog.DISCONTINUED
        self.referencia.save()

    def test_no_se_archiva_con_una_orden_en_proceso(self):
        order = self.production_order().json()
        self.discontinue()
        response = self.boss.delete(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertIn("órdenes en proceso", response.json()["estado"][0])
        self.assertEqual(self.api.post(reverse("inventario_orden_anular", args=[order["id"]]),
                                       {"motivo": "Error de digitación"}, format="json").status_code, 200)
        self.assertEqual(self.boss.delete(self.url).status_code, 204)

    def test_una_orden_cerrada_no_bloquea_el_archivado(self):
        order = self.production_order().json()
        self.api.post(reverse("inventario_ingresos"), {
            "producto": self.generico.id, "cantidad": "95", "fecha": order["fecha_salida"], "orden": order["id"],
        }, format="json")
        self.discontinue()
        self.assertEqual(self.boss.delete(self.url).status_code, 204)

    def test_no_se_quita_la_ficha_con_una_orden_en_proceso(self):
        self.production_order()
        response = self.boss.delete(reverse("referencia_ficha", args=[self.referencia.id]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("órdenes en proceso", response.json()["detail"][0])
