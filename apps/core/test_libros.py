"""Libros de solo inserción (TE-188): los movimientos de inventario, producto terminado y cartera no se editan ni se borran.

- En cualquier base protege el modelo (`AppendOnlyModel`): guardar de nuevo, borrar (lógica o físicamente) o actualizar en bloque
  lanzan `LedgerIsAppendOnly`, que es un `IntegrityError`.
- En PostgreSQL protege además un trigger (migración `sales.0005`): frena el SQL directo y el vaciado de la tabla; solo el reinicio
  de la demostración puede vaciarla, con `texcore.permitir_reinicio` activo en su transacción.
- Las reversiones (anular una orden de salida o una factura, registrar una devolución) dejan un movimiento nuevo: lo prueban
  `apps/inventory/tests.py`, `apps/sales/test_ventas.py` y `apps/shipping/test_cartera_guias.py`, que siguen pasando con esta regla.
"""
import unittest
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase

from apps.core.models import AppendOnlyQuerySet, LedgerIsAppendOnly
from apps.finished.models import MovimientoTerminado
from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Movimiento, Producto
from apps.sales.models import MovimientoCartera


def make_movement(code="LIB-1"):
    product = Producto.objects.create(
        codigo=code, nombre=f"Denim {code}", tipo=inventory_catalog.RAW_MATERIAL, categoria=inventory_catalog.CAT_FABRIC,
        unidad="m", stock_actual=Decimal("10.00"),
    )
    return Movimiento.objects.create(
        producto=product, tipo=inventory_catalog.ENTRY, motivo=inventory_catalog.REASON_PURCHASE, cantidad=Decimal("10.00"),
        stock_antes=Decimal("0.00"), stock_despues=Decimal("10.00"), fecha="2026-11-28",
    )


class LibrosSoloInsercionTests(TestCase):
    def test_los_tres_libros_son_de_solo_insercion(self):
        for model in (Movimiento, MovimientoTerminado, MovimientoCartera):
            with self.subTest(model=model.__name__):
                self.assertIsInstance(model.objects.none(), AppendOnlyQuerySet)
                self.assertIsInstance(model.all_objects.none(), AppendOnlyQuerySet)
        self.assertTrue(issubclass(LedgerIsAppendOnly, IntegrityError))  # la API lo responde como 409

    def test_un_movimiento_guardado_no_se_vuelve_a_guardar(self):
        movement = make_movement()
        movement.observaciones = "cambiado"
        with self.assertRaises(LedgerIsAppendOnly):
            movement.save()
        movement.refresh_from_db()
        self.assertEqual(movement.observaciones, "")

    def test_no_se_borra_ni_logica_ni_fisicamente(self):
        movement = make_movement()
        for action in (movement.delete, movement.hard_delete, movement.restore):
            with self.subTest(action=action.__name__), self.assertRaises(LedgerIsAppendOnly):
                action()
        self.assertTrue(Movimiento.objects.filter(pk=movement.pk).exists())

    def test_no_se_actualiza_ni_borra_en_bloque(self):
        movement = make_movement()
        rows = Movimiento.objects.filter(pk=movement.pk)
        for action in (lambda: rows.update(cantidad=1), rows.delete, rows.hard_delete,
                       lambda: Movimiento.all_objects.filter(pk=movement.pk).update(cantidad=1)):
            with self.assertRaises(LedgerIsAppendOnly):
                action()
        movement.refresh_from_db()
        self.assertEqual(movement.cantidad, Decimal("10.00"))

    def test_la_regla_del_libro_de_cartera_esta_en_la_base(self):
        names = {constraint.name for constraint in MovimientoCartera._meta.constraints}
        self.assertTrue({"ck_cartera_movimiento_saldo", "ck_cartera_movimiento_monto"} <= names)
        with connection.cursor() as cursor:
            in_db = connection.introspection.get_constraints(cursor, MovimientoCartera._meta.db_table)
        self.assertTrue({"ck_cartera_movimiento_saldo", "ck_cartera_movimiento_monto"} <= set(in_db))


@unittest.skipUnless(connection.vendor == "postgresql", "los triggers solo existen en PostgreSQL")
class TriggersPostgresTests(TransactionTestCase):
    """El trigger frena lo que el modelo no ve: `UPDATE`/`DELETE` en SQL directo y el vaciado de la tabla."""

    serialized_rollback = True

    def raw(self, sql, params=()):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, params)

    def test_el_sql_directo_no_edita_ni_borra_un_movimiento(self):
        movement = make_movement("LIB-PG")  # los tres libros comparten la misma función de trigger (ver la prueba de instalación)
        with self.assertRaises(IntegrityError):
            self.raw("UPDATE inventario_movimiento SET cantidad = 1 WHERE id = %s", [movement.pk])
        with self.assertRaises(IntegrityError):
            self.raw("UPDATE inventario_movimiento SET deleted_at = now() WHERE id = %s", [movement.pk])  # ni el borrado lógico
        with self.assertRaises(IntegrityError):
            self.raw("DELETE FROM inventario_movimiento WHERE id = %s", [movement.pk])
        self.assertTrue(Movimiento.objects.filter(pk=movement.pk).exists())

    def test_los_triggers_estan_instalados_en_los_tres_libros(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT t.tgisinternal AND t.tgname LIKE %s", [r"%\_solo\_insercion"]
            )
            row_triggers = {table for table, _ in cursor.fetchall()}
            cursor.execute(
                "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT t.tgisinternal AND t.tgname LIKE %s", [r"%\_sin\_vaciar"]
            )
            truncate_triggers = {table for (table,) in cursor.fetchall()}
        expected = {"inventario_movimiento", "terminado_movimiento", "ventas_movimiento_cartera"}
        self.assertEqual(row_triggers, expected)
        self.assertEqual(truncate_triggers, expected)

    def test_el_permiso_del_reinicio_deja_borrar_dentro_de_su_transaccion(self):
        movement = make_movement("LIB-OK")
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL texcore.permitir_reinicio = 'on'")
            cursor.execute("DELETE FROM inventario_movimiento WHERE id = %s", [movement.pk])
        self.assertFalse(Movimiento.all_objects.filter(pk=movement.pk).exists())
        # el permiso no sobrevive a la transacción
        other = make_movement("LIB-OK2")
        with self.assertRaises(IntegrityError):
            self.raw("DELETE FROM inventario_movimiento WHERE id = %s", [other.pk])
