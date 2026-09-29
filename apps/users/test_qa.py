"""
Regresiones de los bugs que encontró QA en recuperación de contraseña y roles.
Cada prueba falló antes de la corrección.
Ejecutar:
  DJANGO_SECRET_KEY=x-test-key-que-es-suficientemente-larga-para-hmac DJANGO_DEBUG=true DATABASE_URL= \
  ./.venv/Scripts/python.exe manage.py test apps.users.test_qa -v 2
"""

import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import ModulePermission, Role

User = get_user_model()
PASSWORD = "Passw0rd!23"


def make_user(email, role="PENDING", password=PASSWORD, **extra):
    return User.objects.create_user(username=email, email=email, password=password, role_id=role, **extra)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def login(email, password=PASSWORD):
    return APIClient().post(reverse("token_obtain_pair"), {"username": email, "password": password})


def make_role(code, perms):
    role = Role.objects.create(code=code, name=code.title())
    role.permissions.set(ModulePermission.objects.filter(code__in=perms))
    return role


class EscaladaDePrivilegiosTests(TestCase):
    """BUG-01: 'seguridad.gestionar' sin 'seguridad.roles' permite fabricar administradores."""

    def setUp(self):
        self.admin = make_user("admin@t.co", "ADMIN")
        make_role("GESTOR", ["seguridad.ver", "seguridad.gestionar"])
        self.gestor = make_user("gestor@t.co", "GESTOR")
        self.otro = make_user("otro@t.co", "VENDEDOR")

    def test_gestor_no_puede_ascender_a_otro_a_admin(self):
        response = client_for(self.gestor).patch(
            reverse("user_detail", args=[self.otro.id]), {"role": "ADMIN"}
        )
        self.assertEqual(
            response.status_code, 403, "Un gestor sin seguridad.roles no debería poder crear ADMINs"
        )

    def test_gestor_no_puede_crear_usuario_admin(self):
        response = client_for(self.gestor).post(
            reverse("user_list"),
            {"first_name": "N", "last_name": "A", "email": "nuevo@t.co", "role": "ADMIN"},
        )
        self.assertEqual(response.status_code, 403)

    def test_gestor_no_puede_desactivar_a_un_admin(self):
        second_admin = make_user("admin2@t.co", "ADMIN")
        response = client_for(self.gestor).patch(
            reverse("user_detail", args=[second_admin.id]), {"is_active": False}
        )
        self.assertEqual(response.status_code, 403)


class ReglaVerGestionarBackendTests(TestCase):
    """BUG: la regla 'gestionar implica ver' solo existe en el frontend."""

    def test_backend_rechaza_gestionar_sin_ver(self):
        admin = make_user("admin@t.co", "ADMIN")
        role = make_role("QA_ROL", [])
        response = client_for(admin).patch(
            reverse("role_detail", args=[role.id]), {"permissions": ["seguridad.gestionar"]}, format="json"
        )
        self.assertEqual(response.status_code, 400)


class SesionTrasCambioDeCredencialesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin@t.co", "ADMIN")
        self.user = make_user("ana@t.co", "VENDEDOR")

    def _reset(self, new_password):
        APIClient().post(reverse("password_reset"), {"email": "ana@t.co"})
        token = re.search(r"token=([\w\-]+)", mail.outbox[-1].body).group(1)
        return APIClient().post(
            reverse("password_reset_confirm"),
            {"token": token, "password": new_password, "password_confirm": new_password},
        )

    def test_refresh_viejo_no_sirve_tras_restablecer_contrasena(self):
        """BUG: restablecer la contraseña no cierra las sesiones abiertas (7 días de refresh)."""
        refresh = login("ana@t.co").data["refresh"]
        self.assertEqual(self._reset("Nueva#Clave99").status_code, 200)
        response = APIClient().post(reverse("token_refresh"), {"refresh": refresh})
        self.assertEqual(response.status_code, 401)

    def test_refresh_de_usuario_eliminado_da_401_y_no_500(self):
        """BUG: /api/token/refresh/ con un usuario borrado lógicamente lanza DoesNotExist (500)."""
        refresh = login("ana@t.co").data["refresh"]
        client_for(self.admin).delete(reverse("user_detail", args=[self.user.id]))
        client = APIClient()
        client.raise_request_exception = False
        response = client.post(reverse("token_refresh"), {"refresh": refresh})
        self.assertEqual(response.status_code, 401)


class LimiteDeFrecuenciaTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_limite_por_ip_no_se_evade_con_x_forwarded_for(self):
        """BUG: el límite de 5/hora por IP se evade enviando un X-Forwarded-For distinto."""
        codes = []
        for i in range(8):
            response = APIClient().post(
                reverse("password_reset"), {"email": "nadie@t.co"}, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}"
            )
            codes.append(response.status_code)
        self.assertIn(429, codes, f"Nunca se limitó: {codes}")


