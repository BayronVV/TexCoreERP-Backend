"""Ventas y facturación (HU 7.1 / RF23): clientes, precios, factura POS interna con descuento de inventario, anulación y PDF."""
import uuid

from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.finished import catalog as finished_catalog
from apps.finished.models import MovimientoTerminado
from apps.finished.test_terminado import FinishedBase
from apps.inventory.models import Consecutivo
from apps.inventory.tests import client_for, make_user

from . import catalog
from .invoicing import line_amounts, round_half_up
from .models import Cliente, DetalleVenta, FacturaVenta, MovimientoCartera, PrecioReferencia, SaldoFinanciero

COST, WHOLESALE, RETAIL = 47_000, 68_000, 89_900


class SalesBase(FinishedBase):
    """Stock inicial: v30 = 20, v32 = 20, v34 = 10. La referencia cuesta 47.000, mayorista 68.000 y detal 89.900."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.enter().status_code, 201)
        self.manager = self.viewer  # el Gerente: consulta, administra precios y anula
        PrecioReferencia.objects.create(referencia_id=self.ref["id"], costo_fabrica=COST, precio_mayorista=WHOLESALE, precio_detal=RETAIL)
        self.wholesale = self.client_of("Moda Joven", "901234567", catalog.CLIENT_WHOLESALE)
        self.retail = self.client_of("Carolina Pérez", "1032456789", catalog.CLIENT_DETAL, kind="CC")
        self.distributor = self.client_of("Distribuciones El Jean", "900123456", catalog.CLIENT_DISTRIBUTOR)

    def client_of(self, name, document, client_type, kind="NIT"):
        response = self.seller.post(reverse("ventas_clientes"), {
            "tipo_documento": kind, "documento": document, "nombre": name, "tipo": client_type, "ciudad": "Medellín",
            "direccion": "Calle 10 # 20-30", "telefono": "3105551234",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return Cliente.objects.get(pk=response.json()["id"])

    def sell(self, rows, customer=None, client=None, token=None, **extra):
        """`rows` son `(variante, cantidad, descuento_pct)`."""
        body = {
            "cliente": (customer or self.wholesale).id, "token": str(uuid.uuid4()) if token is None else str(token),
            "lineas": [{"variante": variant.id, "cantidad": quantity, "descuento_pct": discount} for variant, quantity, discount in rows],
        }
        body.update(extra)
        return (client or self.seller).post(reverse("ventas_facturas"), body, format="json")

    def book_sum(self, variant):
        return sum(MovimientoTerminado.objects.filter(variante=variant).values_list("cantidad", flat=True))


class AmountTests(SalesBase):
    def test_redondeo_mitad_hacia_arriba(self):
        self.assertEqual([round_half_up(5, 2), round_half_up(1, 3), round_half_up(7, 2), round_half_up(4, 2), round_half_up(0, 5)], [3, 0, 4, 2, 0])

    def test_montos_de_una_linea(self):
        self.assertEqual(line_amounts(68_000, 2, 10), {"subtotal": 136_000, "descuento": 13_600, "base": 122_400, "iva": 23_256, "total": 145_656})
        self.assertEqual(line_amounts(89_900, 1, 0), {"subtotal": 89_900, "descuento": 0, "base": 89_900, "iva": 17_081, "total": 106_981})

    def test_el_total_de_cada_linea_siempre_es_base_mas_iva(self):
        for price in (33_333, 68_000, 89_900, 99_999):
            for quantity in (1, 3, 7):
                for discount in (0, 3, 7, 15, 20):
                    amounts = line_amounts(price, quantity, discount)
                    self.assertEqual(amounts["base"], amounts["subtotal"] - amounts["descuento"])
                    self.assertEqual(amounts["total"], amounts["base"] + amounts["iva"])


class IssueTests(SalesBase):
    def test_emite_la_factura_calcula_los_montos_y_descuenta_el_stock(self):
        response = self.sell([(self.v30, 2, 10)])
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["numero"], body["estado"], body["modalidad_pago"], body["estado_cobro"]), ("FV-0001", "EMITIDA", "CONTRAENTREGA", "POR_COBRAR"))
        self.assertEqual((body["subtotal"], body["descuento_total"], body["base_gravable"], body["iva_tarifa"], body["iva_total"], body["total"]),
                         (136_000, 13_600, 122_400, 19, 23_256, 145_656))
        self.assertEqual(body["valor_a_recaudar"], body["total"])
        self.assertEqual(body["aviso"], "Factura POS interna. No es factura electrónica.")
        line = body["lineas"][0]
        self.assertEqual((line["talla"], line["cantidad"], line["precio_unitario"], line["descuento_pct"]), ("30", 2, WHOLESALE, 10))
        self.assertEqual(self.stock(self.v30), 18)

    def test_deja_un_movimiento_de_salida_por_variante(self):
        self.sell([(self.v30, 2, 0), (self.v34, 3, 0)])
        moves = list(MovimientoTerminado.objects.filter(tipo=finished_catalog.SALE_EXIT).order_by("variante_id"))
        self.assertEqual([(m.variante_id, m.cantidad, m.saldo_antes, m.saldo_despues) for m in moves], [(self.v30.id, -2, 20, 18), (self.v34.id, -3, 10, 7)])
        self.assertTrue(all(m.factura.numero == "FV-0001" and m.usuario_id for m in moves))
        rows = self.seller.get(reverse("terminado_movimientos"), {"tipo": "SALIDA_VENTA"}).json()
        self.assertEqual({row["factura_numero"] for row in rows}, {"FV-0001"})

    def test_el_cliente_de_detal_paga_el_precio_de_detal(self):
        body = self.sell([(self.v30, 1, 0)], customer=self.retail).json()
        self.assertEqual((body["lineas"][0]["precio_unitario"], body["total"]), (RETAIL, 106_981))
        self.assertEqual(self.sell([(self.v32, 1, 0)], customer=self.distributor).json()["lineas"][0]["precio_unitario"], WHOLESALE)

    def test_la_factura_es_la_suma_de_sus_lineas(self):
        body = self.sell([(self.v30, 3, 5), (self.v32, 1, 15), (self.v34, 2, 0)]).json()
        for key in ("subtotal", "descuento", "base", "iva", "total"):
            field = {"subtotal": "subtotal", "descuento": "descuento_total", "base": "base_gravable", "iva": "iva_total", "total": "total"}[key]
            self.assertEqual(body[field], sum(line[key] for line in body["lineas"]), key)
        self.assertEqual(body["unidades"], 6)

    def test_el_saldo_sigue_siendo_la_suma_del_libro(self):
        invoice_id = self.sell([(self.v30, 5, 0), (self.v32, 4, 0)]).json()["id"]
        self.manager.post(reverse("ventas_factura_anular", args=[invoice_id]), {"motivo": "El cliente canceló el pedido"}, format="json")
        self.sell([(self.v30, 1, 0)])
        for variant in (self.v30, self.v32, self.v34):
            self.assertEqual(self.stock(variant), self.book_sum(variant), variant)

    def test_sin_stock_responde_400_con_todas_las_faltantes_y_no_guarda_nada(self):
        before = MovimientoTerminado.objects.count()
        response = self.sell([(self.v30, 25, 0), (self.v32, 5, 0), (self.v34, 11, 0)])
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertIn("Stock insuficiente", body["lineas"][0])
        self.assertEqual({(int(row["variante"]), int(row["disponible"]), int(row["pedido"])) for row in body["faltantes"]},
                         {(self.v30.id, 20, 25), (self.v34.id, 10, 11)})  # las dos faltantes juntas; la que sí alcanza no aparece
        self.assertEqual(FacturaVenta.objects.count(), 0)
        self.assertEqual(MovimientoTerminado.objects.count(), before)
        self.assertEqual((self.stock(self.v30), self.stock(self.v32), self.stock(self.v34)), (20, 20, 10))
        self.assertEqual(Consecutivo.objects.filter(clave=catalog.INVOICE_PREFIX).count(), 0)

    def test_las_ultimas_unidades_son_del_primero(self):
        self.assertEqual(self.sell([(self.v34, 10, 0)]).status_code, 201)
        second = self.sell([(self.v34, 1, 0)], client=client_for(make_user("vendedor2@t.co", "VENDEDOR")))
        self.assertEqual(second.status_code, 400)
        self.assertEqual(self.stock(self.v34), 0)
        self.assertEqual(FacturaVenta.objects.count(), 1)

    def test_la_numeracion_no_tiene_huecos_tras_un_error(self):
        self.assertEqual(self.sell([(self.v30, 99, 0)]).status_code, 400)
        self.assertEqual(self.sell([(self.v30, 1, 0)]).json()["numero"], "FV-0001")
        self.assertEqual(self.sell([(self.v30, 1, 0)]).json()["numero"], "FV-0002")

    def test_cantidades_variantes_y_cliente_invalidos(self):
        for quantity in (0, -1, 1.5, "x", None, True):
            body = {"cliente": self.wholesale.id, "token": str(uuid.uuid4()), "lineas": [{"variante": self.v30.id, "cantidad": quantity}]}
            self.assertEqual(self.seller.post(reverse("ventas_facturas"), body, format="json").status_code, 400, quantity)
        self.assertEqual(self.sell([(self.v30, 1, 0), (self.v30, 1, 0)]).status_code, 400)  # repetida
        self.assertEqual(self.sell([]).status_code, 400)
        self.assertEqual(self.seller.post(reverse("ventas_facturas"), {
            "cliente": self.wholesale.id, "token": str(uuid.uuid4()), "lineas": [{"variante": 999999, "cantidad": 1}]}, format="json").status_code, 400)
        self.assertEqual(self.seller.post(reverse("ventas_facturas"), {
            "cliente": 999999, "token": str(uuid.uuid4()), "lineas": [{"variante": self.v30.id, "cantidad": 1}]}, format="json").status_code, 400)
        Cliente.objects.filter(pk=self.wholesale.pk).update(activo=False)
        self.assertEqual(self.sell([(self.v30, 1, 0)]).status_code, 400)  # un cliente desactivado no compra
        self.assertEqual(FacturaVenta.objects.count(), 0)

    def test_una_referencia_sin_precio_no_se_vende(self):
        PrecioReferencia.objects.all().hard_delete()
        response = self.sell([(self.v30, 1, 0)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("Falta el precio", response.json()["lineas"][0])
        self.assertEqual(self.stock(self.v30), 20)

    def test_transportadora_y_guia_quedan_en_la_factura(self):
        body = self.sell([(self.v30, 1, 0)], transportadora="INTERRAPIDISIMO", numero_guia="700123456789", observaciones="Entregar en portería").json()
        self.assertEqual((body["transportadora"], body["transportadora_nombre"], body["numero_guia"]), ("INTERRAPIDISIMO", "Interrapidísimo", "700123456789"))
        self.assertEqual(self.sell([(self.v30, 1, 0)]).json()["transportadora_nombre"], "")  # opcionales: la guía se asigna después
        self.assertEqual(self.sell([(self.v30, 1, 0)], transportadora="PIGEON").status_code, 400)


class DiscountRuleTests(SalesBase):
    def test_el_descuento_maximo_depende_del_tipo_de_cliente(self):
        self.assertEqual(self.sell([(self.v30, 1, 6)], customer=self.retail).status_code, 400)  # el detal llega a 5 %
        self.assertEqual(self.sell([(self.v30, 1, 5)], customer=self.retail).status_code, 201)
        self.assertEqual(self.sell([(self.v30, 1, 16)], customer=self.wholesale).status_code, 400)  # el mayorista a 15 %
        self.assertEqual(self.sell([(self.v30, 1, 15)], customer=self.wholesale).status_code, 201)
        response = self.sell([(self.v32, 1, 21)], customer=self.distributor)  # el distribuidor a 20 %
        self.assertEqual(response.status_code, 400)
        self.assertIn("descuento máximo", response.json()["lineas"][0])
        self.assertEqual(self.sell([(self.v32, 1, 20)], customer=self.distributor).status_code, 201)

    def test_no_se_vende_por_debajo_del_costo_de_fabrica(self):
        PrecioReferencia.objects.update(precio_mayorista=48_000, precio_detal=89_900)  # 5 % queda en 45.600, bajo el costo de 47.000
        response = self.sell([(self.v30, 1, 5)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("costo de fábrica", response.json()["lineas"][0])
        self.assertIn("$47.000", response.json()["lineas"][0])
        self.assertEqual(self.stock(self.v30), 20)
        self.assertEqual(self.sell([(self.v30, 1, 2)]).status_code, 201)  # 47.040 todavía cubre el costo

    def test_el_costo_exacto_todavia_se_permite_y_un_peso_menos_no(self):
        PrecioReferencia.objects.update(precio_mayorista=50_000)
        self.assertEqual(self.sell([(self.v30, 1, 6)]).status_code, 201)  # 50.000 × 0,94 = 47.000, exactamente el costo
        self.assertEqual(self.sell([(self.v30, 1, 7)]).status_code, 400)  # 46.500 queda bajo el costo
        PrecioReferencia.objects.update(precio_mayorista=47_000)
        self.assertEqual(self.sell([(self.v30, 1, 0)]).status_code, 201)  # sin descuento, el precio es el costo
        self.assertEqual(self.sell([(self.v30, 1, 1)]).status_code, 400)

    def test_el_descuento_debe_ser_un_entero_entre_0_y_100(self):
        for value in (-1, 101, 2.5, "x"):
            body = {"cliente": self.wholesale.id, "token": str(uuid.uuid4()), "lineas": [{"variante": self.v30.id, "cantidad": 1, "descuento_pct": value}]}
            self.assertEqual(self.seller.post(reverse("ventas_facturas"), body, format="json").status_code, 400, value)


class TokenTests(SalesBase):
    def test_el_mismo_token_no_factura_dos_veces(self):
        token = uuid.uuid4()
        first = self.sell([(self.v30, 2, 0)], token=token)
        self.assertEqual(first.status_code, 201)
        second = self.sell([(self.v30, 2, 0)], token=token)  # doble clic
        self.assertEqual(second.status_code, 409)
        self.assertEqual((second.json()["numero"], second.json()["factura"]), ("FV-0001", str(first.json()["id"])))
        self.assertEqual(self.stock(self.v30), 18)
        self.assertEqual(FacturaVenta.objects.count(), 1)

    def test_token_invalido(self):
        for token in ("no-es-un-uuid", ""):
            self.assertEqual(self.sell([(self.v30, 1, 0)], token=token).status_code, 400)

    def test_la_base_impide_repetir_el_token_o_totales_que_no_cuadran(self):
        invoice = FacturaVenta.objects.get(pk=self.sell([(self.v30, 1, 0)]).json()["id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            FacturaVenta.objects.filter(pk=invoice.pk).update(total=invoice.total + 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FacturaVenta.objects.filter(pk=invoice.pk).update(base_gravable=invoice.base_gravable + 1)
        line = DetalleVenta.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            DetalleVenta.objects.filter(pk=line.pk).update(iva=line.iva + 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DetalleVenta.objects.filter(pk=line.pk).update(descuento_pct=101)


class CancelTests(SalesBase):
    def cancel(self, invoice_id, reason="El cliente canceló el pedido", client=None):
        return (client or self.manager).post(reverse("ventas_factura_anular", args=[invoice_id]), {"motivo": reason}, format="json")

    def test_anular_devuelve_las_unidades_y_conserva_la_factura(self):
        invoice_id = self.sell([(self.v30, 5, 0), (self.v34, 4, 0)]).json()["id"]
        response = self.cancel(invoice_id)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["numero"], body["estado"], body["motivo_anulacion"]), ("FV-0001", "ANULADA", "El cliente canceló el pedido"))
        self.assertTrue(body["anulada_por_nombre"] and body["anulada_en"])
        self.assertEqual((self.stock(self.v30), self.stock(self.v34)), (20, 10))
        moves = MovimientoTerminado.objects.filter(tipo=finished_catalog.SALE_RETURN).order_by("variante_id")
        self.assertEqual([(m.cantidad, m.saldo_antes, m.saldo_despues) for m in moves], [(5, 15, 20), (4, 6, 10)])
        self.assertEqual(FacturaVenta.objects.count(), 1)
        self.assertEqual(self.sell([(self.v30, 1, 0)]).json()["numero"], "FV-0002")  # el número anulado no se reutiliza

    def test_no_se_anula_dos_veces(self):
        invoice_id = self.sell([(self.v30, 5, 0)]).json()["id"]
        self.assertEqual(self.cancel(invoice_id).status_code, 200)
        self.assertEqual(self.cancel(invoice_id).status_code, 409)
        self.assertEqual(self.stock(self.v30), 20)  # no se devolvió dos veces

    def test_el_motivo_es_obligatorio(self):
        invoice_id = self.sell([(self.v30, 1, 0)]).json()["id"]
        for reason in ("", "   ", "corto"):
            self.assertEqual(self.cancel(invoice_id, reason).status_code, 400, repr(reason))
        self.assertEqual(FacturaVenta.objects.get().estado, "EMITIDA")
        self.assertEqual(self.cancel(999999).status_code, 404)

    def test_solo_anulan_quienes_tienen_el_permiso(self):
        invoice_id = self.sell([(self.v30, 1, 0)]).json()["id"]
        for client in (self.seller, self.secretary, self.store, self.finisher):
            self.assertEqual(self.cancel(invoice_id, client=client).status_code, 403)
        self.assertEqual(self.cancel(invoice_id, client=self.admin).status_code, 200)


class ReadAndPermissionTests(SalesBase):
    def test_las_facturas_no_se_editan_ni_se_borran(self):
        invoice_id = self.sell([(self.v30, 1, 0)]).json()["id"]
        url = reverse("ventas_factura", args=[invoice_id])
        for method in ("put", "patch", "delete"):
            self.assertIn(getattr(self.seller, method)(url).status_code, (403, 405), method)
        self.assertEqual(FacturaVenta.objects.count(), 1)
        self.assertEqual(self.viewer.get(url).status_code, 200)
        self.assertEqual(self.viewer.get(reverse("ventas_factura", args=[9999])).status_code, 404)

    def test_permisos_por_rol_al_facturar(self):
        for client in (self.viewer, self.secretary, self.store, self.finisher):
            self.assertEqual(self.sell([(self.v30, 1, 0)], client=client).status_code, 403)  # el Gerente solo consulta
        self.assertEqual(FacturaVenta.objects.count(), 0)
        self.assertEqual(self.sell([(self.v30, 1, 0)], client=self.admin).status_code, 201)
        self.assertEqual(self.sell([(self.v30, 1, 0)], client=self.seller).status_code, 201)
        for client in (self.viewer, self.seller):
            self.assertEqual(client.get(reverse("ventas_facturas")).status_code, 200)
            self.assertEqual(client.get(reverse("ventas_metadatos")).status_code, 200)
        for client in (self.store, self.finisher, self.secretary):
            self.assertEqual(client.get(reverse("ventas_facturas")).status_code, 403)

    def test_lista_con_filtros(self):
        self.sell([(self.v30, 1, 0)], customer=self.wholesale)
        invoice_id = self.sell([(self.v32, 1, 0)], customer=self.retail).json()["id"]
        self.manager.post(reverse("ventas_factura_anular", args=[invoice_id]), {"motivo": "Dirección errada del cliente"}, format="json")
        url = reverse("ventas_facturas")
        self.assertEqual([row["numero"] for row in self.viewer.get(url).json()], ["FV-0002", "FV-0001"])
        self.assertEqual(len(self.viewer.get(url, {"estado": "ANULADA"}).json()), 1)
        self.assertEqual(len(self.viewer.get(url, {"cliente": self.wholesale.id}).json()), 1)
        self.assertEqual(len(self.viewer.get(url, {"q": "Carolina"}).json()), 1)
        self.assertEqual(len(self.viewer.get(url, {"q": "FV-0001"}).json()), 1)
        self.assertEqual(len(self.viewer.get(url, {"q": "901234567"}).json()), 1)
        self.assertEqual(len(self.viewer.get(url, {"desde": "2999-01-01"}).json()), 0)
        self.assertEqual(self.viewer.get(url, {"cliente": "x"}).status_code, 400)

    def test_las_consultas_no_crecen_con_las_filas(self):
        self.sell([(self.v30, 1, 0)])
        self.viewer.get(reverse("ventas_facturas"))
        with CaptureQueriesContext(connection) as small:
            self.viewer.get(reverse("ventas_facturas"))
        self.sell([(self.v30, 1, 0), (self.v32, 1, 0), (self.v34, 1, 0)])
        self.sell([(self.v30, 1, 0), (self.v32, 1, 0)])
        with CaptureQueriesContext(connection) as big:
            rows = self.viewer.get(reverse("ventas_facturas")).json()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(big), len(small))

    def test_pdf_de_la_factura(self):
        invoice_id = self.sell([(self.v30, 2, 5), (self.v32, 1, 0)], transportadora="ENVIA").json()["id"]
        response = self.viewer.get(reverse("ventas_factura_pdf", args=[invoice_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn('filename="FV-0001.pdf"', response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF") and len(response.content) > 1000)
        self.manager.post(reverse("ventas_factura_anular", args=[invoice_id]), {"motivo": "El cliente canceló el pedido"}, format="json")
        self.assertEqual(self.viewer.get(reverse("ventas_factura_pdf", args=[invoice_id])).status_code, 200)  # anulada también se descarga
        self.assertEqual(self.viewer.get(reverse("ventas_factura_pdf", args=[9999])).status_code, 404)
        self.assertEqual(self.store.get(reverse("ventas_factura_pdf", args=[invoice_id])).status_code, 403)

    def test_metadatos(self):
        data = self.seller.get(reverse("ventas_metadatos")).json()
        self.assertEqual(data["iva_tarifa"], 19)
        self.assertEqual({row["codigo"]: (row["lista_precios"], row["descuento_maximo"]) for row in data["tipos_cliente"]},
                         {"DETAL": ("detal", 5), "MAYORISTA": ("mayorista", 15), "DISTRIBUIDOR": ("mayorista", 20)})
        self.assertEqual([row["codigo"] for row in data["transportadoras"]], ["INTERRAPIDISIMO", "ENVIA", "OTRA"])
        self.assertIn("No es factura electrónica", data["aviso"])


class ClientTests(SalesBase):
    def test_crea_un_cliente_con_su_codigo(self):
        self.assertEqual([c.codigo for c in Cliente.objects.order_by("id")], ["CLI-0001", "CLI-0002", "CLI-0003"])
        response = self.seller.post(reverse("ventas_clientes"), {
            "tipo_documento": "NIT", "documento": "800111222", "dv": "5", "nombre": "Almacén Centro", "tipo": "MAYORISTA", "ciudad": "Bogotá",
            "direccion": "Carrera 7 # 12-34", "telefono": "601 555 1234", "correo": "centro@ejemplo.co",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((response.json()["codigo"], response.json()["tipo_nombre"], response.json()["descuento_maximo"]), ("CLI-0004", "Mayorista", 15))

    def test_valida_documento_nombre_telefono_y_duplicados(self):
        base = {"tipo_documento": "CC", "documento": "52123456", "nombre": "Ana Gómez", "tipo": "DETAL", "ciudad": "Cúcuta",
                "direccion": "Calle 1 # 2-3", "telefono": "3001234567"}
        url = reverse("ventas_clientes")
        for override in ({"documento": "12.345"}, {"documento": "abc12345"}, {"nombre": "Al"}, {"telefono": "abc"}, {"tipo": "VIP"},
                         {"tipo_documento": "CC", "dv": "3"}, {"documento": "1032456789"}):  # el último ya existe
            self.assertEqual(self.seller.post(url, {**base, **override}, format="json").status_code, 400, override)
        self.assertEqual(self.seller.post(url, base, format="json").status_code, 201)

    def test_modifica_y_desactiva_sin_borrar(self):
        url = reverse("ventas_cliente", args=[self.retail.id])
        self.assertEqual(self.seller.patch(url, {"ciudad": "Bogotá", "tipo": "MAYORISTA"}, format="json").status_code, 200)
        self.retail.refresh_from_db()
        self.assertEqual((self.retail.ciudad, self.retail.tipo), ("Bogotá", "MAYORISTA"))
        self.assertEqual(self.seller.patch(url, {"activo": False}, format="json").status_code, 200)
        self.assertEqual(self.seller.delete(url).status_code, 403)  # no se borra
        self.assertEqual(len(self.seller.get(reverse("ventas_clientes"), {"activo": "true"}).json()), 2)
        self.assertEqual(self.seller.patch(reverse("ventas_cliente", args=[9999]), {}, format="json").status_code, 404)

    def test_la_factura_conserva_los_datos_del_cliente_de_ese_momento(self):
        invoice_id = self.sell([(self.v30, 1, 0)], customer=self.wholesale).json()["id"]
        self.seller.patch(reverse("ventas_cliente", args=[self.wholesale.id]), {"nombre": "Otro nombre", "ciudad": "Cali"}, format="json")
        body = self.viewer.get(reverse("ventas_factura", args=[invoice_id])).json()
        self.assertEqual((body["cliente_nombre"], body["cliente_ciudad"], body["cliente_documento"]), ("Moda Joven", "Medellín", "NIT 901234567"))

    def test_lista_con_filtros_y_permisos(self):
        url = reverse("ventas_clientes")
        self.assertEqual(len(self.seller.get(url, {"tipo": "DETAL"}).json()), 1)
        self.assertEqual(len(self.seller.get(url, {"q": "Carolina"}).json()), 1)
        self.assertEqual(len(self.seller.get(url, {"q": "CLI-0001"}).json()), 1)
        self.assertEqual(self.viewer.get(url).status_code, 200)
        self.assertEqual(self.viewer.post(url, {}, format="json").status_code, 403)  # el Gerente no registra clientes
        self.assertEqual(self.store.get(url).status_code, 403)


class PriceTests(SalesBase):
    def test_lista_las_referencias_activas_con_o_sin_precio(self):
        rows = self.manager.get(reverse("ventas_precios")).json()
        mine = next(row for row in rows if row["referencia"] == self.ref["id"])
        self.assertEqual((mine["costo_fabrica"], mine["precio_mayorista"], mine["precio_detal"]), (COST, WHOLESALE, RETAIL))
        PrecioReferencia.objects.all().hard_delete()
        mine = next(row for row in self.manager.get(reverse("ventas_precios")).json() if row["referencia"] == self.ref["id"])
        self.assertIsNone(mine["costo_fabrica"])

    def test_el_gerente_registra_y_actualiza_los_precios(self):
        url = reverse("ventas_precio", args=[self.ref["id"]])
        response = self.manager.put(url, {"costo_fabrica": 50_000, "precio_mayorista": 72_500, "precio_detal": 94_900}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(PrecioReferencia.objects.get().precio_mayorista, 72_500)
        self.assertEqual(PrecioReferencia.objects.count(), 1)  # actualiza, no duplica
        self.assertEqual(self.manager.put(reverse("ventas_precio", args=[999999]), {"costo_fabrica": 1, "precio_mayorista": 1, "precio_detal": 1},
                                          format="json").status_code, 404)

    def test_precios_coherentes_con_el_costo(self):
        url = reverse("ventas_precio", args=[self.ref["id"]])
        for body in ({"costo_fabrica": 50_000, "precio_mayorista": 49_000, "precio_detal": 90_000},  # mayorista bajo el costo
                     {"costo_fabrica": 50_000, "precio_mayorista": 70_000, "precio_detal": 69_000},  # detal bajo el mayorista
                     {"costo_fabrica": 0, "precio_mayorista": 1, "precio_detal": 1}, {"costo_fabrica": 1.5, "precio_mayorista": 2, "precio_detal": 3}):
            self.assertEqual(self.manager.put(url, body, format="json").status_code, 400, body)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrecioReferencia.objects.update(precio_mayorista=COST - 1)

    def test_permisos(self):
        url = reverse("ventas_precio", args=[self.ref["id"]])
        body = {"costo_fabrica": 50_000, "precio_mayorista": 72_500, "precio_detal": 94_900}
        for client in (self.seller, self.secretary, self.store):
            self.assertEqual(client.put(url, body, format="json").status_code, 403)
        self.assertEqual(self.seller.get(reverse("ventas_precios")).status_code, 200)  # el Vendedor ve los precios
        self.assertEqual(self.admin.put(url, body, format="json").status_code, 200)


class CollectionTests(SalesBase):
    """Pruebas de conciliación de cartera y pagos contraentrega (HU 7.3)."""

    def test_confirmar_recaudo_actualiza_saldo_financiero_y_registra_movimiento(self):
        invoice_resp = self.sell([(self.v30, 2, 0)])
        self.assertEqual(invoice_resp.status_code, 201)
        invoice_id = invoice_resp.json()["id"]
        invoice = FacturaVenta.objects.get(pk=invoice_id)
        total = invoice.valor_a_recaudar

        url = reverse("ventas_factura_conciliar", args=[invoice_id])
        response = self.seller.post(url, {"estado_cobro": "PAGADO", "observaciones": "Guía cancelada en efectivo"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["estado_cobro"], "PAGADO")
        self.assertEqual(data["estado_cobro_nombre"], "Pagado")
        self.assertIsNotNone(data["fecha_cobro"])
        self.assertTrue(data["cobrado_por_nombre"])

        # Saldo financiero de la empresa actualizado
        saldo = SaldoFinanciero.objects.first()
        self.assertIsNotNone(saldo)
        self.assertEqual(saldo.saldo_actual, total)

        # Movimiento de cartera registrado
        move = MovimientoCartera.objects.filter(factura=invoice).first()
        self.assertIsNotNone(move)
        self.assertEqual(move.tipo, "RECAUDO")
        self.assertEqual(move.monto, total)
        self.assertEqual(move.saldo_antes, 0)
        self.assertEqual(move.saldo_despues, total)

    def test_marcar_devolucion_reingresa_prendas_a_stock_sin_tocar_saldo(self):
        initial_stock = self.stock(self.v30)  # 20
        invoice_resp = self.sell([(self.v30, 3, 0)])
        self.assertEqual(invoice_resp.status_code, 201)
        invoice_id = invoice_resp.json()["id"]
        self.assertEqual(self.stock(self.v30), initial_stock - 3)

        url = reverse("ventas_factura_conciliar", args=[invoice_id])
        response = self.seller.post(url, {"estado_cobro": "DEVOLUCION", "motivo": "Dirección errada no localizada"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["estado_cobro"], "DEVOLUCION")
        self.assertEqual(data["motivo_devolucion"], "Dirección errada no localizada")

        # Prendas devueltas al inventario de producto terminado
        self.assertEqual(self.stock(self.v30), initial_stock)
        return_move = MovimientoTerminado.objects.filter(factura_id=invoice_id, tipo=finished_catalog.SALE_RETURN).first()
        self.assertIsNotNone(return_move)
        self.assertEqual(return_move.cantidad, 3)

        # Saldo financiero no incrementa
        saldo = SaldoFinanciero.objects.first()
        self.assertEqual(saldo.saldo_actual if saldo else 0, 0)

    def test_no_se_puede_conciliar_dos_veces(self):
        invoice_resp = self.sell([(self.v30, 1, 0)])
        invoice_id = invoice_resp.json()["id"]
        url = reverse("ventas_factura_conciliar", args=[invoice_id])
        first = self.seller.post(url, {"estado_cobro": "PAGADO"}, format="json")
        self.assertEqual(first.status_code, 200)

        second = self.seller.post(url, {"estado_cobro": "PAGADO"}, format="json")
        self.assertEqual(second.status_code, 400)
        self.assertIn("ya fue gestionada", str(second.content))

        third = self.seller.post(url, {"estado_cobro": "DEVOLUCION", "motivo": "Intento tardío"}, format="json")
        self.assertEqual(third.status_code, 400)

    def test_no_se_puede_conciliar_factura_anulada(self):
        invoice_resp = self.sell([(self.v30, 1, 0)])
        invoice_id = invoice_resp.json()["id"]
        self.manager.post(reverse("ventas_factura_anular", args=[invoice_id]), {"motivo": "Cancelada por error del cliente"}, format="json")

        url = reverse("ventas_factura_conciliar", args=[invoice_id])
        response = self.seller.post(url, {"estado_cobro": "PAGADO"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("anulada", str(response.content))

    def test_no_se_puede_anular_factura_ya_recaudada(self):
        invoice_resp = self.sell([(self.v30, 1, 0)])
        invoice_id = invoice_resp.json()["id"]
        self.seller.post(reverse("ventas_factura_conciliar", args=[invoice_id]), {"estado_cobro": "PAGADO"}, format="json")

        cancel_resp = self.manager.post(reverse("ventas_factura_anular", args=[invoice_id]), {"motivo": "Intento de anulación post-pago"}, format="json")
        self.assertEqual(cancel_resp.status_code, 400)
        self.assertIn("recaudada", str(cancel_resp.content))

    def test_cartera_resumen_y_filtros(self):
        # 1 factura por cobrar, 1 pagada
        inv1 = self.sell([(self.v30, 1, 0)]).json()
        inv2 = self.sell([(self.v32, 2, 0)]).json()
        self.seller.post(reverse("ventas_factura_conciliar", args=[inv1["id"]]), {"estado_cobro": "PAGADO"}, format="json")

        summary_resp = self.seller.get(reverse("ventas_cartera_resumen"))
        self.assertEqual(summary_resp.status_code, 200)
        summary = summary_resp.json()
        self.assertEqual(summary["conteo_pagadas"], 1)
        self.assertEqual(summary["total_recaudado"], inv1["valor_a_recaudar"])
        self.assertEqual(summary["saldo_financiero"], inv1["valor_a_recaudar"])
        self.assertEqual(summary["conteo_por_cobrar"], 1)
        self.assertEqual(summary["total_por_cobrar"], inv2["valor_a_recaudar"])

        # Filtro de facturas por estado_cobro
        list_pending = self.seller.get(reverse("ventas_facturas") + "?estado_cobro=POR_COBRAR").json()
        self.assertTrue(any(f["id"] == inv2["id"] for f in list_pending))
        self.assertFalse(any(f["id"] == inv1["id"] for f in list_pending))

    def test_permisos_conciliar(self):
        invoice_resp = self.sell([(self.v30, 1, 0)])
        invoice_id = invoice_resp.json()["id"]
        url = reverse("ventas_factura_conciliar", args=[invoice_id])

        # Secretaria no puede gestionar cartera
        resp_sec = self.secretary.post(url, {"estado_cobro": "PAGADO"}, format="json")
        self.assertEqual(resp_sec.status_code, 403)

        # Admin sí puede
        resp_admin = self.admin.post(url, {"estado_cobro": "PAGADO"}, format="json")
        self.assertEqual(resp_admin.status_code, 200)

