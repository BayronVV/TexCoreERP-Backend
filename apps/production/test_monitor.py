"""Monitor de estado (HU 4.5 / RF15): lotes agrupados por columna, con totales, límites, filtros, orden y rendimiento."""
from datetime import datetime, timedelta
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.inventory.tests import client_for, make_user

from . import catalog, monitor, tracking
from .models import EtapaLote, Lote, OrdenProduccion
from .test_ordenes import OrderBase

# Las horas de las pruebas se cuentan desde ayer a esta hora: la columna Terminada solo muestra los últimos días, así que una
# fecha fija dejaría de funcionar con el paso del tiempo.
T0 = (timezone.now() - timedelta(days=1)).replace(microsecond=0)
STATES = ["PLANEADA", "EN_PROCESO", "EN_PAUSA", "TERMINADA"]


def at(minutes):
    return T0 + timedelta(minutes=minutes)


class MonitorBase(OrderBase):
    def setUp(self):
        super().setUp()
        self.monitor_url = reverse("produccion_monitor")

    def lots_of(self, quantity=30, parts=3, **extra):
        """Crea una orden con `parts` lotes iguales y devuelve sus lotes en orden."""
        size = quantity // parts
        body = self.placed(quantity, [{"cantidad": size}] * parts, **extra)
        return list(OrdenProduccion.objects.get(pk=body["id"]).lotes.all())

    def act(self, lot, action, minutes, user=None):
        return tracking.act_on_lot(user=user or self.boss, lot_id=lot.id, action=action, now=at(minutes))

    def finish(self, lot, start=0):
        """Termina las tres etapas del lote; devuelve el minuto en que terminó la última."""
        minute = start
        for _ in catalog.STAGE_ORDER:
            self.act(lot, "iniciar", minute)
            self.act(lot, "completar", minute + 5)
            minute += 10
        return minute

    def board(self, client=None, **params):
        response = (client or self.api).get(self.monitor_url, params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    @staticmethod
    def column(body, state):
        return next(column for column in body["columnas"] if column["estado"] == state)

    def codes(self, body, state):
        return [lot["codigo"] for lot in self.column(body, state)["lotes"]]


class StructureTests(MonitorBase):
    def test_siempre_trae_las_cuatro_columnas_en_orden_aunque_no_haya_lotes(self):
        body = self.board()
        self.assertEqual([c["estado"] for c in body["columnas"]], STATES)
        self.assertEqual([c["nombre"] for c in body["columnas"]], ["Planeada", "En proceso", "En pausa", "Terminada"])
        self.assertEqual([(c["total"], c["lotes"]) for c in body["columnas"]], [(0, [])] * 4)
        self.assertEqual(body["limite"], 50)
        self.assertTrue(body["generado_at"])

    def test_una_orden_nueva_deja_todos_sus_lotes_en_planeada(self):
        lots = self.lots_of()
        body = self.board()
        self.assertEqual(self.column(body, "PLANEADA")["total"], 3)
        self.assertEqual(self.codes(body, "PLANEADA"), [lot.codigo for lot in lots])
        self.assertEqual([self.column(body, s)["total"] for s in STATES[1:]], [0, 0, 0])

    def test_la_tarjeta_trae_lo_necesario(self):
        lot = self.lots_of(30, 3)[0]
        card = self.column(self.board(), "PLANEADA")["lotes"][0]
        self.assertEqual((card["id"], card["codigo"], card["cantidad"]), (lot.id, lot.codigo, 10))
        self.assertEqual((card["orden"], card["orden_codigo"]), (lot.orden_id, lot.orden.codigo))
        self.assertEqual((card["referencia_codigo"], card["referencia_nombre"]), (self.ref["codigo"], self.ref["nombre"]))
        self.assertEqual((card["estado"], card["estado_nombre"]), ("PLANEADA", "Planeada"))
        self.assertEqual((card["etapa_actual"], card["etapa_actual_nombre"]), ("CORTE", "Corte"))
        self.assertEqual((card["etapas_terminadas"], card["etapas_total"], card["tiempo_neto_segundos"]), (0, 3, 0))
        self.assertEqual((card["acciones"], card["en_curso_desde"], card["responsable_nombre"]), (["iniciar"], None, ""))
        self.assertFalse(card["termina_el_lote"])

    def test_la_tarjeta_de_un_lote_en_marcha_trae_tiempo_responsable_y_acciones(self):
        lot = self.lots_of()[0]
        self.act(lot, "iniciar", 0)
        card = self.column(self.board(), "EN_PROCESO")["lotes"][0]
        self.assertEqual((card["acciones"], card["responsable_nombre"]), (["pausar", "completar"], "produccion@t.co"))
        self.assertIsNotNone(card["en_curso_desde"])
        self.assertEqual(datetime.fromisoformat(card["ultimo_movimiento"]), at(0))  # misma hora, en la zona del proyecto

    def test_termina_el_lote_solo_en_la_ultima_etapa(self):
        lot = self.lots_of()[0]
        for index in range(2):  # corte y confección terminadas
            self.act(lot, "iniciar", index * 10)
            self.act(lot, "completar", index * 10 + 5)
        self.assertFalse(self.column(self.board(), "EN_PROCESO")["lotes"][0]["termina_el_lote"])
        self.act(lot, "iniciar", 30)  # terminación corriendo
        self.assertTrue(self.column(self.board(), "EN_PROCESO")["lotes"][0]["termina_el_lote"])
        self.act(lot, "pausar", 33)
        self.assertTrue(self.column(self.board(), "EN_PAUSA")["lotes"][0]["termina_el_lote"])


class ClassificationTests(MonitorBase):
    def test_cada_lote_cae_en_su_columna(self):
        planned, running, paused, done = self.lots_of(40, 4)
        self.act(running, "iniciar", 0)
        self.act(paused, "iniciar", 0)
        self.act(paused, "pausar", 5)
        self.finish(done)
        body = self.board()
        self.assertEqual(self.codes(body, "PLANEADA"), [planned.codigo])
        self.assertEqual(self.codes(body, "EN_PROCESO"), [running.codigo])
        self.assertEqual(self.codes(body, "EN_PAUSA"), [paused.codigo])
        self.assertEqual(self.codes(body, "TERMINADA"), [done.codigo])

    def test_un_lote_entre_dos_etapas_sigue_en_proceso(self):
        lot = self.lots_of()[0]
        self.act(lot, "iniciar", 0)
        self.act(lot, "completar", 10)
        self.assertEqual(self.codes(self.board(), "EN_PROCESO"), [lot.codigo])

    def test_el_tablero_coincide_con_el_estado_calculado_en_el_resto_del_sistema(self):
        """La consulta del tablero y `tracking.lot_state` deben dar siempre el mismo estado."""
        lots = self.lots_of(60, 6)
        scripts = [
            [], [("iniciar", 0)], [("iniciar", 0), ("pausar", 3)], [("iniciar", 0), ("completar", 4)],
            [("iniciar", 0), ("pausar", 2), ("reanudar", 5), ("completar", 9), ("iniciar", 12), ("pausar", 14)],
            "done",
        ]
        for lot, script in zip(lots, scripts, strict=True):
            if script == "done":
                self.finish(lot)
                continue
            for action, minute in script:
                self.act(lot, action, minute)
        body = self.board()
        for lot in Lote.objects.all():
            expected = tracking.lot_state([stage.estado for stage in lot.etapas.all()])
            self.assertIn(lot.codigo, self.codes(body, expected), (lot.codigo, expected))
        self.assertEqual(sum(column["total"] for column in body["columnas"]), 6)

    def test_un_lote_sin_etapas_se_muestra_como_planeado(self):
        lot = self.lots_of()[0]
        EtapaLote.all_objects.filter(lote=lot).hard_delete()
        self.assertIn(lot.codigo, self.codes(self.board(), "PLANEADA"))

    def test_los_lotes_de_ordenes_anuladas_no_aparecen(self):
        kept = self.lots_of(30, 3)
        cancelled = self.lots_of(30, 3)
        self.act(cancelled[0], "iniciar", 0)
        self.api.post(reverse("produccion_orden_anular", args=[cancelled[0].orden_id]), {"motivo": "Cambio"}, format="json")
        body = self.board()
        every = [code for state in STATES for code in self.codes(body, state)]
        self.assertEqual(sorted(every), sorted(lot.codigo for lot in kept))
        self.assertEqual(sum(column["total"] for column in body["columnas"]), 3)

    def test_un_lote_terminado_de_una_orden_anulada_tampoco(self):
        lots = self.lots_of(30, 3)
        self.finish(lots[0])
        self.api.post(reverse("produccion_orden_anular", args=[lots[0].orden_id]), {"motivo": "Cambio"}, format="json")
        self.assertEqual(self.column(self.board(), "TERMINADA")["total"], 0)


class OrderingTests(MonitorBase):
    def test_en_pausa_primero_la_que_lleva_mas_tiempo_detenida(self):
        first, second, third = self.lots_of(30, 3)
        for lot, start in ((first, 0), (second, 20), (third, 10)):
            self.act(lot, "iniciar", start)
        self.act(first, "pausar", 60)
        self.act(second, "pausar", 30)
        self.act(third, "pausar", 45)
        self.assertEqual(self.codes(self.board(), "EN_PAUSA"), [second.codigo, third.codigo, first.codigo])

    def test_en_proceso_primero_la_que_lleva_mas_tiempo_sin_movimiento(self):
        first, second, third = self.lots_of(30, 3)
        self.act(third, "iniciar", 0)
        self.act(first, "iniciar", 10)
        self.act(second, "iniciar", 5)
        self.assertEqual(self.codes(self.board(), "EN_PROCESO"), [third.codigo, second.codigo, first.codigo])

    def test_terminada_primero_la_mas_reciente(self):
        old, recent, middle = self.lots_of(30, 3)
        self.finish(old, 0)
        self.finish(recent, 500)
        self.finish(middle, 200)
        self.assertEqual(self.codes(self.board(), "TERMINADA"), [recent.codigo, middle.codigo, old.codigo])

    def test_planeada_primero_la_orden_mas_antigua(self):
        older = self.lots_of(30, 3)
        newer = self.lots_of(30, 3)
        self.assertEqual(self.codes(self.board(), "PLANEADA"), [lot.codigo for lot in older + newer])


class LimitAndFilterTests(MonitorBase):
    def test_el_limite_recorta_las_tarjetas_pero_no_los_totales(self):
        lots = self.lots_of(50, 5)
        for lot in lots[:3]:
            self.finish(lot)
        body = self.board(limite=2)
        self.assertEqual(body["limite"], 2)
        planned, done = self.column(body, "PLANEADA"), self.column(body, "TERMINADA")
        self.assertEqual((planned["total"], len(planned["lotes"])), (2, 2))
        self.assertEqual((done["total"], len(done["lotes"])), (3, 2))

    def test_limites_validos_y_no_validos(self):
        self.assertEqual(self.board(limite=1)["limite"], 1)
        self.assertEqual(self.board(limite=200)["limite"], 200)
        for bad in ("0", "201", "abc", "-1", "1.5"):
            response = self.api.get(self.monitor_url, {"limite": bad})
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("limite", response.json())

    def test_filtra_por_orden_y_los_totales_respetan_el_filtro(self):
        first = self.lots_of(30, 3)
        second = self.lots_of(30, 3)
        self.finish(second[0])
        body = self.board(orden=first[0].orden_id)
        self.assertEqual([self.column(body, s)["total"] for s in STATES], [3, 0, 0, 0])
        body = self.board(orden=second[0].orden_id)
        self.assertEqual([self.column(body, s)["total"] for s in STATES], [2, 0, 0, 1])

    def test_filtra_por_referencia(self):
        self.lots_of(30, 3)
        other = self.new(nombre="Otra referencia", variantes=[{"talla": "28", "color": "Gris"}])
        self.assertEqual(sum(c["total"] for c in self.board(referencia=other["id"])["columnas"]), 0)
        self.assertEqual(sum(c["total"] for c in self.board(referencia=self.ref["id"])["columnas"]), 3)

    def test_filtros_mal_formados_responden_400(self):
        for params in ({"orden": "x"}, {"referencia": "-3"}, {"orden": "0"}):
            self.assertEqual(self.api.get(self.monitor_url, params).status_code, 400, params)

    def test_un_filtro_sin_resultados_devuelve_columnas_vacias(self):
        self.lots_of(30, 3)
        body = self.board(orden=999999)
        self.assertEqual([c["total"] for c in body["columnas"]], [0, 0, 0, 0])


class PermissionTests(MonitorBase):
    def test_produccion_gerente_y_admin_consultan(self):
        for email, role in (("gerente@t.co", "GERENTE"), ("admin@t.co", "ADMIN")):
            self.assertEqual(client_for(make_user(email, role)).get(self.monitor_url).status_code, 200, role)
        self.assertEqual(self.api.get(self.monitor_url).status_code, 200)

    def test_el_almacenista_no_entra_ni_sin_sesion(self):
        keeper = client_for(make_user("almacen@t.co", "ALMACENISTA"))
        self.assertEqual(keeper.get(self.monitor_url).status_code, 403)
        self.assertEqual(APIClient().get(self.monitor_url).status_code, 401)

    def test_solo_se_puede_consultar(self):
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(self.api, method)(self.monitor_url, {}, format="json").status_code, 405, method)


