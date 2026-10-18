"""Órdenes de compra: creación, validación, permisos, edición, aprobación, cancelación, cierre y consultas."""
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Proveedor
from apps.inventory.tests import InventoryBase, client_for, make_user, today

from . import catalog
from .models import LineaCompra, OrdenCompra


class PurchasingBase(InventoryBase):
    """Tela (1000 m), cierre (500 und) y botón (300 und) en el almacén, un proveedor y un cliente por rol."""

    def setUp(self):
        super().setUp()
        self.store = self.api  # almacenista: recibe la mercancía
        self.producer = client_for(make_user("jefe_compras@t.co", "PRODUCCION"))  # crea las órdenes
        self.manager = client_for(make_user("gerente_compras@t.co", "GERENTE"))  # las aprueba
        self.orders_url = reverse("compras_ordenes")

    def order_body(self, lines=None, **extra):
        body = {
            "proveedor": self.supplier.id,
            "lineas": lines if lines is not None else [
                {"producto": self.tela.id, "cantidad": "100", "precio_pactado": "18500"},
                {"producto": self.cierre.id, "cantidad": "50"},
            ],
        }
        body.update(extra)
        return body

    def place(self, lines=None, client=None, **extra):
        return (client or self.producer).post(self.orders_url, self.order_body(lines, **extra), format="json")

    def placed(self, lines=None, **extra):
        response = self.place(lines, **extra)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def order_url(self, order_id, action=""):
        if action:
            return reverse(f"compras_orden_{action}", kwargs={"pk": order_id})
        return reverse("compras_orden", kwargs={"pk": order_id})

    def approve(self, order_id, client=None):
        return (client or self.manager).post(self.order_url(order_id, "aprobar"), {}, format="json")

    def approved(self, lines=None, **extra):
        order = self.placed(lines, **extra)
        response = self.approve(order["id"])
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def cancel(self, order_id, motivo="Ya no se necesita", client=None):
        return (client or self.producer).post(self.order_url(order_id, "cancelar"), {"motivo": motivo}, format="json")

    def close(self, order_id, motivo="El proveedor no tiene más", client=None):
        return (client or self.producer).post(self.order_url(order_id, "cerrar"), {"motivo": motivo}, format="json")


