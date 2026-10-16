"""Control de tiempos por etapa (HU 4.3 / RF13 y RF15): estados derivados, tiempo neto sin pausas, acciones y permisos."""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from apps.inventory.tests import client_for, make_user

from . import catalog, tracking
from .models import EtapaLote, EventoEtapa, Lote, OrdenProduccion
from .test_ordenes import OrderBase

T0 = datetime(2026, 10, 16, 8, 0, 0, tzinfo=dt_timezone.utc)


def at(minutes=0, seconds=0):
    return T0 + timedelta(minutes=minutes, seconds=seconds)


def stage(state=catalog.STAGE_PENDING, accumulated=0, resumed=None):
    return SimpleNamespace(estado=state, acumulado_s=accumulated, reanudada_at=resumed)


P, R, S, D = catalog.STAGE_PENDING, catalog.STAGE_RUNNING, catalog.STAGE_PAUSED, catalog.STAGE_DONE


class NetSecondsTests(SimpleTestCase):
    def test_etapa_sin_empezar_no_tiene_tiempo(self):
        self.assertEqual(tracking.net_seconds(stage()), 0)

    def test_suma_los_intervalos_cerrados(self):
        self.assertEqual(tracking.net_seconds(stage(S, accumulated=300)), 300)

    def test_suma_el_intervalo_que_corre_hasta_ahora(self):
        self.assertEqual(tracking.net_seconds(stage(R, accumulated=300, resumed=at(0)), now=at(2)), 420)

    def test_un_reloj_atrasado_no_da_tiempo_negativo(self):
        self.assertEqual(tracking.net_seconds(stage(R, resumed=at(5)), now=at(1)), 0)


class DerivedStateTests(SimpleTestCase):
    def test_lote_planeado_si_ninguna_etapa_empezo(self):
        self.assertEqual(tracking.lot_state([P, P, P]), catalog.STATE_PLANNED)
        self.assertEqual(tracking.lot_state([]), catalog.STATE_PLANNED)

    def test_lote_en_proceso_si_alguna_corre(self):
        self.assertEqual(tracking.lot_state([D, R, P]), catalog.STATE_RUNNING)

    def test_lote_en_proceso_entre_dos_etapas(self):
        self.assertEqual(tracking.lot_state([D, P, P]), catalog.STATE_RUNNING)

    def test_lote_en_pausa_si_la_etapa_en_curso_esta_pausada(self):
        self.assertEqual(tracking.lot_state([D, S, P]), catalog.STATE_PAUSED)

    def test_lote_terminado_solo_si_todas_terminaron(self):
        self.assertEqual(tracking.lot_state([D, D, D]), catalog.STATE_DONE)
        self.assertNotEqual(tracking.lot_state([D, D, P]), catalog.STATE_DONE)

    def test_lote_cancelado_manda_sobre_todo(self):
        self.assertEqual(tracking.lot_state([D, R], cancelled=True), catalog.STATE_CANCELLED)

    def test_orden_planeada_en_proceso_pausa_y_terminada(self):
        planned, running, paused, done = catalog.STATE_PLANNED, catalog.STATE_RUNNING, catalog.STATE_PAUSED, catalog.STATE_DONE
        self.assertEqual(tracking.order_state([planned, planned]), planned)
        self.assertEqual(tracking.order_state([running, planned]), running)
        self.assertEqual(tracking.order_state([paused, planned]), paused)
        self.assertEqual(tracking.order_state([done, done]), done)

    def test_orden_en_proceso_si_unos_lotes_terminaron_y_otros_no_empiezan(self):
        self.assertEqual(tracking.order_state([catalog.STATE_DONE, catalog.STATE_PLANNED]), catalog.STATE_RUNNING)

    def test_orden_con_un_lote_corriendo_y_otro_pausado_esta_en_proceso(self):
        self.assertEqual(tracking.order_state([catalog.STATE_RUNNING, catalog.STATE_PAUSED]), catalog.STATE_RUNNING)

    def test_los_lotes_cancelados_no_cuentan(self):
        cancelled = catalog.STATE_CANCELLED
        self.assertEqual(tracking.order_state([cancelled, catalog.STATE_DONE]), catalog.STATE_DONE)
        self.assertEqual(tracking.order_state([cancelled, cancelled]), cancelled)

    def test_orden_sin_lotes_esta_planeada(self):
        self.assertEqual(tracking.order_state([]), catalog.STATE_PLANNED)