class PerformanceTests(MonitorBase):
    def populate(self, extra):
        """Lotes en todas las columnas; `extra` multiplica la cantidad de órdenes."""
        for _ in range(extra):
            _planned, running, paused, done = self.lots_of(20, 4)
            self.act(running, "iniciar", 0)
            self.act(paused, "iniciar", 0)
            self.act(paused, "pausar", 5)
            self.finish(done)

    def test_el_numero_de_consultas_no_crece_con_los_lotes(self):
        self.populate(1)
        with CaptureQueriesContext(connection) as few:
            self.board()
        self.populate(2)  # ahora hay el triple de lotes en cada columna
        with CaptureQueriesContext(connection) as many:
            self.board()
        self.assertEqual(len(many), len(few))

    def test_los_indices_del_monitor_existen(self):
        with connection.cursor() as cursor:
            etapas = connection.introspection.get_constraints(cursor, "produccion_etapa_lote")
            eventos = connection.introspection.get_constraints(cursor, "produccion_evento_etapa")
        self.assertIn("ix_prod_etapa_lote_estado", etapas)
        self.assertIn("ix_prod_etapa_abierta", etapas)
        self.assertIn("ix_prod_evento_etapa_momento", eventos)
        self.assertEqual(etapas["ix_prod_etapa_lote_estado"]["columns"], ["lote_id", "estado"])

    def test_el_limite_maximo_esta_definido(self):
        self.assertEqual((monitor.DEFAULT_LIMIT, monitor.MAX_LIMIT), (50, 200))


