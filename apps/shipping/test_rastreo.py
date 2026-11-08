"""Rastreo de guías con Track123 (HU 7.2). Ninguna prueba llama a la API real: el transporte HTTP es falso y el real se bloquea."""
import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.sales import catalog as sales_catalog
from apps.sales.models import MovimientoCartera, SaldoFinanciero

from . import catalog, services, track123, tracking
from .models import EventoGuia, Guia
from .test_envios import ShippingBase

KEY = "clave-de-prueba-no-real"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "track123_entregadas.json"


def result(track_no, transit="DELIVERED", sub="DELIVERED_01", detail="Tú envío fue entregado", address="CUCUTA NORT COL", delivered="2026-01-13 15:43:25"):
    """Resultado con la forma real que devuelve `track/query` (eventos en orden cronológico inverso)."""
    row = {
        "id": "1", "trackNo": track_no, "createTime": "2026-11-08 10:00:00", "trackingStatus": "001", "transitStatus": transit, "transitSubStatus": sub,
        "lastCheckedTime": "2026-11-08 10:00:00", "localLogisticsInfo": {"trackingDetails": [
            {"address": address, "eventTime": delivered or "2026-01-13 15:43:25", "eventDetail": detail, "transitSubStatus": sub},
            {"address": "BOGOTA COL", "eventTime": "2026-01-12 08:00:00", "eventDetail": "En camino hacia ti", "transitSubStatus": "IN_TRANSIT_01"},
        ]},
    }
    if delivered and transit == "DELIVERED":
        row["deliveredTime"] = delivered
    return row


class FakeTrack123:
    """Transporte falso: registra las llamadas y responde como Track123."""

    def __init__(self, quota_remaining=50, results=None, body_error=None, raise_error=None, rejected=None):
        self.calls = []
        self.quota_remaining = quota_remaining
        self.results = results or {}
        self.body_error = body_error  # (code, msg) como lo devuelve Track123 con HTTP 200
        self.raise_error = raise_error
        self.rejected = rejected or []

    def paths(self):
        return [f"{method} {path}" for method, path, _ in self.calls]

    def __call__(self, method, url, headers, body):
        assert headers["Track123-Api-Secret"] == KEY
        path = url.split("/tk/v2.1")[1]
        self.calls.append((method, path, body))
        if self.raise_error:
            raise self.raise_error
        if self.body_error:
            return 200, {"code": self.body_error[0], "msg": self.body_error[1]}
        if path == "/account/quota":
            return 200, {"code": "00000", "data": {"quotaTotal": 50, "quotaRemain": self.quota_remaining}, "msg": "Success"}
        if path == "/track/import":
            return 200, {"code": "00000", "data": {"accepted": [{"trackNo": i["trackNo"], "courierCode": i["courierCode"]} for i in body], "rejected": []}}
        if path == "/track/query":
            infos = body["trackNoInfos"]
            found = [self.results[i["trackNo"]] for i in infos if i["trackNo"] in self.results]
            rejected = self.rejected or [{"index": n, "trackNo": i["trackNo"], "error": {"code": "A0400", "msg": "trackNo not registered"}}
                                         for n, i in enumerate(infos) if i["trackNo"] not in self.results]
            return 200, {"code": "00000", "data": {"accepted": {"content": found}, "rejected": rejected}}
        raise AssertionError(f"Ruta inesperada: {path}")


class NoRealApi(SimpleTestCase):
    def test_el_rastreo_esta_apagado_cuando_se_corren_las_pruebas(self):
        self.assertFalse(settings.TRACK123_ENABLED)
        self.assertIsNone(track123.get_client())


