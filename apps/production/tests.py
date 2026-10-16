"""Planificación de producción (HU 4.1 / RF10): simulación de material, máximo producible y lotes."""
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Movimiento, OrdenSalida, Producto
from apps.inventory.tests import client_for, make_user
from apps.references import catalog as reference_catalog
from apps.references import fichas
from apps.references import test_ficha as ficha_tests  # solo la base: así no se repiten sus pruebas aquí
from apps.references.models import Referencia

from . import catalog, services


class SimulationBase(ficha_tests.FichaBase):
    """Referencia activa con ficha: tela 1,5 m (+10 % de merma), cierre 1 y botón 1 por prenda.
    Stock: tela 500 m, hilo 10 kg, cierre 300 y botón 200.
    """

    def setUp(self):
        super().setUp()
        self.activate(self.ref["id"])
        self.saved()
        self.sim_url = reverse("produccion_simulacion")

    def simulate(self, quantity=100, lots=None, reference=None, client=None, **extra):
        body = {"referencia": (reference or self.ref)["id"], "cantidad": quantity}
        if lots is not None:
            body["lotes"] = lots
        body.update(extra)
        return (client or self.api).post(self.sim_url, body, format="json")

    def ok(self, quantity=100, lots=None):
        response = self.simulate(quantity, lots)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def set_stock(self, product, value):
        product.stock_actual = Decimal(value)
        product.save()


class SimulationTests(SimulationBase):
    def test_hay_material_para_todo_el_total(self):
        body = self.ok(100)  # tela 165 de 500, cierres 100 de 300, botones 100 de 200
        self.assertTrue(body["viable"])
        self.assertEqual(body["faltantes"], [])
        self.assertEqual(body["cantidad"], 100)
        self.assertEqual(body["referencia"]["codigo"], self.ref["codigo"])
        rows = {row["nombre"]: row for row in body["lineas"]}
        self.assertEqual(Decimal(rows["Denim rígido 14 oz"]["requerido"]), Decimal("165.00"))
        self.assertTrue(all(row["suficiente"] for row in rows.values()))

    def test_no_es_viable_y_lista_lo_que_falta(self):
        body = self.ok(400)  # tela 660 de 500, cierres 400 de 300, botones 400 de 200
        self.assertFalse(body["viable"])
        self.assertEqual({row["nombre"] for row in body["faltantes"]},
                         {"Denim rígido 14 oz", "Cierre metálico 18 cm", "Botón 17 mm"})
        tela = next(row for row in body["faltantes"] if row["nombre"] == "Denim rígido 14 oz")
        self.assertEqual((Decimal(tela["falta"]), Decimal(tela["disponible"])), (Decimal("160.00"), Decimal("500")))

    def test_alcanza_justo(self):
        self.set_stock(self.boton, "100")
        self.assertTrue(self.ok(100)["viable"])
        self.set_stock(self.boton, "99")
        body = self.ok(100)
        self.assertFalse(body["viable"])
        self.assertEqual([row["nombre"] for row in body["faltantes"]], ["Botón 17 mm"])

    def test_el_resultado_coincide_con_el_endpoint_de_consumo(self):
        consumo = self.api.get(reverse("ficha_consumo", args=[self.ref["id"]]), {"cantidad": 250}).json()
        body = self.ok(250)
        self.assertEqual(body["lineas"], consumo["lineas"])
        self.assertEqual((body["viable"], body["faltantes"]), (consumo["viable"], consumo["faltantes"]))

    def test_las_cantidades_salen_como_texto(self):
        body = self.ok(100)
        self.assertIsInstance(body["lineas"][0]["requerido"], str)
        self.assertIsInstance(body["cuello_de_botella"]["disponible"], str)

    def test_no_toca_el_stock_ni_crea_registros(self):
        before = {p.id: p.stock_actual for p in Producto.objects.all()}
        self.simulate(400, [100, 300])
        self.assertEqual({p.id: p.stock_actual for p in Producto.objects.all()}, before)
        self.assertEqual((OrdenSalida.objects.count(), Movimiento.objects.count()), (0, 0))


