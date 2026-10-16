"""Órdenes de demostración que siguen el flujo de la ficha técnica (HU 3.2): el seed las crea sobre referencias."""
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from apps.references import fichas

from .models import Movimiento, OrdenSalida
from .tests import InventoryBase

KEYS = ("OP-DEMO-CLASICO", "OP-DEMO-MOM", "LV-DEMO-CLASICO")


def demo(key):
    return OrdenSalida.objects.get(observaciones=f"Orden de demostración {key}")


@override_settings(DEBUG=True)
class DemoOrdersOnReferencesTests(InventoryBase):
    def seed(self):
        call_command("seed_demo_inventario", verbosity=0)

    def test_crea_las_tres_ordenes_en_su_estado_y_ligadas_a_su_referencia(self):
        self.seed()
        clasico, mom, laundry = (demo(key) for key in KEYS)
        self.assertEqual((clasico.tipo, clasico.estado), ("PRODUCCION", "COMPLETADA"))
        self.assertEqual((mom.tipo, mom.estado), ("PRODUCCION", "EN_PROCESO"))
        self.assertEqual((laundry.tipo, laundry.estado), ("LAVANDERIA", "EN_PROCESO"))
        self.assertEqual(clasico.referencia.nombre, "Clásico 5 bolsillos frosteado")
        self.assertEqual(mom.referencia.nombre, "Mom vintage tiro alto")
        self.assertEqual(laundry.referencia_id, clasico.referencia_id)
        self.assertEqual(clasico.cantidad_prendas, 60)
        self.assertEqual(laundry.cantidad_prendas, 40)  # lo que se envía a lavar

    def test_los_materiales_de_produccion_son_los_que_calcula_la_ficha(self):
        self.seed()
        for key, garments in (("OP-DEMO-CLASICO", 60), ("OP-DEMO-MOM", 50)):
            order = demo(key)
            expected = {line.producto_id: fichas.required_total(line, garments) for line in fichas.ficha_lines(order.referencia)}
            actual = {line.producto_id: line.cantidad for line in order.lineas.all()}
            self.assertEqual(actual, expected, key)

    def test_el_lote_del_kardex_es_el_codigo_de_la_referencia(self):
        self.seed()
        for key in KEYS:
            order = demo(key)
            lots = set(Movimiento.objects.filter(orden=order, motivo="SALIDA_ORDEN").values_list("lote", flat=True))
            self.assertEqual(lots, {order.referencia.codigo}, key)

    def test_la_orden_completada_devolvio_pantalones(self):
        self.seed()
        returns = Movimiento.objects.filter(orden=demo("OP-DEMO-CLASICO"), motivo="RETORNO_ORDEN")
        self.assertEqual([m.cantidad for m in returns], [58])

    def test_es_idempotente(self):
        self.seed()
        count = (OrdenSalida.objects.count(), Movimiento.objects.count())
        self.seed()
        self.assertEqual((OrdenSalida.objects.count(), Movimiento.objects.count()), count)

    def test_los_saldos_siguen_coincidiendo_con_el_kardex(self):
        self.seed()
        for order in (demo(key) for key in KEYS):
            for movement in Movimiento.objects.filter(orden=order).select_related("producto"):
                last = movement.producto.movimientos.first()
                self.assertEqual(movement.producto.stock_actual, last.stock_despues, movement.producto.nombre)

    def test_si_no_alcanza_el_material_las_omite_sin_fallar(self):
        not_viable = {"viable": False, "lineas": [], "faltantes": []}
        with mock.patch.object(fichas, "compute_requirements", return_value=not_viable):
            self.seed()  # no lanza
        for key in ("OP-DEMO-CLASICO", "OP-DEMO-MOM"):
            self.assertFalse(OrdenSalida.objects.filter(observaciones=f"Orden de demostración {key}").exists(), key)
        self.seed()  # con material vuelve a intentarlas y las crea
        self.assertTrue(OrdenSalida.objects.filter(observaciones="Orden de demostración OP-DEMO-MOM").exists())

    def test_si_falta_la_ficha_las_omite_sin_fallar(self):
        no_sheet = ValidationError({"referencia": ["La referencia no tiene ficha técnica."]})
        with mock.patch.object(fichas, "compute_requirements", side_effect=no_sheet):
            self.seed()
        self.assertFalse(OrdenSalida.objects.filter(observaciones__contains="OP-DEMO").exists())

    def test_las_seis_ordenes_anteriores_tambien_quedan_ligadas_a_una_referencia(self):
        self.seed()
        old = ("FT-1427-A", "FT-1431-B", "FT-1436-C", "REF-1427-LV1", "REF-N22-LV2", "FT-1440-X")
        for key in old:
            self.assertIsNotNone(demo(key).referencia_id, key)
        self.assertEqual(OrdenSalida.objects.filter(referencia__isnull=False).count(), len(old) + len(KEYS))

    def test_una_base_que_ya_tenia_las_ordenes_antiguas_no_las_duplica(self):
        """Las órdenes sembradas antes de las referencias se reconocen por su ficha escrita a mano."""
        self.seed()
        OrdenSalida.objects.filter(observaciones="Orden de demostración FT-1427-A").update(
            observaciones="Orden de demostración", ficha_tecnica="FT-1427-A", referencia=None
        )
        before = OrdenSalida.objects.count()
        self.seed()
        self.assertEqual(OrdenSalida.objects.count(), before)