class MapperTests(SimpleTestCase):
    def test_tabla_de_mapeo_completa(self):
        table = [
            ("DELIVERED", "DELIVERED_01", catalog.DELIVERED), ("DELIVERED", "DELIVERED_02", catalog.DELIVERED), ("DELIVERED", "DELIVERED_03", catalog.DELIVERED),
            ("DELIVERED", "DELIVERED_04", catalog.DELIVERED), ("DELIVERED", None, catalog.DELIVERED),
            ("IN_TRANSIT", "IN_TRANSIT_01", catalog.IN_TRANSIT), ("IN_TRANSIT", "IN_TRANSIT_07", catalog.IN_TRANSIT), ("INFO_RECEIVED", "INFO_RECEIVED_01", catalog.IN_TRANSIT),
            ("WAITING_DELIVERY", "WAITING_DELIVERY_01", catalog.IN_TRANSIT), ("WAITING_DELIVERY", "WAITING_DELIVERY_02", catalog.IN_TRANSIT),
            ("WAITING_DELIVERY", "WAITING_DELIVERY_03", catalog.INCIDENT),
            ("DELIVERY_FAILED", "DELIVERY_FAILED_01", catalog.INCIDENT), ("DELIVERY_FAILED", "DELIVERY_FAILED_02", catalog.INCIDENT),
            ("DELIVERY_FAILED", "DELIVERY_FAILED_03", catalog.INCIDENT), ("DELIVERY_FAILED", "DELIVERY_FAILED_04", catalog.INCIDENT),
            ("ABNORMAL", "ABNORMAL_01", catalog.INCIDENT), ("ABNORMAL", "ABNORMAL_02", catalog.INCIDENT), ("ABNORMAL", "ABNORMAL_03", catalog.INCIDENT),
            ("ABNORMAL", "ABNORMAL_04", catalog.INCIDENT), ("ABNORMAL", "ABNORMAL_08", catalog.INCIDENT), ("ABNORMAL", None, catalog.INCIDENT),
            # en Track123 no hay «devuelto»: la devolución viene dentro de ABNORMAL
            ("ABNORMAL", "ABNORMAL_05", catalog.RETURNED), ("ABNORMAL", "ABNORMAL_06", catalog.RETURNED), ("ABNORMAL", "ABNORMAL_07", catalog.RETURNED),
            ("INIT", None, None), ("NO_RECORD", None, None), ("EXPIRED", None, None), ("", "", None), (None, None, None), ("ALGO_NUEVO", None, None),
        ]
        for transit, sub, expected in table:
            self.assertEqual(tracking.map_status(transit, sub), expected, (transit, sub))

    def test_descripcion_y_fecha(self):
        self.assertEqual(tracking.describe(result("1")), "Tú envío fue entregado (CUCUTA NORT COL)")
        self.assertEqual(tracking.describe({}), "")
        self.assertEqual(tracking.parse_time("2026-01-13 15:43:25").year, 2026)
        self.assertIsNone(tracking.parse_time(""))
        self.assertIsNone(tracking.parse_time("no es una fecha"))


class ClientTests(SimpleTestCase):
    def make_client(self, **kwargs):
        return track123.Track123Client(KEY, base_url="https://x.test/tk/v2.1", transport=FakeTrack123(**kwargs))

    def test_cuota(self):
        self.assertEqual(self.make_client(quota_remaining=47).quota(), {"total": 50, "restante": 47})

    def test_clave_invalida_responde_con_http_200_y_codigo_b0001(self):
        with self.assertRaises(track123.Track123Error) as caught:
            self.make_client(body_error=("B0001", "Authorization failed or no permission")).quota()
        self.assertEqual(caught.exception.kind, "auth")
        self.assertNotIn(KEY, str(caught.exception))

    def test_limite_de_velocidad_y_error_generico(self):
        with self.assertRaises(track123.Track123Error) as rate:
            self.make_client(body_error=("A0706", "Too Many Requests")).quota()
        self.assertEqual(rate.exception.kind, "rate")
        with self.assertRaises(track123.Track123Error) as other:
            self.make_client(body_error=("D0000", "otro")).quota()
        self.assertEqual(other.exception.kind, "api")

    def test_http_401_y_429_se_clasifican(self):
        for status, kind in ((401, "auth"), (403, "auth"), (429, "rate"), (500, "api")):
            client = track123.Track123Client(KEY, base_url="https://x.test/tk/v2.1", transport=lambda *a, s=status: (s, {}))
            with self.assertRaises(track123.Track123Error) as caught:
                client.quota()
            self.assertEqual(caught.exception.kind, kind, status)

    def test_error_de_red(self):
        with self.assertRaises(track123.Track123Error) as caught:
            self.make_client(raise_error=track123.Track123Error("sin red", kind="network")).quota()
        self.assertEqual(caught.exception.kind, "network")

    def test_el_transporte_real_traduce_los_fallos_de_red(self):
        import urllib.error

        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("sin red")):
            with self.assertRaises(track123.Track123Error) as caught:
                track123.default_transport("GET", "https://x.test", {}, None)
        self.assertEqual(caught.exception.kind, "network")


