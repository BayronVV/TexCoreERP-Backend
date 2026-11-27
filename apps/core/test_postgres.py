"""
Pruebas específicas de compatibilidad y garantías en PostgreSQL:
1. Detección de bloqueos SELECT ... FOR UPDATE con LEFT OUTER JOIN nullable (of=('self',)).
2. Atomicidad autónoma de servicios que usan select_for_update (assign_guide_to en TransactionTestCase).
3. Refresco y consulta de vistas SQL materializadas de reportes (CONCURRENTLY vs bloque atómico).
4. Rechazo de límites de longitud en la API con HTTP 400 antes de provocar DataError (500).
"""
from decimal import Decimal

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.testing import client_for, make_user
from apps.finished import services as finished_services
from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import OrdenSalida, Producto, Proveedor
from apps.production import catalog as production_catalog
from apps.production.models import Lote, OrdenProduccion, RemisionLavanderia, RemisionLote
from apps.production.recepcion_services import create_laundry_reception
from apps.quality import services as quality_services
from apps.references import catalog as reference_catalog
from apps.references.models import Referencia, Variante
from apps.reports.services import build_management_report, refresh_materialized_views
from apps.sales import catalog as sales_catalog
from apps.sales.models import Cliente, FacturaVenta
from apps.shipping import catalog as shipping_catalog
from apps.shipping import services as shipping_services
from apps.shipping.models import EventoGuia, Guia


