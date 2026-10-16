"""Órdenes de producción y lotes (HU 4.2 / RF11 y RF12): validación, códigos, creación en cascada, API y permisos."""
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Consecutivo, Movimiento, OrdenSalida, Producto
from apps.inventory.tests import client_for, make_user
from apps.references.models import Variante

from . import services
from .models import Lote, LoteTalla, OrdenProduccion
from .tests import SimulationBase


class OrderBase(SimulationBase):
    """Referencia activa con ficha (tela, cierre y botón por prenda), tres variantes y un pantalón genérico."""

    def setUp(self):
        super().setUp()
        self.generico = self.material("Pantalón genérico", inventory_catalog.CAT_GENERIC, "unidad")
        reference_id = self.ref["id"]
        self.v30 = Variante.objects.get(referencia_id=reference_id)
        self.v32 = Variante.objects.create(referencia_id=reference_id, talla="32", color="Azul oscuro")
        self.v34 = Variante.objects.create(referencia_id=reference_id, talla="34", color="Negro")
        self.orders_url = reverse("produccion_ordenes")

    def order_body(self, quantity=100, lots=None, **extra):
        data = {"referencia": self.ref["id"], "cantidad": quantity, "producto_resultado": self.generico.id}
        if lots is not None:
            data["lotes"] = lots
        data.update(extra)
        return data

    def place(self, quantity=100, lots=None, client=None, **extra):
        return (client or self.api).post(self.orders_url, self.order_body(quantity, lots, **extra), format="json")

    def placed(self, quantity=100, lots=None, **extra):
        response = self.place(quantity, lots, **extra)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def refresh(self, product):
        product.refresh_from_db()
        return product.stock_actual

    def snapshot(self):
        return (
            OrdenSalida.objects.count(), OrdenProduccion.objects.count(), Lote.objects.count(),
            LoteTalla.objects.count(), Movimiento.objects.count(),
            {p.id: p.stock_actual for p in Producto.objects.all()},
        )


class LotValidationTests(OrderBase):
    def errors(self, lots, quantity=100):
        before = self.snapshot()
        response = self.place(quantity, lots)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.snapshot(), before)  # una orden rechazada no deja nada
        return response.json()

    def test_los_lotes_deben_sumar_el_total(self):
        self.assertIn("faltan 10", self.errors([{"cantidad": 40}, {"cantidad": 50}])["lotes"][0])
        self.assertIn("sobran 10", self.errors([{"cantidad": 60}, {"cantidad": 50}])["lotes"][0])

    def test_cada_lote_es_un_entero_mayor_que_cero(self):
        for bad in (0, -5, "abc", 1.5, True, None, ""):
            self.assertIn("lote 1", self.errors([{"cantidad": bad}, {"cantidad": 50}])["lotes"][0], bad)

    def test_hay_un_maximo_de_lotes(self):
        self.assertIn("50 lotes", self.errors([{"cantidad": 1}] * 51, 51)["lotes"][0])

    def test_los_lotes_no_pueden_ir_vacios_ni_mal_formados(self):
        self.assertIn("al menos un lote", self.errors([])["lotes"][0])
        self.assertIn("al menos un lote", self.errors("100")["lotes"][0])
        self.assertIn("cantidad de prendas", self.errors([100])["lotes"][0])

    def test_las_tallas_deben_sumar_las_prendas_del_lote(self):
        lots = [{"cantidad": 100, "tallas": [{"variante": self.v30.id, "cantidad": 60}, {"variante": self.v32.id, "cantidad": 30}]}]
        self.assertIn("faltan 10", self.errors(lots)["lotes"][0])
        lots[0]["tallas"][0]["cantidad"] = 80
        self.assertIn("sobran 10", self.errors(lots)["lotes"][0])

    def test_una_talla_no_se_repite_en_el_lote(self):
        lots = [{"cantidad": 100, "tallas": [{"variante": self.v30.id, "cantidad": 50}, {"variante": self.v30.id, "cantidad": 50}]}]
        self.assertIn("se repite", self.errors(lots)["lotes"][0])

    def test_la_talla_debe_ser_una_variante_de_la_referencia(self):
        other = self.new(nombre="Otra referencia", variantes=[{"talla": "28", "color": "Gris"}])
        foreign = Variante.objects.get(referencia_id=other["id"]).id
        for variant in (foreign, 999999, "x", None, True):
            lots = [{"cantidad": 100, "tallas": [{"variante": variant, "cantidad": 100}]}]
            self.assertIn("no es una variante", self.errors(lots)["lotes"][0], variant)

    def test_una_variante_archivada_ya_no_se_acepta(self):
        self.v34.delete()
        lots = [{"cantidad": 100, "tallas": [{"variante": self.v34.id, "cantidad": 100}]}]
        self.assertIn("no es una variante", self.errors(lots)["lotes"][0])

    def test_la_cantidad_de_cada_talla_es_un_entero_mayor_que_cero(self):
        for bad in (0, -1, "x", 2.5, None, True):
            lots = [{"cantidad": 100, "tallas": [{"variante": self.v30.id, "cantidad": bad}]}]
            self.assertIn("entero mayor que cero", self.errors(lots)["lotes"][0], bad)

    def test_las_tallas_mal_formadas_se_rechazan(self):
        self.assertIn("deben ser una lista", self.errors([{"cantidad": 100, "tallas": "30"}])["lotes"][0])
        self.assertIn("variante y la cantidad", self.errors([{"cantidad": 100, "tallas": [5]}])["lotes"][0])

    def test_las_tallas_son_opcionales_y_pueden_ir_vacias(self):
        for tallas in (None, []):
            body = self.placed(100, [{"cantidad": 100, "tallas": tallas}])
            self.assertEqual(body["lotes"][0]["tallas"], [])


