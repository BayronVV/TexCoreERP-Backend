import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .models import ModulePermission, PasswordResetToken, Role

User = get_user_model()
PASSWORD = "Passw0rd!23"


def make_user(email, role="PENDING", password=PASSWORD, **extra):
    return User.objects.create_user(username=email, email=email, password=password, role_id=role, **extra)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class SeedDataTests(TestCase):
    def test_roles_y_permisos_iniciales(self):
        self.assertEqual(
            set(Role.objects.values_list("code", flat=True)),
            {
                "ADMIN",
                "GERENTE",
                "PRODUCCION",
                "ALMACENISTA",
                "TERMINACION",
                "SECRETARIA",
                "VENDEDOR",
                "PENDING",
            },
        )
        almacenista = Role.objects.get(code="ALMACENISTA")
        self.assertEqual(
            set(almacenista.permissions.values_list("code", flat=True)),
            {"inventario.ver", "inventario.gestionar"},
        )

    def test_admin_tiene_todos_los_permisos(self):
        admin = make_user("a@t.co", "ADMIN")
        self.assertEqual(
            admin.get_permission_codes(), set(ModulePermission.objects.values_list("code", flat=True))
        )

    def test_usuario_inactivo_no_tiene_permisos(self):
        user = make_user("x@t.co", "ALMACENISTA", is_active=False)
        self.assertEqual(user.get_permission_codes(), set())


