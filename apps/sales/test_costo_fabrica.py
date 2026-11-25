"""Pruebas de cálculo del costo de fábrica desde producción, alertas e historial (HU 4.7 / TE-174)."""
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.testing import client_for, make_user
from apps.inventory import catalog as inv_catalog
from apps.inventory.models import OrdenLinea, Proveedor
from apps.production import catalog as prod_catalog
from apps.production.models import EtapaLote, RecetaLavado, TarifaManoObra
from apps.production.recepcion_services import create_laundry_reception
from apps.production.remisiones_services import create_laundry_remission
from apps.production.test_modelos import ModelBase
from apps.quality import services as quality_services
from apps.references import catalog as ref_catalog
from apps.references.models import Referencia
from apps.users.models import AuditRecord

from . import catalog, pricing
from .models import DetalleVenta, FacturaVenta, HistorialPrecioReferencia, PrecioReferencia
from .test_ventas import SalesBase


class FactoryCostMixin(ModelBase):
    """Utilidad para construir órdenes terminadas completas (producción, lavandería y calidad)."""

    def make_finished_order_with_cost(
        self,
        *,
        reference,
        code,
        quantity=100,
        aptas=100,
        material_total=Decimal("3000000.00"),
        labor_seconds_per_stage=24000,
        labor_rate_per_minute=Decimal("1000.0000"),
        wash_rate=Decimal("4000.00"),
        days_ago=0,
        include_tariffs=True,
    ):
        today = timezone.localdate()
        target_date = today - timedelta(days=days_ago)

        from apps.inventory.models import OrdenSalida
        from apps.production.models import OrdenProduccion
        from apps.production import tracking

        out = OrdenSalida.objects.create(
            codigo=code,
            tipo=inv_catalog.ORDER_PRODUCTION,
            fecha_salida=target_date,
            responsable="Jefe de Producción",
            referencia=reference,
            ficha_tecnica=reference.codigo,
            producto_resultado=self.tela,
            cantidad_prendas=Decimal(quantity),
            registrado_por=self.boss,
        )
        if material_total is not None:
            OrdenLinea.objects.create(
                orden=out,
                producto=self.tela,
                cantidad=Decimal("100.000"),
                costo_unitario=material_total / Decimal("100.000"),
            )
        else:
            OrdenLinea.objects.create(
                orden=out,
                producto=self.tela,
                cantidad=Decimal("100.000"),
                costo_unitario=None,
            )

        order = OrdenProduccion.objects.create(
            orden_salida=out,
            codigo=code,
            referencia=reference,
            cantidad=quantity,
            creado_por=self.boss,
        )
        lot = self.make_lot(order, number=1, quantity=quantity)
        tracking.create_stages([lot])
        EtapaLote.objects.filter(lote=lot).update(
            estado=prod_catalog.STAGE_DONE,
            inicio_at=timezone.now() - timedelta(days=days_ago, hours=5),
            fin_at=timezone.now() - timedelta(days=days_ago),
            acumulado_s=labor_seconds_per_stage,
        )

        if include_tariffs:
            for stage_code, _ in prod_catalog.STAGES:
                TarifaManoObra.objects.get_or_create(
                    etapa=stage_code,
                    vigente_desde=target_date - timedelta(days=10),
                    defaults={"costo_minuto": labor_rate_per_minute, "creado_por": self.boss},
                )

        laundry, _ = Proveedor.objects.get_or_create(
            nit="901888777",
            defaults={
                "nit_dv": "1",
                "razon_social": "Lavandería Real SAS",
                "categoria": inv_catalog.CAT_LAUNDRY,
                "ciudad": "Itagüí",
            },
        )
        recipe_code = f"REC-{code}"
        receta, _ = RecetaLavado.objects.get_or_create(
            codigo=recipe_code,
            defaults={
                "nombre": f"Proceso {code}",
                "duracion_horas": 12,
                "tarifa_sugerida": wash_rate,
            },
        )

        rem = create_laundry_remission(
            user=self.boss,
            lavanderia_id=laundry.id,
            lotes_seleccionados=[{"lote_id": lot.id, "cantidad": quantity, "receta_id": receta.codigo}],
            fecha_emision=target_date,
        )
        lost = quantity - aptas
        recepcion_item = {
            "lote_id": lot.id,
            "cantidad_recibida_conforme": quantity,
            "cantidad_merma": 0,
            "cantidad_danada": 0,
            "costo_unitario_prenda": "25000.00",
        }
        create_laundry_reception(
            user=self.boss,
            remision_id=rem["id"],
            fecha_recepcion=target_date,
            factura_remision_externa=f"FAC-{code}",
            lotes_recibidos=[recepcion_item],
        )

        defectos = []
        if lost > 0:
            from apps.quality.models import TipoDefecto

            defect, _ = TipoDefecto.objects.get_or_create(
                codigo="DEF-TE174",
                defaults={"nombre": "Tono fuera de rango", "corregible": False},
            )
            defectos = [{"defecto": defect.id, "cantidad": lost}]

        quality_services.register_inspection(
            user=self.boss,
            lote_id=lot.id,
            aptas=aptas,
            defectos=defectos,
            fecha=target_date,
        )
        return order


