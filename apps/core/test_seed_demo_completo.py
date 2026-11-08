"""Siembra de demostración completa: todos los módulos quedan con datos, sin duplicar y solo con el permiso explícito."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.core.management.commands import seed_demo_completo as seed
from apps.inventory.tests import make_user
from apps.production.models import TarifaManoObra
from apps.sales.models import FacturaVenta, MovimientoCartera
from apps.shipping.models import Guia


class SeedDemoCompletoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for number, role in enumerate(("ADMIN", "GERENTE", "ALMACENISTA", "PRODUCCION", "SECRETARIA", "VENDEDOR", "TERMINACION")):
            make_user(f"demo{number}@t.co", role)

    def run_seed(self, *args):
        out = StringIO()
        call_command("seed_demo_completo", *args, stdout=out)
        return out.getvalue()

    @override_settings(DEBUG=False)
    def test_en_produccion_exige_el_permiso_explicito(self):
        with self.assertRaises(CommandError):
            self.run_seed()
        self.assertFalse(FacturaVenta.objects.exists())

    @override_settings(DEBUG=False)
    def test_deja_datos_en_todos_los_modulos_y_se_puede_repetir(self):
        first = self.run_seed("--permitir-produccion")
        self.assertIn("Todos los módulos tienen datos de demostración.", first)
        for _, path in seed.REPORT:
            self.assertGreater(seed._model(path).objects.count(), 0, path)
        self.assertEqual(TarifaManoObra.objects.count(), 3)
        self.assertGreaterEqual(MovimientoCartera.objects.count(), 2)
        counts = {path: seed._model(path).objects.count() for _, path in seed.REPORT}
        second = self.run_seed("--permitir-produccion")
        self.assertIn("ya tiene datos, se salta", second)
        for _, path in seed.REPORT:
            if path.endswith("MovimientoTerminado"):
                continue  # el stock se vuelve a completar tras las ventas de la demo
            self.assertEqual(seed._model(path).objects.count(), counts[path], path)
        self.assertEqual(Guia.objects.filter(vigente=True).count(), 10)

    @override_settings(DEBUG=False)
    def test_el_permiso_no_deja_el_modo_depuracion_encendido(self):
        from django.conf import settings

        self.run_seed("--permitir-produccion")
        self.assertFalse(settings.DEBUG)
        from django.core.management.base import CommandError as Refused

        with self.assertRaises(Refused):
            call_command("seed_demo_tarifas", stdout=StringIO())  # cada seed_demo_* sigue negándose por su cuenta


class SeedOnDeployHookTests(TestCase):
    """El gancho del `migrate` de Render: solo siembra si SEED_DEMO_ON_DEPLOY=true y nunca tumba el arranque."""

    def test_apagado_por_defecto_no_hace_nada(self):
        from unittest import mock

        from apps.core.apps import _seed_demo_on_deploy

        with mock.patch("django.core.management.call_command") as called:
            _seed_demo_on_deploy(sender=None, using="default")
        called.assert_not_called()

    @override_settings(SEED_DEMO_ON_DEPLOY=True)
    def test_encendido_siembra_con_permiso_y_un_fallo_no_impide_el_arranque(self):
        from unittest import mock

        from apps.core.apps import _seed_demo_on_deploy

        with mock.patch("django.core.management.call_command") as called:
            _seed_demo_on_deploy(sender=None, using="default")
        called.assert_called_once_with("seed_demo_completo", permitir_produccion=True)
        with mock.patch("django.core.management.call_command", side_effect=RuntimeError("falló la demo")):
            _seed_demo_on_deploy(sender=None, using="default")  # no propaga el error

    @override_settings(SEED_DEMO_ON_DEPLOY=True)
    def test_otra_base_no_se_siembra(self):
        from unittest import mock

        from apps.core.apps import _seed_demo_on_deploy

        with mock.patch("django.core.management.call_command") as called:
            _seed_demo_on_deploy(sender=None, using="replica")
        called.assert_not_called()