class LoginAndMeTests(TestCase):
    def test_token_incluye_rol_y_me_devuelve_permisos(self):
        make_user("alm@t.co", "ALMACENISTA")
        client = APIClient()
        token = client.post(
            reverse("token_obtain_pair"), {"username": "alm@t.co", "password": PASSWORD}
        ).data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        me = client.get(reverse("me"))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["role"], "ALMACENISTA")
        self.assertEqual(me.data["permissions"], ["inventario.gestionar", "inventario.ver"])

    def test_usuario_inactivo_no_inicia_sesion(self):
        make_user("off@t.co", "VENDEDOR", is_active=False)
        response = APIClient().post(
            reverse("token_obtain_pair"), {"username": "off@t.co", "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 401)

    def test_endpoints_privados_exigen_sesion(self):
        self.assertEqual(APIClient().get(reverse("me")).status_code, 401)
        self.assertEqual(APIClient().get(reverse("user_list")).status_code, 401)


class RegistrationTests(TestCase):
    def payload(self, **overrides):
        data = {
            "first_name": "Ana",
            "last_name": "Pérez",
            "email": "Ana@TexCore.test",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "requested_area": "ALMACENISTA",
        }
        data.update(overrides)
        return data

    def test_registro_queda_pendiente_con_area_solicitada(self):
        response = APIClient().post(reverse("user_register"), self.payload())
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="ana@texcore.test")
        self.assertEqual(user.role_id, "PENDING")
        self.assertEqual(user.requested_area_id, "ALMACENISTA")

    def test_correo_duplicado_da_400_y_no_500(self):
        make_user("ana@texcore.test")
        response = APIClient().post(reverse("user_register"), self.payload())
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

    def test_no_se_puede_solicitar_rol_admin(self):
        response = APIClient().post(reverse("user_register"), self.payload(requested_area="ADMIN"))
        self.assertEqual(response.status_code, 400)

    def test_politica_de_contrasena(self):
        response = APIClient().post(
            reverse("user_register"), self.payload(password="abcdefgh", password_confirm="abcdefgh")
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("mayúscula", str(response.data["password"]))


class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@t.co", "ADMIN")
        self.vendedor = make_user("vend@t.co", "VENDEDOR")
        self.pending = make_user("pend@t.co", "PENDING", requested_area_id="ALMACENISTA")

    def test_rol_sin_permiso_recibe_403(self):
        client = client_for(self.vendedor)
        self.assertEqual(client.get(reverse("user_list")).status_code, 403)
        response = client.patch(reverse("user_detail", args=[self.pending.id]), {"role": "ADMIN"})
        self.assertEqual(response.status_code, 403)

    def test_admin_lista_usuarios(self):
        response = client_for(self.admin).get(reverse("user_list"))
        self.assertEqual(response.status_code, 200)
        rows = {row["email"]: row for row in response.data}
        self.assertEqual(rows["pend@t.co"]["requested_area"], "ALMACENISTA")
        self.assertEqual(rows["vend@t.co"]["role_name"], "Vendedor")

    def test_admin_aprueba_pendiente_asignando_rol(self):
        response = client_for(self.admin).patch(
            reverse("user_detail", args=[self.pending.id]), {"role": "ALMACENISTA"}
        )
        self.assertEqual(response.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.role_id, "ALMACENISTA")

    def test_rol_inexistente_da_400(self):
        response = client_for(self.admin).patch(
            reverse("user_detail", args=[self.pending.id]), {"role": "NOEXISTE"}
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_desactiva_usuario_y_este_pierde_acceso(self):
        session = APIClient()
        access = session.post(
            reverse("token_obtain_pair"), {"username": "vend@t.co", "password": PASSWORD}
        ).data["access"]
        session.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = client_for(self.admin).patch(
            reverse("user_detail", args=[self.vendedor.id]), {"is_active": False}
        )
        self.assertEqual((response.status_code, response.data["is_active"]), (200, False))
        # Ni un login nuevo ni el token que ya tenía le sirven.
        login = APIClient().post(
            reverse("token_obtain_pair"), {"username": "vend@t.co", "password": PASSWORD}
        )
        self.assertEqual(login.status_code, 401)
        self.assertEqual(session.get(reverse("me")).status_code, 401)

    def test_admin_no_puede_quitarse_su_rol_ni_desactivarse(self):
        client = client_for(self.admin)
        self.assertEqual(
            client.patch(reverse("user_detail", args=[self.admin.id]), {"role": "VENDEDOR"}).status_code, 400
        )
        self.assertEqual(
            client.patch(reverse("user_detail", args=[self.admin.id]), {"is_active": False}).status_code, 400
        )
        self.assertEqual(client.delete(reverse("user_detail", args=[self.admin.id])).status_code, 400)

    def test_con_dos_admins_uno_puede_degradar_al_otro(self):
        second = make_user("admin2@t.co", "ADMIN")
        response = client_for(second).patch(reverse("user_detail", args=[self.admin.id]), {"role": "GERENTE"})
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role_id, "GERENTE")

    def test_solo_un_admin_toca_cuentas_de_admin(self):
        # Un rol que gestiona usuarios pero no es ADMIN no puede degradar,
        # desactivar ni eliminar a un administrador.
        Role.objects.get(code="GERENTE").permissions.add(
            ModulePermission.objects.get(code="seguridad.gestionar")
        )
        client = client_for(make_user("g@t.co", "GERENTE"))
        url = reverse("user_detail", args=[self.admin.id])
        self.assertEqual(client.patch(url, {"role": "VENDEDOR"}).status_code, 403)
        self.assertEqual(client.patch(url, {"is_active": False}).status_code, 403)
        self.assertEqual(client.delete(url).status_code, 403)
        self.admin.refresh_from_db()
        self.assertEqual((self.admin.role_id, self.admin.is_active), ("ADMIN", True))

    def test_eliminar_es_borrado_logico(self):
        response = client_for(self.admin).delete(reverse("user_detail", args=[self.vendedor.id]))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.vendedor.pk).exists())
        row = User.all_objects.get(pk=self.vendedor.pk)
        self.assertIsNotNone(row.deleted_at)
        self.assertFalse(row.is_active)

    def test_admin_crea_usuario_y_se_envia_invitacion(self):
        response = client_for(self.admin).post(
            reverse("user_list"),
            {"first_name": "Luis", "last_name": "Rojas", "email": "Luis@T.co", "role": "PRODUCCION"},
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="luis@t.co")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Activa tu cuenta", mail.outbox[0].subject)
        self.assertEqual(user.reset_tokens.get().purpose, PasswordResetToken.PURPOSE_INVITE)

    def test_crear_usuario_con_correo_eliminado_da_400(self):
        client = client_for(self.admin)
        client.delete(reverse("user_detail", args=[self.vendedor.id]))
        response = client.post(
            reverse("user_list"),
            {"first_name": "V", "last_name": "V", "email": "vend@t.co", "role": "VENDEDOR"},
        )
        self.assertEqual(response.status_code, 400)

    def test_cambio_de_permisos_aplica_con_el_mismo_token(self):
        client = APIClient()
        access = client.post(
            reverse("token_obtain_pair"), {"username": "vend@t.co", "password": PASSWORD}
        ).data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(client.get(reverse("user_list")).status_code, 403)
        Role.objects.get(code="VENDEDOR").permissions.add(ModulePermission.objects.get(code="seguridad.ver"))
        self.assertEqual(client.get(reverse("user_list")).status_code, 200)


class RoleManagementTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@t.co", "ADMIN")
        self.client_admin = client_for(self.admin)

    def test_lista_roles_con_conteo_de_usuarios(self):
        make_user("v@t.co", "VENDEDOR")
        roles = {r["code"]: r for r in self.client_admin.get(reverse("role_list")).data}
        self.assertEqual(roles["VENDEDOR"]["users_count"], 1)
        self.assertTrue(roles["ADMIN"]["has_all_permissions"])

    def test_editar_permisos_de_un_rol(self):
        role = Role.objects.get(code="SECRETARIA")
        response = self.client_admin.patch(
            reverse("role_detail", args=[role.id]),
            {"permissions": ["producto_terminado.ver", "reportes.ver"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(response.data["permissions"]), ["producto_terminado.ver", "reportes.ver"])

    def test_no_se_editan_permisos_de_admin_ni_pending(self):
        for code in ("ADMIN", "PENDING"):
            role = Role.objects.get(code=code)
            response = self.client_admin.patch(
                reverse("role_detail", args=[role.id]), {"permissions": ["ventas.ver"]}, format="json"
            )
            self.assertEqual(response.status_code, 400, code)

    def test_crear_y_borrar_rol_personalizado(self):
        response = self.client_admin.post(
            reverse("role_list"),
            {"code": "supervisor", "name": "Supervisor", "permissions": ["produccion.ver"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["code"], "SUPERVISOR")
        self.assertFalse(response.data["is_system"])
        self.assertEqual(
            self.client_admin.delete(reverse("role_detail", args=[response.data["id"]])).status_code, 204
        )

    def test_no_se_borra_rol_del_sistema_ni_con_usuarios(self):
        vendedor = Role.objects.get(code="VENDEDOR")
        self.assertEqual(
            self.client_admin.delete(reverse("role_detail", args=[vendedor.id])).status_code, 400
        )
        custom = self.client_admin.post(
            reverse("role_list"), {"code": "AUX", "name": "Auxiliar"}, format="json"
        ).data
        make_user("aux@t.co", "AUX")
        self.assertEqual(
            self.client_admin.delete(reverse("role_detail", args=[custom["id"]])).status_code, 400
        )

    def test_codigo_de_rol_inmutable(self):
        role = Role.objects.get(code="GERENTE")
        response = self.client_admin.patch(
            reverse("role_detail", args=[role.id]), {"code": "OTRO"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_solo_quien_tiene_seguridad_roles_edita_roles(self):
        gerente = make_user("g@t.co", "GERENTE")
        role = Role.objects.get(code="VENDEDOR")
        response = client_for(gerente).patch(
            reverse("role_detail", args=[role.id]), {"name": "X"}, format="json"
        )
        self.assertEqual(response.status_code, 403)


@override_settings(PASSWORD_RESET_TOKEN_MINUTES=15)
class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()  # el throttling usa la caché
        self.user = make_user("ana@t.co", "VENDEDOR", first_name="Ana")

    def _request(self, email="ana@t.co"):
        return APIClient().post(reverse("password_reset"), {"email": email})

    def _token_from_mail(self):
        return re.search(r"token=([\w\-]+)", mail.outbox[-1].body).group(1)

    def test_solicitud_envia_correo_con_enlace(self):
        response = self._request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/restablecer-contrasena?token=", mail.outbox[0].body)
        self.assertIn("15 minutos", mail.outbox[0].body)

    def test_correo_inexistente_responde_igual_y_no_envia(self):
        known = self._request().data
        unknown = self._request("nadie@t.co").data
        self.assertEqual(known, unknown)
        self.assertEqual(len(mail.outbox), 1)

    def test_token_se_guarda_hasheado(self):
        self._request()
        raw = self._token_from_mail()
        self.assertFalse(PasswordResetToken.objects.filter(token_hash=raw).exists())

    def test_flujo_completo_y_token_de_un_solo_uso(self):
        self._request()
        raw = self._token_from_mail()
        client = APIClient()
        self.assertEqual(client.post(reverse("password_reset_validate"), {"token": raw}).status_code, 200)
        new_password = "Nuev0#Clave"
        data = {"token": raw, "password": new_password, "password_confirm": new_password}
        self.assertEqual(client.post(reverse("password_reset_confirm"), data).status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        # El mismo enlace ya no sirve.
        self.assertEqual(client.post(reverse("password_reset_confirm"), data).status_code, 400)
        login = client.post(reverse("token_obtain_pair"), {"username": "ana@t.co", "password": new_password})
        self.assertEqual(login.status_code, 200)

    def test_token_vencido(self):
        self._request()
        raw = self._token_from_mail()
        PasswordResetToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = APIClient().post(reverse("password_reset_validate"), {"token": raw})
        self.assertEqual(response.status_code, 400)

    def test_nueva_solicitud_invalida_el_enlace_anterior(self):
        self._request()
        first = self._token_from_mail()
        self._request()
        response = APIClient().post(reverse("password_reset_validate"), {"token": first})
        self.assertEqual(response.status_code, 400)

    def test_contrasenas_distintas_o_debiles(self):
        self._request()
        raw = self._token_from_mail()
        client = APIClient()
        mismatch = client.post(
            reverse("password_reset_confirm"),
            {"token": raw, "password": "Nuev0#Clave", "password_confirm": "Otra#1234"},
        )
        self.assertEqual(mismatch.status_code, 400)
        weak = client.post(
            reverse("password_reset_confirm"),
            {"token": raw, "password": "corta", "password_confirm": "corta"},
        )
        self.assertEqual(weak.status_code, 400)

    def test_usuario_desactivado_no_recibe_correo(self):
        self.user.is_active = False
        self.user.save()
        self._request()
        self.assertEqual(len(mail.outbox), 0)

    def test_limite_de_solicitudes_por_usuario(self):
        # IPs distintas para que no actúe el límite por IP, sino el de 3 correos por usuario.
        for i in range(5):
            APIClient().post(reverse("password_reset"), {"email": "ana@t.co"}, REMOTE_ADDR=f"10.0.0.{i}")
        self.assertEqual(len(mail.outbox), 3)

    def test_invitacion_permite_definir_contrasena(self):
        admin = make_user("admin@t.co", "ADMIN")
        client_for(admin).post(
            reverse("user_list"),
            {"first_name": "Luis", "last_name": "R", "email": "luis@t.co", "role": "VENDEDOR"},
        )
        raw = self._token_from_mail()
        check = APIClient().post(reverse("password_reset_validate"), {"token": raw})
        self.assertEqual(check.data["purpose"], "invite")
        data = {"token": raw, "password": "Nuev0#Clave", "password_confirm": "Nuev0#Clave"}
        self.assertEqual(APIClient().post(reverse("password_reset_confirm"), data).status_code, 200)
        self.assertTrue(User.objects.get(email="luis@t.co").check_password("Nuev0#Clave"))
