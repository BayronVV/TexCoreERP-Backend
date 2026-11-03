"""Ajuste manual del producto terminado (HU 6.3 / RF22): conteo real contra el sistema, motivo, observación y comprobante."""
import uuid

from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.inventory.models import Consecutivo

from . import catalog
from .models import AjusteLinea, AjusteTerminado, MovimientoTerminado
from .test_terminado import FinishedBase

OBSERVATION = "Conteo de la bodega del viernes"
LONG_OBSERVATION = "Se contó dos veces la estantería B y faltan cajas completas"


class AdjustBase(FinishedBase):
    """Stock inicial: v30 = 20, v32 = 20, v34 = 10 (del ingreso de la inspección 1); v30n sin saldo."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.enter().status_code, 201)

    def adjust(self, rows, motivo="ERROR_CONTEO", observacion=OBSERVATION, client=None, token=None, **extra):
        """`rows` son `(variante, esperado, contado)`."""
        body = {
            "motivo": motivo, "observacion": observacion, "token": str(uuid.uuid4()) if token is None else str(token),
            "lineas": [{"variante": variant.id, "esperado": expected, "contado": counted} for variant, expected, counted in rows],
        }
        body.update(extra)
        return (client or self.secretary).post(reverse("terminado_ajustes"), body, format="json")

    def book_sum(self, variant):
        return sum(MovimientoTerminado.objects.filter(variante=variant).values_list("cantidad", flat=True))


class AdjustTests(AdjustBase):
    def test_calcula_la_diferencia_desde_el_conteo_y_deja_el_comprobante(self):
        response = self.adjust([(self.v30, 20, 18), (self.v32, 20, 20), (self.v34, 10, 12)])
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["codigo"], body["motivo"], body["motivo_nombre"]), ("AJT-0001", "ERROR_CONTEO", "Error de conteo"))
        self.assertEqual((body["unidades_faltantes"], body["unidades_sobrantes"]), (2, 2))  # nunca se netean
        self.assertEqual(body["observacion"], OBSERVATION)
        self.assertEqual([(l["talla"], l["stock_antes"], l["stock_contado"], l["diferencia"]) for l in body["lineas"]],
                         [("30", 20, 18, -2), ("34", 10, 12, 2)])  # la línea sin diferencia no se guarda
        self.assertEqual((self.stock(self.v30), self.stock(self.v32), self.stock(self.v34)), (18, 20, 12))
        self.assertEqual(body["referencia"], self.ref["id"])

    def test_cada_linea_escribe_un_movimiento_de_ajuste_con_su_saldo(self):
        self.adjust([(self.v30, 20, 15), (self.v34, 10, 11)], motivo="ERROR_CONTEO")
        moves = list(MovimientoTerminado.objects.filter(tipo=catalog.ADJUSTMENT).order_by("variante_id"))
        self.assertEqual([(m.variante_id, m.cantidad, m.saldo_antes, m.saldo_despues) for m in moves],
                         [(self.v30.id, -5, 20, 15), (self.v34.id, 1, 10, 11)])
        self.assertTrue(all(m.ajuste.codigo == "AJT-0001" and m.usuario_id and "Error de conteo" in m.motivo for m in moves))
        rows = self.seller.get(reverse("terminado_movimientos"), {"tipo": "AJUSTE"}).json()
        self.assertEqual({row["ajuste_codigo"] for row in rows}, {"AJT-0001"})

    def test_el_saldo_sigue_siendo_la_suma_del_libro(self):
        self.adjust([(self.v30, 20, 12), (self.v32, 20, 25)])
        self.adjust([(self.v30, 12, 13), (self.v30n, 0, 3)], motivo="SOBRANTE")
        for variant in (self.v30, self.v32, self.v34, self.v30n):
            self.assertEqual(self.stock(variant), self.book_sum(variant), variant)
        self.assertEqual(self.stock(self.v30n), 3)  # una variante sin saldo previo se crea en cero y se ajusta

    def test_el_conteo_puede_dejar_el_saldo_en_cero(self):
        self.assertEqual(self.adjust([(self.v34, 10, 0)], motivo="PERDIDA").status_code, 201)
        self.assertEqual(self.stock(self.v34), 0)

    def test_si_el_saldo_cambio_responde_409_y_no_guarda_nada(self):
        self.enter(self.inspection2, self.lines((self.v30, 40)))  # alguien ingresó mientras se contaba
        before = MovimientoTerminado.objects.count()
        response = self.adjust([(self.v30, 20, 18), (self.v32, 20, 19)])
        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn("30 Azul oscuro", response.json()["detail"][0])
        self.assertEqual(response.json()["variantes"], ["30 Azul oscuro"])
        self.assertEqual(AjusteTerminado.objects.count(), 0)
        self.assertEqual(MovimientoTerminado.objects.count(), before)
        self.assertEqual((self.stock(self.v30), self.stock(self.v32)), (60, 20))  # ni siquiera la línea que sí coincidía
        self.assertEqual(Consecutivo.objects.filter(clave=catalog.ADJUST_PREFIX).count(), 0)

    def test_sin_diferencias_no_hay_ajuste(self):
        response = self.adjust([(self.v30, 20, 20), (self.v32, 20, 20)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("No hay diferencias", response.json()["lineas"][0])
        self.assertEqual(AjusteTerminado.objects.count(), 0)

    def test_conteos_y_variantes_invalidos(self):
        bad_counts = [-1, 1.5, "x", True, None]
        for value in bad_counts:
            body = {"motivo": "ERROR_CONTEO", "observacion": OBSERVATION, "token": str(uuid.uuid4()),
                    "lineas": [{"variante": self.v30.id, "esperado": 20, "contado": value}]}
            response = self.secretary.post(reverse("terminado_ajustes"), body, format="json")
            self.assertEqual(response.status_code, 400, value)
        self.assertEqual(self.adjust([(self.v30, 20, 19), (self.v30, 20, 18)]).status_code, 400)  # repetida
        self.assertEqual(self.adjust([]).status_code, 400)
        body = {"motivo": "ERROR_CONTEO", "observacion": OBSERVATION, "token": str(uuid.uuid4()),
                "lineas": [{"variante": 999999, "esperado": 0, "contado": 1}]}
        self.assertEqual(self.secretary.post(reverse("terminado_ajustes"), body, format="json").status_code, 400)
        self.assertEqual(AjusteTerminado.objects.count(), 0)

    def test_motivo_y_token_validos(self):
        self.assertEqual(self.adjust([(self.v30, 20, 19)], motivo="INVENTADO").status_code, 400)
        self.assertEqual(self.adjust([(self.v30, 20, 19)], motivo="").status_code, 400)
        self.assertEqual(self.adjust([(self.v30, 20, 19)], token="no-es-un-uuid").status_code, 400)
        self.assertEqual(self.adjust([(self.v30, 20, 19)], token="").status_code, 400)
        self.assertEqual(AjusteTerminado.objects.count(), 0)


class ReasonRuleTests(AdjustBase):
    def test_los_motivos_que_solo_restan_rechazan_los_sobrantes(self):
        balance = 20
        for reason in ("MUESTRA_COMERCIAL", "PERDIDA", "PRENDA_DANADA"):
            response = self.adjust([(self.v30, balance, balance + 1)], motivo=reason)
            self.assertEqual(response.status_code, 400, reason)
            self.assertIn("solo puede restar", response.json()["motivo"][0])
            self.assertEqual(self.adjust([(self.v30, balance, balance - 1)], motivo=reason).status_code, 201, reason)
            balance -= 1
        self.assertEqual(self.stock(self.v30), 17)

    def test_sobrante_solo_suma(self):
        response = self.adjust([(self.v30, 20, 19)], motivo="SOBRANTE")
        self.assertEqual(response.status_code, 400)
        self.assertIn("solo puede sumar", response.json()["motivo"][0])
        self.assertEqual(self.adjust([(self.v30, 20, 24)], motivo="SOBRANTE").status_code, 201)

    def test_error_de_conteo_y_otro_admiten_ambos_signos(self):
        self.assertEqual(self.adjust([(self.v30, 20, 19), (self.v32, 20, 22)], motivo="ERROR_CONTEO").status_code, 201)
        self.assertEqual(self.adjust([(self.v30, 19, 20), (self.v32, 22, 21)], motivo="OTRO").status_code, 201)

    def test_la_observacion_es_siempre_obligatoria(self):
        for text in ("", "   ", "corto", "x" * 9):
            self.assertEqual(self.adjust([(self.v30, 20, 19)], observacion=text).status_code, 400, repr(text))
        self.assertEqual(self.adjust([(self.v30, 20, 19)], observacion="x" * 501).status_code, 400)
        self.assertEqual(self.adjust([(self.v30, 20, 19)], observacion="x" * 10).status_code, 201)

    def test_la_base_exige_observacion(self):
        self.adjust([(self.v30, 20, 19)])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AjusteTerminado.objects.filter().update(observacion="")


class LargeAdjustmentTests(AdjustBase):
    """RF22 / MSG-ERR-18: más de 20 unidades en una línea. Se mide por línea, no por el total del ajuste."""

    def test_exactamente_20_no_supera_el_umbral(self):
        response = self.adjust([(self.v30, 20, 0)], motivo="OTRO")
        self.assertEqual(response.status_code, 201, response.content)

    def test_21_en_una_linea_con_otro_se_rechaza(self):
        self.enter(self.inspection2, self.lines((self.v30, 40)))
        response = self.adjust([(self.v30, 60, 38)], motivo="OTRO", observacion=LONG_OBSERVATION)
        self.assertEqual(response.status_code, 400)
        self.assertIn("«Otro» no se acepta", response.json()["motivo"][0])
        self.assertEqual(AjusteTerminado.objects.count(), 0)

    def test_mas_de_20_pide_observacion_de_30_caracteres(self):
        self.enter(self.inspection2, self.lines((self.v30, 40)))
        response = self.adjust([(self.v30, 60, 38)], motivo="PERDIDA", observacion="Faltan cajas del lote")
        self.assertEqual(response.status_code, 400)
        self.assertIn("al menos 30", response.json()["observacion"][0])
        self.assertEqual(self.adjust([(self.v30, 60, 38)], motivo="PERDIDA", observacion=LONG_OBSERVATION).status_code, 201)

    def test_el_total_del_ajuste_no_cuenta_solo_cada_linea(self):
        self.enter(self.inspection2, self.lines((self.v30, 40)))
        # 15 + 15 + 10 = 40 unidades en total, pero ninguna línea pasa de 20: «Otro» y observación corta valen.
        response = self.adjust([(self.v30, 60, 45), (self.v32, 20, 5), (self.v34, 10, 0)], motivo="OTRO")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["unidades_faltantes"], 40)

    def test_el_sobrante_grande_tambien_cuenta(self):
        response = self.adjust([(self.v34, 10, 40)], motivo="OTRO", observacion=LONG_OBSERVATION)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.adjust([(self.v34, 10, 40)], motivo="SOBRANTE", observacion=LONG_OBSERVATION).status_code, 201)

    def test_los_umbrales_salen_de_los_metadatos(self):
        data = self.seller.get(reverse("terminado_metadatos")).json()
        self.assertEqual((data["umbral_unidades"], data["observacion_minima"], data["observacion_minima_umbral"]), (20, 10, 30))
        self.assertEqual(data["motivo_no_valido_sobre_umbral"], "OTRO")
        signs = {m["codigo"]: m["signo"] for m in data["motivos"]}
        self.assertEqual((signs["PERDIDA"], signs["SOBRANTE"], signs["OTRO"]), ("-", "+", "+-"))
        self.assertEqual(len(data["motivos"]), 6)


class TokenTests(AdjustBase):
    def test_el_mismo_token_no_ajusta_dos_veces(self):
        token = uuid.uuid4()
        first = self.adjust([(self.v30, 20, 18)], token=token)
        self.assertEqual(first.status_code, 201)
        second = self.adjust([(self.v30, 20, 18)], token=token)  # doble clic: mismos datos
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["codigo"], "AJT-0001")
        self.assertEqual(second.json()["ajuste"], str(first.json()["id"]))
        self.assertEqual(self.stock(self.v30), 18)
        self.assertEqual(AjusteTerminado.objects.count(), 1)

    def test_la_base_impide_repetir_el_token(self):
        self.adjust([(self.v30, 20, 18)])
        adjustment = AjusteTerminado.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AjusteTerminado.objects.create(
                codigo="AJT-9999", motivo="OTRO", observacion="repetido", fecha=adjustment.fecha, token=adjustment.token,
                unidades_faltantes=0, unidades_sobrantes=0,
            )

    def test_la_base_impide_lineas_que_no_cuadran(self):
        self.adjust([(self.v30, 20, 18)])
        line = AjusteLinea.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AjusteLinea.objects.filter(pk=line.pk).update(diferencia=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AjusteLinea.objects.filter(pk=line.pk).update(diferencia=-5)


class ReadAndPermissionTests(AdjustBase):
    def test_los_comprobantes_no_se_editan_ni_se_borran(self):
        adjustment_id = self.adjust([(self.v30, 20, 18)]).json()["id"]
        url = reverse("terminado_ajuste", args=[adjustment_id])
        for method in ("put", "patch", "delete"):
            self.assertIn(getattr(self.secretary, method)(url).status_code, (403, 405), method)
        self.assertEqual(AjusteTerminado.objects.count(), 1)
        self.assertEqual(self.seller.get(url).status_code, 200)
        self.assertEqual(self.seller.get(reverse("terminado_ajuste", args=[9999])).status_code, 404)

    def test_permisos_por_rol(self):
        for client in (self.seller, self.viewer, self.finisher, self.store):
            self.assertEqual(self.adjust([(self.v30, 20, 19)], client=client).status_code, 403)  # ver no es ajustar
        self.assertEqual(AjusteTerminado.objects.count(), 0)
        self.assertEqual(self.adjust([(self.v30, 20, 19)], client=self.admin).status_code, 201)
        self.assertEqual(self.adjust([(self.v30, 19, 18)], client=self.secretary).status_code, 201)
        for client in (self.seller, self.viewer, self.secretary):
            self.assertEqual(client.get(reverse("terminado_ajustes")).status_code, 200)
            self.assertEqual(client.get(reverse("terminado_metadatos")).status_code, 200)
        for client in (self.store, self.finisher):
            self.assertEqual(client.get(reverse("terminado_ajustes")).status_code, 403)
            self.assertEqual(client.get(reverse("terminado_metadatos")).status_code, 403)

    def test_lista_con_filtros(self):
        self.adjust([(self.v30, 20, 18)], motivo="ERROR_CONTEO", observacion="Error del conteo de la tarde")
        self.adjust([(self.v32, 20, 19)], motivo="PERDIDA", observacion="Se perdió una prenda en el traslado")
        url = reverse("terminado_ajustes")
        rows = self.seller.get(url).json()
        self.assertEqual([row["codigo"] for row in rows], ["AJT-0002", "AJT-0001"])
        self.assertTrue(rows[0]["realizado_por_nombre"])
        self.assertEqual(len(self.seller.get(url, {"motivo": "PERDIDA"}).json()), 1)
        self.assertEqual(len(self.seller.get(url, {"referencia": self.ref["id"]}).json()), 2)
        self.assertEqual(len(self.seller.get(url, {"q": "traslado"}).json()), 1)
        self.assertEqual(len(self.seller.get(url, {"q": "AJT-0001"}).json()), 1)
        self.assertEqual(len(self.seller.get(url, {"desde": "2999-01-01"}).json()), 0)
        self.assertEqual(self.seller.get(url, {"referencia": "x"}).status_code, 400)

    def test_las_consultas_no_crecen_con_las_filas(self):
        self.adjust([(self.v30, 20, 19)])
        self.seller.get(reverse("terminado_ajustes"))
        with CaptureQueriesContext(connection) as small:
            self.seller.get(reverse("terminado_ajustes"))
        self.adjust([(self.v30, 19, 18), (self.v32, 20, 19), (self.v34, 10, 9)])
        self.adjust([(self.v30, 18, 17), (self.v32, 19, 18)])
        with CaptureQueriesContext(connection) as big:
            rows = self.seller.get(reverse("terminado_ajustes")).json()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(big), len(small))
