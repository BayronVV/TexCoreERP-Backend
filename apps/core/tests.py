import importlib
import os
import re
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from django.db import DatabaseError, DataError, IntegrityError, connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import Resolver404, clear_url_caches, resolve, reverse
from rest_framework.test import APIRequestFactory

from apps.core.exceptions import api_exception_handler


class HealthTests(SimpleTestCase):
    def test_health_responde_ok(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class HealthDbTests(TestCase):
    def test_health_db_responde_ok_solo_con_estado_y_latencia(self):
        response = self.client.get(reverse("health-db"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        # Es público: no cuenta qué motor ni qué versión hay detrás ni lista las tablas.
        self.assertEqual(set(body), {"status", "latency_ms"})

    @override_settings(DEBUG=True)
    def test_health_db_no_lista_tablas_ni_en_desarrollo(self):
        self.assertNotIn("tables", self.client.get(reverse("health-db")).json())

    def test_si_la_base_falla_responde_no_disponible_sin_detalles_y_lo_registra(self):
        secreto = 'could not connect to server at "db.interno.supabase.co" (10.0.0.5): password authentication failed'
        # Solo se simula `cursor`: con la conexión real, si una regresión devolviera `connection.vendor`
        # en el cuerpo, la prueba fallaría con un texto en vez de intentar serializar un objeto simulado.
        with mock.patch.object(connection, "cursor", side_effect=DatabaseError(secreto)):
            with self.assertLogs("apps.core.views", level="ERROR") as logs:
                response = self.client.get(reverse("health-db"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "no disponible"})
        self.assertNotIn("db.interno", response.content.decode())
        self.assertNotIn("password", response.content.decode())
        self.assertTrue(any("db/" in line for line in logs.output))  # el diagnóstico queda en el registro del servidor


class DocumentacionDeLaApiTests(SimpleTestCase):
    """B-15: `/api/docs/`, `/api/redoc/` y `/api/schema/` solo se publican en desarrollo, salvo que se pidan."""

    def api_docs_enabled(self, **env):
        base = {key: value for key, value in os.environ.items() if key != "API_DOCS_ENABLED"}
        base.update(DJANGO_SETTINGS_MODULE="config.settings", **env)
        result = subprocess.run(
            [sys.executable, "-c", "from django.conf import settings; print(settings.API_DOCS_ENABLED)"],
            cwd=settings.BASE_DIR, env=base, capture_output=True, text=True, timeout=60, check=True,
        )
        return result.stdout.strip() == "True"

    def test_por_defecto_sigue_a_django_debug(self):
        self.assertTrue(self.api_docs_enabled(DJANGO_DEBUG="true"))
        self.assertFalse(self.api_docs_enabled(DJANGO_DEBUG="false"))

    def test_la_variable_la_enciende_o_apaga_en_cualquier_ambiente(self):
        self.assertTrue(self.api_docs_enabled(DJANGO_DEBUG="false", API_DOCS_ENABLED="true"))
        self.assertFalse(self.api_docs_enabled(DJANGO_DEBUG="true", API_DOCS_ENABLED="false"))

    def test_apagadas_las_rutas_no_existen(self):
        import config.urls

        try:
            with override_settings(API_DOCS_ENABLED=False):
                importlib.reload(config.urls)
                clear_url_caches()
                for path in ("/api/docs/", "/api/redoc/", "/api/schema/"):
                    with self.assertRaises(Resolver404, msg=path):
                        resolve(path, urlconf=config.urls)
            with override_settings(API_DOCS_ENABLED=True):
                importlib.reload(config.urls)
                clear_url_caches()
                for path in ("/api/docs/", "/api/redoc/", "/api/schema/"):
                    self.assertTrue(resolve(path, urlconf=config.urls), path)
        finally:
            importlib.reload(config.urls)
            clear_url_caches()


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


class SeparacionDeAmbientesTests(SimpleTestCase):
    """TE-185: un `.env` de desarrollo (o las pruebas) no puede conectarse a la base de producción."""

    def test_reconoce_la_base_de_produccion_por_usuario_del_pooler_o_por_host_directo(self):
        from config.settings import points_to_production

        prod, dev = "prodref123", "devref456"
        pooler = "postgresql://postgres.{ref}:clave@aws-0-us-west-2.pooler.supabase.com:5432/postgres"
        self.assertTrue(points_to_production(pooler.format(ref=prod), prod))
        self.assertTrue(points_to_production(f"postgresql://postgres:clave@db.{prod}.supabase.co:5432/postgres", prod))
        self.assertFalse(points_to_production(pooler.format(ref=dev), prod))  # mismo host del pooler, otro proyecto
        self.assertFalse(points_to_production("postgresql://texcore:texcore@localhost:5432/texcore_test", prod))
        self.assertFalse(points_to_production(pooler.format(ref=prod), ""))  # sin DB_PROD_REF no se compara
        self.assertFalse(points_to_production("", prod))  # SQLite local

    def test_settings_se_niega_a_arrancar_en_desarrollo_contra_produccion(self):
        import subprocess
        import sys

        env = {
            **os.environ, "DJANGO_DEBUG": "true", "DJANGO_SECRET_KEY": "solo-prueba", "DB_PROD_REF": "prodref123",
            "DATABASE_URL": "postgresql://postgres.prodref123:clave@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
            "DJANGO_SETTINGS_MODULE": "config.settings", "PYTHONIOENCODING": "utf-8",
        }
        result = subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"], cwd=settings.BASE_DIR, env=env, capture_output=True, text=True,
            encoding="utf-8",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PRODUCCIÓN", result.stderr)
        env["DJANGO_DEBUG"] = "false"  # una terminal de operación (DEBUG apagado) sí puede, con sus comandos --permitir-produccion
        ok = subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"], cwd=settings.BASE_DIR, env=env, capture_output=True, text=True,
            encoding="utf-8",
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)
