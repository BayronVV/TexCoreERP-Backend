"""HU 1.5 (TE-175): consulta de accesos y retención del registro."""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from . import trace
from .models import AccessLog, ModulePermission

User = get_user_model()
PASSWORD = "Passw0rd!23"


def make_user(email, role="VENDEDOR"):
    return User.objects.create_user(username=email, email=email, password=PASSWORD, role_id=role)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def log(email, event, ip="203.0.113.5", user=None, days_ago=0):
    row = AccessLog.objects.create(email=email, event=event, ip=ip, user=user, forwarded="cf=secreto", user_agent="UA")
    if days_ago:
        AccessLog.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    return row


class AccessListTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin@t.co", "ADMIN")
        self.ana = make_user("ana@t.co")
        log("ana@t.co", trace.LOGIN_OK, user=self.ana, days_ago=1)
        log("ana@t.co", trace.LOGIN_FAIL, ip="198.51.100.7", days_ago=2)
        log("ana@t.co", trace.LOGIN_FAIL, ip="198.51.100.7", days_ago=20)
        log("luis@t.co", trace.LOGIN_FAIL, ip="192.0.2.8", days_ago=3)
        log("ana@t.co", trace.ACCOUNT_LOCKED, user=self.ana, days_ago=2)

    def get(self, **params):
        return client_for(self.admin).get(reverse("access_list"), params)

    def test_el_administrador_ve_fecha_usuario_evento_resultado_e_ip(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 5)
        first = response.data["results"][0]
        self.assertEqual(set(first), {"id", "created_at", "user", "email", "user_name", "event", "event_label", "result", "ip"})
        self.assertEqual(first["event"], trace.LOGIN_OK)  # el más reciente primero
        self.assertEqual(first["result"], "exitoso")

    def test_fallidos_de_la_ultima_semana(self):
        since = (timezone.localtime() - timedelta(days=7)).date().isoformat()
        response = self.get(result="fallido", date_from=since)
        rows = response.data["results"]
        self.assertEqual({row["email"] for row in rows}, {"ana@t.co", "luis@t.co"})
        self.assertEqual(len(rows), 2)  # el de hace 20 días queda fuera
        self.assertTrue(all(row["ip"] and row["created_at"] for row in rows))

    def test_filtros_por_usuario_evento_ip_y_correo(self):
        self.assertEqual(self.get(user=self.ana.pk).data["count"], 2)
        self.assertEqual(self.get(event=trace.ACCOUNT_LOCKED).data["count"], 1)
        self.assertEqual(self.get(ip="192.0.2.8").data["count"], 1)
        self.assertEqual(self.get(q="LUIS").data["count"], 1)
        self.assertEqual(self.get(result="bloqueado").data["count"], 1)

    def test_rango_de_fechas_inclusivo(self):
        day = (timezone.localtime() - timedelta(days=3)).date().isoformat()
        self.assertEqual(self.get(date_from=day, date_to=day).data["count"], 1)

    def test_filtros_invalidos_responden_400(self):
        self.assertEqual(self.get(date_from="ayer").status_code, 400)
        self.assertEqual(self.get(event="inventado").status_code, 400)
        self.assertEqual(self.get(result="raro").status_code, 400)
        self.assertEqual(self.get(user="abc").status_code, 400)

    def test_paginado(self):
        for _ in range(60):
            log("bulk@t.co", trace.LOGIN_FAIL)
        response = self.get()
        self.assertEqual(len(response.data["results"]), 50)
        self.assertEqual(self.get(page_size=500).data["results"].__len__(), 65)  # tope 200

    def test_sin_permiso_recibe_403_y_sin_sesion_401(self):
        self.assertEqual(client_for(make_user("vend@t.co")).get(reverse("access_list")).status_code, 403)
        self.assertEqual(client_for(make_user("ger@t.co", "GERENTE")).get(reverse("access_list")).status_code, 403)
        self.assertEqual(APIClient().get(reverse("access_list")).status_code, 401)

    def test_es_solo_lectura(self):
        client = client_for(self.admin)
        url = reverse("access_list")
        for method in ("post", "put", "patch", "delete"):
            self.assertIn(getattr(client, method)(url, {}).status_code, (403, 405))  # sin permiso declarado: falla cerrado

    def test_no_expone_cabeceras_ni_user_agent(self):
        body = str(self.get().data)
        self.assertNotIn("secreto", body)
        self.assertNotIn("user_agent", body)

    def test_el_permiso_puede_concederse_a_otro_rol(self):
        self.assertTrue(ModulePermission.objects.filter(code="seguridad.accesos").exists())


class RetentionTests(TestCase):
    def test_purga_lo_que_supera_los_12_meses(self):
        log("viejo@t.co", trace.LOGIN_OK, days_ago=400)
        log("reciente@t.co", trace.LOGIN_OK, days_ago=100)
        out = StringIO()
        call_command("purgar_registros", stdout=out)
        self.assertEqual(list(AccessLog.objects.values_list("email", flat=True)), ["reciente@t.co"])
        self.assertIn("1 accesos", out.getvalue())

    def test_simular_no_borra(self):
        log("viejo@t.co", trace.LOGIN_OK, days_ago=400)
        call_command("purgar_registros", "--simular", stdout=StringIO())
        self.assertEqual(AccessLog.objects.count(), 1)

    def test_los_meses_son_configurables(self):
        log("a@t.co", trace.LOGIN_OK, days_ago=200)
        call_command("purgar_registros", "--meses", "6", stdout=StringIO())
        self.assertEqual(AccessLog.objects.count(), 0)