class FactoryCostCalculationTests(FactoryCostMixin):
    """Pruebas del cálculo puro/servicio (Escenarios 1, 3 y varias órdenes / redondeos)."""

    def setUp(self):
        super().setUp()
        self.reference = Referencia.objects.create(
            codigo="REF-COST-1",
            nombre="Jean Bootcut Real",
            ajuste="BOTA_CAMPANA",
            estado=ref_catalog.ACTIVE,
        )
        self.manager = client_for(make_user("gerente_costos@t.co", "GERENTE"))

    def test_escenario_1_sugerencia_desde_una_orden_exacta(self):
        # 100 aptas, $3.000.000 materiales, 3 etapas * 24000s (400 min * $1.000) = $1.200.000 MO,
        # 100 conformes * $4.000 lavandería = $400.000 -> total $4.600.000 / 100 = $46.000 por prenda.
        self.make_finished_order_with_cost(
            reference=self.reference,
            code="OP-TE174-01",
            quantity=100,
            aptas=100,
            material_total=Decimal("3000000.00"),
            labor_seconds_per_stage=24000,
            labor_rate_per_minute=Decimal("1000.0000"),
            wash_rate=Decimal("4000.00"),
        )

        rows = self.manager.get(reverse("ventas_precios")).json()
        mine = next(r for r in rows if r["referencia"] == self.reference.id)
        self.assertEqual(mine["costo_calculado"], 46_000)
        calc = mine["calculo_produccion"]
        self.assertEqual(calc["estado"], catalog.CALC_STATUS_OK)
        self.assertEqual(calc["total_prendas_aptas"], 100)
        self.assertEqual(calc["ordenes_completas"], 1)
        self.assertEqual(len(calc["ordenes"]), 1)
        order_row = calc["ordenes"][0]
        self.assertEqual(order_row["codigo"], "OP-TE174-01")
        self.assertEqual(order_row["materiales"], "3000000.00")
        self.assertEqual(order_row["mano_obra"], "1200000.00")
        self.assertEqual(order_row["lavanderia"], "400000.00")
        self.assertEqual(order_row["costo_total"], "4600000.00")
        self.assertEqual(order_row["costo_por_prenda"], 46_000)

    def test_varias_ordenes_promedio_ponderado_redondeo_y_ventana_90_dias(self):
        # Orden 1: 100 aptas, $4.600.000 total ($46.000/u)
        self.make_finished_order_with_cost(
            reference=self.reference,
            code="OP-TE174-A",
            quantity=100,
            aptas=100,
            material_total=Decimal("3000000.00"),
            labor_seconds_per_stage=24000,
            wash_rate=Decimal("4000.00"),
            days_ago=5,
        )
        # Orden 2: 50 conformes / 45 aptas, materiales $1.500.000 + MO (3*6000s/60*$1000=$300.000) + lav (50*$2.000=$100.000) = $1.900.000
        self.make_finished_order_with_cost(
            reference=self.reference,
            code="OP-TE174-B",
            quantity=50,
            aptas=45,
            material_total=Decimal("1500000.00"),
            labor_seconds_per_stage=6000,
            wash_rate=Decimal("2000.00"),
            days_ago=1,
        )
        # Orden 3: fuera de ventana (95 días atrás) -> ignorada
        self.make_finished_order_with_cost(
            reference=self.reference,
            code="OP-TE174-OLD",
            quantity=100,
            aptas=100,
            material_total=Decimal("9000000.00"),
            labor_seconds_per_stage=24000,
            wash_rate=Decimal("5000.00"),
            days_ago=95,
        )

        # Ponderado = ($4.600.000 + $1.900.000) / (100 + 45) = 6.500.000 / 145 = 44.827,586 -> 44.828
        calc = pricing.calculate_references_costs([self.reference.id])[self.reference.id]
        self.assertEqual(calc["ordenes_completas"], 2)
        self.assertEqual(calc["total_prendas_aptas"], 145)
        self.assertEqual(calc["costo_calculado"], 44_828)

    def test_escenario_3_costo_incompleto_sin_tarifa_o_sin_costo_material(self):
        self.make_finished_order_with_cost(
            reference=self.reference,
            code="OP-TE174-INC1",
            quantity=50,
            aptas=50,
            material_total=Decimal("1000000.00"),
            include_tariffs=False,
        )
        calcs = pricing.calculate_references_costs([self.reference.id])
        self.assertEqual(calcs[self.reference.id]["estado"], catalog.CALC_STATUS_INCOMPLETE)
        self.assertIsNone(calcs[self.reference.id]["costo_calculado"])
        self.assertTrue(any("tarifa" in item.lower() for item in calcs[self.reference.id]["faltantes"]))

        resp = self.manager.post(reverse("ventas_precio_aplicar_costo", args=[self.reference.id]), {}, format="json")
        self.assertEqual(resp.status_code, 400)

        ref2 = Referencia.objects.create(
            codigo="REF-COST-2",
            nombre="Jean Sin Costo Material",
            ajuste="RECTO",
            estado=ref_catalog.ACTIVE,
        )
        self.make_finished_order_with_cost(
            reference=ref2,
            code="OP-TE174-INC2",
            quantity=50,
            aptas=50,
            material_total=None,
            include_tariffs=True,
        )

        calcs2 = pricing.calculate_references_costs([ref2.id])
        self.assertEqual(calcs2[ref2.id]["estado"], catalog.CALC_STATUS_INCOMPLETE)
        self.assertIsNone(calcs2[ref2.id]["costo_calculado"])
        self.assertTrue(any("no tiene costo" in item.lower() for item in calcs2[ref2.id]["faltantes"]))


