"""Producto terminado (HU 6.2 / RF21): ingreso de las aptas por talla, existencias en matriz y libro de movimientos."""
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Consecutivo
from apps.inventory.tests import client_for, make_user
from apps.production.models import LoteTalla
from apps.quality.models import Inspeccion
from apps.quality.test_calidad import QualityBase
from apps.references import catalog as reference_catalog
from apps.references.models import Referencia, Variante

from . import catalog
from .models import IngresoTerminado, MovimientoTerminado, StockTerminado


class FinishedBase(QualityBase):
    """Lote 1 inspeccionado con 50 aptas y 5 marras; lote 2 con 40 aptas. La referencia tiene cuatro variantes."""

    def setUp(self):
        super().setUp()
        Referencia.objects.filter(pk=self.ref["id"]).update(estado=reference_catalog.ACTIVE)
        self.secretary = client_for(make_user("secretaria@t.co", "SECRETARIA"))
        self.admin = client_for(make_user("admin@t.co", "ADMIN"))
        self.v30 = Variante.objects.get(referencia_id=self.ref["id"], talla="30")
        self.v32 = Variante.objects.create(referencia_id=self.ref["id"], talla="32", color="Azul oscuro")
        self.v34 = Variante.objects.create(referencia_id=self.ref["id"], talla="34", color="Azul oscuro")
        self.v30n = Variante.objects.create(referencia_id=self.ref["id"], talla="30", color="Negro")
        seam = self.defect("Costura floja")
        self.inspection1 = self.inspected(self.lot1, aptas=50, defects=[{"defecto": seam.id, "cantidad": 5}])
        self.inspection2 = self.inspected(self.lot2, aptas=40)

    def inspected(self, lot, aptas, defects=None):
        response = self.inspect(lot, aptas=aptas, defects=defects or [])
        self.assertEqual(response.status_code, 201, response.content)
        return Inspeccion.objects.get(pk=response.json()["id"])

    def lines(self, *pairs):
        return [{"variante": variant.id, "cantidad": quantity} for variant, quantity in pairs]

    def enter(self, inspection=None, lines=None, client=None, **extra):
        inspection = inspection or self.inspection1
        body = {"inspeccion": inspection.id, "lineas": lines if lines is not None else self.lines((self.v30, 20), (self.v32, 20), (self.v34, 10))}
        body.update(extra)
        return (client or self.secretary).post(reverse("terminado_ingresos"), body, format="json")

    def stock(self, variant):
        row = StockTerminado.objects.filter(variante=variant).first()
        return row.cantidad if row else 0