class AlertTests(MonitorBase):
    def board_at(self, minutes_after_t0, **params):
        with mock.patch("apps.production.monitor.timezone.now", return_value=at(minutes_after_t0)):
            return self.board(**params)

    def card(self, body, state, code):
        return next(lot for lot in self.column(body, state)["lotes"] if lot["codigo"] == code)

    def test_los_niveles_de_alerta_en_sus_limites(self):
        two_hours, eight_hours = 2 * 3600, 8 * 3600
        self.assertIsNone(monitor.alert_level(None))
        self.assertIsNone(monitor.alert_level(0))
        self.assertIsNone(monitor.alert_level(two_hours - 1))
        self.assertEqual(monitor.alert_level(two_hours), "ATENCION")
        self.assertEqual(monitor.alert_level(eight_hours - 1), "ATENCION")
        self.assertEqual(monitor.alert_level(eight_hours), "CRITICA")
        self.assertEqual(monitor.alert_level(30 * 24 * 3600), "CRITICA")

    def test_solo_un_lote_detenido_acumula_espera(self):
        last, now = at(0), at(300)
        stalled = monitor.stalled_seconds
        self.assertEqual(stalled("EN_PAUSA", ["PAUSADA", "PENDIENTE"], last, now), 300 * 60)
        self.assertEqual(stalled("EN_PROCESO", ["COMPLETADA", "PENDIENTE"], last, now), 300 * 60)  # entre etapas
        self.assertIsNone(stalled("EN_PROCESO", ["EN_PROCESO", "PENDIENTE"], last, now))  # una etapa corre
        self.assertIsNone(stalled("PLANEADA", ["PENDIENTE"], last, now))
        self.assertIsNone(stalled("TERMINADA", ["COMPLETADA"], last, now))
        self.assertIsNone(stalled("EN_PAUSA", ["PAUSADA"], None, now))  # sin movimientos no hay desde cuándo contar

    def test_un_lote_en_pausa_pasa_de_sin_alerta_a_atencion_y_a_critica(self):
        lot = self.lots_of()[0]
        self.act(lot, "iniciar", 0)
        self.act(lot, "pausar", 10)
        before = self.card(self.board_at(10 + 119), "EN_PAUSA", lot.codigo)
        self.assertEqual((before["alerta"], before["espera_segundos"]), (None, 119 * 60))
        attention = self.card(self.board_at(10 + 121), "EN_PAUSA", lot.codigo)
        self.assertEqual((attention["alerta"], attention["espera_segundos"]), ("ATENCION", 121 * 60))
        critical = self.card(self.board_at(10 + 8 * 60), "EN_PAUSA", lot.codigo)
        self.assertEqual(critical["alerta"], "CRITICA")

    def test_un_lote_entre_dos_etapas_tambien_alerta(self):
        lot = self.lots_of()[0]
        self.act(lot, "iniciar", 0)
        self.act(lot, "completar", 5)
        card = self.card(self.board_at(5 + 3 * 60), "EN_PROCESO", lot.codigo)
        self.assertEqual((card["alerta"], card["espera_segundos"]), ("ATENCION", 180 * 60))

    def test_un_lote_con_una_etapa_corriendo_no_alerta_aunque_pase_el_tiempo(self):
        lot = self.lots_of()[0]
        self.act(lot, "iniciar", 0)
        card = self.card(self.board_at(24 * 60), "EN_PROCESO", lot.codigo)
        self.assertEqual((card["alerta"], card["espera_segundos"]), (None, None))

    def test_planeados_y_terminados_no_alertan(self):
        planned, done = self.lots_of(30, 3)[:2]
        self.finish(done)
        body = self.board_at(60)
        self.assertIsNone(self.card(body, "PLANEADA", planned.codigo)["alerta"])
        self.assertIsNone(self.card(body, "TERMINADA", done.codigo)["alerta"])

    def test_el_resumen_cuenta_todos_los_lotes_activos_no_solo_las_tarjetas_visibles(self):
        lots = self.lots_of(60, 6)
        for lot in lots[:3]:  # tres lotes en pausa desde hace 3 horas (atención)
            self.act(lot, "iniciar", 0)
            self.act(lot, "pausar", 5)
        for lot in lots[3:5]:  # dos desde hace 9 horas (crítica)
            self.act(lot, "iniciar", -400)
            self.act(lot, "pausar", -390)
        body = self.board_at(5 + 180, limite=1)
        self.assertEqual(body["alertas"], {"atencion": 3, "critica": 2})
        self.assertEqual(len(self.column(body, "EN_PAUSA")["lotes"]), 1)

    def test_sin_lotes_el_resumen_es_cero(self):
        self.assertEqual(self.board()["alertas"], {"atencion": 0, "critica": 0})


