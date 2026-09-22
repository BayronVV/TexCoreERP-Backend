from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class HealthTests(SimpleTestCase):
    def test_health_responde_ok(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class HealthDbTests(TestCase):
    def test_health_db_ejecuta_consulta(self):
        response = self.client.get(reverse("health-db"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertIsInstance(body["tables"], list)