class EntryTests(FinishedBase):
    def test_ingresa_las_aptas_por_talla_y_suma_al_saldo(self):
        LoteTalla.objects.create(lote=self.lot1, variante=self.v30, talla="30", color="Azul oscuro", cantidad=25)
        response = self.enter(ubicacion="Estante A2", observaciones="Revisado")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["codigo"], body["lote_codigo"], body["aptas"], body["ubicacion"]), ("IPT-0001", self.lot1.codigo, 50, "Estante A2"))
        self.assertEqual(body["inspeccion_codigo"], self.inspection1.codigo)
        self.assertEqual([(row["talla"], row["cantidad"]) for row in body["lineas"]], [("30", 20), ("32", 20), ("34", 10)])
        first = body["lineas"][0]
        self.assertEqual((first["planificada"], first["diferencia"]), (25, -5))  # lo planificado es solo un dato
        self.assertIsNone(body["lineas"][1]["planificada"])
        self.assertEqual((self.stock(self.v30), self.stock(self.v32), self.stock(self.v34)), (20, 20, 10))
        self.assertEqual(IngresoTerminado.objects.count(), 1)

    def test_deja_un_movimiento_por_variante_con_su_saldo(self):
        self.enter()
        moves = list(MovimientoTerminado.objects.order_by("variante_id"))
        self.assertEqual([(m.variante_id, m.cantidad, m.saldo_antes, m.saldo_despues) for m in moves],
                         [(self.v30.id, 20, 0, 20), (self.v32.id, 20, 0, 20), (self.v34.id, 10, 0, 10)])
        self.assertTrue(all(m.tipo == catalog.ENTRY_PRODUCTION and m.lote_id == self.lot1.id and m.ingreso_id for m in moves))
        self.enter(self.inspection2, self.lines((self.v30, 40)))
        last = MovimientoTerminado.objects.filter(variante=self.v30).order_by("id").last()
        self.assertEqual((last.saldo_antes, last.saldo_despues), (20, 60))  # el saldo sigue al anterior
        self.assertEqual(self.stock(self.v30), 60)

    def test_el_saldo_es_la_suma_del_libro(self):
        self.enter()
        self.enter(self.inspection2, self.lines((self.v30, 15), (self.v30n, 25)))
        for variant in (self.v30, self.v32, self.v34, self.v30n):
            total = sum(m.cantidad for m in MovimientoTerminado.objects.filter(variante=variant))
            self.assertEqual(self.stock(variant), total)

    def test_las_marras_no_entran_al_saldo(self):
        self.enter()
        self.assertEqual(sum(row.cantidad for row in StockTerminado.objects.all()), 50)  # 50 aptas, sin las 5 marras

    def test_la_suma_debe_ser_exactamente_las_aptas(self):
        for lines in (self.lines((self.v30, 20), (self.v32, 20)), self.lines((self.v30, 30), (self.v32, 21)),
                      self.lines((self.v30, 50), (self.v32, 1))):
            response = self.enter(lines=lines)
            self.assertEqual(response.status_code, 400, lines)
            self.assertIn("suman", response.json()["lineas"][0])
        self.assertIn("faltan 10", self.enter(lines=self.lines((self.v30, 40))).json()["lineas"][0])
        self.assertIn("falta 1", self.enter(lines=self.lines((self.v30, 49))).json()["lineas"][0])
        self.assertIn("sobra 1", self.enter(lines=self.lines((self.v30, 51))).json()["lineas"][0])
        self.assertEqual((IngresoTerminado.objects.count(), StockTerminado.objects.count()), (0, 0))
        self.assertFalse(Consecutivo.objects.filter(clave="IPT").exists())  # los rechazos no gastan el consecutivo

    def test_una_inspeccion_se_ingresa_una_sola_vez(self):
        self.assertEqual(self.enter().status_code, 201)
        response = self.enter()
        self.assertEqual(response.status_code, 409)
        self.assertIn("ya fue ingresada", response.json()["inspeccion"][0])
        self.assertEqual((IngresoTerminado.objects.count(), self.stock(self.v30)), (1, 20))  # no se sumó dos veces

    def test_la_base_impide_el_doble_ingreso_y_los_saldos_que_no_cuadran(self):
        self.enter()
        with self.assertRaises(IntegrityError), transaction.atomic():
            IngresoTerminado.objects.create(codigo="IPT-9999", inspeccion=self.inspection1, lote=self.lot1, aptas=50, fecha=self.today)
        variant = self.v30
        with self.assertRaises(IntegrityError), transaction.atomic():
            MovimientoTerminado.objects.create(variante=variant, tipo=catalog.ADJUSTMENT, cantidad=5, saldo_antes=0, saldo_despues=9)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MovimientoTerminado.objects.create(variante=variant, tipo=catalog.ADJUSTMENT, cantidad=0, saldo_antes=3, saldo_despues=3)

    def test_las_variantes_deben_ser_de_la_referencia_del_lote(self):
        other = self.new(nombre="Mom vintage")
        foreign = Variante.objects.get(referencia_id=other["id"])
        response = self.enter(lines=self.lines((self.v30, 40), (foreign, 10)))
        self.assertEqual(response.status_code, 400)
        self.assertIn("no es de la referencia", response.json()["lineas"][0])
        self.assertEqual(StockTerminado.objects.count(), 0)

    def test_cantidades_enteras_y_sin_repetir(self):
        for bad in (0, -3, 2.5, "x", True):
            lines = [{"variante": self.v30.id, "cantidad": bad}, {"variante": self.v32.id, "cantidad": 50}]
            self.assertEqual(self.enter(lines=lines).status_code, 400, bad)
        repeated = self.lines((self.v30, 25), (self.v30, 25))
        self.assertIn("repetirse", self.enter(lines=repeated).json()["lineas"][0])
        self.assertEqual(self.enter(lines=[]).status_code, 400)
        self.assertEqual(self.enter(lines=[{"variante": "x", "cantidad": 5}]).status_code, 400)
        self.assertEqual(self.enter(lines=[{"variante": 9999, "cantidad": 50}]).status_code, 400)

    def test_inspeccion_inexistente_sin_aptas_o_de_orden_anulada(self):
        self.assertEqual(self.enter(inspeccion=99999).status_code, 400)
        lot3 = self.make_lot(self.order, number=3, quantity=10)
        self.returned(lot3, sent=10, good=9, lost=1)
        only_flawed = self.inspected(lot3, aptas=0, defects=[{"defecto": self.defect("Mancha").id, "cantidad": 9}])
        response = self.enter(only_flawed, self.lines((self.v30, 1)))
        self.assertEqual(response.status_code, 400)
        self.assertIn("no tiene prendas aptas", response.json()["inspeccion"][0])
        out = self.order.orden_salida
        out.estado = inventory_catalog.STATUS_CANCELLED
        out.save()
        self.assertIn("anulada", self.enter().json()["inspeccion"][0])

    def test_la_fecha_no_puede_ser_futura(self):
        future = (self.today + timezone.timedelta(days=1)).isoformat()
        self.assertEqual(self.enter(fecha=future).status_code, 400)

    def test_permisos_por_rol(self):
        self.assertEqual(self.enter(client=self.seller).status_code, 403)  # el Vendedor solo consulta
        self.assertEqual(self.enter(client=self.viewer).status_code, 403)  # el Gerente también
        self.assertEqual(self.enter(client=self.finisher).status_code, 403)
        self.assertEqual(self.enter(client=self.store).status_code, 403)
        self.assertEqual(self.enter(client=self.admin).status_code, 201)
        for client in (self.seller, self.viewer, self.secretary):
            self.assertEqual(client.get(reverse("terminado_ingresos")).status_code, 200)
        self.assertEqual(self.store.get(reverse("terminado_ingresos")).status_code, 403)
        self.assertEqual(self.finisher.get(reverse("terminado_existencias")).status_code, 403)

    def test_los_ingresos_no_se_editan_ni_se_borran(self):
        entry_id = self.enter().json()["id"]
        url = reverse("terminado_ingreso", args=[entry_id])
        for method in ("put", "patch", "delete"):
            self.assertIn(getattr(self.secretary, method)(url).status_code, (403, 405), method)
        self.assertEqual(IngresoTerminado.objects.count(), 1)
        self.assertEqual(self.seller.get(url).status_code, 200)
        self.assertEqual(self.seller.get(reverse("terminado_ingreso", args=[9999])).status_code, 404)