class AvailableActionsTests(SimpleTestCase):
    def test_lote_sin_empezar_solo_puede_iniciar(self):
        self.assertEqual(tracking.available_actions([P, P]), [catalog.ACTION_START])

    def test_con_una_etapa_corriendo_se_pausa_o_se_completa(self):
        self.assertEqual(tracking.available_actions([D, R, P]), [catalog.ACTION_PAUSE, catalog.ACTION_COMPLETE])

    def test_con_una_etapa_pausada_se_reanuda_o_se_completa(self):
        self.assertEqual(tracking.available_actions([D, S, P]), [catalog.ACTION_RESUME, catalog.ACTION_COMPLETE])

    def test_entre_dos_etapas_se_puede_iniciar_la_siguiente(self):
        self.assertEqual(tracking.available_actions([D, P, P]), [catalog.ACTION_START])

    def test_lote_terminado_o_cancelado_no_admite_acciones(self):
        self.assertEqual(tracking.available_actions([D, D]), [])
        self.assertEqual(tracking.available_actions([P, P], cancelled=True), [])

    def test_etapa_en_curso_o_la_siguiente_pendiente(self):
        stages = [stage(D), stage(S), stage(P)]
        self.assertIs(tracking.current_stage(stages), stages[1])
        stages = [stage(D), stage(P), stage(P)]
        self.assertIs(tracking.current_stage(stages), stages[1])
        self.assertIsNone(tracking.current_stage([stage(D), stage(D)]))


class TrackingBase(OrderBase):
    def setUp(self):
        super().setUp()
        body = self.placed(100, [{"cantidad": 60}, {"cantidad": 40}])
        self.order = OrdenProduccion.objects.get(pk=body["id"])
        self.lot1, self.lot2 = self.order.lotes.all()

    def act(self, action, lot=None, at_=None, user=None, note=""):
        return tracking.act_on_lot(user=user or self.boss, lot_id=(lot or self.lot1).id, action=action, now=at_, note=note)

    def stage(self, name, lot=None):
        return EtapaLote.objects.get(lote=lot or self.lot1, etapa=name)

    def rejected(self, action, lot=None, at_=None):
        with self.assertRaises(ValidationError) as caught:
            self.act(action, lot, at_)
        return str(caught.exception.detail["accion"][0])

    def action_url(self, lot, action):
        return reverse("produccion_lote_accion", args=[lot.id, action])

    def post(self, lot, action, client=None, **body):
        return (client or self.api).post(self.action_url(lot, action), body, format="json")