class CodeTests(OrderBase):
    def test_la_orden_toma_el_codigo_de_la_salida_de_inventario(self):
        body = self.placed()
        self.assertEqual(body["codigo"], "OP-0001")
        self.assertEqual(OrdenSalida.objects.get().codigo, "OP-0001")

    def test_los_codigos_son_consecutivos(self):
        self.assertEqual([self.placed(10)["codigo"] for _ in range(3)], ["OP-0001", "OP-0002", "OP-0003"])

    def test_los_lotes_llevan_el_codigo_de_la_orden_y_su_numero(self):
        body = self.placed(100, [{"cantidad": 30}, {"cantidad": 30}, {"cantidad": 40}])
        self.assertEqual([lot["codigo"] for lot in body["lotes"]], ["OP-0001-L01", "OP-0001-L02", "OP-0001-L03"])
        self.assertEqual([lot["numero"] for lot in body["lotes"]], [1, 2, 3])

    def test_con_cincuenta_lotes_el_formato_sigue_ordenado(self):
        body = self.placed(50, [{"cantidad": 1}] * 50)
        self.assertEqual((body["lotes"][0]["codigo"], body["lotes"][-1]["codigo"]), ("OP-0001-L01", "OP-0001-L50"))
        self.assertEqual(len({lot["codigo"] for lot in body["lotes"]}), 50)

    def test_una_orden_fallida_no_gasta_numero(self):
        self.assertEqual(self.place(400).status_code, 400)  # no alcanza el material
        self.assertEqual(self.placed(10)["codigo"], "OP-0001")
        self.assertEqual(Consecutivo.objects.get(clave="OP").ultimo, 1)

    def test_comparte_el_consecutivo_con_las_ordenes_de_salida_del_inventario(self):
        Consecutivo.objects.create(clave="OP", ultimo=7)
        self.assertEqual(self.placed(10)["codigo"], "OP-0008")

    def test_un_codigo_borrado_no_bloquea_los_nuevos_lotes(self):
        order = OrdenProduccion.objects.get(pk=self.placed(10, [{"cantidad": 10}])["id"])
        order.lotes.first().delete()
        self.assertEqual(Lote.all_objects.filter(codigo="OP-0001-L01").count(), 1)
        Lote.objects.create(orden=order, numero=1, codigo="OP-0001-L01", cantidad=3)