class CancelledTests(MonitorBase):
    def cancel(self, lot, reason="Cambio"):
        self.api.post(reverse("produccion_orden_anular", args=[lot.orden_id]), {"motivo": reason}, format="json")

    def test_por_defecto_no_hay_columna_de_canceladas(self):
        self.cancel(self.lots_of(30, 3)[0])
        self.assertEqual([c["estado"] for c in self.board()["columnas"]], STATES)

    def test_con_canceladas_1_aparece_una_columna_aparte_al_final(self):
        kept = self.lots_of(30, 3)
        gone = self.lots_of(30, 3)
        self.cancel(gone[0])
        body = self.board(canceladas=1)
        self.assertEqual([c["estado"] for c in body["columnas"]], STATES + ["CANCELADA"])
        cancelled = self.column(body, "CANCELADA")
        self.assertEqual((cancelled["nombre"], cancelled["total"]), ("Cancelada", 3))
        self.assertEqual(sorted(lot["codigo"] for lot in cancelled["lotes"]), sorted(lot.codigo for lot in gone))
        self.assertEqual(self.column(body, "PLANEADA")["total"], len(kept))  # las demás columnas no cambian

    def test_las_tarjetas_canceladas_no_tienen_acciones_ni_alertas(self):
        lot = self.lots_of(30, 3)[0]
        self.act(lot, "iniciar", 0)
        self.act(lot, "pausar", 5)
        self.cancel(lot)
        card = self.column(self.board(canceladas=1), "CANCELADA")["lotes"][0]
        self.assertEqual((card["estado"], card["estado_nombre"], card["acciones"]), ("CANCELADA", "Cancelada", []))
        self.assertEqual((card["alerta"], card["espera_segundos"], card["termina_el_lote"]), (None, None, False))

    def test_las_canceladas_van_de_la_mas_recientemente_anulada_a_la_mas_antigua(self):
        first, second, third = (self.lots_of(10, 1)[0] for _ in range(3))
        for lot in (second, first, third):
            self.cancel(lot)
        codes = self.codes(self.board(canceladas=1), "CANCELADA")
        self.assertEqual(codes, [third.codigo, first.codigo, second.codigo])

    def test_respetan_el_limite_y_los_filtros(self):
        lots = [self.lots_of(10, 1)[0] for _ in range(3)]
        for lot in lots:
            self.cancel(lot)
        body = self.board(canceladas=1, limite=2)
        cancelled = self.column(body, "CANCELADA")
        self.assertEqual((cancelled["total"], len(cancelled["lotes"])), (3, 2))
        only = self.column(self.board(canceladas=1, orden=lots[0].orden_id), "CANCELADA")
        self.assertEqual((only["total"], [lot["id"] for lot in only["lotes"]]), (1, [lots[0].id]))

    def test_el_parametro_acepta_1_true_0_y_false(self):
        for value, expected in (("1", True), ("true", True), ("0", False), ("false", False)):
            columns = self.board(canceladas=value)["columnas"]
            self.assertEqual(len(columns) == 5, expected, value)
        self.assertEqual(self.api.get(self.monitor_url, {"canceladas": "si"}).status_code, 400)
        self.assertEqual(self.api.get(self.monitor_url, {"canceladas": "2"}).status_code, 400)