class CrearOrdenTests(PurchasingBase):
    def test_nace_en_borrador_con_codigo_consecutivo(self):
        first, second = self.placed(), self.placed()
        self.assertEqual((first["codigo"], second["codigo"]), ("OC-0001", "OC-0002"))
        self.assertEqual((first["estado"], first["estado_nombre"]), ("BORRADOR", "Borrador"))
        self.assertEqual(first["proveedor_nombre"], "Textiles SA")
        self.assertEqual(first["fecha"], today())
        self.assertEqual(first["recibible"], False)
        self.assertEqual(first["aprobado_por_nombre"], "")
        self.assertTrue(first["creado_por_nombre"])

    def test_las_lineas_traen_lo_recibido_y_lo_pendiente(self):
        order = self.placed()
        tela, cierre = order["lineas"]
        self.assertEqual((tela["producto_nombre"], tela["unidad"], tela["cantidad_pedida"]), ("Tela denim", "m", "100.00"))
        self.assertEqual((tela["cantidad_recibida"], tela["pendiente"], tela["completa"]), ("0.00", "100.00", False))
        self.assertEqual(tela["maximo_a_recibir"], "105.00")  # el 5 % de tolerancia
        self.assertEqual((tela["precio_pactado"], cierre["precio_pactado"]), ("18500.0000", None))

    def test_valor_estimado_y_lineas_sin_precio(self):
        order = self.placed()
        self.assertEqual(order["valor_estimado"], "1850000.00")  # 100 m × 18.500; el cierre no tiene precio
        self.assertEqual(order["lineas_sin_precio"], 1)

    def test_guarda_las_condiciones_y_la_fecha_esperada(self):
        expected = (timezone.localdate() + timedelta(days=15)).isoformat()
        order = self.placed(fecha_esperada=expected, condiciones_pago=" 30 días ", notas=" Entregar en bodega 2 ")
        self.assertEqual((order["fecha_esperada"], order["condiciones_pago"], order["notas"]), (expected, "30 días", "Entregar en bodega 2"))

    def test_una_orden_de_hoy_o_de_una_fecha_pasada(self):
        past = (timezone.localdate() - timedelta(days=3)).isoformat()
        self.assertEqual(self.placed(fecha=past)["fecha"], past)

    def assertRejected(self, response, field, text=""):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(field, response.json())
        self.assertIn(text, str(response.json()[field][0]))
        self.assertEqual(OrdenCompra.objects.count(), 0)  # una orden rechazada no deja nada

    def test_valida_el_proveedor(self):
        self.assertRejected(self.place(proveedor=99999), "proveedor", "no existe")
        archived = Proveedor.objects.create(nit="800100200", nit_dv="1", razon_social="Archivado SA", categoria=inventory_catalog.CAT_FABRIC)
        archived.delete()  # borrado lógico
        self.assertRejected(self.place(proveedor=archived.id), "proveedor", "archivado")
        self.assertRejected(self.place(proveedor=True), "proveedor")

    def test_valida_las_lineas(self):
        for lines, text in (
            ([], "al menos un producto"),
            (None, "requerido"),  # sin el campo: lo dice DRF
            ("tela", "al menos un producto"),
            ([{"cantidad": "5"}], "indicar el producto"),
            ([{"producto": 99999, "cantidad": "5"}], "no existe"),
            ([{"producto": self.generico.id, "cantidad": "5"}], "no se compra"),
            ([{"producto": self.skinny.id, "cantidad": "5"}], "no se compra"),
            ([{"producto": self.tela.id, "cantidad": "5"}, {"producto": self.tela.id, "cantidad": "7"}], "no puede repetirse"),
            ([{"producto": self.tela.id, "cantidad": "0"}], "mayor que cero"),
            ([{"producto": self.tela.id, "cantidad": "abc"}], "número"),
            ([{"producto": self.cierre.id, "cantidad": "2.5"}], "no admite decimales"),
            ([{"producto": self.tela.id, "cantidad": "5", "precio_pactado": "-3"}], "mayor que cero"),
            ([{"producto": self.tela.id, "cantidad": "5", "precio_pactado": "1.123456"}], "decimales"),
            (["no es un objeto"], "datos inválidos"),
        ):
            body = self.order_body(lines)
            if lines is None:
                body.pop("lineas")
            response = self.producer.post(self.orders_url, body, format="json")
            self.assertEqual(response.status_code, 400, (lines, response.content))
            self.assertIn(text, str(response.json()), lines)
        self.assertEqual(OrdenCompra.objects.count(), 0)

    def test_el_error_de_una_linea_dice_cual_es(self):
        lines = [{"producto": self.tela.id, "cantidad": "5"}, {"producto": self.cierre.id, "cantidad": "0"}]
        self.assertRejected(self.place(lines), "lineas", "Línea 2")

    def test_valida_las_fechas(self):
        future = (timezone.localdate() + timedelta(days=2)).isoformat()
        self.assertRejected(self.place(fecha=future), "fecha", "futura")
        past = (timezone.localdate() - timedelta(days=5)).isoformat()
        early = (timezone.localdate() - timedelta(days=9)).isoformat()
        self.assertRejected(self.place(fecha=past, fecha_esperada=early), "fecha_esperada", "anterior")

    def test_demasiadas_lineas(self):
        lines = [{"producto": self.tela.id, "cantidad": "1"}] * (catalog.MAX_LINES + 1)
        self.assertEqual(self.place(lines).status_code, 400)

    def test_solo_materia_prima_e_insumos(self):
        self.assertEqual(self.place([{"producto": self.boton.id, "cantidad": "10"}]).status_code, 201)


