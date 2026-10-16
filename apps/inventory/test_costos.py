"""Costo de las compras (HU 4.6, parte de compras): costo unitario, promedio ponderado, foto en la orden y devolución al anular."""
from decimal import Decimal

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse

from . import catalog
from .models import Movimiento, OrdenLinea
from .tests import InventoryBase, today


class CostBase(InventoryBase):
    def purchase(self, product=None, quantity="100", cost=None, **extra):
        body = {
            "producto": (product or self.tela).id, "cantidad": quantity, "fecha": today(),
            "proveedor": self.supplier.id, "orden_compra": "OC-1", "lote": "L-2026-01",
        }
        if cost is not None:
            body["costo_unitario"] = cost
        body.update(extra)
        return self.api.post(reverse("inventario_ingresos"), body, format="json")

    def bought(self, product=None, quantity="100", cost=None, **extra):
        response = self.purchase(product, quantity, cost, **extra)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def average(self, product=None):
        product = product or self.tela
        product.refresh_from_db()
        return product.costo_promedio


class PurchaseCostTests(CostBase):
    def test_una_compra_con_costo_lo_guarda_en_el_movimiento_y_fija_el_promedio(self):
        body = self.bought(cost="18500")
        self.assertEqual(Decimal(body["costo_unitario"]), Decimal("18500"))
        self.assertEqual(self.average(), Decimal("18500.0000"))

    def test_la_segunda_compra_promedia_con_las_existencias(self):
        self.bought(quantity="150", cost="20000")  # había 1000 sin costo: el costo de la compra manda
        self.bought(quantity="150", cost="22000")  # (1150 × 20000 + 150 × 22000) / 1300
        self.assertEqual(self.average(), Decimal("20230.7692"))

    def test_las_existencias_anteriores_sin_costo_no_diluyen_el_promedio(self):
        self.assertEqual((self.tela.stock_actual, self.average()), (Decimal("1000"), Decimal("0")))
        self.bought(quantity="100", cost="18000")
        self.assertEqual(self.average(), Decimal("18000.0000"))  # no 1636,36, que sería mezclar con un costo cero

    def test_una_compra_sin_costo_no_cambia_el_promedio(self):
        self.bought(cost="20000")
        body = self.bought(quantity="500")
        self.assertIsNone(body["costo_unitario"])
        self.assertEqual(self.average(), Decimal("20000.0000"))

    def test_sin_existencias_el_costo_de_la_compra_manda(self):
        empty = self.product("Tela nueva", catalog.CAT_FABRIC, "m")
        self.bought(empty, "50", "7000")
        self.assertEqual(self.average(empty), Decimal("7000.0000"))

    def test_el_redondeo_es_hacia_arriba_en_la_mitad(self):
        self.cierre.stock_actual = Decimal("3")
        self.cierre.costo_promedio = Decimal("1")
        self.cierre.save()
        self.bought(self.cierre, "1", "1.0002")  # (3 × 1 + 1 × 1,0002) / 4 = 1,00005
        self.assertEqual(self.average(self.cierre), Decimal("1.0001"))

    def test_acepta_hasta_cuatro_decimales(self):
        self.bought(cost="12.3456")
        self.assertEqual(self.average(), Decimal("12.3456"))

    def test_costos_invalidos_se_rechazan_y_no_registran_nada(self):
        before = Movimiento.objects.count()
        for bad in ("0", "-5", "abc", "1.23456", "99999999999999"):
            response = self.purchase(cost=bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("costo_unitario", response.json(), bad)
        self.assertEqual(Movimiento.objects.count(), before)
        self.assertEqual(self.average(), Decimal("0"))

    def test_el_costo_es_opcional_y_null_cuenta_como_vacio(self):
        self.assertEqual(self.purchase().status_code, 201)
        self.assertEqual(self.purchase(costo_unitario=None).status_code, 201)

    def test_los_pantalones_que_vuelven_de_una_orden_no_llevan_costo(self):
        order = self.production_order().json()
        response = self.api.post(reverse("inventario_ingresos"), {
            "producto": self.generico.id, "cantidad": "95", "fecha": today(), "orden": order["id"], "costo_unitario": "30000",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Solo las compras", response.json()["costo_unitario"][0])

    def test_un_ingreso_rechazado_por_otro_motivo_tampoco_cambia_el_promedio(self):
        self.bought(cost="20000")
        self.assertEqual(self.purchase(cost="30000", proveedor=None).status_code, 400)  # falta el proveedor
        self.assertEqual(self.average(), Decimal("20000.0000"))


class ExposureTests(CostBase):
    def test_el_inventario_muestra_el_costo_promedio_y_el_kardex_el_costo_de_cada_compra(self):
        self.bought(cost="19000.5")
        products = {p["id"]: p for p in self.api.get(reverse("inventario_productos")).json()}
        self.assertEqual(Decimal(products[self.tela.id]["costo_promedio"]), Decimal("19000.5"))
        self.assertEqual(Decimal(products[self.cierre.id]["costo_promedio"]), Decimal("0"))
        moves = self.api.get(reverse("inventario_movimientos"), {"producto": self.tela.id}).json()
        self.assertEqual(Decimal(moves[0]["costo_unitario"]), Decimal("19000.5"))

    def test_los_costos_salen_como_texto(self):
        self.bought(cost="100")
        product = next(p for p in self.api.get(reverse("inventario_productos")).json() if p["id"] == self.tela.id)
        self.assertIsInstance(product["costo_promedio"], str)


class OrderCostSnapshotTests(CostBase):
    def test_la_linea_de_la_orden_guarda_el_costo_del_momento(self):
        self.bought(cost="20000")
        order = self.production_order().json()
        lines = {line["producto"]: line for line in order["lineas"]}
        self.assertEqual(Decimal(lines[self.tela.id]["costo_unitario"]), Decimal("20000"))
        self.assertIsNone(lines[self.cierre.id]["costo_unitario"])  # el cierre no tenía costo conocido

    def test_si_despues_sube_el_precio_el_costo_de_la_orden_no_cambia(self):
        self.bought(quantity="100", cost="20000")
        order = self.production_order().json()
        self.bought(quantity="500", cost="30000")
        self.assertGreater(self.average(), Decimal("20000"))
        line = OrdenLinea.objects.get(orden_id=order["id"], producto=self.tela)
        self.assertEqual(line.costo_unitario, Decimal("20000.0000"))
        again = self.api.get(reverse("inventario_orden", args=[order["id"]])).json()
        self.assertEqual(Decimal(next(l for l in again["lineas"] if l["producto"] == self.tela.id)["costo_unitario"]), Decimal("20000"))

    def test_las_ordenes_anteriores_a_los_costos_quedan_sin_costo(self):
        order = self.production_order().json()
        self.assertTrue(all(line["costo_unitario"] is None for line in order["lineas"]))


class CancellationCostTests(CostBase):
    def test_al_anular_el_material_vuelve_al_costo_de_la_foto_y_entra_al_promedio(self):
        self.bought(quantity="100", cost="20000")  # promedio 20000
        order = self.production_order().json()  # saca 300 m a 20000
        self.bought(quantity="300", cost="26000")  # sube el promedio
        high = self.average()
        self.assertGreater(high, Decimal("20000"))
        response = self.api.post(reverse("inventario_orden_anular", args=[order["id"]]), {"motivo": "Cambio"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.tela.refresh_from_db()
        back = Movimiento.objects.get(orden_id=order["id"], producto=self.tela, motivo="ANULACION")
        self.assertEqual(back.costo_unitario, Decimal("20000.0000"))
        # antes de volver: existencias 1100 + 300 - 300 = 1100 a `high`; vuelven 300 a 20000
        expected = ((Decimal("1100") * high + Decimal("300") * Decimal("20000")) / Decimal("1400")).quantize(Decimal("0.0001"))
        self.assertEqual(self.tela.costo_promedio, expected)

    def test_una_linea_sin_costo_no_toca_el_promedio_al_anular(self):
        order = self.production_order().json()  # nada tenía costo
        self.bought(cost="15000")
        before = self.average()
        self.api.post(reverse("inventario_orden_anular", args=[order["id"]]), {"motivo": "Cambio"}, format="json")
        self.assertEqual(self.average(), before)
        back = Movimiento.objects.filter(orden_id=order["id"], motivo="ANULACION")
        self.assertTrue(all(move.costo_unitario is None for move in back))

    def test_el_stock_se_restablece_igual_que_antes(self):
        self.bought(cost="20000")
        order = self.production_order().json()
        self.api.post(reverse("inventario_orden_anular", args=[order["id"]]), {"motivo": "Cambio"}, format="json")
        self.tela.refresh_from_db()
        self.assertEqual(self.tela.stock_actual, Decimal("1100"))


class ConstraintTests(CostBase):
    def rejects(self, create):
        with self.assertRaises(IntegrityError), transaction.atomic():
            create()

    def test_la_base_rechaza_costos_no_positivos(self):
        self.rejects(lambda: Movimiento.objects.filter(pk=self.bought(cost="10")["id"]).update(costo_unitario=Decimal("0")))
        self.tela.costo_promedio = Decimal("-1")
        self.rejects(lambda: self.tela.save())


@override_settings(DEBUG=True)
class DemoSeedCostTests(CostBase):
    def test_el_seed_de_demostracion_trae_costos_y_promedios(self):
        call_command("seed_demo_inventario", verbosity=0)
        from .models import Producto
        denim = Producto.objects.get(nombre="Denim rígido índigo 14 oz")
        self.assertGreater(denim.costo_promedio, Decimal("21000"))  # dos compras: 21000 y 22050, ponderadas
        self.assertLess(denim.costo_promedio, Decimal("22050"))
        costs = list(Movimiento.objects.filter(producto=denim, motivo="COMPRA").values_list("costo_unitario", flat=True))
        self.assertEqual(sorted(costs), [Decimal("21000.0000"), Decimal("22050.0000")])
        demo = Producto.objects.filter(movimientos__observaciones="Compra de demostración").distinct()
        self.assertGreater(demo.count(), 20)
        self.assertEqual(demo.filter(costo_promedio=0).count(), 0)  # toda compra de la demo trae costo