class PostgresVerificationTests(TransactionTestCase):
    """Corre fuera de una transacción externa para detectar fallos reales de PostgreSQL del Sprint 3."""

    serialized_rollback = True

    def test_sprint3_fallo1_bloqueo_of_self_con_outer_join_nullable(self):
        """
        Verifica el arreglo 3c11d18 del Sprint 3:
        En PostgreSQL, select_for_update() junto a select_related() sobre FK nullable (receta=None)
        falla con 'FOR UPDATE cannot be applied to the nullable side of an outer join' si falta of=('self',).
        """
        user = make_user("pg_prod@t.co", "PRODUCCION")
        store = make_user("pg_almacen@t.co", "ALMACENISTA")
        finisher = make_user("pg_term@t.co", "TERMINACION")
        secretary = make_user("pg_sec@t.co", "SECRETARIA")
        today = timezone.localdate()

        tela = Producto.objects.create(
            codigo="PG-TEL-1",
            nombre="Denim PG",
            tipo=inventory_catalog.RAW_MATERIAL,
            categoria=inventory_catalog.CAT_FABRIC,
            unidad="m",
            stock_actual=Decimal("100.00"),
            ancho_util=Decimal("1.50"),
            composicion="100% algodón",
        )
        ref = Referencia.objects.create(
            codigo="REF-PG-1",
            nombre="Jean Verificación PG",
            ajuste="RECTO",
            estado=reference_catalog.ACTIVE,
        )
        variante = Variante.objects.create(referencia=ref, talla="32", color="Azul")
        orden_salida = OrdenSalida.objects.create(
            codigo="OP-PG-1",
            tipo=inventory_catalog.ORDER_PRODUCTION,
            fecha_salida=today,
            responsable="Planta",
            referencia=ref,
            ficha_tecnica=ref.codigo,
            producto_resultado=tela,
            cantidad_prendas=Decimal("20"),
            registrado_por=user,
        )
        orden = OrdenProduccion.objects.create(
            orden_salida=orden_salida,
            codigo="OP-PG-1",
            referencia=ref,
            cantidad=20,
            creado_por=user,
        )
        lote = Lote.objects.create(
            orden=orden,
            numero=1,
            codigo="OP-PG-1-L01",
            cantidad=20,
            estado_inventario=production_catalog.LOT_INV_IN_TRANSIT,
        )
        lavanderia = Proveedor.objects.create(
            nit="900555111",
            razon_social="Lavandería PG SAS",
            categoria=inventory_catalog.CAT_LAUNDRY,
        )
        remision = RemisionLavanderia.objects.create(
            codigo="REM-LAV-PG-0001",
            lavanderia=lavanderia,
            fecha_emision=today,
            transportador_nombre="Carlos",
            vehiculo_placa="PG123",
            tulas_bultos=1,
            peso_kg=Decimal("8.00"),
            estado=production_catalog.REMISSION_IN_TRANSIT,
            creado_por=user,
        )
        # receta=None fuerza el LEFT OUTER JOIN nullable que rompía PostgreSQL sin of=('self',)
        rl = RemisionLote.objects.create(remision=remision, lote=lote, cantidad=20, receta=None)

        if connection.vendor == "postgresql":
            with transaction.atomic():
                sql = str(
                    RemisionLote.objects.select_for_update(of=("self",))
                    .select_related("lote", "receta")
                    .filter(pk=rl.pk)
                    .query
                )
            self.assertIn("LEFT OUTER JOIN", sql)

        recepcion = create_laundry_reception(
            remision_id=remision.id,
            factura_remision_externa="FAC-PG-001",
            lotes_recibidos=[
                {
                    "remision_lote_id": rl.id,
                    "cantidad_recibida_conforme": 20,
                    "cantidad_merma": 0,
                    "cantidad_danada": 0,
                    "costo_unitario_prenda": "25000.00",
                }
            ],
            user=store,
            fecha_recepcion=today,
        )
        self.assertEqual(recepcion["codigo"].startswith("REC-LAV-"), True)

        inspeccion = quality_services.register_inspection(
            user=finisher,
            lote_id=lote.id,
            aptas=20,
            defectos=[],
            fecha=today,
        )
        ingreso = finished_services.register_entry(
            user=secretary,
            inspeccion_id=inspeccion.id,
            lineas=[{"variante": variante.id, "cantidad": 20}],
            fecha=today,
        )
        self.assertEqual(ingreso.aptas, 20)

    def test_te172_recepcion_cero_conformes_en_postgres_conserva_cantidad_original(self):
        """TE-172: recibir 0 conformes y pérdida total no viola CheckConstraint(cantidad >= 1) en PostgreSQL."""
        boss = make_user("pg_jefe2@t.co", "PRODUCCION")
        store = make_user("pg_alm2@t.co", "ALMACENISTA")
        today = timezone.localdate()
        tela = Producto.objects.create(
            codigo="MAT-PG-172",
            nombre="Denim PG 172",
            tipo=inventory_catalog.RAW_MATERIAL,
            categoria=inventory_catalog.CAT_FABRIC,
            unidad="m",
            stock_actual=Decimal("100.00"),
            ancho_util=Decimal("1.50"),
            composicion="100% algodón",
        )
        ref = Referencia.objects.create(
            codigo="REF-PG-172",
            nombre="Jean PG 172",
            ajuste="RECTO",
            estado=reference_catalog.ACTIVE,
        )
        orden_salida = OrdenSalida.objects.create(
            codigo="OP-PG-172",
            tipo=inventory_catalog.ORDER_PRODUCTION,
            fecha_salida=today,
            responsable="Planta",
            referencia=ref,
            ficha_tecnica=ref.codigo,
            producto_resultado=tela,
            cantidad_prendas=Decimal("40"),
            registrado_por=boss,
        )
        orden = OrdenProduccion.objects.create(
            orden_salida=orden_salida,
            codigo="OP-PG-172",
            referencia=ref,
            cantidad=40,
            creado_por=boss,
        )
        lote = Lote.objects.create(
            orden=orden,
            numero=1,
            codigo="OP-PG-172-L01",
            cantidad=40,
            estado_inventario=production_catalog.LOT_INV_IN_TRANSIT,
        )

        prov = Proveedor.objects.create(
            nit="901777222",
            nit_dv="5",
            razon_social="Lavandería PG Cero Conformes",
            categoria=inventory_catalog.CAT_LAUNDRY,
            ciudad="Medellín",
        )
        remision = RemisionLavanderia.objects.create(
            codigo="REM-LAV-PG-0172",
            lavanderia=prov,
            fecha_emision=today,
            transportador_nombre="Carlos",
            vehiculo_placa="PG172",
            tulas_bultos=1,
            peso_kg=Decimal("12.00"),
            estado=production_catalog.REMISSION_IN_TRANSIT,
            creado_por=boss,
        )
        rl = RemisionLote.objects.create(remision=remision, lote=lote, cantidad=40, receta=None)

        recepcion = create_laundry_reception(
            remision_id=remision.id,
            factura_remision_externa="FAC-PG-172",
            lotes_recibidos=[
                {
                    "remision_lote_id": rl.id,
                    "cantidad_recibida_conforme": 0,
                    "cantidad_merma": 40,
                    "motivo_merma": "Pérdida total en proceso",
                    "cantidad_danada": 0,
                    "costo_unitario_prenda": "28000.00",
                }
            ],
            user=store,
            fecha_recepcion=today,
        )
        self.assertEqual(recepcion["total_recibido_conforme"], 0)
        self.assertEqual(recepcion["total_merma"], 40)
        lote.refresh_from_db()
        self.assertEqual(lote.cantidad, 40)
        self.assertEqual(lote.estado_inventario, production_catalog.LOT_INV_INTERNAL)

    def test_sprint3_fallo2_assign_guide_to_funciona_fuera_de_transaccion_externa(self):
        """
        Verifica el arreglo 06225a7 del Sprint 3:
        assign_guide_to usa select_for_update, por lo que debe ser @transaction.atomic por sí misma
        para no lanzar TransactionManagementError en PostgreSQL cuando se invoca fuera de una transacción.
        """
        self.assertFalse(connection.in_atomic_block)
        user = make_user("pg_vendedor@t.co", "VENDEDOR")
        cliente = Cliente.objects.create(
            codigo="CLI-PG-1",
            tipo_documento="CC",
            documento="1090111222",
            nombre="Cliente PG",
            tipo=sales_catalog.CLIENT_DETAL,
            ciudad="Cúcuta",
            direccion="Av 0 # 10-20",
            telefono="3001112233",
        )
        factura = FacturaVenta.objects.create(
            numero="FV-PG-0001",
            cliente=cliente,
            cliente_nombre=cliente.nombre,
            cliente_documento=cliente.documento,
            cliente_tipo=cliente.tipo,
            cliente_ciudad=cliente.ciudad,
            cliente_direccion=cliente.direccion,
            cliente_telefono=cliente.telefono,
            vendedor=user,
            fecha=timezone.localdate(),
            subtotal=100_000,
            descuento_total=0,
            base_gravable=100_000,
            iva_tarifa=19,
            iva_total=19_000,
            total=119_000,
            valor_a_recaudar=119_000,
            token="11111111-1111-1111-1111-111111111111",
        )

        guide = shipping_services.assign_guide_to(factura, "INTERRAPIDISIMO", "700888999000", user)
        self.assertEqual(guide.estado, shipping_catalog.PENDING)
        self.assertEqual(Guia.objects.filter(factura=factura, vigente=True).count(), 1)
        self.assertEqual(EventoGuia.objects.filter(guia=guide).count(), 1)

    def test_vistas_materializadas_de_reportes_se_refrescan_y_consultan(self):
        outside = refresh_materialized_views()
        with transaction.atomic():
            inside = refresh_materialized_views()

        if connection.vendor == "postgresql":
            self.assertTrue(outside)
            self.assertTrue(inside)
        else:
            self.assertFalse(outside)
            self.assertFalse(inside)

        report = build_management_report({}, auto_refresh=True)
        self.assertIn("kpis", report)
        self.assertIn("consolidado_tipo_jean", report)

    def test_te170_unificacion_pt_bloqueos_y_restricciones_en_postgres(self):
        """TE-170: alta automática con select_for_update, unicidad por referencia y cálculo vivo en PostgreSQL."""
        from apps.finished.models import StockTerminado
        from apps.inventory.finished_link import ensure_finished_product_for_reference
        from apps.inventory.services import stock_alerts

        ref = Referencia.objects.create(
            codigo="REF-PG-170",
            nombre="Jean PG Unificado",
            ajuste="RECTO",
            estado=reference_catalog.ACTIVE,
        )
        var = Variante.objects.create(referencia=ref, talla="30", color="Azul")
        pt = ensure_finished_product_for_reference(ref)
        pt_same = ensure_finished_product_for_reference(ref)
        self.assertEqual(pt.id, pt_same.id)
        self.assertEqual(pt.stock_minimo, Decimal("30"))

        StockTerminado.objects.create(variante=var, cantidad=24)
        admin = client_for(make_user("pg_alm_170@t.co", "ADMIN"))
        rows = admin.get(reverse("inventario_productos"), {"tipo": "TERMINADO"}).json()
        hit = next(row for row in rows if row["id"] == pt.id)
        self.assertEqual(hit["stock_actual"], "24.00")
        self.assertTrue(hit["bajo_minimo"])
        self.assertTrue(any(a["id"] == pt.id and a["stock"] == "24.00" for a in stock_alerts()))

        with transaction.atomic():
            with self.assertRaises(Exception):
                Producto.objects.create(
                    codigo="PT-PG-DUP",
                    nombre="Duplicado",
                    tipo=inventory_catalog.FINISHED_PANTS,
                    categoria=inventory_catalog.CAT_FINISHED,
                    unidad="unidad",
                    referencia=ref,
                    heredado=True,
                )


