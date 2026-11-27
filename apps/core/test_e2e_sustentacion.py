"""
Pruebas integrales de sustentación (TE-187):
1. Escenario obligatorio de lavandería y calidad: 120 -> 115 conformes + 5 faltantes -> 8 marras = 107 disponibles para ingreso.
2. Controles del inventario final: tope de aptas, no doble ingreso/ajuste, sin saldos negativos, trazabilidad y atomicidad ante fallos.
3. Reportes coherentes antes y después de pago y devolución: factura emitida no cuenta como recaudo y fletes de devolución cuadran con la exportación.
"""
import uuid
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.core.testing import client_for, make_user
from apps.finished.models import IngresoTerminado, MovimientoTerminado, StockTerminado
from apps.finished.test_terminado import FinishedBase
from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Proveedor
from apps.production.models import Lote, LoteTalla, OrdenProduccion, RecetaLavado, RemisionLavanderia
from apps.production.test_modelos import ModelBase
from apps.quality.models import TipoDefecto
from apps.references import catalog as reference_catalog
from apps.references.models import Referencia, Variante
from apps.shipping import catalog as shipping_catalog
from apps.shipping.test_envios import ShippingBase


class LavanderiaCalidadInventarioE2ETests(ModelBase):
    """Escenario obligatorio (TE-187): 120 enviadas a lavandería -> 115 recibidas (5 faltantes) -> 8 marras -> 107 aptas ingresables."""

    def test_te187_escenario_lavanderia_calidad_120_a_107_disponibles(self):
        today = timezone.localdate()
        Referencia.objects.filter(pk=self.ref["id"]).update(estado=reference_catalog.ACTIVE)
        v30 = Variante.objects.get(referencia_id=self.ref["id"], talla="30")
        v32 = Variante.objects.create(referencia_id=self.ref["id"], talla="32", color="Azul oscuro")

        order = self.make_order(code="OP-0187", quantity=120)
        lot = self.make_lot(order, number=1, quantity=120)
        LoteTalla.objects.create(lote=lot, variante=v30, talla="30", color="Azul oscuro", cantidad=60)
        LoteTalla.objects.create(lote=lot, variante=v32, talla="32", color="Azul oscuro", cantidad=60)

        laundry = Proveedor.objects.create(
            nit="900187001",
            nit_dv="4",
            razon_social="Lavandería Industrial Sustentación S.A.S.",
            categoria=inventory_catalog.CAT_LAUNDRY,
            ciudad="Medellín",
            contacto="Marta Lucía",
            telefono="3120001870",
        )
        recipe = RecetaLavado.objects.create(
            codigo="REC-E2E-187",
            nombre="Lavado enzimático 187",
            categoria="Enzimático",
            temperatura_proceso="55 °C",
            duracion_horas=18,
            tarifa_sugerida=Decimal("3200.00"),
        )

        prod_client = client_for(self.boss)
        finisher_client = client_for(make_user("e2e_term@t.co", "TERMINACION"))
        secretary_client = client_for(make_user("e2e_sec@t.co", "SECRETARIA"))
        manager_client = client_for(make_user("e2e_ger@t.co", "GERENTE"))

        # 1. Enviar exactamente 120 prendas a lavandería
        rem_res = prod_client.post(
            reverse("lavanderia_remisiones"),
            {
                "lavanderia_id": laundry.id,
                "fecha_emision": str(today),
                "transportador_nombre": "Carlos Conductor",
                "vehiculo_placa": "E2E-187",
                "tulas_bultos": 3,
                "peso_kg": "68.50",
                "lotes": [{"lote_id": lot.id, "cantidad": 120, "receta_id": recipe.codigo}],
            },
            format="json",
        )
        self.assertEqual(rem_res.status_code, 201, rem_res.content)
        rem_id = rem_res.json()["id"]
        rem_lote_id = RemisionLavanderia.objects.get(pk=rem_id).lotes_detalle.first().id

        # 2. Recibir 115 conformes y registrar 5 faltantes (merma)
        rec_res = prod_client.post(
            reverse("lavanderia_recepciones"),
            {
                "remision_id": rem_id,
                "fecha_recepcion": str(today),
                "factura_remision_externa": "FAC-EXT-187",
                "lotes": [
                    {
                        "remision_lote_id": rem_lote_id,
                        "cantidad_recibida_conforme": 115,
                        "cantidad_merma": 5,
                        "motivo_merma": "5 prendas faltantes en conteo de retorno",
                        "cantidad_danada": 0,
                        "costo_unitario_prenda": "35000.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(rec_res.status_code, 201, rec_res.content)
        rec_body = rec_res.json()
        self.assertEqual(rec_body["total_recibido_conforme"], 115)
        self.assertEqual(rec_body["total_merma"], 5)
        self.assertEqual(rec_body["total_danadas"], 0)
        # TE-172: la cantidad original del lote (120) no se sobrescribe
        lot.refresh_from_db()
        self.assertEqual(lot.cantidad, 120)

        # 3. Inspeccionar en Calidad: clasificar 8 de las 115 recibidas como marras -> 107 aptas
        d1 = TipoDefecto.objects.create(codigo="DEF-E1", nombre="Costura abierta", corregible=True, activo=True)
        d2 = TipoDefecto.objects.create(codigo="DEF-E2", nombre="Mancha de cloro", corregible=False, activo=True)
        ins_res = finisher_client.post(
            reverse("calidad_inspecciones"),
            {
                "lote": lot.id,
                "aptas": 107,
                "defectos": [
                    {"defecto": d1.id, "cantidad": 5, "nota": "Pretina"},
                    {"defecto": d2.id, "cantidad": 3, "nota": "Bota delantera"},
                ],
                "observaciones": "Inspección escenario 187",
            },
            format="json",
        )
        self.assertEqual(ins_res.status_code, 201, ins_res.content)
        ins_body = ins_res.json()
        self.assertEqual((ins_body["cantidad_recibida"], ins_body["aptas"], ins_body["marras"]), (115, 107, 8))

        # 4. Consultar cuántas quedan disponibles para ingresar al inventario final: exactamente 107
        pending = secretary_client.get(reverse("terminado_pendientes")).json()
        target = next(row for row in pending if row["inspeccion"] == ins_body["id"])
        self.assertEqual(target["aptas"], 107)

        # No permite ingresar 108 ni menos de 107
        self.assertEqual(
            secretary_client.post(
                reverse("terminado_ingresos"),
                {"inspeccion": ins_body["id"], "lineas": [{"variante": v30.id, "cantidad": 58}, {"variante": v32.id, "cantidad": 50}]},
                format="json",
            ).status_code,
            400,
        )

        # Ingreso exacto de las 107 aptas
        entry_res = secretary_client.post(
            reverse("terminado_ingresos"),
            {"inspeccion": ins_body["id"], "lineas": [{"variante": v30.id, "cantidad": 57}, {"variante": v32.id, "cantidad": 50}]},
            format="json",
        )
        self.assertEqual(entry_res.status_code, 201, entry_res.content)
        self.assertEqual(StockTerminado.objects.get(variante=v30).cantidad, 57)
        self.assertEqual(StockTerminado.objects.get(variante=v32).cantidad, 50)
        self.assertEqual(sum(StockTerminado.objects.values_list("cantidad", flat=True)), 107)

        # 5. Cada diferencia conserva su historial consultable por Gerencia
        rec_detail = manager_client.get(reverse("lavanderia_recepcion_detail", args=[rec_body["id"]])).json()
        self.assertEqual(rec_detail["lotes_detalle"][0]["cantidad_enviada"], 120)
        self.assertEqual(rec_detail["lotes_detalle"][0]["cantidad_recibida_conforme"], 115)
        self.assertEqual(rec_detail["lotes_detalle"][0]["cantidad_merma"], 5)
        self.assertIn("faltantes", rec_detail["lotes_detalle"][0]["motivo_merma"])

        ins_detail = manager_client.get(reverse("calidad_inspeccion", args=[ins_body["id"]])).json()
        self.assertEqual(ins_detail["marras"], 8)
        self.assertEqual([(d["cantidad"], d["defecto_nombre"]) for d in ins_detail["detalle"]], [(5, "Costura abierta"), (3, "Mancha de cloro")])
        self.assertEqual(OrdenProduccion.objects.get(pk=order.id).cantidad, 120)
        self.assertEqual(Lote.objects.get(pk=lot.id).cantidad, 120)


class ControlesInventarioFinalTests(FinishedBase):
    """Controles del inventario final (TE-187): topes, no duplicidad, no negativos, trazabilidad y cero huérfanos ante fallos."""

    def test_te187_controles_inventario_final_integrales(self):
        # 1. No se ingresan más aptas que las de la inspección (50 aptas)
        over_entry = self.enter(lines=self.lines((self.v30, 30), (self.v32, 21)))
        self.assertEqual(over_entry.status_code, 400)
        self.assertEqual(MovimientoTerminado.objects.count(), 0)
        self.assertEqual(IngresoTerminado.objects.count(), 0)

        # 2. Ingreso válido y rechazo del doble ingreso sobre el mismo lote/inspección
        ok_entry = self.enter()
        self.assertEqual(ok_entry.status_code, 201)
        duplicate_entry = self.enter()
        self.assertEqual(duplicate_entry.status_code, 409)
        self.assertEqual(self.stock(self.v30), 20)

        # 3. Un ajuste no deja existencias negativas y si falla no deja movimientos huérfanos
        moves_before = MovimientoTerminado.objects.count()
        neg_adj = self.secretary.post(
            reverse("terminado_ajustes"),
            {
                "motivo": "PERDIDA",
                "observacion": "Intento de dejar stock en valor negativo",
                "token": str(uuid.uuid4()),
                "lineas": [{"variante": self.v30.id, "esperado": 20, "contado": -1}],
            },
            format="json",
        )
        self.assertEqual(neg_adj.status_code, 400)
        self.assertEqual(MovimientoTerminado.objects.count(), moves_before)
        self.assertEqual(self.stock(self.v30), 20)

        # 4. Ajuste válido guarda usuario, fecha, motivo, saldo anterior y posterior, y su token no se repite
        token = str(uuid.uuid4())
        adj_body = {
            "motivo": "PERDIDA",
            "observacion": "Dos prendas no aparecieron en el conteo de revisión",
            "token": token,
            "lineas": [{"variante": self.v30.id, "esperado": 20, "contado": 18}],
        }
        adj_ok = self.secretary.post(reverse("terminado_ajustes"), adj_body, format="json")
        self.assertEqual(adj_ok.status_code, 201, adj_ok.content)
        adj_json = adj_ok.json()
        self.assertEqual(adj_json["motivo"], "PERDIDA")
        self.assertTrue(adj_json["realizado_por_nombre"])
        self.assertTrue(adj_json["fecha"])
        self.assertEqual((adj_json["lineas"][0]["stock_antes"], adj_json["lineas"][0]["stock_contado"]), (20, 18))

        last_move = MovimientoTerminado.objects.filter(variante=self.v30).order_by("id").last()
        self.assertEqual((last_move.saldo_antes, last_move.saldo_despues, last_move.cantidad), (20, 18, -2))
        self.assertTrue(last_move.ajuste_id and last_move.usuario_id and last_move.created_at)

        # Doble clic con el mismo token responde 409 y no modifica saldos
        self.assertEqual(self.secretary.post(reverse("terminado_ajustes"), adj_body, format="json").status_code, 409)
        self.assertEqual(self.stock(self.v30), 18)

        # Ningún movimiento queda sin documento origen (ingreso, ajuste o factura)
        self.assertFalse(
            MovimientoTerminado.objects.filter(ingreso__isnull=True, ajuste__isnull=True, factura__isnull=True).exists()
        )


class ReportesCoherentesE2ETests(ShippingBase):
    """Escenario obligatorio (TE-187): reportes antes y después de pago y devolución, coherencia con exportación y fletes."""

    def test_te187_reportes_coherentes_antes_y_despues_de_pago_y_devolucion(self):
        inv1, g1 = self.invoice_with_guide(1)
        inv2, g2 = self.invoice_with_guide(2)
        self.dispatch([g1, g2])
        self.assertEqual(self.store.patch(reverse("envios_guia_flete", args=[g2.id]), {"valor_flete": 14_000}, format="json").status_code, 200)

        url_report = reverse("reportes-gerencial")

        # 1. Antes de conciliar: factura emitida NO cuenta como dinero recaudado
        before = self.manager.get(url_report).json()
        k_before = before["kpis"]
        expected_total = inv1.total + inv2.total
        self.assertEqual(k_before["facturas_emitidas"], 2)
        self.assertEqual(k_before["ingresos_totales"], expected_total)
        self.assertEqual(k_before["recaudado_periodo"], 0)
        self.assertEqual(k_before["pendiente_recaudo_periodo"], expected_total)
        self.assertEqual(k_before["saldo_financiero_empresa"], 0)
        self.assertEqual(k_before["devoluciones_guias"], 0)
        self.assertEqual(k_before["flete_devoluciones_total"], 0)
        # Coherencia KPIs vs detalle exportable
        self.assertEqual(sum(r["total"] for r in before["ventas_detalle"]), expected_total)
        self.assertEqual(sum(r["ingresos_totales"] for r in before["ventas_por_referencia"]), expected_total)

        # 2. Entregar guía 1 y confirmar pago -> sube recaudado y caja; factura 2 sigue por cobrar
        self.assertEqual(self.state(g1, shipping_catalog.DELIVERED).status_code, 200)
        self.assertEqual(
            self.manager.post(reverse("ventas_factura_conciliar", args=[inv1.id]), {"nota": "Giro verificado"}, format="json").status_code,
            200,
        )
        after_pay = self.manager.get(url_report).json()
        k_pay = after_pay["kpis"]
        self.assertEqual(k_pay["recaudado_periodo"], inv1.total)
        self.assertEqual(k_pay["pendiente_recaudo_periodo"], inv2.total)
        self.assertEqual(k_pay["saldo_financiero_empresa"], inv1.total)
        self.assertEqual(k_pay["devoluciones_guias"], 0)

        # 3. Marcar guía 2 devuelta y registrar devolución física -> pendiente baja a 0, caja no cambia y flete aparece en devoluciones
        self.assertEqual(self.state(g2, shipping_catalog.RETURNED, "Cliente no recibió pedido").status_code, 200)
        self.assertEqual(self.store.post(reverse("envios_guia_devolucion", args=[g2.id]), {}, format="json").status_code, 200)

        after_return = self.manager.get(url_report).json()
        k_ret = after_return["kpis"]
        self.assertEqual(k_ret["recaudado_periodo"], inv1.total)
        self.assertEqual(k_ret["pendiente_recaudo_periodo"], 0)
        self.assertEqual(k_ret["saldo_financiero_empresa"], inv1.total)
        self.assertEqual(k_ret["devoluciones_guias"], 1)
        self.assertEqual(k_ret["flete_devoluciones_total"], 14_000)

        # La tabla de devoluciones por vendedor (y su exportación) cuadra exactamente con los KPIs
        dev_rows = after_return["devoluciones_por_vendedor"]
        self.assertEqual(len(dev_rows), 1)
        self.assertEqual(dev_rows[0]["guias_devueltas"], 1)
        self.assertEqual(dev_rows[0]["flete_vendedor"], 14_000)
        self.assertEqual(sum(r["total"] for r in after_return["ventas_detalle"]), expected_total)