class DoneWindowTests(MonitorBase):
    def test_por_defecto_la_columna_terminada_solo_trae_los_ultimos_siete_dias(self):
        recent, old = self.lots_of(30, 3)[:2]
        self.finish(recent)  # ayer
        self.finish(old, start=-10 * 24 * 60)  # hace unos diez días
        body = self.board()
        self.assertEqual(body["terminadas_dias"], 7)
        self.assertEqual(self.codes(body, "TERMINADA"), [recent.codigo])
        self.assertEqual(self.column(body, "TERMINADA")["total"], 1)

    def test_se_puede_ampliar_la_ventana(self):
        recent, old = self.lots_of(30, 3)[:2]
        self.finish(recent)
        self.finish(old, start=-10 * 24 * 60)
        body = self.board(terminadas_dias=30)
        self.assertEqual(body["terminadas_dias"], 30)
        self.assertEqual(self.column(body, "TERMINADA")["total"], 2)

    def test_la_ventana_no_afecta_a_los_lotes_activos(self):
        lot = self.lots_of()[0]
        self.act(lot, "iniciar", -20 * 24 * 60)
        self.assertEqual(self.codes(self.board(terminadas_dias=1), "EN_PROCESO"), [lot.codigo])

    def test_ventanas_validas_y_no_validas(self):
        self.assertEqual(self.board(terminadas_dias=1)["terminadas_dias"], 1)
        self.assertEqual(self.board(terminadas_dias=90)["terminadas_dias"], 90)
        for bad in ("0", "91", "x", "-2"):
            response = self.api.get(self.monitor_url, {"terminadas_dias": bad})
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("terminadas_dias", response.json())
