"""Guías de envío, relaciones de despacho y devolución física (HU 7.2). El rastreo con Track123 se prueba en `test_rastreo.py`."""
import uuid

from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.finished import catalog as finished_catalog
from apps.finished.models import MovimientoTerminado
from apps.inventory.models import Consecutivo
from apps.inventory.tests import client_for, make_user
from apps.sales import catalog as sales_catalog
from apps.sales.models import FacturaVenta, MovimientoCartera
from apps.sales.test_ventas import SalesBase
from apps.users.models import Role

from . import catalog, services
from .models import EventoGuia, Guia, RelacionDespacho


class ShippingBase(SalesBase):
    """Vendedor (self.seller), Almacenista (self.store), Secretaria, Gerente (self.manager) y Admin. Stock: v30 = 20, v32 = 20, v34 = 10."""

    def setUp(self):
        super().setUp()
        self.clerk = self.secretary

    def number(self, n):
        return f"7001{n:08d}"

    def sale(self, rows=None, carrier="", number="", **extra):
        body = dict(extra)
        if carrier:
            body["transportadora"] = carrier
        if number:
            body["numero_guia"] = number
        return self.sell(rows or [(self.v30, 1, 0)], **body)

    def invoice_with_guide(self, n=1, carrier="INTERRAPIDISIMO"):
        response = self.sale(carrier=carrier, number=self.number(n))
        self.assertEqual(response.status_code, 201, response.content)
        invoice = FacturaVenta.objects.get(pk=response.json()["id"])
        return invoice, Guia.objects.get(factura=invoice, vigente=True)

    def state(self, guide, new_state, note="", client=None):
        return (client or self.store).post(reverse("envios_guia_estado", args=[guide.id]), {"estado": new_state, "nota": note}, format="json")

    def dispatch(self, guides, carrier="INTERRAPIDISIMO", token=None, client=None):
        return (client or self.store).post(reverse("envios_relaciones"), {
            "transportadora": carrier, "guias": [g.id for g in guides], "token": str(token or uuid.uuid4()), "responsable": "Bodega",
        }, format="json")


