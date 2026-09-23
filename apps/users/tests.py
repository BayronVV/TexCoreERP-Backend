from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

User = get_user_model()


def make_user(email, role, password="Passw0rd!23"):
    return User.objects.create_user(
        username=email, email=email, password=password, role=role
    )


class UserRegistrationTests(TestCase):
    def test_registro_crea_usuario_pendiente(self):
        client = APIClient()
        response = client.post(
            reverse("user_register"),
            {
                "first_name": "Ana",
                "last_name": "Perez",
                "email": "ana@texcore.test",
                "password": "Passw0rd!23",
                "password_confirm": "Passw0rd!23",
            },
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="ana@texcore.test")
        self.assertEqual(user.role, "PENDING")


class RoleBasedAccessTests(TestCase):
    """HU 1.4 (TE-77): los endpoints de /api/users/ solo los usa ADMIN."""

    def setUp(self):
        self.admin = make_user("admin@texcore.test", "ADMIN")
        self.vendedor = make_user("vendedor@texcore.test", "VENDEDOR")

    def _token_for(self, email, password="Passw0rd!23"):
        response = APIClient().post(
            reverse("token_obtain_pair"), {"username": email, "password": password}
        )
        return response.data["access"]

    def test_anonimo_no_accede_al_listado(self):
        response = APIClient().get(reverse("user_list"))
        self.assertEqual(response.status_code, 401)

    def test_rol_sin_permiso_recibe_403(self):
        token = self._token_for("vendedor@texcore.test")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.get(reverse("user_list"))
        self.assertEqual(response.status_code, 403)

    def test_admin_si_accede_al_listado(self):
        token = self._token_for("admin@texcore.test")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.get(reverse("user_list"))
        self.assertEqual(response.status_code, 200)
        emails = {row["email"] for row in response.data}
        self.assertIn("admin@texcore.test", emails)

    def test_rol_sin_permiso_no_puede_cambiar_roles(self):
        token = self._token_for("vendedor@texcore.test")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.patch(
            reverse("role_update", args=[self.vendedor.id]), {"role": "ADMIN"}
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_si_puede_cambiar_roles(self):
        token = self._token_for("admin@texcore.test")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.patch(
            reverse("role_update", args=[self.vendedor.id]), {"role": "GERENTE"}
        )
        self.assertEqual(response.status_code, 200)
        self.vendedor.refresh_from_db()
        self.assertEqual(self.vendedor.role, "GERENTE")
