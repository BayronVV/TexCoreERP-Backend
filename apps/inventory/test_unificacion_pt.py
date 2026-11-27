"""Unificación de existencias de producto terminado (HU 6.5 / TE-170).

Fuente única: `terminado_stock`. En Inventario los PT enlazados a una referencia calculan su saldo
en vivo desde Producto Terminado, bloquean captura manual, alertan con el saldo unificado y conservan
los PT anteriores sin referencia como heredados fuera de existencias y alertas.
"""
import uuid
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.core.testing import PNG, client_for, make_user, today
from apps.finished import adjustments as finished_adjustments
from apps.finished.models import StockTerminado
from apps.inventory import catalog
from apps.inventory.finished_link import (
    ensure_finished_product_for_reference,
    unify_existing_finished_products,
)
from apps.inventory.models import Consecutivo, Movimiento, OrdenSalida, Producto
from apps.references import catalog as reference_catalog
from apps.references import services as reference_services
from apps.references.models import FichaLinea, FichaTecnica, Referencia, Variante
from apps.sales import catalog as sales_catalog
from apps.sales import invoicing
from apps.sales.models import Cliente, PrecioReferencia


class FinishedUnificationTests(TestCase):
    def setUp(self):
        self.storekeeper = make_user("almacen_170@t.co", "ALMACENISTA")
        self.manager = make_user("gerente_170@t.co", "GERENTE")
        self.seller = make_user("vendedor_170@t.co", "VENDEDOR")
        self.prod_user = make_user("produccion_170@t.co", "PRODUCCION")
        self.secretary = make_user("secretaria_170@t.co", "SECRETARIA")

        self.store_api = client_for(self.storekeeper)
        self.prod_api = client_for(self.prod_user)

        self.ref = reference_services.create_reference(
            user=self.prod_user,
            data={"nombre": "Clásico 5 bolsillos", "ajuste": "RECTO"},
            variants=[
                {"talla": "30", "color": "Azul índigo"},
                {"talla": "32", "color": "Azul índigo"},
                {"talla": "34", "color": "Azul claro"},
            ],
        )
        reference_services.add_images(
            self.ref, [SimpleUploadedFile("proto.png", PNG, "image/png")]
        )
        reference_services.change_state(self.ref, reference_catalog.ACTIVE)
        self.pt = Producto.objects.get(referencia=self.ref)
        self.variants = list(self.ref.variantes.order_by("id"))

        PrecioReferencia.objects.create(
            referencia=self.ref,
            costo_fabrica=45_000,
            precio_detal=89_900,
            precio_mayorista=72_000,
            actualizado_por=self.manager,
        )
        self.client_buyer = Cliente.objects.create(
            codigo="CLI-170-1",
            tipo_documento="CC",
            documento="1090777888",
            nombre="Boutique Centro",
            tipo=sales_catalog.CLIENT_WHOLESALE,
            ciudad="Cúcuta",
            direccion="Av 0 # 12-30",
            telefono="3005556677",
        )

    def _set_finished_stock(self, quantities):
        for variant, qty in zip(self.variants, quantities):
            StockTerminado.objects.update_or_create(variante=variant, defaults={"cantidad": qty})

    def _inventory_row(self, product_id=None):
        pid = product_id or self.pt.id
        rows = self.store_api.get(reverse("inventario_productos")).json()
        return next((row for row in rows if row["id"] == pid), None)

    def test_escenario1_misma_cifra_en_los_dos_modulos_sin_copiar_ni_n1(self):
        self._set_finished_stock([65, 80, 50])  # 195 prendas repartidas por talla y color
        row = self._inventory_row()
        self.assertIsNotNone(row)
        self.assertEqual(row["stock_actual"], "195.00")
        self.assertEqual(row["referencia"], self.ref.id)
        self.assertEqual(row["referencia_codigo"], self.ref.codigo)
        self.assertTrue(row["es_terminado_enlazado"])
        # No se guarda copia sincronizada en la columna física `stock_actual`.
        self.pt.refresh_from_db()
        self.assertEqual(self.pt.stock_actual, Decimal("0.00"))

        # Varias referencias enlazadas resuelven en un número constante de consultas (sin N+1).
        for idx in range(5):
            r = reference_services.create_reference(
                user=self.prod_user,
                data={"nombre": f"Extra Modelo {idx}", "ajuste": "SKINNY"},
                variants=[{"talla": "30", "color": "Negro"}],
            )
            StockTerminado.objects.create(variante=r.variantes.first(), cantidad=10 + idx)

        url = reverse("inventario_productos")
        self.store_api.get(url)
        with self.assertNumQueries(2):
            listed = self.store_api.get(url).json()
        self.assertGreaterEqual(len([p for p in listed if p["es_terminado_enlazado"]]), 6)

    def test_escenario2_venta_anulacion_y_ajuste_actualizan_ambas_vistas(self):
        self._set_finished_stock([100, 60, 35])  # 195
        self.assertEqual(self._inventory_row()["stock_actual"], "195.00")

        factura = invoicing.issue_invoice(
            user=self.seller,
            cliente=self.client_buyer.id,
            lineas=[{"variante": self.variants[0].id, "cantidad": 3}],
            fecha=today(),
            token=str(uuid.uuid4()),
        )
        self.assertEqual(self._inventory_row()["stock_actual"], "192.00")

        invoicing.cancel_invoice(user=self.manager, factura_id=factura.id, motivo="Devolución del cliente")
        self.assertEqual(self._inventory_row()["stock_actual"], "195.00")

        finished_adjustments.adjust_stock(
            user=self.secretary,
            motivo="SOBRANTE",
            observacion="Conteo físico de bodega",
            lineas=[{"variante": self.variants[2].id, "esperado": 35, "contado": 40}],
            token=uuid.uuid4(),
        )
        self.assertEqual(self._inventory_row()["stock_actual"], "200.00")

    def test_escenario3_movimiento_manual_rechazado_en_inventario(self):
        self._set_finished_stock([40, 0, 0])
        entry = self.store_api.post(
            reverse("inventario_ingresos"),
            {"producto": self.pt.id, "cantidad": "10", "fecha": today()},
            format="json",
        )
        self.assertEqual(entry.status_code, 400)
        self.assertIn("Producto Terminado", str(entry.json()["producto"][0]))

        tela = Producto.objects.create(
            codigo="TEL-170",
            nombre="Tela 170",
            tipo=catalog.RAW_MATERIAL,
            categoria=catalog.CAT_FABRIC,
            unidad="m",
            stock_actual=Decimal("500.00"),
            ancho_util=Decimal("1.50"),
            composicion="100% algodón",
        )
        ficha = FichaTecnica.objects.create(referencia=self.ref, lavado="ENZIMATICO")
        FichaLinea.objects.create(ficha=ficha, producto=tela, cantidad=Decimal("1.5"))
        generico = Producto.objects.create(
            codigo="PG-170",
            nombre="Genérico 170",
            tipo=catalog.GENERIC_PANTS,
            categoria=catalog.CAT_GENERIC,
            unidad="unidad",
        )
        # Rechaza usar el PT como línea de salida o como resultado de una orden en Inventario.
        out_line = self.store_api.post(
            reverse("inventario_ordenes"),
            {
                "tipo": "PRODUCCION",
                "fecha_salida": today(),
                "responsable": "Planta",
                "referencia": self.ref.id,
                "producto_resultado": generico.id,
                "cantidad_prendas": 10,
                "lineas": [{"producto": self.pt.id, "cantidad": "2"}],
            },
            format="json",
        )
        self.assertEqual(out_line.status_code, 400)
        self.assertIn("Producto Terminado", str(out_line.json()["lineas"][0]))

        out_res = self.store_api.post(
            reverse("inventario_ordenes"),
            {
                "tipo": "PRODUCCION",
                "fecha_salida": today(),
                "responsable": "Planta",
                "referencia": self.ref.id,
                "producto_resultado": self.pt.id,
                "cantidad_prendas": 10,
                "lineas": [{"producto": tela.id, "cantidad": "10"}],
            },
            format="json",
        )
        self.assertEqual(out_res.status_code, 400)
        self.assertIn("Producto Terminado", str(out_res.json()["producto_resultado"][0]))
        self.assertEqual(Movimiento.objects.filter(producto=self.pt).count(), 0)
        self.assertEqual(self._inventory_row()["stock_actual"], "40.00")

    def test_escenario4_alerta_stock_minimo_usa_saldo_producto_terminado(self):
        self.assertEqual(self.pt.stock_minimo, Decimal("30"))
        self._set_finished_stock([10, 10, 8])  # 28 < 30

        alerts = self.store_api.get(reverse("inventario_alertas")).json()["alerts"]
        hit = next((a for a in alerts if a["id"] == self.pt.id), None)
        self.assertIsNotNone(hit)
        self.assertEqual((hit["stock"], hit["threshold"], hit["severity"]), ("28.00", "30.00", "warning"))
        self.assertEqual((hit["referencia"], hit["referencia_codigo"]), (self.ref.id, self.ref.codigo))
        self.assertTrue(self._inventory_row()["bajo_minimo"])

        self._set_finished_stock([0, 0, 0])
        alerts_zero = self.store_api.get(reverse("inventario_alertas")).json()["alerts"]
        self.assertEqual(next(a for a in alerts_zero if a["id"] == self.pt.id)["severity"], "critical")

        self._set_finished_stock([15, 10, 6])  # 31 > 30
        alerts_ok = self.store_api.get(reverse("inventario_alertas")).json()["alerts"]
        self.assertIsNone(next((a for a in alerts_ok if a["id"] == self.pt.id), None))
        self.assertFalse(self._inventory_row()["bajo_minimo"])

        # Mínimo configurable por referencia desde Catálogo, y referencias en borrador/descontinuada no alertan.
        patch = self.store_api.patch(
            reverse("inventario_catalogo_detalle", args=[self.pt.id]),
            {"stock_minimo": "40"},
            format="json",
        )
        self.assertEqual(patch.status_code, 200)
        self.assertTrue(self._inventory_row()["bajo_minimo"])

        draft = reference_services.create_reference(
            user=self.prod_user,
            data={"nombre": "Borrador con variantes", "ajuste": "MOM"},
            variants=[{"talla": "28", "color": "Azul"}],
        )
        draft_pt = Producto.objects.get(referencia=draft)
        self.assertIsNone(next((a for a in self.store_api.get(reverse("inventario_alertas")).json()["alerts"] if a["id"] == draft_pt.id), None))

    def test_escenario5_pt_heredados_fuera_de_existencias_y_alertas_conservan_historial_y_lv(self):
        legacy = Producto.objects.create(
            codigo="PT-0099",
            nombre="MOD-SKINNY HEREDADO",
            tipo=catalog.FINISHED_PANTS,
            categoria=catalog.CAT_FINISHED,
            unidad="unidad",
            stock_actual=Decimal("25.00"),
            stock_minimo=Decimal("30.00"),
            heredado=False,
        )
        Movimiento.objects.create(
            producto=legacy,
            tipo=catalog.ENTRY,
            motivo=catalog.REASON_ORDER_RETURN,
            cantidad=Decimal("25.00"),
            stock_antes=Decimal("0.00"),
            stock_despues=Decimal("25.00"),
            fecha=today(),
            registrado_por=self.storekeeper,
        )
        lv_open = OrdenSalida.objects.create(
            codigo="LV-0099",
            tipo=catalog.ORDER_LAUNDRY,
            estado=catalog.STATUS_OPEN,
            fecha_salida=today(),
            responsable="Lavandería Histórica",
            ficha_tecnica="HIST-01",
            producto_resultado=legacy,
            cantidad_prendas=Decimal("25.00"),
            registrado_por=self.storekeeper,
        )

        # Ejecutar unificación tal como la migración 0008 (e idempotencia).
        unify_existing_finished_products(Producto, Consecutivo, Referencia, Variante)
        unify_existing_finished_products(Producto, Consecutivo, Referencia, Variante)

        legacy.refresh_from_db()
        self.assertTrue(legacy.heredado)
        self.assertIsNone(legacy.referencia_id)
        self.assertEqual(legacy.stock_actual, Decimal("25.00"))

        self.assertIsNone(self._inventory_row(legacy.id))
        self.assertTrue(
            any(row["id"] == legacy.id for row in self.store_api.get(reverse("inventario_productos"), {"incluir_heredados": "true"}).json())
        )
        self.assertIsNone(
            next((a for a in self.store_api.get(reverse("inventario_alertas")).json()["alerts"] if a["id"] == legacy.id), None)
        )
        self.assertIsNone(
            next((c for c in self.store_api.get(reverse("inventario_catalogo")).json() if c["id"] == legacy.id), None)
        )
        self.assertEqual(
            len(self.store_api.get(reverse("inventario_movimientos"), {"producto": legacy.id}).json()),
            1,
        )
        orders = self.store_api.get(reverse("inventario_ordenes"), {"tipo": "LAVANDERIA"}).json()
        self.assertEqual([o["id"] for o in orders], [lv_open.id])

        self.assertEqual(self.store_api.patch(reverse("inventario_catalogo_detalle", args=[legacy.id]), {"stock_minimo": "5"}, format="json").status_code, 400)
        self.assertEqual(self.store_api.delete(reverse("inventario_catalogo_detalle", args=[legacy.id])).status_code, 400)

    def test_alta_automatica_renombre_y_archivado_desde_referencias(self):
        # Borrador sin variantes no crea PT todavía.
        no_var = reference_services.create_reference(
            user=self.prod_user,
            data={"nombre": "Wide leg sin tallas", "ajuste": "WIDE_LEG"},
            variants=[],
        )
        self.assertFalse(Producto.objects.filter(referencia=no_var).exists())

        # Al agregar variantes se crea automáticamente su PT enlazado con mínimo 30.
        reference_services.update_reference(no_var, {"nombre": "Wide leg lavado"}, variants=[{"talla": "30", "color": "Gris"}])
        linked = Producto.objects.get(referencia=no_var)
        self.assertTrue(linked.codigo.startswith("PT-"))
        self.assertEqual(linked.stock_minimo, Decimal("30.00"))
        self.assertIn("Wide leg lavado", linked.nombre)

        # No se puede borrar ni renombrar directamente desde Catálogo de Inventario.
        self.assertEqual(self.store_api.delete(reverse("inventario_catalogo_detalle", args=[linked.id])).status_code, 400)
        self.assertEqual(
            self.store_api.patch(reverse("inventario_catalogo_detalle", args=[linked.id]), {"nombre": "Otro"}, format="json").status_code,
            400,
        )

        # Archivar referencia con saldo > 0 en Producto Terminado falla; en 0 archiva también su PT.
        self._set_finished_stock([5, 0, 0])
        reference_services.change_state(self.ref, reference_catalog.DISCONTINUED)
        self.assertEqual(self.prod_api.delete(reverse("referencia", args=[self.ref.id])).status_code, 400)

        finished_adjustments.adjust_stock(
            user=self.secretary,
            motivo="ERROR_CONTEO",
            observacion="Cero para archivar",
            lineas=[{"variante": self.variants[0].id, "esperado": 5, "contado": 0}],
            token=uuid.uuid4(),
        )
        self.assertEqual(self.prod_api.delete(reverse("referencia", args=[self.ref.id])).status_code, 204)
        self.assertFalse(Producto.objects.filter(pk=self.pt.id).exists())
        # Conservar idempotencia si se asegura sobre referencia restaurada o existente.
        restored_check = ensure_finished_product_for_reference(no_var)
        self.assertEqual(restored_check.id, linked.id)