class AssignGuideTests(ShippingBase):
    def test_facturar_con_guia_las_crea_juntas_y_actualiza_el_espejo(self):
        invoice, guide = self.invoice_with_guide()
        self.assertEqual((guide.estado, guide.numero_guia, guide.transportadora), (catalog.PENDING, self.number(1), "INTERRAPIDISIMO"))
        invoice.refresh_from_db()
        self.assertEqual((invoice.transportadora, invoice.numero_guia), ("INTERRAPIDISIMO", self.number(1)))
        event = EventoGuia.objects.get(guia=guide)
        self.assertEqual((event.estado_antes, event.estado_despues, event.origen), ("", catalog.PENDING, catalog.ORIGIN_MANUAL))

    def test_el_numero_se_normaliza_sin_espacios(self):
        response = self.sale(carrier="ENVIA", number=" 0284 719 283 ")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Guia.objects.get(factura_id=response.json()["id"]).numero_guia, "0284719283")

    def test_facturar_sin_guia_deja_la_factura_en_pendientes(self):
        response = self.sale()
        self.assertEqual(response.status_code, 201)
        self.assertFalse(Guia.objects.filter(factura_id=response.json()["id"]).exists())
        pendientes = self.store.get(reverse("envios_pendientes")).json()
        self.assertEqual([p["numero"] for p in pendientes], [response.json()["numero"]])
        self.assertEqual(pendientes[0]["urgencia"], "normal")
        self.assertEqual(pendientes[0]["horas_sin_guia"], 0)

    def test_numero_repetido_en_la_transportadora_rechaza_y_no_gasta_consecutivos_ni_stock(self):
        self.invoice_with_guide(1)
        stock, invoices = self.stock(self.v30), Consecutivo.objects.get(clave="FV").ultimo
        response = self.sale(carrier="INTERRAPIDISIMO", number=self.number(1))
        self.assertEqual(response.status_code, 400)
        self.assertIn("ya está asignada", response.json()["numero_guia"][0])
        self.assertEqual(self.stock(self.v30), stock)
        self.assertEqual(Consecutivo.objects.get(clave="FV").ultimo, invoices)
        self.assertEqual(sales_count(), 1)

    def test_el_mismo_numero_en_otra_transportadora_si_se_permite(self):
        self.invoice_with_guide(1, "INTERRAPIDISIMO")
        self.assertEqual(self.sale(carrier="ENVIA", number=self.number(1)).status_code, 201)

    def test_numero_sin_transportadora_rechaza(self):
        response = self.sale(number=self.number(9))
        self.assertEqual(response.status_code, 400)
        self.assertIn("transportadora", response.json())

    def test_anotar_la_guia_despues_desde_pendientes(self):
        response = self.sale()
        url = reverse("envios_factura_guia", args=[response.json()["id"]])
        created = self.seller.post(url, {"transportadora": "INTERRAPIDISIMO", "numero_guia": self.number(2)}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["estado"], catalog.PENDING)
        self.assertEqual(self.store.get(reverse("envios_pendientes")).json(), [])
        self.assertEqual(FacturaVenta.objects.get(pk=response.json()["id"]).numero_guia, self.number(2))

    def test_reemplazar_la_guia_por_despachar_anula_la_anterior_con_evento(self):
        invoice, first = self.invoice_with_guide(1)
        url = reverse("envios_factura_guia", args=[invoice.id])
        self.assertEqual(self.seller.post(url, {"transportadora": "ENVIA", "numero_guia": "ENV-77"}, format="json").status_code, 201)
        first.refresh_from_db()
        self.assertEqual((first.estado, first.vigente), (catalog.VOIDED, False))
        self.assertTrue(EventoGuia.objects.filter(guia=first, estado_despues=catalog.VOIDED, nota__contains="Reemplazada").exists())
        invoice.refresh_from_db()
        self.assertEqual((invoice.transportadora, invoice.numero_guia), ("ENVIA", "ENV-77"))
        self.assertEqual(Guia.objects.filter(factura=invoice, vigente=True).count(), 1)

    def test_no_se_reemplaza_una_guia_ya_despachada(self):
        invoice, guide = self.invoice_with_guide()
        self.assertEqual(self.dispatch([guide]).status_code, 201)
        response = self.seller.post(reverse("envios_factura_guia", args=[invoice.id]), {"transportadora": "ENVIA", "numero_guia": "ENV-77"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("ya fue despachada", response.json()["numero_guia"][0])

    def test_repetir_la_misma_guia_es_idempotente(self):
        invoice, guide = self.invoice_with_guide()
        response = self.seller.post(reverse("envios_factura_guia", args=[invoice.id]), {"transportadora": "INTERRAPIDISIMO", "numero_guia": self.number(1)}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], guide.id)
        self.assertEqual(EventoGuia.objects.filter(guia=guide).count(), 1)

    def test_una_factura_anulada_no_recibe_guia(self):
        response = self.sale()
        self.manager.post(reverse("ventas_factura_anular", args=[response.json()["id"]]), {"motivo": "Cliente canceló el pedido"}, format="json")
        again = self.seller.post(reverse("envios_factura_guia", args=[response.json()["id"]]), {"transportadora": "ENVIA", "numero_guia": "X1"}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_dos_guias_vigentes_para_la_misma_factura_no_caben_en_la_base(self):
        invoice, _ = self.invoice_with_guide()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Guia.objects.create(factura=invoice, transportadora="ENVIA", numero_guia="OTRA", vigente=True)

    def test_urgencia_de_la_guia_pendiente_segun_las_horas(self):
        self.assertEqual([services.urgency(h) for h in (0, 3, 4, 23, 24, 80)], ["normal", "normal", "atencion", "atencion", "vencida", "vencida"])


def sales_count():
    return FacturaVenta.objects.count()


class StateMachineTests(ShippingBase):
    def test_todas_las_transiciones_permitidas_y_todas_las_prohibidas(self):
        _, guide = self.invoice_with_guide()
        for origin, targets in catalog.TRANSITIONS.items():
            for target in catalog.STATE_NAMES:
                if target == origin:
                    continue
                Guia.objects.filter(pk=guide.pk).update(estado=origin, vigente=True)
                response = self.state(guide, target, "Una nota válida")
                expected = 200 if target in targets else 400
                self.assertEqual(response.status_code, expected, (origin, target, response.content))
                if expected == 200:
                    guide.refresh_from_db()
                    self.assertEqual(guide.estado, target)

    def test_novedad_y_devolucion_exigen_una_nota(self):
        _, guide = self.invoice_with_guide()
        self.assertEqual(self.dispatch([guide]).status_code, 201)
        self.assertEqual(self.state(guide, catalog.INCIDENT, "").status_code, 400)
        self.assertEqual(self.state(guide, catalog.INCIDENT, "no").status_code, 400)
        self.assertEqual(self.state(guide, catalog.RETURNED, "").status_code, 400)
        self.assertEqual(self.state(guide, catalog.INCIDENT, "Nadie en casa al primer intento").status_code, 200)
        guide.refresh_from_db()
        self.assertEqual(guide.novedad, "Nadie en casa al primer intento")

    def test_cada_cambio_deja_un_evento_y_los_eventos_no_se_editan(self):
        _, guide = self.invoice_with_guide()
        self.dispatch([guide])
        self.state(guide, catalog.DELIVERED)
        trail = list(EventoGuia.objects.filter(guia=guide).values_list("estado_despues", flat=True))
        self.assertEqual(trail, [catalog.PENDING, catalog.IN_TRANSIT, catalog.DELIVERED])
        event = EventoGuia.objects.filter(guia=guide).first()
        event.nota = "cambiada"
        with self.assertRaises(ValueError):
            event.save()

    def test_los_estados_finales_no_se_mueven(self):
        _, guide = self.invoice_with_guide()
        self.dispatch([guide])
        self.state(guide, catalog.DELIVERED)
        self.assertEqual(self.state(guide, catalog.RETURNED, "Intento de devolver una entregada").status_code, 400)

    def test_una_guia_reemplazada_no_se_gestiona(self):
        invoice, first = self.invoice_with_guide(1)
        self.seller.post(reverse("envios_factura_guia", args=[invoice.id]), {"transportadora": "ENVIA", "numero_guia": "ENV-9"}, format="json")
        response = self.state(first, catalog.IN_TRANSIT)
        self.assertEqual(response.status_code, 400)

    def test_anular_manualmente_la_guia_por_despachar_deja_la_factura_sin_guia(self):
        invoice, guide = self.invoice_with_guide()
        self.assertEqual(self.state(guide, catalog.VOIDED, "").status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual((invoice.transportadora, invoice.numero_guia), ("", ""))
        self.assertEqual(len(self.store.get(reverse("envios_pendientes")).json()), 1)

    def test_camino_entre_estados_para_el_rastreo(self):
        self.assertEqual(services._path(catalog.PENDING, catalog.DELIVERED), [catalog.IN_TRANSIT, catalog.DELIVERED])
        self.assertEqual(services._path(catalog.PENDING, catalog.RETURNED), [catalog.IN_TRANSIT, catalog.RETURNED])
        self.assertIsNone(services._path(catalog.DELIVERED, catalog.IN_TRANSIT))
        self.assertEqual(services._path(catalog.INCIDENT, catalog.INCIDENT), [])


class DispatchTests(ShippingBase):
    def test_la_relacion_pasa_todas_las_guias_a_en_transito(self):
        guides = [self.invoice_with_guide(n)[1] for n in (1, 2, 3)]
        response = self.dispatch(guides)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["codigo"], body["total_guias"]), ("RD-0001", 3))
        for guide in guides:
            guide.refresh_from_db()
            self.assertEqual((guide.estado, guide.relacion_id), (catalog.IN_TRANSIT, body["id"]))
            self.assertIsNotNone(guide.despachada_en)

    def test_si_una_guia_no_sirve_no_cambia_ninguna_ni_se_gasta_el_consecutivo(self):
        ok = self.invoice_with_guide(1)[1]
        bad = self.invoice_with_guide(2)[1]
        self.dispatch([bad])  # ya despachada
        before = Consecutivo.objects.filter(clave="RD").values_list("ultimo", flat=True).first()
        response = self.dispatch([ok, bad])
        self.assertEqual(response.status_code, 400)
        ok.refresh_from_db()
        self.assertEqual(ok.estado, catalog.PENDING)
        self.assertEqual(Consecutivo.objects.filter(clave="RD").values_list("ultimo", flat=True).first(), before)

    def test_mezclar_transportadoras_rechaza(self):
        a = self.invoice_with_guide(1, "INTERRAPIDISIMO")[1]
        b = self.invoice_with_guide(2, "ENVIA")[1]
        response = self.dispatch([a, b], carrier="INTERRAPIDISIMO")
        self.assertEqual(response.status_code, 400)
        self.assertIn("no de Interrapidísimo", response.json()["guias"][0])

    def test_token_repetido_responde_409_con_la_relacion_existente(self):
        guide = self.invoice_with_guide()[1]
        token = uuid.uuid4()
        first = self.dispatch([guide], token=token)
        again = self.dispatch([guide], token=token)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 409)
        self.assertEqual(RelacionDespacho.objects.count(), 1)

    def test_validaciones_de_la_lista(self):
        guide = self.invoice_with_guide()[1]
        self.assertEqual(self.store.post(reverse("envios_relaciones"), {"transportadora": "ENVIA", "guias": [], "token": str(uuid.uuid4())}, format="json").status_code, 400)
        self.assertEqual(self.dispatch([guide, guide]).status_code, 400)
        self.assertEqual(self.store.post(reverse("envios_relaciones"), {"transportadora": "ENVIA", "guias": [999999], "token": str(uuid.uuid4())}, format="json").status_code, 400)

    def test_pdf_de_la_relacion_es_un_pdf_valido(self):
        guides = [self.invoice_with_guide(n)[1] for n in (1, 2)]
        relation = self.dispatch(guides).json()
        response = self.seller.get(reverse("envios_relacion_pdf", args=[relation["id"]]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 1000)

    def test_detalle_y_lista_de_relaciones(self):
        guide = self.invoice_with_guide()[1]
        relation = self.dispatch([guide]).json()
        detail = self.seller.get(reverse("envios_relacion", args=[relation["id"]])).json()
        self.assertEqual([g["numero_guia"] for g in detail["guias"]], [guide.numero_guia])
        self.assertEqual(len(self.seller.get(reverse("envios_relaciones")).json()), 1)
        self.assertEqual(self.seller.get(reverse("envios_relacion", args=[9999])).status_code, 404)


class FreightAndReturnTests(ShippingBase):
    def returned_guide(self, n=1):
        invoice, guide = self.invoice_with_guide(n)
        self.dispatch([guide])
        self.assertEqual(self.state(guide, catalog.RETURNED, "El destinatario rechazó el paquete").status_code, 200)
        guide.refresh_from_db()
        return invoice, guide

    def test_flete_de_una_devolucion_queda_a_cargo_del_vendedor(self):
        _, guide = self.returned_guide()
        response = self.store.patch(reverse("envios_guia_flete", args=[guide.id]), {"valor_flete": 12000}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        guide.refresh_from_db()
        self.assertEqual((guide.valor_flete, guide.flete_vendedor), (12000, 12000))

    def test_flete_antes_de_la_devolucion_se_copia_al_devolver(self):
        _, guide = self.invoice_with_guide()
        self.store.patch(reverse("envios_guia_flete", args=[guide.id]), {"valor_flete": 9000}, format="json")
        self.dispatch([guide])
        self.state(guide, catalog.RETURNED, "Devuelto por la transportadora")
        guide.refresh_from_db()
        self.assertEqual(guide.flete_vendedor, 9000)

    def test_flete_invalido_rechaza(self):
        _, guide = self.invoice_with_guide()
        for bad in (-1, "abc", 10_000_001, 1.5):
            self.assertEqual(self.store.patch(reverse("envios_guia_flete", args=[guide.id]), {"valor_flete": bad}, format="json").status_code, 400, bad)

    def test_devolucion_fisica_reingresa_el_stock_una_sola_vez(self):
        invoice, guide = self.returned_guide()
        initial = self.stock(self.v30)  # ya descontada la venta
        url = reverse("envios_guia_devolucion", args=[guide.id])
        first = self.store.post(url, {}, format="json")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(self.stock(self.v30), initial + 1)
        invoice.refresh_from_db()
        self.assertEqual(invoice.estado_cobro, sales_catalog.COLLECT_RETURNED)
        again = self.store.post(url, {}, format="json")
        self.assertEqual(again.status_code, 400)
        self.assertEqual(self.stock(self.v30), initial + 1)
        self.assertEqual(MovimientoTerminado.objects.filter(factura=invoice, tipo=finished_catalog.SALE_RETURN).count(), 1)
        self.assertEqual(MovimientoCartera.objects.filter(factura=invoice).count(), 1)

    def test_la_devolucion_exige_guia_devuelta(self):
        _, guide = self.invoice_with_guide()
        self.assertEqual(self.store.post(reverse("envios_guia_devolucion", args=[guide.id]), {}, format="json").status_code, 400)

    def test_resumen_de_devoluciones_por_vendedor_con_su_flete(self):
        _, guide = self.returned_guide()
        self.store.patch(reverse("envios_guia_flete", args=[guide.id]), {"valor_flete": 15000}, format="json")
        summary = self.manager.get(reverse("envios_resumen")).json()
        self.assertEqual(summary["devoluciones_por_vendedor"][0]["guias"], 1)
        self.assertEqual(summary["devoluciones_por_vendedor"][0]["flete"], 15000)
        self.assertEqual(next(e for e in summary["estados"] if e["codigo"] == catalog.RETURNED)["cantidad"], 1)


class InvoiceIntegrationTests(ShippingBase):
    def test_no_se_anula_una_factura_con_guia_despachada(self):
        invoice, guide = self.invoice_with_guide()
        self.dispatch([guide])
        response = self.manager.post(reverse("ventas_factura_anular", args=[invoice.id]), {"motivo": "Cliente canceló el pedido"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("ya fue despachada", response.json()["estado"][0])
        invoice.refresh_from_db()
        self.assertEqual(invoice.estado, sales_catalog.STATUS_ISSUED)

    def test_anular_con_guia_por_despachar_anula_tambien_la_guia(self):
        invoice, guide = self.invoice_with_guide()
        stock = self.stock(self.v30)
        response = self.manager.post(reverse("ventas_factura_anular", args=[invoice.id]), {"motivo": "Cliente canceló el pedido"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        guide.refresh_from_db()
        self.assertEqual((guide.estado, guide.vigente), (catalog.VOIDED, False))
        self.assertEqual(self.stock(self.v30), stock + 1)

    def test_la_factura_muestra_el_estado_de_su_guia(self):
        invoice, guide = self.invoice_with_guide()
        self.dispatch([guide])
        body = self.seller.get(reverse("ventas_factura", args=[invoice.id])).json()
        self.assertEqual((body["guia"]["estado"], body["guia"]["color"]), (catalog.IN_TRANSIT, "azul"))
        sin = self.sale().json()
        self.assertIsNone(sin["guia"])

    def test_el_pago_sigue_funcionando_igual(self):
        invoice, guide = self.invoice_with_guide()
        self.dispatch([guide])
        self.state(guide, catalog.DELIVERED)
        response = self.seller.post(reverse("ventas_factura_conciliar", args=[invoice.id]), {"estado_cobro": "PAGADO"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.seller.get(reverse("ventas_cartera_resumen")).json()["conteo_pagadas"], 1)

    def test_el_listado_de_facturas_no_hace_consultas_de_mas_por_la_guia(self):
        for n in range(1, 5):
            self.invoice_with_guide(n)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as small:
            self.seller.get(reverse("ventas_facturas"))
        for n in range(5, 9):
            self.invoice_with_guide(n)
        with CaptureQueriesContext(connection) as large:
            self.seller.get(reverse("ventas_facturas"))
        self.assertEqual(len(small), len(large))


class ListAndPermissionTests(ShippingBase):
    def test_filtros_y_busqueda_de_guias(self):
        a = self.invoice_with_guide(1, "INTERRAPIDISIMO")[1]
        b = self.invoice_with_guide(2, "ENVIA")[1]
        self.dispatch([b], carrier="ENVIA")
        url = reverse("envios_guias")
        self.assertEqual(len(self.seller.get(url).json()), 2)
        self.assertEqual([g["id"] for g in self.seller.get(url + "?estado=EN_TRANSITO").json()], [b.id])
        self.assertEqual([g["id"] for g in self.seller.get(url + "?transportadora=INTERRAPIDISIMO").json()], [a.id])
        self.assertEqual([g["id"] for g in self.seller.get(url + f"?q={self.number(1)}").json()], [a.id])
        self.assertEqual(self.seller.get(url + "?factura=abc").status_code, 400)

    def test_detalle_incluye_historial_y_estados_siguientes(self):
        _, guide = self.invoice_with_guide()
        body = self.seller.get(reverse("envios_guia", args=[guide.id])).json()
        self.assertEqual(body["acciones"], sorted([catalog.IN_TRANSIT, catalog.VOIDED]))
        self.assertEqual(len(body["eventos"]), 1)
        self.assertEqual(self.seller.get(reverse("envios_guia", args=[999999])).status_code, 404)

    def test_metadatos(self):
        body = self.seller.get(reverse("envios_metadatos")).json()
        self.assertEqual([s["codigo"] for s in body["estados"]][:2], [catalog.PENDING, catalog.IN_TRANSIT])
        self.assertTrue(next(c for c in body["transportadoras"] if c["codigo"] == "INTERRAPIDISIMO")["rastreable"])
        self.assertFalse(next(c for c in body["transportadoras"] if c["codigo"] == "ENVIA")["rastreable"])

    def test_permisos_por_rol(self):
        def granted(role):
            return set(Role.objects.get(code=role).permissions.filter(code__startswith="envios.").values_list("code", flat=True))

        self.assertEqual(granted("VENDEDOR"), {"envios.ver", "envios.anotar"})
        self.assertEqual(granted("ALMACENISTA"), {"envios.ver", "envios.anotar", "envios.gestionar", "envios.devolucion"})
        self.assertEqual(granted("SECRETARIA"), {"envios.ver", "envios.anotar", "envios.gestionar"})
        self.assertEqual(granted("GERENTE"), {"envios.ver", "envios.devolucion"})
        for role in ("PRODUCCION", "TERMINACION", "PENDING"):
            self.assertEqual(granted(role), set(), role)

    def test_acciones_segun_permiso(self):
        invoice, guide = self.invoice_with_guide()
        self.assertEqual(self.state(guide, catalog.IN_TRANSIT, client=self.seller).status_code, 403)  # el vendedor solo consulta y anota
        self.assertEqual(self.dispatch([guide], client=self.seller).status_code, 403)
        self.assertEqual(self.seller.post(reverse("envios_guia_rastrear", args=[guide.id]), {}, format="json").status_code, 403)
        self.assertEqual(self.store.get(reverse("envios_rastreo_estado")).status_code, 200)
        self.assertEqual(self.seller.get(reverse("envios_rastreo_estado")).status_code, 403)
        outsider = client_for(make_user("terminacion2@t.co", "TERMINACION"))
        self.assertEqual(outsider.get(reverse("envios_guias")).status_code, 403)
        self.assertEqual(self.manager.post(reverse("envios_guia_devolucion", args=[guide.id]), {}, format="json").status_code, 400)  # tiene permiso; la guía no está devuelta
        self.assertEqual(self.secretary.post(reverse("envios_guia_devolucion", args=[guide.id]), {}, format="json").status_code, 403)

    def test_resumen_de_pendientes_y_estados(self):
        self.sale()
        self.invoice_with_guide(1)
        summary = self.seller.get(reverse("envios_resumen")).json()
        self.assertEqual(summary["sin_guia"], {"total": 1, "con_atencion": 0, "vencidas": 0})
        self.assertEqual(next(e for e in summary["estados"] if e["codigo"] == catalog.PENDING)["cantidad"], 1)
