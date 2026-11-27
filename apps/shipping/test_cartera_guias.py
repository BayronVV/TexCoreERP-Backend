"""HU 7.5 (TE-173): coherencia entre cartera y guías de envío. El pago exige la guía entregada y la devolución, la guía devuelta."""
from django.urls import reverse

from apps.finished import catalog as finished_catalog
from apps.finished.models import MovimientoTerminado
from apps.sales import catalog as sales_catalog
from apps.sales.models import FacturaVenta, MovimientoCartera, SaldoFinanciero

from . import catalog
from .test_envios import ShippingBase


class CrossRuleTests(ShippingBase):
    def returned_guide(self, n=1):
        invoice, guide = self.invoice_with_guide(n)
        self.dispatch([guide])
        self.assertEqual(self.state(guide, catalog.RETURNED, "El destinatario rechazó el paquete").status_code, 200)
        guide.refresh_from_db()
        return invoice, guide

    def confirm(self, invoice, client=None, **body):
        return (client or self.manager).post(reverse("ventas_factura_conciliar", args=[invoice.id]), body, format="json")

    def test_pago_con_guia_entregada_suma_a_la_caja(self):
        invoice, guide = self.invoice_with_guide()
        self.dispatch([guide])
        self.state(guide, catalog.DELIVERED)
        response = self.confirm(invoice)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["estado_cobro"], sales_catalog.COLLECT_PAID)
        self.assertEqual(SaldoFinanciero.objects.get().saldo_actual, invoice.valor_a_recaudar)

    def test_pago_con_guia_en_transito_se_rechaza_y_dice_el_estado(self):
        invoice, guide = self.invoice_with_guide()
        self.dispatch([guide])
        response = self.confirm(invoice)
        self.assertEqual(response.status_code, 400)
        self.assertIn("en tránsito", response.content.decode())
        invoice.refresh_from_db()
        self.assertEqual(invoice.estado_cobro, sales_catalog.COLLECT_PENDING)
        self.assertFalse(MovimientoCartera.objects.filter(factura=invoice).exists())

    def test_pago_con_guia_por_despachar_con_novedad_o_devuelta_se_rechaza(self):
        pending, _ = self.invoice_with_guide(1)
        incident, g2 = self.invoice_with_guide(2)
        returned, _ = self.returned_guide(3)
        self.dispatch([g2])
        self.state(g2, catalog.INCIDENT, "Dirección errada, no localizan al cliente")
        for invoice in (pending, incident, returned):
            self.assertEqual(self.confirm(invoice).status_code, 400, invoice.numero)

    def test_con_guia_no_basta_una_nota_para_saltarse_la_regla(self):
        invoice, guide = self.invoice_with_guide()
        self.dispatch([guide])
        self.assertEqual(self.confirm(invoice, nota="El cliente dice que ya pagó al mensajero").status_code, 400)

    def test_devolucion_con_guia_en_transito_se_rechaza_y_el_stock_no_cambia(self):
        invoice, guide = self.invoice_with_guide()
        self.dispatch([guide])
        stock = self.stock(self.v30)
        response = self.store.post(reverse("envios_guia_devolucion", args=[guide.id]), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stock(self.v30), stock)
        self.assertFalse(MovimientoTerminado.objects.filter(factura=invoice, tipo=finished_catalog.SALE_RETURN).exists())

    def test_devolucion_con_guia_devuelta_reingresa_una_vez_y_luego_no_se_cobra(self):
        invoice, guide = self.returned_guide()
        stock = self.stock(self.v30)
        self.assertEqual(self.store.post(reverse("envios_guia_devolucion", args=[guide.id]), {}, format="json").status_code, 200)
        self.assertEqual(self.stock(self.v30), stock + 1)
        self.assertEqual(self.confirm(invoice).status_code, 400)  # ya está en devolución
        self.assertEqual(MovimientoTerminado.objects.filter(factura=invoice, tipo=finished_catalog.SALE_RETURN).count(), 1)

    def test_el_vendedor_no_registra_la_devolucion(self):
        _, guide = self.returned_guide()
        self.assertEqual(self.seller.post(reverse("envios_guia_devolucion", args=[guide.id]), {}, format="json").status_code, 403)

    def test_cada_factura_indica_la_accion_de_cartera_que_admite(self):
        delivered, g1 = self.invoice_with_guide(1)
        transit, g2 = self.invoice_with_guide(2)
        returned, _ = self.returned_guide(3)
        self.dispatch([g1, g2])
        self.state(g1, catalog.DELIVERED)
        no_guide = FacturaVenta.objects.get(pk=self.sale().json()["id"])
        expected = {
            delivered.id: sales_catalog.CARTERA_PAY, transit.id: sales_catalog.CARTERA_WAIT,
            returned.id: sales_catalog.CARTERA_RETURN, no_guide.id: sales_catalog.CARTERA_PAY_NO_GUIDE,
        }
        rows = {row["id"]: row["accion_cartera"] for row in self.seller.get(reverse("ventas_facturas")).json()}
        for invoice_id, action in expected.items():
            self.assertEqual(rows[invoice_id], action)
        self.confirm(delivered)
        self.assertEqual(self.seller.get(reverse("ventas_factura", args=[delivered.id])).json()["accion_cartera"], sales_catalog.CARTERA_NONE)