@override_settings(TRACK123_ENABLED=True, TRACK123_API_KEY=KEY, TRACK123_COOLDOWN_MINUTES=10, TRACK123_QUOTA_RESERVE=10)
class RefreshTests(ShippingBase):
    def setUp(self):
        super().setUp()
        real_block = mock.patch.object(track123, "default_transport", side_effect=AssertionError("Una prueba intentó llamar a Track123 de verdad"))
        real_block.start()
        self.addCleanup(real_block.stop)
        self.fake = FakeTrack123()
        patcher = mock.patch.object(track123, "get_client", lambda transport=None: track123.Track123Client(KEY, base_url="https://x.test/tk/v2.1", transport=self.fake))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.invoice, self.guide = self.invoice_with_guide(1)

    def refresh(self, guide=None, client=None, **body):
        return (client or self.store).post(reverse("envios_guia_rastrear", args=[(guide or self.guide).id]), body, format="json")

    def deliver(self, number=None, **kwargs):
        self.fake.results[number or self.guide.numero_guia] = result(number or self.guide.numero_guia, **kwargs)

    def test_primera_consulta_registra_consulta_y_entrega_la_guia(self):
        self.deliver()
        response = self.refresh()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.fake.paths(), ["GET /account/quota", "POST /track/import", "POST /track/query"])
        self.assertEqual(self.fake.calls[1][2], [{"trackNo": self.guide.numero_guia, "courierCode": "inter-rapidisimo-inter-rapidsimo"}])
        body = response.json()
        self.assertEqual((body["estado"], body["color"], body["aviso"]), (catalog.DELIVERED, "verde", ""))
        self.assertTrue(body["rastreo"]["registrado"])
        self.assertEqual(body["rastreo"]["estado"], "DELIVERED")
        self.assertEqual(len(body["rastreo_eventos"]), 2)
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.entregada_en.year, 2026)
        trail = list(EventoGuia.objects.filter(guia=self.guide).values_list("estado_despues", "origen"))
        self.assertEqual(trail, [(catalog.PENDING, "MANUAL"), (catalog.IN_TRANSIT, "TRACK123"), (catalog.DELIVERED, "TRACK123")])
        self.assertNotIn(KEY, response.content.decode())

    def test_la_segunda_consulta_no_vuelve_a_registrar_y_respeta_el_enfriamiento(self):
        self.deliver(transit="IN_TRANSIT", sub="IN_TRANSIT_01", detail="En camino", delivered=None)
        self.assertEqual(self.refresh().status_code, 200)
        calls = len(self.fake.calls)
        again = self.refresh()
        self.assertEqual(again.status_code, 429)
        self.assertEqual(len(self.fake.calls), calls)  # el enfriamiento no gasta ni una llamada
        Guia.objects.filter(pk=self.guide.pk).update(rastreo_proxima_consulta=timezone.now() - timedelta(minutes=1))
        third = self.refresh()
        self.assertEqual(third.status_code, 200)
        self.assertEqual(self.fake.paths()[calls:], ["POST /track/query"])  # ya está registrada: solo consulta (no gasta cuota)

    def test_una_guia_en_estado_final_con_respuesta_guardada_no_se_vuelve_a_consultar_salvo_forzar(self):
        self.deliver()
        self.refresh()
        Guia.objects.filter(pk=self.guide.pk).update(rastreo_proxima_consulta=None)
        calls = len(self.fake.calls)
        self.assertEqual(self.refresh().status_code, 400)
        self.assertEqual(len(self.fake.calls), calls)
        self.assertEqual(self.refresh(forzar=True).status_code, 200)
        self.assertEqual(len(self.fake.calls), calls + 1)

    def test_reserva_de_cuota_no_registra_guias_nuevas(self):
        self.fake.quota_remaining = 10
        self.deliver()
        response = self.refresh()
        self.assertEqual(response.status_code, 400)
        self.assertIn("reserva", response.json()["rastreo"][0])
        self.assertNotIn("POST /track/import", self.fake.paths())
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.estado, catalog.PENDING)

    def test_devuelta_sintetica_por_rechazo_del_destinatario(self):
        self.dispatch([self.guide])
        self.deliver(transit="ABNORMAL", sub="ABNORMAL_05", detail="El destinatario rechazó el paquete", delivered=None)
        self.assertEqual(self.refresh().status_code, 200)
        self.guide.refresh_from_db()
        self.assertEqual((self.guide.estado, self.guide.novedad[:12]), (catalog.RETURNED, "El destinata"))
        self.assertIsNotNone(self.guide.devuelta_en)

    def test_novedad_sintetica_por_entrega_fallida(self):
        self.dispatch([self.guide])
        self.deliver(transit="DELIVERY_FAILED", sub="DELIVERY_FAILED_02", detail="Nadie en casa", delivered=None)
        self.assertEqual(self.refresh().status_code, 200)
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.estado, catalog.INCIDENT)
        self.assertIn("Nadie en casa", self.guide.novedad)

    def test_de_novedad_vuelve_a_en_transito_y_de_por_despachar_salta_a_devuelta(self):
        self.dispatch([self.guide])
        self.state(self.guide, catalog.INCIDENT, "Dirección incompleta, se llamó al cliente")
        self.deliver(transit="IN_TRANSIT", sub="IN_TRANSIT_01", detail="En camino", delivered=None)
        self.refresh()
        self.guide.refresh_from_db()
        self.assertEqual((self.guide.estado, self.guide.novedad), (catalog.IN_TRANSIT, ""))
        _, other = self.invoice_with_guide(2)
        self.fake.results[other.numero_guia] = result(other.numero_guia, "ABNORMAL", "ABNORMAL_07", "En camino de regreso al remitente", delivered=None)
        self.assertEqual(self.refresh(other).status_code, 200)
        other.refresh_from_db()
        self.assertEqual(other.estado, catalog.RETURNED)
        self.assertEqual(list(EventoGuia.objects.filter(guia=other).values_list("estado_despues", flat=True)), [catalog.PENDING, catalog.IN_TRANSIT, catalog.RETURNED])

    def test_sin_informacion_no_cambia_nada(self):
        self.deliver(transit="NO_RECORD", sub=None, detail="", delivered=None)
        self.fake.results[self.guide.numero_guia]["localLogisticsInfo"] = {}
        response = self.refresh()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sin información", response.json()["aviso"])
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.estado, catalog.PENDING)
        self.assertEqual(self.guide.rastreo_estado, "NO_RECORD")
        self.assertEqual(EventoGuia.objects.filter(guia=self.guide).count(), 1)

    def test_una_transicion_invalida_se_ignora_con_aviso(self):
        self.dispatch([self.guide])
        self.state(self.guide, catalog.DELIVERED)
        self.deliver(transit="IN_TRANSIT", sub="IN_TRANSIT_01", detail="En camino", delivered=None)
        response = self.refresh(forzar=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no se aplica", response.json()["aviso"])
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.estado, catalog.DELIVERED)

    def test_clave_invalida_responde_503_sin_cambiar_la_guia_ni_filtrar_la_clave(self):
        self.fake.body_error = ("B0001", "Authorization failed or no permission")
        response = self.refresh()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(KEY, response.content.decode())
        self.guide.refresh_from_db()
        self.assertEqual((self.guide.estado, self.guide.rastreo_consultado_en, self.guide.rastreo_proxima_consulta), (catalog.PENDING, None, None))

    def test_error_de_red_y_limite_de_velocidad_no_cambian_la_guia(self):
        self.fake.raise_error = track123.Track123Error("No se pudo comunicar con el servicio de rastreo.", kind="network")
        self.assertEqual(self.refresh().status_code, 503)
        self.fake.raise_error = None
        self.fake.body_error = ("A0706", "Too Many Requests")
        self.assertEqual(self.refresh().status_code, 503)
        self.guide.refresh_from_db()
        self.assertEqual(self.guide.estado, catalog.PENDING)

    def test_una_venta_nunca_depende_del_rastreo(self):
        self.fake.raise_error = track123.Track123Error("caído", kind="network")
        self.assertEqual(self.sale(carrier="INTERRAPIDISIMO", number=self.number(50)).status_code, 201)
        self.assertEqual(self.dispatch([self.guide]).status_code, 201)

    def test_guia_que_track123_dice_no_registrada_vuelve_a_pendiente_de_registro(self):
        Guia.objects.filter(pk=self.guide.pk).update(rastreo_registrado=True)
        response = self.refresh()  # sin resultados: Track123 la rechaza como no registrada
        self.assertEqual(response.status_code, 200)
        self.guide.refresh_from_db()
        self.assertFalse(self.guide.rastreo_registrado)

    def test_envia_y_otra_no_se_rastrean_ni_gastan_llamadas(self):
        _, envia = self.invoice_with_guide(3, "ENVIA")
        response = self.refresh(envia)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.fake.calls, [])

    def test_una_guia_anulada_no_se_rastrea(self):
        self.state(self.guide, catalog.VOIDED)
        self.assertEqual(self.refresh().status_code, 400)
        self.assertEqual(self.fake.calls, [])

    def test_permiso_y_estado_de_la_cuota(self):
        self.assertEqual(self.refresh(client=self.seller).status_code, 403)
        body = self.store.get(reverse("envios_rastreo_estado")).json()
        self.assertEqual((body["habilitado"], body["total"], body["restante"], body["reserva"]), (True, 50, 50, 10))
        self.fake.quota_remaining = 8
        self.assertIn("reserva", self.store.get(reverse("envios_rastreo_estado")).json()["mensaje"])
        self.fake.body_error = ("B0001", "x")
        self.assertIn("clave", self.store.get(reverse("envios_rastreo_estado")).json()["mensaje"])

    def test_con_las_respuestas_reales_de_las_tres_guias(self):
        real = json.loads(FIXTURE.read_text(encoding="utf-8"))["guias"]
        self.assertEqual(len(real), 3)
        for index, item in enumerate(real):
            guide = self.invoice_with_guide(10 + index)[1]
            Guia.objects.filter(pk=guide.pk).update(numero_guia=item["trackNo"])
            self.fake.results[item["trackNo"]] = item
            response = self.refresh(guide)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["estado"], catalog.DELIVERED, item["trackNo"])
            self.assertEqual(len(response.json()["rastreo_eventos"]), 6)

    def test_el_rastreo_apagado_responde_503(self):
        with override_settings(TRACK123_ENABLED=False):
            with mock.patch.object(track123, "get_client", return_value=None):
                response = self.refresh()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.fake.calls, [])


