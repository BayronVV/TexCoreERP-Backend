"""
Pruebas de concurrencia real en facturación sobre PostgreSQL (TE-187):
- Dos ventas simultáneas de las últimas unidades con conexiones/transacciones independientes (solo gana una, sin saldos negativos).
- Verificación de consecutivo FV sin huecos, descuentos, IVA, totales, movimientos `SALIDA_VENTA`, cartera pendiente y reversión por anulación.
- Verificación explícita de que el bloqueo por fila (`SELECT ... FOR UPDATE` en `lock_stock`) está activo.
"""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest import mock
import uuid

from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from django.urls import reverse

from apps.core.testing import client_for, make_user
from apps.finished import catalog as finished_catalog
from apps.finished.models import MovimientoTerminado, StockTerminado
from apps.finished.services import lock_stock
from apps.inventory.models import Consecutivo
from apps.references import catalog as reference_catalog
from apps.references.models import Referencia, Variante
from apps.sales import catalog as sales_catalog
from apps.sales.invoicing import get_sales_panel
from apps.sales.models import Cliente, FacturaVenta, PrecioReferencia, SaldoFinanciero


class ConcurrencyInvoicingTests(TransactionTestCase):
    """Corre fuera de una transacción envolvente para verificar bloqueos reales y atomicidad en PostgreSQL."""

    serialized_rollback = True

    def _setup_last_units_scenario(self, stock_qty=5):
        seller1 = make_user("conc_vend1@t.co", "VENDEDOR")
        seller2 = make_user("conc_vend2@t.co", "VENDEDOR")
        manager = make_user("conc_ger@t.co", "GERENTE")

        ref = Referencia.objects.create(
            codigo="REF-CONC-187",
            nombre="Jean Concurrencia Ventas",
            ajuste="RECTO",
            estado=reference_catalog.ACTIVE,
        )
        variant = Variante.objects.create(referencia=ref, talla="30", color="Azul")
        PrecioReferencia.objects.create(
            referencia=ref,
            costo_fabrica=50_000,
            precio_mayorista=100_000,
            precio_detal=120_000,
        )
        customer = Cliente.objects.create(
            codigo="CLI-CONC-1",
            tipo_documento="NIT",
            documento="901888187",
            nombre="Distribuidora Concurrente S.A.S.",
            tipo=sales_catalog.CLIENT_WHOLESALE,
            ciudad="Medellín",
            direccion="Calle 50 # 10-20",
            telefono="3100001870",
        )
        StockTerminado.objects.create(variante=variant, cantidad=stock_qty)
        return seller1, seller2, manager, variant, customer

    def _sale_payload(self, variant, customer, quantity=4, discount_pct=10):
        return {
            "cliente": customer.id,
            "token": str(uuid.uuid4()),
            "lineas": [{"variante": variant.id, "cantidad": quantity, "descuento_pct": discount_pct}],
        }

    def _assert_single_invoice_and_cancel(self, manager, seller, variant, customer):
        # 4 unidades * 100.000 = 400.000; 10% desc = 40.000 -> base 360.000; IVA 19% = 68.400 -> total 428.400
        self.assertEqual(FacturaVenta.objects.count(), 1)
        invoice = FacturaVenta.objects.get()
        self.assertEqual(invoice.numero, "FV-0001")
        self.assertEqual(Consecutivo.objects.get(clave=sales_catalog.INVOICE_PREFIX).ultimo, 1)
        self.assertEqual((invoice.subtotal, invoice.descuento_total, invoice.base_gravable, invoice.iva_total, invoice.total),
                         (400_000, 40_000, 360_000, 68_400, 428_400))
        self.assertEqual(invoice.valor_a_recaudar, 428_400)
        self.assertEqual(invoice.estado_cobro, sales_catalog.COLLECT_PENDING)

        # Stock quedó en 1 y solo existe 1 movimiento de salida
        self.assertEqual(StockTerminado.objects.get(variante=variant).cantidad, 1)
        out_moves = MovimientoTerminado.objects.filter(variante=variant, tipo=finished_catalog.SALE_EXIT)
        self.assertEqual(out_moves.count(), 1)
        move = out_moves.get()
        self.assertEqual((move.cantidad, move.saldo_antes, move.saldo_despues, move.factura_id), (-4, 5, 1, invoice.id))

        # Cartera y caja: emitida cuenta por cobrar, cero recaudado
        cash_box = SaldoFinanciero.objects.filter(nombre=sales_catalog.CASH_BOX).first()
        self.assertEqual(cash_box.saldo_actual if cash_box else 0, 0)
        self.assertEqual(get_sales_panel()["por_cobrar"], 428_400)

        # Anulación: revierte stock a 5, deja DEVOLUCION_VENTA y conserva FV-0001 sin reutilizar consecutivo
        cancel_res = client_for(manager).post(
            reverse("ventas_factura_anular", args=[invoice.id]),
            {"motivo": "Prueba de anulación tras venta concurrente"},
            format="json",
        )
        self.assertEqual(cancel_res.status_code, 200, cancel_res.content)
        self.assertEqual(StockTerminado.objects.get(variante=variant).cantidad, 5)
        ret_move = MovimientoTerminado.objects.get(variante=variant, tipo=finished_catalog.SALE_RETURN)
        self.assertEqual((ret_move.cantidad, ret_move.saldo_antes, ret_move.saldo_despues, ret_move.factura_id), (4, 1, 5, invoice.id))
        invoice.refresh_from_db()
        self.assertEqual(invoice.estado, sales_catalog.STATUS_CANCELLED)
        self.assertEqual(get_sales_panel()["por_cobrar"], 0)

        # Nueva factura tras anular toma FV-0002 (sin huecos ni reutilización de FV-0001)
        next_res = client_for(seller).post(
            reverse("ventas_facturas"),
            self._sale_payload(variant, customer, quantity=1, discount_pct=0),
            format="json",
        )
        self.assertEqual(next_res.status_code, 201, next_res.content)
        self.assertEqual(next_res.json()["numero"], "FV-0002")

    @unittest.skipUnless(
        connection.vendor == "postgresql",
        "La concurrencia multi-hilo con SELECT ... FOR UPDATE por fila se verifica sobre PostgreSQL.",
    )
    def test_te187_concurrencia_postgresql_dos_ventas_ultimas_unidades(self):
        seller1, seller2, manager, variant, customer = self._setup_last_units_scenario(stock_qty=5)
        barrier = threading.Barrier(2)
        url = reverse("ventas_facturas")

        def send_sale(user):
            try:
                barrier.wait(timeout=5)
                client = client_for(user)
                response = client.post(url, self._sale_payload(variant, customer, quantity=4, discount_pct=10), format="json")
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(send_sale, seller1)
            f2 = pool.submit(send_sale, seller2)
            statuses = [f1.result(timeout=15), f2.result(timeout=15)]

        self.assertEqual(sorted(statuses), [201, 400], statuses)
        self._assert_single_invoice_and_cancel(manager, seller1, variant, customer)

    def test_te187_facturacion_secuencial_montos_cartera_y_anulacion(self):
        seller1, seller2, manager, variant, customer = self._setup_last_units_scenario(stock_qty=5)
        url = reverse("ventas_facturas")

        first = client_for(seller1).post(url, self._sale_payload(variant, customer, quantity=4, discount_pct=10), format="json")
        self.assertEqual(first.status_code, 201, first.content)
        second = client_for(seller2).post(url, self._sale_payload(variant, customer, quantity=4, discount_pct=10), format="json")
        self.assertEqual(second.status_code, 400, second.content)

        self._assert_single_invoice_and_cancel(manager, seller1, variant, customer)

    def test_te187_prueba_concurrencia_detecta_ausencia_de_bloqueo(self):
        """Si se retirara `select_for_update()` de `lock_stock`, esta verificación falla explícitamente."""
        _, _, _, variant, _ = self._setup_last_units_scenario(stock_qty=5)
        with transaction.atomic():
            if connection.vendor == "postgresql":
                sql = str(StockTerminado.objects.select_for_update().filter(variante_id=variant.id).query)
                self.assertIn("FOR UPDATE", sql)

            original_qs = StockTerminado.objects
            with mock.patch.object(
                original_qs,
                "select_for_update",
                wraps=original_qs.select_for_update,
            ) as spy_lock:
                locked = lock_stock([variant.id])
        self.assertEqual(spy_lock.call_count, 1)
        self.assertEqual(locked[variant.id].cantidad, 5)
