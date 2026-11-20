import re
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from django.db import DataError, IntegrityError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIRequestFactory

from apps.core.exceptions import api_exception_handler


class HealthTests(SimpleTestCase):
    def test_health_responde_ok(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


@override_settings(DEBUG=True)
class HealthDbTests(TestCase):
    def test_health_db_ejecuta_consulta(self):
        response = self.client.get(reverse("health-db"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertIsInstance(body["tables"], list)


class LoggingAndExceptionHandlerTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _context(self, path="/api/test/"):
        return {"request": self.factory.get(path)}

    def test_logging_configurado_hacia_consola(self):
        self.assertIn("console", settings.LOGGING["handlers"])
        self.assertEqual(settings.LOGGING["handlers"]["console"]["class"], "logging.StreamHandler")
        req_logger = settings.LOGGING["loggers"]["django.request"]
        self.assertEqual(req_logger["level"], "ERROR")
        self.assertIn("console", req_logger["handlers"])

    def test_error_no_controlado_registra_traza_y_responde_500_json(self):
        with self.assertLogs("django.request", level="ERROR") as captured:
            response = api_exception_handler(RuntimeError("Fallo simulado de prueba"), self._context("/api/boom/"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["detail"], "Ocurrió un error interno en el servidor.")
        joined = "\n".join(captured.output)
        self.assertIn("/api/boom/", joined)
        self.assertIn("RuntimeError: Fallo simulado de prueba", joined)

    def test_errores_bd_y_validacion_responden_400_o_409_claros(self):
        data_err = api_exception_handler(DataError("value too long for type character varying(20)"), self._context())
        self.assertEqual(data_err.status_code, 400)
        self.assertIn("longitud máxima", str(data_err.data["detail"][0]))

        dup_err = api_exception_handler(IntegrityError("duplicate key value violates unique constraint uq_x"), self._context())
        self.assertEqual(dup_err.status_code, 409)
        self.assertIn("Ya existe", str(dup_err.data["detail"][0]))

        check_err = api_exception_handler(IntegrityError("new row violates check constraint ck_cantidad"), self._context())
        self.assertEqual(check_err.status_code, 400)

        val_err = api_exception_handler(DjangoValidationError({"codigo": ["Código inválido."]}), self._context())
        self.assertEqual(val_err.status_code, 400)
        self.assertEqual(val_err.data, {"codigo": ["Código inválido."]})


class OpenApiAndEnvExampleTests(TestCase):
    def test_esquema_openapi_valida_sin_advertencias(self):
        from io import BytesIO

        # spectacular --validate --fail-on-warn lanza SystemExit o CommandError si hay warnings.
        out = StringIO()
        err = StringIO()
        call_command("spectacular", validate=True, fail_on_warn=True, stdout=out, stderr=err)
        schema_text = out.getvalue()
        self.assertIn("/api/lavanderia/remisiones/", schema_text)
        self.assertIn("/api/reportes/refrescar/", schema_text)
        self.assertIn("EstadoConciliacionCarteraEnum", schema_text)
        self.assertIn("TipoMovimientoTerminadoEnum", schema_text)
        _ = BytesIO  # mantiene compatibilidad sin warnings

    def test_env_example_documenta_todas_las_variables_de_settings(self):
        base = Path(settings.BASE_DIR)
        settings_text = (base / "config" / "settings.py").read_text(encoding="utf-8")
        env_example_text = (base / ".env.example").read_text(encoding="utf-8")

        declared_in_example = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", env_example_text, re.MULTILINE))
        used_in_settings = set(re.findall(r'env_(?:bool|list)\(\s*"([A-Z][A-Z0-9_]+)"', settings_text))
        used_in_settings |= set(re.findall(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]+)"', settings_text))
        used_in_settings |= set(re.findall(r'os\.environ\[\s*"([A-Z][A-Z0-9_]+)"', settings_text))
        used_in_settings.discard("RENDER_EXTERNAL_HOSTNAME")  # inyectada automáticamente por Render

        missing = sorted(used_in_settings - declared_in_example)
        self.assertEqual(missing, [], f"Variables faltantes en .env.example: {missing}")