class LoginCorreoTests(TestCase):
    def test_login_no_distingue_mayusculas_en_el_correo(self):
        """BUG: el registro guarda el correo en minúsculas pero el login compara exacto."""
        APIClient().post(
            reverse("user_register"),
            {
                "first_name": "Ana",
                "last_name": "QA",
                "email": "Ana.QA@T.co",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
        )
        self.assertEqual(login("ana.qa@t.co").status_code, 200)
        self.assertEqual(login("Ana.QA@T.co").status_code, 200)


class UltimoAdminTests(TestCase):
    def test_admin_sin_contrasena_no_cuenta_como_admin_activo(self):
        """Un ADMIN invitado que nunca activó su cuenta no puede entrar: no cuenta como el admin que queda."""
        from .serializers import other_working_admins

        admin = make_user("admin@t.co", "ADMIN")
        invitado = User(username="inv@t.co", email="inv@t.co", role_id="ADMIN")
        invitado.set_unusable_password()
        invitado.save()
        self.assertFalse(other_working_admins(admin))
        make_user("admin2@t.co", "ADMIN")
        self.assertTrue(other_working_admins(admin))


class RespuestaCrearRolTests(TestCase):
    def test_crear_rol_devuelve_users_count(self):
        """BUG menor: POST /api/roles/ no incluye users_count; la UI muestra ' usuarios' sin número."""
        admin = make_user("admin@t.co", "ADMIN")
        response = client_for(admin).post(
            reverse("role_list"), {"code": "QA_X", "name": "QA X"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("users_count", response.data)


class ReglasDeDelegacionTests(TestCase):
    """Lo que sí y lo que no puede hacer alguien que administra usuarios o roles sin ser ADMIN."""

    def setUp(self):
        make_user("admin@t.co", "ADMIN")
        make_role("GESTOR", ["seguridad.ver", "seguridad.gestionar", "seguridad.roles"])
        self.gestor = client_for(make_user("gestor@t.co", "GESTOR"))
        self.otro = make_user("otro@t.co", "PENDING")

    def test_gestor_asigna_roles_operativos(self):
        response = self.gestor.patch(reverse("user_detail", args=[self.otro.id]), {"role": "ALMACENISTA"})
        self.assertEqual(response.status_code, 200)

    def test_gestor_no_asigna_roles_con_permisos_de_seguridad(self):
        response = self.gestor.patch(reverse("user_detail", args=[self.otro.id]), {"role": "GESTOR"})
        self.assertEqual(response.status_code, 403)

    def test_gestor_no_da_permisos_de_seguridad_a_otro_rol(self):
        role = Role.objects.get(code="VENDEDOR")
        perms = ["ventas.ver", "ventas.gestionar", "producto_terminado.ver", "seguridad.ver"]
        response = self.gestor.patch(
            reverse("role_detail", args=[role.id]), {"permissions": perms}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_gestor_no_edita_su_propio_rol(self):
        role = Role.objects.get(code="GESTOR")
        perms = ["seguridad.ver", "seguridad.gestionar", "seguridad.roles", "reportes.ver"]
        response = self.gestor.patch(
            reverse("role_detail", args=[role.id]), {"permissions": perms}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_gestor_si_edita_permisos_operativos_de_otro_rol(self):
        role = Role.objects.get(code="SECRETARIA")
        perms = ["producto_terminado.ver", "producto_terminado.gestionar", "reportes.ver"]
        response = self.gestor.patch(
            reverse("role_detail", args=[role.id]), {"permissions": perms}, format="json"
        )
        self.assertEqual(response.status_code, 200)


class FalloDeCorreoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin@t.co", "ADMIN")
        make_user("ana@t.co", "VENDEDOR")

    def test_si_falla_el_correo_la_recuperacion_responde_igual(self):
        from unittest import mock

        with mock.patch("apps.users.password_reset.send_mail", side_effect=OSError("SMTP caído")):
            existe = APIClient().post(reverse("password_reset"), {"email": "ana@t.co"})
            no_existe = APIClient().post(reverse("password_reset"), {"email": "nadie@t.co"})
        self.assertEqual((existe.status_code, existe.data), (no_existe.status_code, no_existe.data))

    def test_si_falla_el_correo_el_alta_avisa_sin_romperse(self):
        from unittest import mock

        with mock.patch("apps.users.password_reset.send_mail", side_effect=OSError("SMTP caído")):
            response = client_for(self.admin).post(
                reverse("user_list"),
                {"first_name": "L", "last_name": "R", "email": "l@t.co", "role": "VENDEDOR"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["email_sent"])


class SesionDeslizanteTests(TestCase):
    def test_refresh_entrega_un_refresh_nuevo(self):
        make_user("ana@t.co", "VENDEDOR")
        refresh = login("ana@t.co").data["refresh"]
        response = APIClient().post(reverse("token_refresh"), {"refresh": refresh})
        self.assertEqual(response.status_code, 200)
        self.assertIn("refresh", response.data)
