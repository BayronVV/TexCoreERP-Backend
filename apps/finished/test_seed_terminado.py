"""Ingreso de demostración de producto terminado (HU 6.2): el seed lo hace con las reglas de la aplicación y es idempotente."""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.inventory.tests import make_user
from apps.quality.models import Inspeccion

from .models import IngresoTerminado, MovimientoTerminado, StockTerminado


@override_settings(DEBUG=True)
class DemoFinishedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_user("produccion@t.co", "PRODUCCION")
        make_user("terminacion@t.co", "TERMINACION")
        make_user("secretaria@t.co", "SECRETARIA")
        call_command("seed_demo_inventario", verbosity=0)
        call_command("seed_demo_produccion", verbosity=0)
        call_command("seed_demo_calidad", verbosity=0)

    def seed(self):
        call_command("seed_demo_terminado", verbosity=0)

    def test_ingresa_las_aptas_de_la_inspeccion_de_demostracion(self):
        self.seed()
        entry = IngresoTerminado.objects.get()
        inspection = Inspeccion.objects.get(observaciones="Inspección de demostración")
        self.assertEqual((entry.inspeccion_id, entry.aptas), (inspection.id, inspection.aptas))
        self.assertEqual(entry.recibido_por.role_id, "SECRETARIA")
        self.assertEqual(sum(line.cantidad for line in entry.lineas.all()), inspection.aptas)
        self.assertEqual(sum(row.cantidad for row in StockTerminado.objects.all()), inspection.aptas)
        self.assertEqual(MovimientoTerminado.objects.count(), entry.lineas.count())

    def test_es_idempotente(self):
        self.seed()
        counts = (IngresoTerminado.objects.count(), StockTerminado.objects.count(), MovimientoTerminado.objects.count())
        self.seed()
        self.assertEqual((IngresoTerminado.objects.count(), StockTerminado.objects.count(), MovimientoTerminado.objects.count()), counts)

    @override_settings(DEBUG=False)
    def test_solo_con_debug(self):
        with self.assertRaises(CommandError):
            self.seed()
