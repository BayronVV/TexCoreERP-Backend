"""Modelos de órdenes de producción y lotes (HU 4.2 / TE-113): restricciones, borrado lógico y relaciones."""
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.inventory.models import OrdenSalida
from apps.references import test_ficha as ficha_tests
from apps.references.models import Referencia, Variante

from .models import Lote, LoteTalla, OrdenProduccion


class ModelBase(ficha_tests.FichaBase):
    def make_order(self, code="OP-0001", quantity=100):
        reference = Referencia.objects.get(pk=self.ref["id"])
        out = OrdenSalida.objects.create(
            codigo=code, tipo="PRODUCCION", fecha_salida=timezone.localdate(), responsable="Taller",
            referencia=reference, ficha_tecnica=reference.codigo, producto_resultado=self.tela,
        )
        return OrdenProduccion.objects.create(
            orden_salida=out, codigo=code, referencia=reference, cantidad=quantity, creado_por=self.boss,
        )

    def make_lot(self, order, number=1, quantity=50):
        return Lote.objects.create(orden=order, numero=number, codigo=f"{order.codigo}-L{number:02d}", cantidad=quantity)

    def variant(self):
        return Variante.objects.filter(referencia_id=self.ref["id"]).first()

    def rejects(self, create):
        with self.assertRaises(IntegrityError), transaction.atomic():
            create()


class OrderModelTests(ModelBase):
    def test_la_orden_cuelga_de_la_salida_de_inventario(self):
        order = self.make_order()
        self.assertEqual(order.orden_salida.produccion, order)
        self.assertEqual(str(order), "OP-0001")

    def test_la_cantidad_debe_ser_al_menos_uno(self):
        self.rejects(lambda: self.make_order(quantity=0))

    def test_una_salida_solo_tiene_una_orden_de_produccion(self):
        order = self.make_order()
        self.rejects(lambda: OrdenProduccion.objects.create(
            orden_salida=order.orden_salida, codigo="OP-0002", referencia=order.referencia, cantidad=5,
        ))

    def test_el_codigo_es_unico_entre_ordenes_activas_y_se_libera_al_borrar(self):
        order = self.make_order()
        other = OrdenSalida.objects.create(
            codigo="OP-0009", tipo="PRODUCCION", fecha_salida=timezone.localdate(), responsable="Taller",
            producto_resultado=self.tela,
        )
        self.rejects(lambda: OrdenProduccion.objects.create(
            orden_salida=other, codigo="OP-0001", referencia=order.referencia, cantidad=5,
        ))
        order.delete()  # borrado lógico
        self.assertTrue(OrdenProduccion.all_objects.filter(pk=order.pk).exists())
        OrdenProduccion.objects.create(orden_salida=other, codigo="OP-0001", referencia=order.referencia, cantidad=5)

    def test_el_borrado_logico_la_oculta_de_las_consultas_normales(self):
        order = self.make_order()
        order.delete()
        self.assertFalse(OrdenProduccion.objects.filter(pk=order.pk).exists())


class LotModelTests(ModelBase):
    def test_el_lote_pertenece_a_su_orden(self):
        order = self.make_order()
        lot = self.make_lot(order)
        self.assertEqual(list(order.lotes.all()), [lot])
        self.assertEqual(str(lot), "OP-0001-L01")

    def test_los_lotes_salen_en_orden_de_numero(self):
        order = self.make_order()
        second, first = self.make_lot(order, 2, 40), self.make_lot(order, 1, 60)
        self.assertEqual(list(order.lotes.all()), [first, second])

    def test_el_numero_no_se_repite_dentro_de_la_orden(self):
        order = self.make_order()
        self.make_lot(order, 1)
        self.rejects(lambda: Lote.objects.create(orden=order, numero=1, codigo="OP-0001-L99", cantidad=5))

    def test_el_codigo_del_lote_es_unico(self):
        order = self.make_order()
        self.make_lot(order, 1)
        self.rejects(lambda: Lote.objects.create(orden=order, numero=2, codigo="OP-0001-L01", cantidad=5))

    def test_la_cantidad_del_lote_debe_ser_al_menos_uno(self):
        order = self.make_order()
        self.rejects(lambda: self.make_lot(order, 1, 0))

    def test_una_orden_con_lotes_no_se_borra_de_verdad(self):
        order = self.make_order()
        self.make_lot(order)
        with self.assertRaises(ProtectedError):
            order.hard_delete()


class LotSizeModelTests(ModelBase):
    def test_guarda_la_talla_y_el_color_copiados(self):
        lot = self.make_lot(self.make_order())
        variant = self.variant()
        row = LoteTalla.objects.create(lote=lot, variante=variant, talla=variant.talla, color=variant.color, cantidad=20)
        self.assertEqual(list(lot.tallas.all()), [row])
        self.assertEqual((row.talla, row.color), (variant.talla, variant.color))

    def test_la_copia_sobrevive_al_borrado_logico_de_la_variante(self):
        lot = self.make_lot(self.make_order())
        variant = self.variant()
        LoteTalla.objects.create(lote=lot, variante=variant, talla=variant.talla, color=variant.color, cantidad=20)
        variant.delete()
        row = lot.tallas.get()
        self.assertEqual((row.talla, row.color), (variant.talla, variant.color))

    def test_una_variante_no_se_repite_en_el_lote(self):
        lot = self.make_lot(self.make_order())
        variant = self.variant()
        LoteTalla.objects.create(lote=lot, variante=variant, talla=variant.talla, color=variant.color, cantidad=20)
        self.rejects(lambda: LoteTalla.objects.create(
            lote=lot, variante=variant, talla=variant.talla, color=variant.color, cantidad=5,
        ))

    def test_la_cantidad_debe_ser_al_menos_uno(self):
        lot = self.make_lot(self.make_order())
        variant = self.variant()
        self.rejects(lambda: LoteTalla.objects.create(
            lote=lot, variante=variant, talla=variant.talla, color=variant.color, cantidad=0,
        ))
