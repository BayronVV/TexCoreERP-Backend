"""Operarios y máquinas de demostración (HU 4.4): el seed los crea y los asigna de forma idempotente."""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.inventory.tests import make_user

from . import catalog
from .models import AsignacionEtapa, Maquina, Operario


@override_settings(DEBUG=True)
class DemoResourcesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_user("produccion@t.co", "PRODUCCION")
        call_command("seed_demo_inventario", verbosity=0)
        call_command("seed_demo_produccion", verbosity=0)

    def seed(self):
        call_command("seed_demo_recursos", verbosity=0)

    def test_crea_operarios_y_maquinas_con_codigos_consecutivos(self):
        self.seed()
        self.assertEqual(Operario.objects.count(), 6)
        self.assertEqual(Maquina.objects.count(), 9)
        self.assertEqual(Operario.objects.order_by("id").first().codigo, "OPE-0001")
        self.assertEqual(Maquina.objects.order_by("id").last().codigo, "MAQ-0009")

    def test_una_maquina_queda_en_mantenimiento_y_no_se_asigna(self):
        self.seed()
        broken = Maquina.objects.get(serial="DEMO-MAQ-08")
        self.assertEqual(broken.estado, catalog.MACHINE_MAINTENANCE)
        self.assertFalse(AsignacionEtapa.objects.filter(maquina=broken).exists())

    def test_asigna_la_etapa_en_curso_de_los_lotes_de_demostracion(self):
        self.seed()
        rows = AsignacionEtapa.objects.filter(fin_at__isnull=True).select_related("etapa_lote", "operario", "maquina")
        self.assertGreater(rows.count(), 0)
        for row in rows:
            self.assertIn(row.etapa_lote.etapa, row.operario.etapas)  # el operario está habilitado para esa etapa
            if row.maquina:
                self.assertIn(row.etapa_lote.etapa, row.maquina.etapas)
                self.assertEqual(row.maquina.estado, catalog.MACHINE_AVAILABLE)
            self.assertNotEqual(row.etapa_lote.estado, catalog.STAGE_DONE)

    def test_es_idempotente(self):
        self.seed()
        counts = (Operario.objects.count(), Maquina.objects.count(), AsignacionEtapa.objects.count())
        self.seed()
        self.assertEqual((Operario.objects.count(), Maquina.objects.count(), AsignacionEtapa.objects.count()), counts)

    @override_settings(DEBUG=False)
    def test_solo_funciona_con_debug(self):
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(Operario.objects.count(), 0)