class CascadeTests(OrderBase):
    def test_descuenta_el_material_de_la_ficha_con_merma(self):
        self.placed(100)  # tela 1,5 × 1,10 × 100 = 165, cierres 100, botones 100
        self.assertEqual(self.refresh(self.tela), Decimal("335.00"))
        self.assertEqual(self.refresh(self.cierre), Decimal("200"))
        self.assertEqual(self.refresh(self.boton), Decimal("100"))
        self.assertEqual(self.refresh(self.hilo), Decimal("10"))  # lo que no está en la ficha no se toca

    def test_el_descuento_es_el_mismo_que_dice_la_simulacion(self):
        simulated = {row["producto"]: Decimal(row["requerido"]) for row in self.ok(100)["lineas"]}
        body = self.placed(100)
        self.assertEqual({m["producto"]: Decimal(m["cantidad"]) for m in body["materiales"]}, simulated)

    def test_registra_una_salida_en_el_kardex_por_material_con_el_lote_de_la_referencia(self):
        self.placed(100)
        movements = Movimiento.objects.filter(tipo=inventory_catalog.EXIT)
        self.assertEqual(movements.count(), 3)
        self.assertEqual({m.lote for m in movements}, {self.ref["codigo"]})
        self.assertEqual({m.orden.codigo for m in movements}, {"OP-0001"})

    def test_los_lotes_no_descuentan_de_nuevo(self):
        self.placed(100, [{"cantidad": 20}, {"cantidad": 30}, {"cantidad": 50}])
        self.assertEqual(self.refresh(self.tela), Decimal("335.00"))
        self.assertEqual(Movimiento.objects.count(), 3)

    def test_si_falta_material_no_queda_nada_y_responde_con_faltantes(self):
        before = self.snapshot()
        response = self.place(400, [{"cantidad": 400, "tallas": [{"variante": self.v30.id, "cantidad": 400}]}])
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual({row["nombre"] for row in body["faltantes"]},
                         {"Denim rígido 14 oz", "Cierre metálico 18 cm", "Botón 17 mm"})
        self.assertEqual(self.snapshot(), before)

    def test_alcanza_justo_el_ultimo_material(self):
        self.set_stock(self.boton, "100")
        self.placed(100)
        self.assertEqual(self.refresh(self.boton), Decimal("0"))
        self.assertEqual(self.place(1).status_code, 400)

    def test_la_orden_nace_en_proceso_con_su_salida_vinculada(self):
        body = self.placed(100)
        order = OrdenProduccion.objects.get(pk=body["id"])
        self.assertEqual(order.orden_salida.estado, inventory_catalog.STATUS_OPEN)
        self.assertEqual((body["estado"], body["estado_nombre"]), ("EN_PROCESO", "En proceso"))
        self.assertEqual(order.orden_salida.cantidad_prendas, Decimal("100"))
        self.assertEqual(order.orden_salida.referencia_id, self.ref["id"])
        self.assertEqual(order.creado_por, self.boss)

    def test_guarda_las_tallas_con_copia_de_talla_y_color(self):
        lots = [
            {"cantidad": 60, "tallas": [{"variante": self.v30.id, "cantidad": 40}, {"variante": self.v32.id, "cantidad": 20}]},
            {"cantidad": 40, "tallas": [{"variante": self.v34.id, "cantidad": 40}]},
        ]
        body = self.placed(100, lots)
        first, second = body["lotes"]
        self.assertEqual([(t["talla"], t["color"], t["cantidad"]) for t in first["tallas"]],
                         [("30", "Azul oscuro", 40), ("32", "Azul oscuro", 20)])
        self.assertEqual([(t["talla"], t["color"], t["cantidad"]) for t in second["tallas"]], [("34", "Negro", 40)])
        self.v34.delete()  # archivar la variante no cambia lo ya pedido
        self.assertEqual(LoteTalla.objects.get(lote__numero=2).color, "Negro")

    def test_sin_lotes_crea_un_unico_lote_con_todo_el_total(self):
        body = self.placed(100)
        self.assertEqual([(lot["codigo"], lot["cantidad"]) for lot in body["lotes"]], [("OP-0001-L01", 100)])

    def test_la_referencia_debe_estar_activa_y_tener_ficha(self):
        before = self.snapshot()
        draft = self.new(nombre="Borrador", variantes=[{"talla": "30", "color": "Rojo"}])
        for reference, message in ((draft["id"], "no está activa"), (999999, "no está activa")):
            response = self.api.post(self.orders_url, {**self.order_body(), "referencia": reference}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertIn(message, response.json()["referencia"][0])
        no_sheet = self.new(nombre="Sin ficha", variantes=[{"talla": "30", "color": "Rojo"}])
        self.activate(no_sheet["id"])
        response = self.api.post(self.orders_url, {**self.order_body(), "referencia": no_sheet["id"]}, format="json")
        self.assertIn("ficha técnica", response.json()["referencia"][0])
        self.assertEqual(self.snapshot(), before)

    def test_el_resultado_debe_ser_un_pantalon_generico(self):
        response = self.place(10, producto_resultado=self.tela.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("pantalón genérico", response.json()["producto_resultado"][0])

    def test_la_cantidad_total_se_valida_como_en_la_simulacion(self):
        for bad in (0, -3, "x", 1.5, 100001, None):
            self.assertEqual(self.place(bad).status_code, 400, bad)

    def test_responsable_y_fecha_tienen_valores_por_defecto(self):
        body = self.placed(10)
        self.assertEqual(body["responsable"], "produccion@t.co")
        self.assertTrue(body["fecha_salida"])
        explicit = self.placed(10, responsable="  Marta Ruiz ", fecha_salida="2026-10-01")
        self.assertEqual((explicit["responsable"], explicit["fecha_salida"]), ("Marta Ruiz", "2026-10-01"))


class EndpointTests(OrderBase):
    def test_la_respuesta_trae_la_orden_con_lotes_y_materiales(self):
        body = self.placed(100, [{"cantidad": 100, "tallas": [{"variante": self.v30.id, "cantidad": 100}]}])
        self.assertEqual((body["referencia"], body["referencia_codigo"]), (self.ref["id"], self.ref["codigo"]))
        self.assertEqual((body["cantidad"], body["creado_por_nombre"]), (100, "produccion@t.co"))
        self.assertEqual(body["producto_resultado_nombre"], "Pantalón genérico")
        self.assertEqual(len(body["materiales"]), 3)
        self.assertIsInstance(body["materiales"][0]["cantidad"], str)

    def test_consulta_el_detalle(self):
        created = self.placed(100, [{"cantidad": 40}, {"cantidad": 60}])
        body = self.api.get(reverse("produccion_orden", args=[created["id"]])).json()
        self.assertEqual(body, created)

    def test_detalle_de_una_orden_que_no_existe(self):
        self.assertEqual(self.api.get(reverse("produccion_orden", args=[999999])).status_code, 404)

    def test_lista_de_la_mas_reciente_a_la_mas_antigua(self):
        first, second = self.placed(10)["codigo"], self.placed(10)["codigo"]
        listed = self.api.get(self.orders_url).json()
        self.assertEqual([order["codigo"] for order in listed], [second, first])

    def test_filtra_por_estado_y_por_referencia(self):
        keep, cancel = self.placed(10), self.placed(10)
        self.api.post(reverse("produccion_orden_anular", args=[cancel["id"]]), {"motivo": "Prueba"}, format="json")
        by_state = self.api.get(self.orders_url, {"estado": "ANULADA"}).json()
        self.assertEqual([order["id"] for order in by_state], [cancel["id"]])
        other = self.api.get(self.orders_url, {"referencia": self.ref["id"]}).json()
        self.assertEqual({order["id"] for order in other}, {keep["id"], cancel["id"]})
        self.assertEqual(self.api.get(self.orders_url, {"referencia": 999999}).json(), [])

    def test_un_filtro_mal_formado_responde_400(self):
        self.assertEqual(self.api.get(self.orders_url, {"referencia": "abc"}).status_code, 400)

    def test_el_limite_se_respeta(self):
        for _ in range(3):
            self.placed(5)
        self.assertEqual(len(self.api.get(self.orders_url, {"limit": 2}).json()), 2)

    def test_el_listado_no_hace_consultas_por_orden(self):
        for _ in range(4):
            self.placed(5, [{"cantidad": 3, "tallas": [{"variante": self.v30.id, "cantidad": 3}]}, {"cantidad": 2}])
        with CaptureQueriesContext(connection) as many:
            self.api.get(self.orders_url)
        OrdenProduccion.objects.filter(pk__in=list(OrdenProduccion.objects.values_list("pk", flat=True)[:3])).delete()
        with CaptureQueriesContext(connection) as few:
            self.api.get(self.orders_url)
        self.assertEqual(len(many), len(few))

    def test_exige_sesion(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get(self.orders_url).status_code, 401)
        self.assertEqual(APIClient().post(self.orders_url, self.order_body(), format="json").status_code, 401)

    def test_el_cuerpo_sin_los_campos_obligatorios_responde_400(self):
        for missing in ("referencia", "cantidad", "producto_resultado"):
            data = self.order_body()
            data.pop(missing)
            self.assertEqual(self.api.post(self.orders_url, data, format="json").status_code, 400, missing)

    def test_la_fecha_futura_se_rechaza(self):
        self.assertEqual(self.place(10, fecha_salida="2999-01-01").status_code, 400)


class PermissionTests(OrderBase):
    def test_produccion_crea_y_consulta_sin_tener_inventario_gestionar(self):
        self.assertEqual(self.place(10).status_code, 201)
        self.assertEqual(self.api.get(self.orders_url).status_code, 200)

    def test_el_gerente_consulta_pero_no_crea(self):
        manager = client_for(make_user("gerente@t.co", "GERENTE"))
        order = self.placed(10)
        self.assertEqual(manager.get(self.orders_url).status_code, 200)
        self.assertEqual(manager.get(reverse("produccion_orden", args=[order["id"]])).status_code, 200)
        self.assertEqual(self.place(10, client=manager).status_code, 403)

    def test_el_gerente_no_anula(self):
        manager = client_for(make_user("gerente@t.co", "GERENTE"))
        order = self.placed(10)
        response = manager.post(reverse("produccion_orden_anular", args=[order["id"]]), {"motivo": "x"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_el_almacenista_no_entra_a_produccion(self):
        keeper = client_for(make_user("almacen@t.co", "ALMACENISTA"))
        self.assertEqual(keeper.get(self.orders_url).status_code, 403)
        self.assertEqual(self.place(10, client=keeper).status_code, 403)

    def test_un_usuario_sin_rol_no_entra(self):
        pending = client_for(make_user("nuevo@t.co", "PENDING"))
        self.assertEqual(pending.get(self.orders_url).status_code, 403)

    def test_el_administrador_puede_todo(self):
        admin = client_for(make_user("admin@t.co", "ADMIN"))
        order = admin.post(self.orders_url, self.order_body(10), format="json")
        self.assertEqual(order.status_code, 201, order.content)
        self.assertEqual(admin.post(reverse("produccion_orden_anular", args=[order.json()["id"]]),
                                    {"motivo": "x"}, format="json").status_code, 200)

    def test_produccion_sigue_sin_poder_registrar_ordenes_de_salida_de_inventario(self):
        response = self.api.post(reverse("inventario_ordenes"), {}, format="json")
        self.assertEqual(response.status_code, 403)


class CancelTests(OrderBase):
    def cancel(self, order_id, motivo="Se cambió el pedido", client=None):
        return (client or self.api).post(reverse("produccion_orden_anular", args=[order_id]), {"motivo": motivo}, format="json")

    def test_anular_devuelve_el_material_y_marca_la_orden(self):
        order = self.placed(100)
        response = self.cancel(order["id"])
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["estado"], body["motivo_anulacion"]), ("ANULADA", "Se cambió el pedido"))
        self.assertIsNotNone(body["anulada_at"])
        self.assertEqual(self.refresh(self.tela), Decimal("500.00"))
        self.assertEqual(self.refresh(self.boton), Decimal("200"))

    def test_los_lotes_se_conservan_para_el_historial(self):
        order = self.placed(100, [{"cantidad": 50}, {"cantidad": 50}])
        self.cancel(order["id"])
        self.assertEqual(len(self.api.get(reverse("produccion_orden", args=[order["id"]])).json()["lotes"]), 2)

    def test_exige_el_motivo(self):
        order = self.placed(10)
        for bad in ("", "   "):
            response = self.cancel(order["id"], bad)
            self.assertEqual(response.status_code, 400, bad)
        self.assertEqual(self.api.post(reverse("produccion_orden_anular", args=[order["id"]]), {}, format="json").status_code, 400)

    def test_no_se_anula_dos_veces(self):
        order = self.placed(10)
        self.assertEqual(self.cancel(order["id"]).status_code, 200)
        self.assertEqual(self.cancel(order["id"]).status_code, 400)
        self.assertEqual(self.refresh(self.tela), Decimal("500.00"))

    def test_anular_una_orden_que_no_existe(self):
        self.assertEqual(self.cancel(999999).status_code, 400)

    def test_la_orden_anulada_libera_el_material_para_otra(self):
        self.set_stock(self.boton, "100")
        first = self.placed(100)
        self.assertEqual(self.place(100).status_code, 400)
        self.cancel(first["id"])
        self.assertEqual(self.place(100).status_code, 201)


class RegressionTests(OrderBase):
    def test_la_simulacion_sigue_igual_y_no_se_ve_afectada_por_las_ordenes(self):
        self.assertTrue(self.ok(100, [60, 40])["viable"])
        self.placed(100)
        body = self.ok(100)
        self.assertEqual(Decimal(body["lineas"][0]["disponible"]) + Decimal(body["lineas"][1]["disponible"]) > 0, True)

    def test_la_simulacion_sigue_aceptando_lotes_como_lista_de_numeros(self):
        self.assertEqual([lot["cantidad"] for lot in self.ok(100, [30, 70])["lotes"]], [30, 70])

    def test_clean_lots_no_cambio(self):
        self.assertEqual(services.clean_lots(None, 10), None)
        self.assertEqual(services.clean_lots([4, "6"], 10), [4, 6])

    def test_la_orden_aparece_tambien_en_el_inventario(self):
        order = self.placed(100)
        keeper = client_for(make_user("almacen@t.co", "ALMACENISTA"))
        listed = keeper.get(reverse("inventario_ordenes")).json()
        self.assertEqual([item["codigo"] for item in listed], [order["codigo"]])
        self.assertEqual(listed[0]["referencia"], self.ref["id"])