class PermisosTests(PurchasingBase):
    def test_quien_puede_ver_y_quien_puede_crear(self):
        self.assertEqual(self.client.get(self.orders_url).status_code, 401)
        for client in (self.producer, self.manager, self.store):
            self.assertEqual(client.get(self.orders_url).status_code, 200)
        self.assertEqual(self.place(client=self.manager).status_code, 403)  # el gerente aprueba, no crea
        self.assertEqual(self.place(client=self.store).status_code, 403)
        self.assertEqual(self.place(client=client_for(make_user("vendedor_c@t.co", "VENDEDOR"))).status_code, 403)
        self.assertEqual(self.place(client=client_for(make_user("admin_c@t.co", "ADMIN"))).status_code, 201)
        self.assertEqual(OrdenCompra.objects.count(), 1)

    def test_un_rol_sin_compras_no_ve_nada(self):
        seller = client_for(make_user("vendedor_v@t.co", "VENDEDOR"))
        order = self.placed()
        self.assertEqual(seller.get(self.orders_url).status_code, 403)
        self.assertEqual(seller.get(self.order_url(order["id"])).status_code, 403)
        self.assertEqual(seller.get(reverse("compras_metadatos")).status_code, 403)

    def test_solo_el_gerente_aprueba(self):
        order = self.placed()
        self.assertEqual(self.approve(order["id"], self.producer).status_code, 403)
        self.assertEqual(self.approve(order["id"], self.store).status_code, 403)
        self.assertEqual(OrdenCompra.objects.get(pk=order["id"]).estado, "BORRADOR")
        self.assertEqual(self.approve(order["id"]).status_code, 200)

    def test_cancelar_y_cerrar_son_de_quien_gestiona(self):
        order = self.placed()
        self.assertEqual(self.cancel(order["id"], client=self.manager).status_code, 403)
        self.assertEqual(self.cancel(order["id"], client=self.store).status_code, 403)
        self.assertEqual(self.close(order["id"], client=self.manager).status_code, 403)
        self.assertEqual(self.client.post(self.order_url(order["id"], "cancelar"), {"motivo": "x"}, format="json").status_code, 401)