class MaxProducibleTests(SimulationBase):
    def test_maximo_y_cuello_de_botella(self):
        # tela: 500 / 1,65 = 303; cierre: 300; botón: 200 -> el botón limita
        body = self.ok(10)
        self.assertEqual(body["maximo_producible"], 200)
        self.assertEqual(body["cuello_de_botella"]["nombre"], "Botón 17 mm")
        self.assertEqual(body["cuello_de_botella"]["maximo"], 200)
        self.assertEqual(Decimal(body["cuello_de_botella"]["disponible"]), Decimal("200"))

    def test_la_merma_cuenta_una_sola_vez(self):
        self.set_stock(self.boton, "1000")
        self.set_stock(self.cierre, "1000")
        self.set_stock(self.tela, "165")  # 100 prendas × 1,5 m × 1,10
        self.assertEqual(self.ok(10)["maximo_producible"], 100)
        self.set_stock(self.tela, "164.99")
        self.assertEqual(self.ok(10)["maximo_producible"], 99)

    def test_el_maximo_es_el_ultimo_que_alcanza(self):
        """Propiedad: con el máximo hay material y con una prenda más no, para stocks de todo tipo."""
        cases = [("500", "10", "300", "200"), ("12.34", "0.5", "7", "9"), ("1000", "3.33", "1000", "1000"),
                 ("165", "10", "100", "100"), ("0.01", "10", "300", "200"), ("77.77", "0.07", "55", "42")]
        for tela, hilo, cierre, boton in cases:
            self.saved(lines=[self.line(self.tela, "1.5", "10"), self.line(self.hilo, "0.02", "5"),
                              self.line(self.cierre, "1"), self.line(self.boton, "2")])
            for product, value in ((self.tela, tela), (self.hilo, hilo), (self.cierre, cierre), (self.boton, boton)):
                self.set_stock(product, value)
            best = self.ok(1)["maximo_producible"]
            if best >= 1:
                self.assertTrue(self.ok(best)["viable"], (best, cases))
            if best + 1 <= reference_catalog.MAX_GARMENTS:
                self.assertFalse(self.ok(best + 1)["viable"], (best, cases))

    def test_sin_stock_el_maximo_es_cero(self):
        self.set_stock(self.tela, "0")
        body = self.ok(10)
        self.assertEqual(body["maximo_producible"], 0)
        self.assertEqual(body["cuello_de_botella"]["nombre"], "Denim rígido 14 oz")

    def test_las_unidades_enteras_usan_solo_la_parte_entera_del_saldo(self):
        self.saved(lines=[self.line(self.cierre, "2")])
        self.set_stock(self.cierre, "9.99")  # 9 piezas -> 4 prendas de 2 cierres
        self.assertEqual(self.ok(1)["maximo_producible"], 4)

    def test_se_topa_en_el_maximo_de_prendas(self):
        for product in (self.tela, self.hilo, self.cierre, self.boton):
            self.set_stock(product, "9999999")
        self.assertEqual(self.ok(1)["maximo_producible"], reference_catalog.MAX_GARMENTS)

    def test_en_un_empate_el_cuello_de_botella_es_el_primero_por_nombre(self):
        self.saved(lines=[self.line(self.cierre, "1"), self.line(self.boton, "1")])
        self.set_stock(self.cierre, "50")
        self.set_stock(self.boton, "50")
        body = self.ok(10)
        self.assertEqual(body["maximo_producible"], 50)
        self.assertEqual(body["cuello_de_botella"]["nombre"], "Botón 17 mm")  # B antes que C

    def test_es_un_dato_de_la_referencia_aunque_se_pida_poco(self):
        self.assertEqual(self.ok(1)["maximo_producible"], self.ok(500)["maximo_producible"])