@override_settings(DEBUG=True)
class SeedTests(ShippingBase):
    def test_la_siembra_deja_el_semaforo_y_las_tres_guias_reales_sin_llamar_a_la_api(self):
        with mock.patch.object(track123, "default_transport", side_effect=AssertionError("La siembra llamó a Track123")):
            for _ in range(2):  # idempotente
                call_command("seed_demo_envios", stdout=StringIO())
        real = {g.numero_guia: g for g in Guia.objects.filter(transportadora="INTERRAPIDISIMO", vigente=True)}
        self.assertEqual(set(real), {"700187211301", "700180879081", "700200165317"})
        for guide in real.values():
            self.assertEqual(guide.estado, catalog.DELIVERED)
            self.assertFalse(guide.rastreo_sintetico)
            self.assertEqual(guide.rastreo_estado, "DELIVERED")
        states = sorted(Guia.objects.filter(vigente=True, rastreo_sintetico=True).values_list("estado", flat=True))
        self.assertEqual(states, sorted([catalog.PENDING, catalog.IN_TRANSIT, catalog.IN_TRANSIT, catalog.INCIDENT, catalog.RETURNED, catalog.DELIVERED, catalog.RETURNED]))
        self.assertEqual(Guia.objects.filter(vigente=True).count(), 10)
        self.assertEqual(services.invoices_without_guide().count(), 1)
        self.assertEqual(Guia.objects.get(numero_guia="OTR-DEMO-0005").flete_vendedor, 12_000)
        # historial de cartera: una factura cobrada (saldo y movimiento) y una devolución registrada (stock de vuelta)
        self.assertEqual(MovimientoCartera.objects.filter(tipo=sales_catalog.FINANCIAL_LEDGER_RECAUDO).count(), 1)
        self.assertEqual(MovimientoCartera.objects.filter(tipo=sales_catalog.FINANCIAL_LEDGER_DEVOLUCION).count(), 1)
        self.assertGreater(SaldoFinanciero.objects.first().saldo_actual, 0)

    def test_la_siembra_exige_debug(self):
        from django.core.management.base import CommandError

        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command("seed_demo_envios", stdout=StringIO())