class EditarOrdenTests(PurchasingBase):
    def test_edita_un_borrador_y_reemplaza_las_lineas(self):
        order = self.placed()
        response = self.producer.patch(
            self.order_url(order["id"]),
            {"notas": "Urgente", "lineas": [{"producto": self.boton.id, "cantidad": "200", "precio_pactado": "90"}]}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["notas"], "Urgente")
        self.assertEqual([line["producto_nombre"] for line in body["lineas"]], ["Botón"])
        self.assertEqual(LineaCompra.all_objects.filter(orden_id=order["id"]).count(), 3)  # lo anterior queda como historial
        self.assertEqual(LineaCompra.objects.filter(orden_id=order["id"]).count(), 1)

    def test_cambiar_solo_un_dato_deja_las_lineas(self):
        order = self.placed()
        body = self.producer.patch(self.order_url(order["id"]), {"condiciones_pago": "Contado"}, format="json").json()
        self.assertEqual((body["condiciones_pago"], len(body["lineas"])), ("Contado", 2))

    def test_cambiar_el_proveedor(self):
        other = Proveedor.objects.create(nit="800555666", nit_dv="3", razon_social="Hilos SAS", categoria=inventory_catalog.CAT_THREAD)
        order = self.placed()
        body = self.producer.patch(self.order_url(order["id"]), {"proveedor": other.id}, format="json").json()
        self.assertEqual(body["proveedor_nombre"], "Hilos SAS")

    def test_una_edicion_invalida_no_cambia_nada(self):
        order = self.placed()
        response = self.producer.patch(self.order_url(order["id"]), {"notas": "x", "lineas": []}, format="json")
        self.assertEqual(response.status_code, 400)
        stored = self.producer.get(self.order_url(order["id"])).json()
        self.assertEqual((stored["notas"], len(stored["lineas"])), ("", 2))

    def test_solo_se_edita_en_borrador(self):
        order = self.approved()
        response = self.producer.patch(self.order_url(order["id"]), {"notas": "tarde"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("solo se edita en borrador", str(response.json()))

    def test_quien_no_gestiona_no_edita(self):
        order = self.placed()
        self.assertEqual(self.manager.patch(self.order_url(order["id"]), {"notas": "x"}, format="json").status_code, 403)
        self.assertEqual(self.producer.patch(self.order_url(99999), {"notas": "x"}, format="json").status_code, 400)


class AprobarCancelarCerrarTests(PurchasingBase):
    def test_aprobar_deja_quien_y_cuando(self):
        order = self.approved()
        self.assertEqual((order["estado"], order["recibible"]), ("APROBADA", True))
        self.assertTrue(order["aprobado_por_nombre"])
        self.assertIsNotNone(order["aprobada_at"])

    def test_aprobar_dos_veces_o_una_cancelada(self):
        order = self.approved()
        self.assertEqual(self.approve(order["id"]).status_code, 400)
        other = self.placed()
        self.cancel(other["id"])
        response = self.approve(other["id"])
        self.assertEqual(response.status_code, 400)
        self.assertIn("solo se aprueba un borrador", str(response.json()))

    def test_cancelar_un_borrador_y_una_aprobada_sin_recepciones(self):
        for order in (self.placed(), self.approved()):
            response = self.cancel(order["id"], "El proveedor subió el precio")
            self.assertEqual(response.status_code, 200, response.content)
            body = response.json()
            self.assertEqual((body["estado"], body["motivo_cierre"]), ("CANCELADA", "El proveedor subió el precio"))
            self.assertIsNotNone(body["cerrada_at"])

    def test_cancelar_exige_el_motivo(self):
        order = self.placed()
        for motivo in ("", "   "):
            self.assertEqual(self.cancel(order["id"], motivo).status_code, 400)
        self.assertEqual(self.producer.post(self.order_url(order["id"], "cancelar"), {}, format="json").status_code, 400)
        self.assertEqual(OrdenCompra.objects.get(pk=order["id"]).estado, "BORRADOR")

    def test_una_cancelada_no_se_vuelve_a_cancelar(self):
        order = self.placed()
        self.cancel(order["id"])
        response = self.cancel(order["id"])
        self.assertEqual(response.status_code, 400)
        self.assertIn("no se puede cancelar", str(response.json()))

    def test_cerrar_solo_aplica_con_recepciones_parciales(self):
        order = self.approved()
        response = self.close(order["id"])
        self.assertEqual(response.status_code, 400)
        self.assertIn("recepciones parciales", str(response.json()))
        self.assertEqual(self.close(self.placed()["id"]).status_code, 400)

    def test_orden_inexistente(self):
        for action, client in (("aprobar", self.manager), ("cancelar", self.producer), ("cerrar", self.producer)):
            response = client.post(self.order_url(99999, action), {"motivo": "x"}, format="json")
            self.assertEqual(response.status_code, 400, (action, response.content))
        self.assertEqual(self.producer.get(self.order_url(99999)).status_code, 404)


class ConsultasTests(PurchasingBase):
    def test_filtros_de_la_lista(self):
        other = Proveedor.objects.create(nit="800777888", nit_dv="5", razon_social="Cremalleras Ltda", categoria=inventory_catalog.CAT_ZIPPER)
        draft = self.placed()
        approved = self.approved()
        cancelled = self.placed(proveedor=other.id)
        self.cancel(cancelled["id"])

        def codes(**params):
            return [item["codigo"] for item in self.producer.get(self.orders_url, params).json()]

        self.assertEqual(codes(), [cancelled["codigo"], approved["codigo"], draft["codigo"]])  # la más reciente primero
        self.assertEqual(codes(estado="BORRADOR"), [draft["codigo"]])
        self.assertEqual(codes(estado="APROBADA"), [approved["codigo"]])
        self.assertEqual(codes(proveedor=other.id), [cancelled["codigo"]])
        self.assertEqual(codes(q="cremalleras"), [cancelled["codigo"]])
        self.assertEqual(codes(q=draft["codigo"]), [draft["codigo"]])
        self.assertEqual(codes(limit="2"), [cancelled["codigo"], approved["codigo"]])
        self.assertEqual(self.producer.get(self.orders_url, {"proveedor": "abc"}).status_code, 400)

    def test_detalle(self):
        order = self.placed()
        body = self.store.get(self.order_url(order["id"])).json()
        self.assertEqual((body["codigo"], len(body["lineas"]), body["recepciones"]), ("OC-0001", 2, []))

    def test_metadatos(self):
        body = self.producer.get(reverse("compras_metadatos")).json()
        self.assertEqual([state["codigo"] for state in body["estados"]],
                         ["BORRADOR", "APROBADA", "RECIBIDA_PARCIAL", "RECIBIDA", "CERRADA", "CANCELADA"])
        self.assertEqual(Decimal(body["tolerancia_exceso"]), Decimal("0.05"))

    def test_las_consultas_no_crecen_con_el_numero_de_ordenes(self):
        self.placed()
        self.producer.get(self.orders_url)  # calienta cachés de permisos

        def count():
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.producer.get(self.orders_url).status_code, 200)
            return len(queries)

        baseline = count()
        for _ in range(4):
            self.placed()
        self.assertEqual(count(), baseline)