class StagesCreationTests(TrackingBase):
    def test_cada_lote_nace_con_las_tres_etapas_pendientes_en_orden(self):
        for lot in (self.lot1, self.lot2):
            rows = list(lot.etapas.all())
            self.assertEqual([row.etapa for row in rows], catalog.STAGE_ORDER)
            self.assertEqual([row.secuencia for row in rows], [1, 2, 3])
            self.assertTrue(all(row.estado == catalog.STAGE_PENDING for row in rows))

    def test_una_orden_nueva_esta_planeada(self):
        body = self.api.get(reverse("produccion_orden", args=[self.order.id])).json()
        self.assertEqual((body["estado_produccion"], body["estado_produccion_nombre"]), ("PLANEADA", "Planeada"))
        self.assertEqual(body["tiempo_neto_segundos"], 0)

    def test_etapa_duplicada_en_un_lote_no_se_acepta(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            EtapaLote.objects.create(lote=self.lot1, etapa="CORTE", secuencia=9)


class ActionTests(TrackingBase):
    def test_iniciar_arranca_el_corte_y_registra_quien_y_cuando(self):
        self.act("iniciar", at_=at(0))
        cutting = self.stage("CORTE")
        self.assertEqual((cutting.estado, cutting.inicio_at, cutting.reanudada_at), (R, at(0), at(0)))
        self.assertEqual(cutting.responsable, self.boss)

    def test_pausa_y_reanudacion_no_cuentan_como_tiempo(self):
        self.act("iniciar", at_=at(0))
        self.act("pausar", at_=at(10))  # corrió 10 min
        self.assertEqual(self.stage("CORTE").acumulado_s, 600)
        self.act("reanudar", at_=at(40))  # 30 min de pausa que no cuentan
        self.act("completar", at_=at(45))  # 5 min más
        cutting = self.stage("CORTE")
        self.assertEqual((cutting.estado, cutting.acumulado_s, cutting.fin_at), (D, 900, at(45)))
        self.assertIsNone(cutting.reanudada_at)

    def test_varias_pausas_suman_todos_los_intervalos(self):
        self.act("iniciar", at_=at(0))
        for pause, resume in ((5, 6), (11, 20), (23, 30)):
            self.act("pausar", at_=at(pause))
            self.act("reanudar", at_=at(resume))
        self.act("completar", at_=at(34))
        self.assertEqual(self.stage("CORTE").acumulado_s, (5 + 5 + 3 + 4) * 60)

    def test_completar_una_etapa_pausada_no_suma_tiempo_extra(self):
        self.act("iniciar", at_=at(0))
        self.act("pausar", at_=at(8))
        self.act("completar", at_=at(50))
        self.assertEqual(self.stage("CORTE").acumulado_s, 480)

    def test_las_etapas_siguen_el_orden_del_flujo(self):
        for index, name in enumerate(catalog.STAGE_ORDER):
            self.act("iniciar", at_=at(index * 10))
            self.assertEqual(self.stage(name).estado, R)
            self.act("completar", at_=at(index * 10 + 5))
        self.assertTrue(all(row.estado == D for row in self.lot1.etapas.all()))

    def test_no_se_inicia_otra_etapa_con_una_corriendo_ni_pausada(self):
        self.act("iniciar", at_=at(0))
        self.assertIn("Ya hay una etapa en proceso", self.rejected("iniciar"))
        self.act("pausar", at_=at(1))
        self.assertIn("Hay una etapa en pausa", self.rejected("iniciar"))

    def test_acciones_que_no_corresponden_se_rechazan_con_su_motivo(self):
        self.assertIn("No hay una etapa en proceso para pausar", self.rejected("pausar"))
        self.assertIn("No hay una etapa en pausa para reanudar", self.rejected("reanudar"))
        self.assertIn("No hay una etapa en curso para terminar", self.rejected("completar"))
        self.act("iniciar", at_=at(0))
        self.assertIn("La etapa ya está en proceso", self.rejected("reanudar"))
        self.act("pausar", at_=at(1))
        self.assertIn("La etapa ya está en pausa", self.rejected("pausar"))

    def test_un_lote_terminado_no_admite_mas_acciones(self):
        for index in range(len(catalog.STAGE_ORDER)):
            self.act("iniciar", at_=at(index * 2))
            self.act("completar", at_=at(index * 2 + 1))
        for action in catalog.ACTIONS:
            self.assertIn("ya terminaron", self.rejected(action))

    def test_una_accion_desconocida_se_rechaza(self):
        with self.assertRaises(ValidationError):
            tracking.act_on_lot(user=self.boss, lot_id=self.lot1.id, action="borrar")

    def test_un_lote_que_no_existe(self):
        with self.assertRaises(ValidationError):
            tracking.act_on_lot(user=self.boss, lot_id=999999, action="iniciar")

    def test_los_lotes_de_una_orden_corren_por_separado(self):
        self.act("iniciar", self.lot1, at(0))
        self.act("iniciar", self.lot2, at(1))
        self.assertEqual(self.stage("CORTE", self.lot1).estado, R)
        self.assertEqual(self.stage("CORTE", self.lot2).estado, R)
        self.act("completar", self.lot1, at(5))
        self.assertEqual(self.stage("CORTE", self.lot2).estado, R)

    def test_una_orden_anulada_no_admite_acciones(self):
        self.act("iniciar", at_=at(0))
        self.api.post(reverse("produccion_orden_anular", args=[self.order.id]), {"motivo": "Cambio"}, format="json")
        with self.assertRaises(ValidationError) as caught:
            self.act("pausar", at_=at(1))
        self.assertIn("anulada", str(caught.exception.detail["orden"][0]))

    def test_un_lote_sin_etapas_las_recibe_al_primer_movimiento(self):
        EtapaLote.all_objects.filter(lote=self.lot1).hard_delete()
        self.act("iniciar", at_=at(0))
        self.assertEqual(self.lot1.etapas.count(), len(catalog.STAGE_ORDER))
        self.assertEqual(self.stage("CORTE").estado, R)


class HistoryTests(TrackingBase):
    def test_cada_accion_deja_un_evento_con_su_estado_y_usuario(self):
        self.act("iniciar", at_=at(0), note="  Arranca el turno  ")
        self.act("pausar", at_=at(3))
        events = list(EventoEtapa.objects.all())
        self.assertEqual([(e.accion, e.de_estado, e.a_estado) for e in events],
                         [("iniciar", P, R), ("pausar", R, S)])
        self.assertEqual((events[0].usuario, events[0].momento, events[0].nota), (self.boss, at(0), "Arranca el turno"))

    def test_una_accion_rechazada_no_deja_historial_ni_cambia_la_etapa(self):
        self.rejected("pausar")
        self.assertEqual(EventoEtapa.objects.count(), 0)
        self.assertEqual(self.stage("CORTE").estado, P)

    def test_el_tiempo_guardado_coincide_con_el_de_los_eventos(self):
        self.act("iniciar", at_=at(0))
        self.act("pausar", at_=at(4))
        self.act("reanudar", at_=at(10))
        self.act("completar", at_=at(17))
        total, started = 0, None
        for event in EventoEtapa.objects.order_by("momento", "id"):
            if event.accion in ("iniciar", "reanudar"):
                started = event.momento
            else:
                total += int((event.momento - started).total_seconds())
        self.assertEqual(total, self.stage("CORTE").acumulado_s)


class ApiTests(TrackingBase):
    def test_play_pausa_y_stop_devuelven_el_lote_actualizado(self):
        body = self.post(self.lot1, "iniciar")
        self.assertEqual(body.status_code, 200, body.content)
        lot = body.json()
        self.assertEqual((lot["estado"], lot["etapa_actual"], lot["acciones"]), ("EN_PROCESO", "CORTE", ["pausar", "completar"]))
        self.assertEqual(lot["etapas"][0]["estado"], "EN_PROCESO")
        self.assertIsNotNone(lot["etapas"][0]["en_curso_desde"])
        paused = self.post(self.lot1, "pausar").json()
        self.assertEqual((paused["estado"], paused["acciones"]), ("EN_PAUSA", ["reanudar", "completar"]))
        self.assertIsNone(paused["etapas"][0]["en_curso_desde"])
        done = self.post(self.lot1, "completar").json()
        self.assertEqual((done["estado"], done["etapa_actual"], done["acciones"]), ("EN_PROCESO", "CONFECCION", ["iniciar"]))

    def test_el_tiempo_neto_se_calcula_con_la_hora_del_servidor(self):
        with mock.patch("apps.production.tracking.timezone.now", return_value=at(0)):
            self.post(self.lot1, "iniciar")
        with mock.patch("apps.production.tracking.timezone.now", return_value=at(7)):
            lot = self.post(self.lot1, "pausar").json()
        self.assertEqual(lot["etapas"][0]["tiempo_neto_segundos"], 420)
        self.assertEqual(lot["tiempo_neto_segundos"], 420)

    def test_un_error_responde_400_con_el_motivo(self):
        response = self.post(self.lot1, "pausar")
        self.assertEqual(response.status_code, 400)
        self.assertIn("No hay una etapa en proceso", response.json()["accion"][0])
        self.assertEqual(self.post(self.lot1, "volar").status_code, 400)

    def test_la_nota_es_opcional(self):
        self.assertEqual(self.post(self.lot1, "iniciar", nota="Turno de la mañana").status_code, 200)
        self.assertEqual(EventoEtapa.objects.get().nota, "Turno de la mañana")

    def test_lote_inexistente(self):
        response = self.api.post(reverse("produccion_lote_accion", args=[999999, "iniciar"]), {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_la_orden_refleja_el_estado_y_el_tiempo_de_sus_lotes(self):
        url = reverse("produccion_orden", args=[self.order.id])
        self.post(self.lot1, "iniciar")
        self.assertEqual(self.api.get(url).json()["estado_produccion"], "EN_PROCESO")
        self.post(self.lot1, "pausar")
        self.post(self.lot2, "iniciar")
        self.post(self.lot2, "pausar")
        self.assertEqual(self.api.get(url).json()["estado_produccion"], "EN_PAUSA")
        listed = self.api.get(reverse("produccion_ordenes")).json()[0]
        self.assertEqual(listed["estado_produccion_nombre"], "En pausa")
        self.assertEqual([lot["estado"] for lot in listed["lotes"]], ["EN_PAUSA", "EN_PAUSA"])

    def test_orden_terminada_cuando_todos_los_lotes_terminan(self):
        for lot in (self.lot1, self.lot2):
            for _ in catalog.STAGE_ORDER:
                self.post(lot, "iniciar")
                self.post(lot, "completar")
        self.assertEqual(self.api.get(reverse("produccion_orden", args=[self.order.id])).json()["estado_produccion"], "TERMINADA")

    def test_la_orden_anulada_queda_cancelada_con_sus_lotes(self):
        self.api.post(reverse("produccion_orden_anular", args=[self.order.id]), {"motivo": "Cambio"}, format="json")
        body = self.api.get(reverse("produccion_orden", args=[self.order.id])).json()
        self.assertEqual(body["estado_produccion"], "CANCELADA")
        self.assertEqual({lot["estado"] for lot in body["lotes"]}, {"CANCELADA"})
        self.assertEqual({tuple(lot["acciones"]) for lot in body["lotes"]}, {()})
        self.assertEqual(self.post(self.lot1, "iniciar").status_code, 400)

    def test_historial_del_lote(self):
        self.post(self.lot1, "iniciar", nota="Arranque")
        self.post(self.lot1, "pausar")
        history = self.api.get(reverse("produccion_lote_historial", args=[self.lot1.id])).json()
        self.assertEqual([(e["accion"], e["etapa"], e["usuario_nombre"]) for e in history],
                         [("iniciar", "CORTE", "produccion@t.co"), ("pausar", "CORTE", "produccion@t.co")])
        self.assertEqual(history[0]["accion_nombre"], "Inicio")
        self.assertEqual(self.api.get(reverse("produccion_lote_historial", args=[self.lot2.id])).json(), [])

    def test_el_listado_no_hace_consultas_por_lote(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as few:
            self.api.get(reverse("produccion_ordenes"))
        for _ in range(3):
            self.placed(10, [{"cantidad": 4}, {"cantidad": 3}, {"cantidad": 3}])
        with CaptureQueriesContext(connection) as many:
            self.api.get(reverse("produccion_ordenes"))
        self.assertEqual(len(few), len(many))


class PermissionTests(TrackingBase):
    def test_produccion_y_admin_controlan_los_tiempos(self):
        self.assertEqual(self.post(self.lot1, "iniciar").status_code, 200)
        admin = client_for(make_user("admin@t.co", "ADMIN"))
        self.assertEqual(self.post(self.lot2, "iniciar", client=admin).status_code, 200)

    def test_el_gerente_consulta_pero_no_controla(self):
        manager = client_for(make_user("gerente@t.co", "GERENTE"))
        self.assertEqual(self.post(self.lot1, "iniciar", client=manager).status_code, 403)
        self.assertEqual(manager.get(reverse("produccion_lote_historial", args=[self.lot1.id])).status_code, 200)
        self.assertEqual(manager.get(reverse("produccion_orden", args=[self.order.id])).status_code, 200)

    def test_el_almacenista_no_entra(self):
        keeper = client_for(make_user("almacen@t.co", "ALMACENISTA"))
        self.assertEqual(self.post(self.lot1, "iniciar", client=keeper).status_code, 403)
        self.assertEqual(keeper.get(reverse("produccion_lote_historial", args=[self.lot1.id])).status_code, 403)

    def test_sin_sesion(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().post(self.action_url(self.lot1, "iniciar"), {}, format="json").status_code, 401)
        self.assertEqual(APIClient().get(reverse("produccion_lote_historial", args=[self.lot1.id])).status_code, 401)

    def test_una_accion_denegada_no_cambia_nada(self):
        manager = client_for(make_user("gerente@t.co", "GERENTE"))
        self.post(self.lot1, "iniciar", client=manager)
        self.assertEqual((EventoEtapa.objects.count(), self.stage("CORTE").estado), (0, P))


class MigrationBackfillTests(TrackingBase):
    def test_el_relleno_crea_las_etapas_de_los_lotes_existentes(self):
        import importlib

        from django.apps import apps as django_apps
        migration = importlib.import_module("apps.production.migrations.0002_control_de_tiempos")
        EtapaLote.all_objects.all().hard_delete()
        migration.create_stages_for_existing_lots(django_apps, None)
        self.assertEqual(EtapaLote.objects.count(), Lote.objects.count() * len(catalog.STAGE_ORDER))
        self.assertEqual({row.estado for row in EtapaLote.objects.all()}, {catalog.STAGE_PENDING})