class ListTests(FinishedBase):
    def test_pendientes_trae_las_variantes_y_lo_planificado(self):
        LoteTalla.objects.create(lote=self.lot1, variante=self.v30, talla="30", color="Azul oscuro", cantidad=30)
        rows = self.seller.get(reverse("terminado_pendientes")).json()
        self.assertEqual([row["lote_codigo"] for row in rows], [self.lot1.codigo, self.lot2.codigo])
        first = rows[0]
        self.assertEqual((first["aptas"], first["marras"], first["orden_codigo"]), (50, 5, "OP-0300"))
        self.assertEqual({(v["talla"], v["color"]) for v in first["variantes"]},
                         {("30", "Azul oscuro"), ("32", "Azul oscuro"), ("34", "Azul oscuro"), ("30", "Negro")})
        self.assertEqual(first["planificado"], [{"variante": self.v30.id, "cantidad": 30}])
        self.assertEqual(rows[1]["planificado"], [])

    def test_una_inspeccion_ingresada_sale_de_pendientes(self):
        self.enter(self.inspection2, self.lines((self.v30, 40)))
        rows = self.secretary.get(reverse("terminado_pendientes")).json()
        self.assertEqual([row["inspeccion"] for row in rows], [self.inspection1.id])

    def test_pendientes_no_hace_consultas_por_fila(self):
        self.secretary.get(reverse("terminado_pendientes"))  # la primera llamada carga los permisos
        with CaptureQueriesContext(connection) as small:
            self.secretary.get(reverse("terminado_pendientes"))
        for number in range(3, 6):
            lot = self.make_lot(self.order, number=number, quantity=5)
            self.returned(lot, sent=5, good=5)
            self.inspected(lot, aptas=5)
        with CaptureQueriesContext(connection) as big:
            rows = self.secretary.get(reverse("terminado_pendientes")).json()
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(big), len(small))

    def test_lista_de_ingresos_con_filtros(self):
        self.enter()
        self.enter(self.inspection2, self.lines((self.v30, 40)))
        url = reverse("terminado_ingresos")
        self.assertEqual(len(self.seller.get(url).json()), 2)
        self.assertEqual(len(self.seller.get(url, {"lote": self.lot2.id}).json()), 1)
        self.assertEqual(len(self.seller.get(url, {"referencia": self.ref["id"]}).json()), 2)
        self.assertEqual(len(self.seller.get(url, {"q": "IPT-0002"}).json()), 1)
        self.assertEqual(len(self.seller.get(url, {"desde": (self.today + timezone.timedelta(days=1)).isoformat()}).json()), 0)
        self.assertEqual(self.seller.get(url, {"lote": "abc"}).status_code, 400)

    def test_existencias_en_matriz_con_ceros_y_totales(self):
        self.enter()
        matrix = self.seller.get(reverse("terminado_existencias")).json()
        self.assertEqual(len(matrix), 1)
        reference = matrix[0]
        self.assertEqual((reference["nombre"], reference["total"]), ("Skinny 5 bolsillos", 50))
        self.assertEqual(reference["tallas"], ["30", "32", "34"])  # las tallas, en orden numérico
        colors = {row["color"]: row for row in reference["colores"]}
        self.assertEqual(colors["Azul oscuro"]["total"], 50)
        self.assertEqual(colors["Azul oscuro"]["tallas"]["32"]["cantidad"], 20)
        self.assertEqual(colors["Negro"]["tallas"]["30"]["cantidad"], 0)  # variante sin saldo: en cero
        self.assertNotIn("32", colors["Negro"]["tallas"])

    def test_existencias_filtra_por_referencia_y_valida(self):
        other = self.new(nombre="Mom vintage")
        Referencia.objects.filter(pk=other["id"]).update(estado=reference_catalog.ACTIVE)
        everything = self.seller.get(reverse("terminado_existencias")).json()
        only = self.seller.get(reverse("terminado_existencias"), {"referencia": other["id"]}).json()
        self.assertEqual(len(only), 1)
        self.assertGreaterEqual(len(everything), 1)
        self.assertEqual(self.seller.get(reverse("terminado_existencias"), {"referencia": "x"}).status_code, 400)

    def test_movimientos_con_filtros_y_solo_lectura(self):
        self.enter()
        url = reverse("terminado_movimientos")
        rows = self.seller.get(url).json()
        self.assertEqual(len(rows), 3)
        self.assertEqual((rows[0]["tipo"], rows[0]["tipo_nombre"]), ("ENTRADA_PRODUCCION", "Entrada de producción"))
        self.assertTrue(rows[0]["ingreso_codigo"].startswith("IPT-") and rows[0]["lote_codigo"] == self.lot1.codigo)
        self.assertEqual(len(self.seller.get(url, {"variante": self.v32.id}).json()), 1)
        self.assertEqual(len(self.seller.get(url, {"tipo": "AJUSTE"}).json()), 0)
        self.assertEqual(len(self.seller.get(url, {"referencia": self.ref["id"]}).json()), 3)
        self.assertEqual(self.seller.get(url, {"variante": "x"}).status_code, 400)
        for method in ("post", "put", "patch", "delete"):
            self.assertIn(getattr(self.secretary, method)(url, {}, format="json").status_code, (403, 405), method)

    def test_las_consultas_no_crecen_con_las_filas(self):
        self.enter()
        self.seller.get(reverse("terminado_movimientos"))
        with CaptureQueriesContext(connection) as small:
            self.seller.get(reverse("terminado_movimientos"))
        self.enter(self.inspection2, self.lines((self.v30, 10), (self.v32, 10), (self.v34, 10), (self.v30n, 10)))
        with CaptureQueriesContext(connection) as big:
            rows = self.seller.get(reverse("terminado_movimientos")).json()
        self.assertEqual(len(rows), 7)
        self.assertEqual(len(big), len(small))
        with CaptureQueriesContext(connection) as ingresos:
            self.seller.get(reverse("terminado_ingresos"))
        self.assertLessEqual(len(ingresos), 6)
