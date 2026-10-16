"""Órdenes de producción de demostración (HU 4.2): el seed las crea con lotes y tallas, de forma idempotente."""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.inventory.models import Movimiento, OrdenSalida, Producto
from apps.inventory.tests import make_user
from apps.references.models import Referencia

from .models import Lote, LoteTalla, OrdenProduccion

KEYS = ("OPL-DEMO-CLASICO", "OPL-DEMO-MOM")


def demo(key):
    return OrdenProduccion.objects.get(orden_salida__observaciones=f"Orden de demostración {key}")


@override_settings(DEBUG=True)
class DemoProductionOrdersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_user("produccion@t.co", "PRODUCCION")
        call_command("seed_demo_inventario", verbosity=0)

    def seed(self):
        call_command("seed_demo_produccion", verbosity=0)

    def test_crea_las_dos_ordenes_con_sus_lotes(self):
        before = OrdenProduccion.objects.count()
        self.seed()
        self.assertEqual(OrdenProduccion.objects.count(), before + 2)
        clasico, mom = demo(KEYS[0]), demo(KEYS[1])
        self.assertEqual([lot.cantidad for lot in clasico.lotes.all()], [30, 30, 20])
        self.assertEqual([lot.cantidad for lot in mom.lotes.all()], [25, 15])
        self.assertEqual(clasico.referencia.nombre, "Clásico 5 bolsillos frosteado")
        self.assertEqual(clasico.orden_salida.estado, "EN_PROCESO")

    def test_los_lotes_llevan_codigo_y_las_tallas_suman_el_lote(self):
        self.seed()
        clasico = demo(KEYS[0])
        first, second, third = clasico.lotes.all()
        self.assertEqual(first.codigo, f"{clasico.codigo}-L01")
        for lot in (first, second):
            self.assertEqual(sum(t.cantidad for t in lot.tallas.all()), lot.cantidad)
        self.assertEqual(third.tallas.count(), 0)  # un lote puede ir sin tallas

    def test_descuenta_el_material_y_deja_kardex(self):
        stock = {p.id: p.stock_actual for p in Producto.objects.all()}
        moves = Movimiento.objects.count()
        self.seed()
        self.assertGreater(Movimiento.objects.count(), moves)
        self.assertTrue(any(p.stock_actual < stock[p.id] for p in Producto.objects.all() if p.id in stock))

    def test_es_idempotente(self):
        self.seed()
        snapshot = (OrdenProduccion.objects.count(), Lote.objects.count(), LoteTalla.objects.count(),
                    OrdenSalida.objects.count(), Movimiento.objects.count())
        self.seed()
        self.assertEqual((OrdenProduccion.objects.count(), Lote.objects.count(), LoteTalla.objects.count(),
                          OrdenSalida.objects.count(), Movimiento.objects.count()), snapshot)

    def test_omite_la_orden_si_no_alcanza_el_material(self):
        Producto.objects.update(stock_actual=0)
        self.seed()
        self.assertFalse(OrdenProduccion.objects.filter(orden_salida__observaciones__contains="OPL-DEMO").exists())

    def test_omite_la_orden_si_la_referencia_no_esta_activa(self):
        Referencia.objects.update(estado="BORRADOR")
        self.seed()
        self.assertFalse(OrdenProduccion.objects.filter(orden_salida__observaciones__contains="OPL-DEMO").exists())


class DemoProductionDebugGuardTests(TestCase):
    @override_settings(DEBUG=False)
    def test_no_corre_fuera_de_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo_produccion", verbosity=0)
