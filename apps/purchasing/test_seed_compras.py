"""Órdenes de compra de demostración: el seed las crea con las reglas de la aplicación y de forma idempotente."""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.inventory.models import Movimiento
from apps.inventory.tests import make_user
from apps.users.models import CustomUser

from .models import OrdenCompra, Recepcion


@override_settings(DEBUG=True)
class DemoPurchasingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_user("produccion@t.co", "PRODUCCION")
        make_user("gerente@t.co", "GERENTE")
        make_user("almacen@t.co", "ALMACENISTA")
        call_command("seed_demo_inventario", verbosity=0)

    def seed(self):
        call_command("seed_demo_compras", verbosity=0)

    def test_crea_las_tres_ordenes_en_sus_estados(self):
        self.seed()
        states = {order.notas.split()[-1]: order.estado for order in OrdenCompra.objects.all()}
        self.assertEqual(states, {"OC-DEMO-BORRADOR": "BORRADOR", "OC-DEMO-APROBADA": "APROBADA", "OC-DEMO-PARCIAL": "RECIBIDA_PARCIAL"})

    def test_la_recepcion_parcial_sumo_al_stock_y_dejo_kardex(self):
        self.seed()
        self.assertEqual(Recepcion.objects.count(), 1)
        movements = Movimiento.objects.filter(motivo="COMPRA", observaciones__startswith="Recepción RC-")
        self.assertGreater(movements.count(), 0)
        self.assertTrue(all(movement.orden_compra.startswith("OC-") for movement in movements))

    def test_es_idempotente(self):
        self.seed()
        counts = (OrdenCompra.objects.count(), Recepcion.objects.count(), Movimiento.objects.count())
        self.seed()
        self.assertEqual((OrdenCompra.objects.count(), Recepcion.objects.count(), Movimiento.objects.count()), counts)

    def test_sin_almacenista_la_orden_parcial_queda_aprobada(self):
        CustomUser.objects.filter(role_id="ALMACENISTA").update(is_active=False)  # no quedan almacenistas activos
        self.seed()
        self.assertEqual(Recepcion.objects.count(), 0)
        self.assertEqual(OrdenCompra.objects.get(notas__endswith="OC-DEMO-PARCIAL").estado, "APROBADA")

    @override_settings(DEBUG=False)
    def test_solo_funciona_con_debug(self):
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(OrdenCompra.objects.count(), 0)