class LotsTests(SimulationBase):
    def test_sin_lotes_no_hay_cobertura(self):
        body = self.ok(100)
        self.assertIsNone(body["lotes"])
        self.assertIsNone(body["lotes_cubiertos"])

    def test_cobertura_acumulada_por_lote(self):
        # El botón alcanza para 200 prendas: los lotes de 100 y 100 se cubren, el tercero no.
        body = self.ok(250, [100, 100, 50])
        self.assertFalse(body["viable"])
        lots = body["lotes"]
        self.assertEqual([(l["numero"], l["cantidad"], l["acumulado"]) for l in lots], [(1, 100, 100), (2, 100, 200), (3, 50, 250)])
        self.assertEqual([l["cubierto"] for l in lots], [True, True, False])
        self.assertEqual(lots[2]["faltantes"], ["Botón 17 mm"])
        self.assertEqual(lots[0]["faltantes"], [])
        self.assertEqual(body["lotes_cubiertos"], 2)

    def test_un_lote_grande_puede_ser_el_que_no_alcanza(self):
        body = self.ok(250, [50, 200])
        self.assertEqual([l["cubierto"] for l in body["lotes"]], [True, False])
        self.assertEqual(body["lotes_cubiertos"], 1)

    def test_todos_cubiertos_cuando_es_viable(self):
        body = self.ok(150, [50, 50, 50])
        self.assertTrue(body["viable"])
        self.assertEqual(body["lotes_cubiertos"], 3)

    def test_un_solo_lote_igual_al_total(self):
        body = self.ok(100, [100])
        self.assertEqual(len(body["lotes"]), 1)
        self.assertTrue(body["lotes"][0]["cubierto"])

    def test_los_lotes_comparten_el_material_no_se_cuenta_doble(self):
        """Dos lotes de 120 con 200 botones: cada uno solo cabe, pero juntos no."""
        body = self.ok(240, [120, 120])
        self.assertEqual([l["cubierto"] for l in body["lotes"]], [True, False])

    def test_el_total_manda_en_el_redondeo(self):
        """Los requeridos se redondean sobre el acumulado, no lote por lote: coherente con `viable`."""
        self.saved(lines=[self.line(self.tela, "1.333", "10")])
        self.set_stock(self.tela, "10.27")
        body = self.ok(7, [3, 4])  # 1,333 × 1,10 × 7 = 10,2641 -> 10,27 alcanza justo
        self.assertTrue(body["viable"])
        self.assertTrue(all(l["cubierto"] for l in body["lotes"]))

    def test_la_suma_debe_ser_el_total(self):
        for lots, word in (([50, 40], "faltan 10"), ([60, 60], "sobran 20")):
            response = self.simulate(100, lots)
            self.assertEqual(response.status_code, 400, lots)
            message = response.json()["lotes"][0]
            self.assertIn(word, message)
            self.assertIn("suman", message)

    def test_lotes_invalidos(self):
        for bad in ([], [0, 100], [-5, 105], [50.5, 49.5], ["a", 100], [None, 100], [True, 99], "100", 100, {"a": 1}, [[50], [50]]):
            response = self.simulate(100, bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("lotes", response.json(), bad)

    def test_los_lotes_numericos_como_texto_se_aceptan(self):
        body = self.ok(100, ["60", " 40 "])
        self.assertEqual([l["cantidad"] for l in body["lotes"]], [60, 40])

    def test_tope_de_lotes(self):
        too_many = [1] * (catalog.MAX_LOTS + 1)
        response = self.simulate(len(too_many), too_many)
        self.assertEqual(response.status_code, 400)
        self.assertIn("máximo", response.json()["lotes"][0])
        self.assertEqual(self.simulate(catalog.MAX_LOTS, [1] * catalog.MAX_LOTS).status_code, 200)

    def test_los_lotes_nulos_equivalen_a_no_enviarlos(self):
        response = self.simulate(100, None)
        body = self.api.post(self.sim_url, {"referencia": self.ref["id"], "cantidad": 100, "lotes": None}, format="json").json()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(body["lotes"])


class ValidationTests(SimulationBase):
    def test_cantidad_invalida(self):
        for bad in (0, -1, "abc", 1.5, "", None, 100001, True, [5]):
            response = self.simulate(bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("cantidad", response.json(), bad)
        self.assertEqual(self.simulate(reference_catalog.MAX_GARMENTS).status_code, 200)

    def test_cantidad_como_texto(self):
        self.assertEqual(self.ok("100")["cantidad"], 100)

    def test_faltan_campos(self):
        self.assertEqual(self.api.post(self.sim_url, {}, format="json").status_code, 400)
        self.assertIn("referencia", self.api.post(self.sim_url, {"cantidad": 5}, format="json").json())
        self.assertIn("cantidad", self.api.post(self.sim_url, {"referencia": self.ref["id"]}, format="json").json())

    def test_la_referencia_debe_existir_y_estar_activa(self):
        borrador = self.new(nombre="Borrador")
        descontinuada = self.new(nombre="Vieja")
        self.activate(descontinuada["id"])
        self.set_state(descontinuada["id"], reference_catalog.DISCONTINUED)
        for ref in ({"id": 99999}, borrador, descontinuada):
            response = self.simulate(10, reference=ref)
            self.assertEqual(response.status_code, 400, ref)
            self.assertIn("no existe o no está activa", response.json()["referencia"][0])

    def test_una_referencia_archivada_no_se_simula(self):
        other = self.new(nombre="Archivada")
        Referencia.objects.get(pk=other["id"]).delete()
        self.assertEqual(self.simulate(10, reference=other).status_code, 400)

    def test_la_referencia_debe_tener_ficha(self):
        sin_ficha = self.new(nombre="Sin ficha")
        self.activate(sin_ficha["id"])
        response = self.simulate(10, reference=sin_ficha)
        self.assertEqual(response.status_code, 400)
        self.assertIn("ficha técnica", response.json()["referencia"][0])

    def test_una_ficha_quitada_tampoco_se_simula(self):
        self.api.delete(self.url_ficha())
        self.assertEqual(self.simulate(10).status_code, 400)

    def url_ficha(self):
        return reverse("referencia_ficha", args=[self.ref["id"]])


class PermissionTests(SimulationBase):
    def test_pueden_planificar_produccion_gerente_y_administrador(self):
        for role in ("PRODUCCION", "GERENTE", "ADMIN"):
            client = client_for(make_user(f"{role.lower()}@t.co", role)) if role != "PRODUCCION" else self.api
            self.assertEqual(self.simulate(10, client=client).status_code, 200, role)

    def test_los_demas_roles_no(self):
        for role in ("ALMACENISTA", "VENDEDOR", "TERMINACION", "SECRETARIA", "PENDING"):
            client = client_for(make_user(f"{role.lower()}@t.co", role))
            self.assertEqual(self.simulate(10, client=client).status_code, 403, role)

    def test_sin_sesion(self):
        self.assertEqual(self.simulate(10, client=APIClient()).status_code, 401)

    def test_solo_se_acepta_post(self):
        for method in ("get", "put", "patch", "delete"):
            self.assertEqual(getattr(self.api, method)(self.sim_url).status_code, 403, method)  # sin permiso declarado: cerrado

    def test_la_simulacion_solo_exige_poder_ver(self):
        from apps.users.models import Role

        perms = set(Role.objects.get(code="PRODUCCION").permissions.values_list("code", flat=True))
        self.assertIn(catalog.PRODUCTION_VIEW, perms)
        self.assertEqual(catalog.PRODUCTION_VIEW, "produccion.ver")


class QueryCountTests(SimulationBase):
    def test_el_numero_de_consultas_no_crece_con_los_materiales(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.simulate(10, [5, 5]).status_code, 200)
            return len(queries)

        few = count()
        extra = [self.line(self.material(f"Extra {n}", inventory_catalog.CAT_OTHER, "unidad", stock="1000"), "1") for n in range(15)]
        self.saved(lines=[self.line(self.tela, "1.5", "10"), *extra])
        self.assertEqual(count(), few)


class ServiceTests(SimulationBase):
    """Las reglas del servicio, sin pasar por HTTP."""

    def reference(self):
        return Referencia.objects.get(pk=self.ref["id"])

    def test_clean_lots(self):
        self.assertIsNone(services.clean_lots(None, 10))
        self.assertEqual(services.clean_lots([4, "6"], 10), [4, 6])

    def test_get_reference_solo_activas(self):
        self.assertEqual(services.get_reference(self.ref["id"]).pk, self.ref["id"])

    def test_producible_con_una_ficha_cargada(self):
        lines = fichas.ficha_lines(self.reference())
        self.assertEqual(min(services.producible(line) for line in lines), 200)
        best, bottleneck = services.max_producible(lines)
        self.assertEqual((best, bottleneck["nombre"]), (200, "Botón 17 mm"))

    def test_lot_coverage_con_stock_justo(self):
        lines = fichas.ficha_lines(self.reference())
        coverage = services.lot_coverage(lines, [100, 100, 1])
        self.assertEqual([lot["cubierto"] for lot in coverage], [True, True, False])