class FactoryCostPricingFlowTests(SalesBase, FactoryCostMixin):
    """Pruebas de flujo completo: aplicar costo, alertas, historial, piso en venta, permisos y N+1."""

    def test_escenario_2_y_4_aplicar_costo_historial_y_alerta_bajo_costo(self):
        # Precio inicial en SalesBase: costo=47.000, mayorista=68.000, detal=89.900.
        # Bajamos temporalmente a costo=40.000, mayorista=45.000, detal=70.000 y emitimos factura previa.
        put_url = reverse("ventas_precio", args=[self.ref["id"]])
        self.assertEqual(
            self.manager.put(
                put_url,
                {"costo_fabrica": 40_000, "precio_mayorista": 45_000, "precio_detal": 70_000},
                format="json",
            ).status_code,
            200,
        )
        old_invoice_id = self.sell([(self.v30, 1, 0)]).json()["id"]
        self.assertEqual(DetalleVenta.objects.get(factura_id=old_invoice_id).costo_fabrica, 40_000)

        # Creamos orden terminada con costo real de $46.000/prenda (> mayorista 45.000 -> alerta bajo costo)
        ref_obj = Referencia.objects.get(pk=self.ref["id"])
        self.make_finished_order_with_cost(
            reference=ref_obj,
            code="OP-TE174-FLOW",
            quantity=100,
            aptas=100,
            material_total=Decimal("3000000.00"),
            labor_seconds_per_stage=24000,
            wash_rate=Decimal("4000.00"),
        )

        # Escenario 4: alerta de precio por debajo del costo calculado
        rows = self.manager.get(reverse("ventas_precios")).json()
        row = next(r for r in rows if r["referencia"] == ref_obj.id)
        self.assertEqual(row["costo_calculado"], 46_000)
        self.assertEqual(row["diferencia_costo"], 6_000)
        self.assertTrue(row["costo_desactualizado"])
        self.assertTrue(row["precio_bajo_costo"])

        # No deja aplicar sin subir el mayorista
        apply_url = reverse("ventas_precio_aplicar_costo", args=[ref_obj.id])
        blocked = self.manager.post(apply_url, {}, format="json")
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(PrecioReferencia.objects.get(referencia=ref_obj).costo_fabrica, 40_000)

        # Al subir el mayorista a 68.000 sí aplica el costo calculado ($46.000)
        applied = self.manager.post(apply_url, {"precio_mayorista": 68_000}, format="json")
        self.assertEqual(applied.status_code, 200, applied.content)
        body = applied.json()
        self.assertEqual(body["costo_fabrica"], 46_000)
        self.assertEqual(body["precio_mayorista"], 68_000)
        self.assertFalse(body["costo_desactualizado"])
        self.assertFalse(body["precio_bajo_costo"])

        # Factura ya emitida conserva su costo histórico (40.000), nueva venta respeta piso 46.000
        self.assertEqual(DetalleVenta.objects.get(factura_id=old_invoice_id).costo_fabrica, 40_000)
        self.assertEqual(FacturaVenta.objects.count(), 1)
        # Mayorista 68.000 con 35% desc sería < 46.000 (y además tope mayorista es 15%; probamos floor con precio=47.000 y desc 5%):
        self.assertEqual(
            self.manager.post(apply_url, {"precio_mayorista": 47_000}, format="json").status_code,
            200,
        )
        too_low = self.sell([(self.v32, 1, 5)])  # 47.000 * 0,95 = 44.650 < 46.000
        self.assertEqual(too_low.status_code, 400)
        self.assertIn("46.000", str(too_low.json()))

        # Historial registra PUT manual + los 2 aplicar desde producción
        hist_resp = self.manager.get(reverse("ventas_precio_historial", args=[ref_obj.id]))
        self.assertEqual(hist_resp.status_code, 200)
        history = hist_resp.json()
        self.assertGreaterEqual(len(history), 3)
        latest = history[0]
        self.assertEqual(latest["origen"], catalog.PRICE_SOURCE_PRODUCTION)
        self.assertEqual(latest["costo_fabrica_nuevo"], 46_000)
        self.assertEqual(latest["ordenes_respaldo"], ["OP-TE174-FLOW"])
        self.assertTrue(latest["usuario_nombre"])
        self.assertEqual(HistorialPrecioReferencia.objects.filter(precio_referencia__referencia=ref_obj).count(), len(history))

        # Auditoría registró precio.aplicar_costo
        self.assertTrue(AuditRecord.objects.filter(action="precio.aplicar_costo", result=AuditRecord.EXITO).exists())

    def test_escenario_5_permisos_vendedor_no_ve_calculo_ni_puede_aplicar(self):
        ref_obj = Referencia.objects.get(pk=self.ref["id"])
        self.make_finished_order_with_cost(reference=ref_obj, code="OP-TE174-PERM")

        rows = self.seller.get(reverse("ventas_precios")).json()
        mine = next(r for r in rows if r["referencia"] == ref_obj.id)
        self.assertEqual((mine["costo_fabrica"], mine["precio_mayorista"], mine["precio_detal"]), (47_000, 68_000, 89_900))
        self.assertNotIn("costo_calculado", mine)
        self.assertNotIn("calculo_produccion", mine)
        self.assertNotIn("diferencia_costo", mine)

        self.assertEqual(
            self.seller.post(reverse("ventas_precio_aplicar_costo", args=[ref_obj.id]), {}, format="json").status_code,
            403,
        )
        self.assertEqual(
            self.seller.get(reverse("ventas_precio_historial", args=[ref_obj.id])).status_code,
            403,
        )

    def test_consultas_sin_n_plus_1_al_listar_precios(self):
        ref_obj = Referencia.objects.get(pk=self.ref["id"])
        self.make_finished_order_with_cost(reference=ref_obj, code="OP-TE174-Q1")
        url = reverse("ventas_precios")
        self.assertEqual(self.manager.get(url).status_code, 200)
        with CaptureQueriesContext(connection) as first_ctx:
            self.assertEqual(self.manager.get(url).status_code, 200)

        for idx in (2, 3):
            extra_ref = Referencia.objects.create(
                codigo=f"REF-Q-{idx}",
                nombre=f"Jean Query {idx}",
                ajuste="RECTO",
                estado=ref_catalog.ACTIVE,
            )
            self.make_finished_order_with_cost(reference=extra_ref, code=f"OP-TE174-Q{idx}")

        with CaptureQueriesContext(connection) as second_ctx:
            rows = self.manager.get(url).json()
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(len(second_ctx), len(first_ctx))