class MaxLengthValidationTests(TestCase):
    """Verifica que entradas que exceden max_length responden 400 y no causan DataError (500) en PostgreSQL."""

    def test_cadenas_excesivas_se_rechazan_con_400_en_apis(self):
        admin = client_for(make_user("pg_admin@t.co", "ADMIN"))

        too_long_ref = admin.post(
            reverse("referencias"),
            {
                "nombre": "X" * 200,  # max_length=150
                "ajuste": "SKINNY",
                "variantes": [{"talla": "30", "color": "Azul"}],
            },
            format="json",
        )
        self.assertEqual(too_long_ref.status_code, 400)

        too_long_client = admin.post(
            reverse("ventas_clientes"),
            {
                "tipo_documento": "CC",
                "documento": "1090222333",
                "nombre": "C" * 200,  # max_length=150
                "tipo": "DETAL",
                "ciudad": "Bogotá",
                "direccion": "Calle 1",
                "telefono": "3001234567",
            },
            format="json",
        )
        self.assertEqual(too_long_client.status_code, 400)

        too_long_product = admin.post(
            reverse("inventario_catalogo"),
            {
                "nombre": "P" * 200,  # max_length=150
                "categoria": "TELA",
                "unidad": "m",
                "ancho_util": "1.50",
                "composicion": "100% algodón",
            },
            format="json",
        )
        self.assertEqual(too_long_product.status_code, 400)
