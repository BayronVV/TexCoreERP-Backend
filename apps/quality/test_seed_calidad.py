"""Datos de demostración de calidad (HU 6.1): el seed los crea con las reglas de la aplicación y de forma idempotente."""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.inventory.tests import make_user
from apps.inventory import catalog as inventory_catalog
from apps.production import catalog as production_catalog
from apps.production.models import OrdenProduccion, RecepcionLavanderia

from .models import Inspeccion, MarraDetalle, TipoDefecto
from .services import pending_lots


@override_settings(DEBUG=True)
class DemoQualityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_user("produccion@t.co", "PRODUCCION")
        make_user("terminacion@t.co", "TERMINACION")
        call_command("seed_demo_inventario", verbosity=0)
        call_command("seed_demo_produccion", verbosity=0)

    def seed(self):
        call_command("seed_demo_calidad", verbosity=0)

    def test_crea_el_catalogo_con_defectos_corregibles_e_incorregibles(self):
        self.seed()
        self.assertEqual(TipoDefecto.objects.count(), 8)
        self.assertTrue(TipoDefecto.objects.filter(corregible=True).exists())
        self.assertTrue(TipoDefecto.objects.filter(corregible=False).exists())
        self.assertEqual(TipoDefecto.objects.order_by("id").first().codigo, "DEF-0001")

    def test_deja_un_lote_inspeccionado_y_otro_pendiente(self):
        self.seed()
        self.assertEqual(RecepcionLavanderia.objects.count(), 2)
        inspection = Inspeccion.objects.get()
        self.assertEqual(inspection.cantidad_recibida, inspection.aptas + inspection.marras)
        self.assertEqual(inspection.inspector.role_id, "TERMINACION")
        self.assertEqual(MarraDetalle.objects.filter(inspeccion=inspection).count(), 2)
        pending = list(pending_lots())
        self.assertEqual(len(pending), 1)
        self.assertNotEqual(pending[0].pk, inspection.lote_id)
        self.assertEqual(pending[0].estado_inventario, production_catalog.LOT_INV_INTERNAL)

    def test_no_usa_lotes_de_ordenes_anuladas(self):
        for order in OrdenProduccion.objects.all():
            order.orden_salida.estado = inventory_catalog.STATUS_CANCELLED
            order.orden_salida.save()
        self.seed()
        self.assertEqual(RecepcionLavanderia.objects.count(), 0)
        self.assertEqual(Inspeccion.objects.count(), 0)

    def test_es_idempotente(self):
        self.seed()
        counts = (TipoDefecto.objects.count(), RecepcionLavanderia.objects.count(), Inspeccion.objects.count(), len(list(pending_lots())))
        self.seed()
        self.assertEqual(
            (TipoDefecto.objects.count(), RecepcionLavanderia.objects.count(), Inspeccion.objects.count(), len(list(pending_lots()))), counts
        )

    @override_settings(DEBUG=False)
    def test_solo_con_debug(self):
        with self.assertRaises(CommandError):
            self.seed()
