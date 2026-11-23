"""HU 1.5 (TE-175): bloqueo temporal de la cuenta por intentos fallidos."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from . import lockout, password_reset, trace
from .models import AccessLog

User = get_user_model()
PASSWORD = "Passw0rd!23"


def make_user(email, role="PENDING", **extra):
    return User.objects.create_user(username=email, email=email, password=PASSWORD, role_id=role, **extra)


def login(email, password):
    return APIClient().post(reverse("token_obtain_pair"), {"username": email, "password": password})


class LockoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin@t.co", "ADMIN")
        self.user = make_user("ana@t.co", "VENDEDOR", first_name="Ana")

    def fail(self, times, email="ana@t.co"):
        return [login(email, "mala-clave") for _ in range(times)]

    def test_tercer_intento_fallido_bloquea_y_ni_la_clave_correcta_entra(self):
        first, second, third = self.fail(3)
        for response in (first, second, third):
            self.assertEqual(response.status_code, 401)
            self.assertNotEqual(response.data.get("code"), lockout.LOCKED_CODE)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked)
        blocked = login("ana@t.co", PASSWORD)
        self.assertEqual(blocked.status_code, 401)
        self.assertEqual(blocked.data["code"], lockout.LOCKED_CODE)
        self.assertIn("bloqueada temporalmente", blocked.data["detail"])

    def test_dos_fallos_no_bloquean(self):
        self.fail(2)
        self.assertEqual(login("ana@t.co", PASSWORD).status_code, 200)

    def test_un_acceso_correcto_reinicia_el_contador(self):
        self.fail(2)
        self.assertEqual(login("ana@t.co", PASSWORD).status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 0)
        self.fail(2)  # dos fallos más no bloquean: el contador empezó de cero
        self.assertEqual(login("ana@t.co", PASSWORD).status_code, 200)

    def test_el_bloqueo_vence_con_el_tiempo(self):
        self.fail(3)
        User.objects.filter(pk=self.user.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
        response = login("ana@t.co", PASSWORD)
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)
        self.assertEqual(self.user.failed_login_count, 0)

    def test_el_bloqueo_dura_el_tiempo_configurado(self):
        self.fail(3)
        self.user.refresh_from_db()
        remaining = self.user.locked_until - timezone.now()
        self.assertGreater(remaining, timedelta(minutes=14))
        self.assertLessEqual(remaining, timedelta(minutes=15))

    def test_intentos_con_la_cuenta_bloqueada_no_alargan_el_bloqueo(self):
        self.fail(3)
        self.user.refresh_from_db()
        until = self.user.locked_until
        self.fail(5)
        self.user.refresh_from_db()
        self.assertEqual(self.user.locked_until, until)
        self.assertEqual(self.user.failed_login_count, 0)

    def test_correo_inexistente_responde_igual_que_clave_incorrecta(self):
        real = login("ana@t.co", "mala-clave")
        ghost = login("nadie@t.co", "mala-clave")
        self.assertEqual(real.status_code, ghost.status_code)
        self.assertEqual(real.data, ghost.data)
        # y por mucho que se intente, un correo inexistente no queda «bloqueado»
        for _ in range(5):
            ghost = login("nadie@t.co", "mala-clave")
        self.assertNotEqual(ghost.data.get("code"), lockout.LOCKED_CODE)

    def test_las_mayusculas_del_correo_no_evaden_el_conteo(self):
        for email in ("ANA@t.co", "Ana@T.co", "ana@t.co"):
            login(email, "mala-clave")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked)

    def test_el_bloqueo_se_cuenta_por_cuenta_no_por_ip(self):
        for i in range(3):
            APIClient().post(
                reverse("token_obtain_pair"), {"username": "ana@t.co", "password": "mala"}, REMOTE_ADDR=f"10.1.0.{i}"
            )
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked)

    def test_el_bloqueo_de_una_cuenta_no_afecta_a_otra(self):
        make_user("luis@t.co", "VENDEDOR")
        self.fail(3)
        self.assertEqual(login("luis@t.co", PASSWORD).status_code, 200)

    def test_cuenta_bloqueada_no_puede_renovar_la_sesion(self):
        tokens = login("ana@t.co", PASSWORD).data
        User.objects.filter(pk=self.user.pk).update(locked_until=timezone.now() + timedelta(minutes=5))
        response = APIClient().post(reverse("token_refresh"), {"refresh": tokens["refresh"]})
        self.assertEqual(response.status_code, 401)

    def test_aviso_por_correo_una_sola_vez_al_bloquear(self):
        self.fail(3)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ana@t.co"])
        self.assertNotIn(PASSWORD, mail.outbox[0].body)
        self.fail(3)  # ya bloqueada: no reenvía
        self.assertEqual(len(mail.outbox), 1)

    def test_si_el_correo_falla_el_login_sigue_respondiendo(self):
        with override_settings(EMAIL_BACKEND="apps.users.test_bloqueo.BrokenBackend"):
            responses = self.fail(3)
        self.assertEqual([r.status_code for r in responses], [401, 401, 401])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked)

    def test_eventos_de_acceso_registrados(self):
        self.fail(3)
        login("ana@t.co", PASSWORD)
        events = list(AccessLog.objects.filter(email="ana@t.co").order_by("id").values_list("event", flat=True))
        self.assertEqual(
            events,
            [trace.LOGIN_FAIL] * 3 + [trace.ACCOUNT_LOCKED] + [trace.BLOCKED_ATTEMPT],
        )

    @override_settings(LOGIN_MAX_ATTEMPTS=5)
    def test_el_umbral_es_configurable(self):
        self.fail(4)
        self.assertEqual(login("ana@t.co", PASSWORD).status_code, 200)


class LastAdminTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_el_unico_administrador_no_se_bloquea(self):
        make_user("admin@t.co", "ADMIN")
        for _ in range(6):
            login("admin@t.co", "mala-clave")
        self.assertEqual(login("admin@t.co", PASSWORD).status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_con_otro_administrador_activo_si_se_bloquea(self):
        make_user("a1@t.co", "ADMIN")
        make_user("a2@t.co", "ADMIN")
        for _ in range(3):
            login("a1@t.co", "mala-clave")
        self.assertEqual(login("a1@t.co", PASSWORD).data["code"], lockout.LOCKED_CODE)

    def test_el_otro_administrador_bloqueado_no_cuenta_como_disponible(self):
        a1 = make_user("a1@t.co", "ADMIN")
        make_user("a2@t.co", "ADMIN")
        for _ in range(3):
            login("a1@t.co", "mala-clave")  # a1 bloqueado: a2 queda como el último que puede entrar
        a1.refresh_from_db()
        self.assertTrue(a1.is_locked)
        for _ in range(6):
            login("a2@t.co", "mala-clave")
        self.assertEqual(login("a2@t.co", PASSWORD).status_code, 200)

    def test_un_administrador_invitado_sin_contrasena_no_cuenta(self):
        make_user("a1@t.co", "ADMIN")
        ghost = make_user("a2@t.co", "ADMIN")
        ghost.set_unusable_password()
        ghost.save()
        for _ in range(6):
            login("a1@t.co", "mala-clave")
        self.assertEqual(login("a1@t.co", PASSWORD).status_code, 200)


class UnlockTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin@t.co", "ADMIN")
        make_user("otro@t.co", "ADMIN")
        self.user = make_user("ana@t.co", "VENDEDOR")
        for _ in range(3):
            login("ana@t.co", "mala-clave")

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_el_administrador_desbloquea_y_la_persona_entra(self):
        response = self.as_user(self.admin).post(reverse("user_unlock", args=[self.user.pk]))
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_locked)
        self.assertEqual(self.user.failed_login_count, 0)
        self.assertEqual(login("ana@t.co", PASSWORD).status_code, 200)
        self.assertTrue(AccessLog.objects.filter(event=trace.UNLOCK, user=self.user).exists())

    def test_sin_permiso_no_puede_desbloquear(self):
        seller = make_user("vend@t.co", "VENDEDOR")
        response = self.as_user(seller).post(reverse("user_unlock", args=[self.user.pk]))
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked)

    def test_un_bloqueado_no_puede_desbloquearse_a_si_mismo(self):
        response = APIClient().post(reverse("user_unlock", args=[self.user.pk]))
        self.assertEqual(response.status_code, 401)

    def test_restablecer_la_contrasena_levanta_el_bloqueo(self):
        raw = password_reset.issue_token(self.user)
        response = APIClient().post(
            reverse("password_reset_confirm"),
            {"token": raw, "password": "Nueva-Clave#456", "password_confirm": "Nueva-Clave#456"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(login("ana@t.co", "Nueva-Clave#456").status_code, 200)

    def test_el_listado_de_usuarios_muestra_hasta_cuando_esta_bloqueado(self):
        response = self.as_user(self.admin).get(reverse("user_list"))
        rows = {row["email"]: row for row in response.data}
        self.assertIsNotNone(rows["ana@t.co"]["locked_until"])
        self.assertIsNone(rows["admin@t.co"]["locked_until"])


class ClientIPThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        make_user("ana@t.co", "VENDEDOR")

    def test_el_limite_usa_el_mismo_criterio_de_ip_que_el_registro(self):
        from .throttling import ClientIPScopedRateThrottle

        class FakeRequest:
            META = {"HTTP_CF_CONNECTING_IP": "198.51.100.9", "REMOTE_ADDR": "10.0.0.1"}

        self.assertEqual(ClientIPScopedRateThrottle().get_ident(FakeRequest()), "198.51.100.9")


class BrokenBackend:
    """Servidor de correo caído: construir el backend ya falla."""

    def __init__(self, *args, **kwargs):
        raise OSError("sin correo")
