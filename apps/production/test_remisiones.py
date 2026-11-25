from decimal import Decimal
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.inventory import catalog as inv_catalog
from apps.inventory.models import Proveedor
from apps.production import catalog
from apps.production.models import RecetaLavado
from apps.production.recepcion_services import create_laundry_reception
from apps.production.remisiones_services import (
    create_laundry_remission,
    get_available_lots_for_washing,
    get_laundry_providers,
    get_wash_recipes,
    list_laundry_remissions,
)
from apps.production.test_modelos import ModelBase


class RemisionesTests(ModelBase):
    def setUp(self):
        super().setUp()
        self.order = self.make_order(code="OP-0099", quantity=100)
        self.lot1 = self.make_lot(self.order, number=1, quantity=60)
        self.lot2 = self.make_lot(self.order, number=2, quantity=40)

        self.prov = Proveedor.objects.create(
            nit="900999888",
            nit_dv="7",
            razon_social="Lavandería Test S.A.S.",
            categoria=inv_catalog.CAT_LAUNDRY,
            ciudad="Medellín",
            contacto="Pedro Perez",
            telefono="3001234567",
        )
        self.non_laundry_prov = Proveedor.objects.create(
            nit="900111999",
            nit_dv="1",
            razon_social="Textiles No Lavandería S.A.S.",
            categoria=inv_catalog.CAT_FABRIC,
            ciudad="Bogotá",
        )

        self.receta = RecetaLavado.objects.create(
            codigo="REC-TEST-01",
            nombre="Stone Wash Test",
            categoria="Efectos",
            temperatura_proceso="60 °C",
            duracion_horas=24,
            tarifa_sugerida=Decimal("3500.00"),
        )

    def test_lotes_disponibles_retorna_lotes_en_planta(self):
        lots = get_available_lots_for_washing()
        lot_ids = [l["id"] for l in lots]
        self.assertIn(self.lot1.id, lot_ids)
        self.assertIn(self.lot2.id, lot_ids)
        first = next(l for l in lots if l["id"] == self.lot1.id)
        self.assertNotIn("receta_sugerida", first)
        self.assertNotIn("taller_confeccion", first)

    def test_proveedores_lavanderia_solo_lista_categoria_lavanderia_y_sin_datos_inventados(self):
        provs = get_laundry_providers()
        prov_ids = [p["id"] for p in provs]
        self.assertIn(self.prov.id, prov_ids)
        self.assertNotIn(self.non_laundry_prov.id, prov_ids)
        row = next(p for p in provs if p["id"] == self.prov.id)
        self.assertNotIn("tarifa_base_unidad", row)
        self.assertNotIn("tiempo_promedio_dias", row)
        self.assertNotIn("calificacion_calidad", row)

        # Aunque se elimine la lavandería, no cae en proveedores de otra categoría
        self.prov.delete()
        self.assertEqual(get_laundry_providers(), [])

    def test_recetas_lavado_retorna_receta_creada(self):
        recipes = get_wash_recipes()
        recipe_codes = [r["codigo"] for r in recipes]
        self.assertIn("REC-TEST-01", recipe_codes)

    def test_crear_remision_descuenta_lote_de_planta_y_genera_consecutivo(self):
        today = timezone.localdate()
        remision = create_laundry_remission(
            user=self.boss,
            lavanderia_id=self.prov.id,
            lotes_seleccionados=[
                {
                    "lote_id": self.lot1.id,
                    "cantidad": 60,
                    "receta_id": "REC-TEST-01",
                    "instrucciones_especiales": "Muestra física",
                }
            ],
            fecha_emision=today,
            transportador_nombre="Juan Conductor",
            vehiculo_placa="ABC-123",
            tulas_bultos=2,
            peso_kg=35,
            observaciones="Entrega inicial",
        )

        # 1. Consecutivo generado con formato correcto
        self.assertTrue(remision["codigo"].startswith(f"REM-LAV-{today.year}-"))
        self.assertEqual(remision["total_prendas"], 60)
        self.assertEqual(remision["lavanderia_nombre"], "Lavandería Test S.A.S.")

        # 2. Descuento de planta interna: estado_inventario pasa a EN_TRANSITO
        self.lot1.refresh_from_db()
        self.assertEqual(self.lot1.estado_inventario, catalog.LOT_INV_IN_TRANSIT)

        # 3. Ya no aparece en lotes disponibles para lavado
        lots = get_available_lots_for_washing()
        lot_ids = [l["id"] for l in lots]
        self.assertNotIn(self.lot1.id, lot_ids)
        self.assertIn(self.lot2.id, lot_ids)

        # 4. Aparece en el historial de remisiones
        history = list_laundry_remissions()
        history_codes = [h["codigo"] for h in history]
        self.assertIn(remision["codigo"], history_codes)

    def test_rechaza_remision_parcial_y_proveedor_no_lavanderia(self):
        today = timezone.localdate()
        with self.assertRaises(ValidationError) as ctx_partial:
            create_laundry_remission(
                user=self.boss,
                lavanderia_id=self.prov.id,
                lotes_seleccionados=[{"lote_id": self.lot1.id, "cantidad": 40}],
                fecha_emision=today,
            )
        self.assertIn("completo", str(ctx_partial.exception.detail).lower())

        with self.assertRaises(ValidationError):
            create_laundry_remission(
                user=self.boss,
                lavanderia_id=self.non_laundry_prov.id,
                lotes_seleccionados=[{"lote_id": self.lot1.id, "cantidad": 60}],
                fecha_emision=today,
            )

    def test_no_se_puede_remitir_un_lote_que_ya_no_esta_en_planta_o_ya_recibido(self):
        today = timezone.localdate()
        # Remitir lote 1
        remision = create_laundry_remission(
            user=self.boss,
            lavanderia_id=self.prov.id,
            lotes_seleccionados=[{"lote_id": self.lot1.id, "cantidad": 60}],
            fecha_emision=today,
        )

        # Intentar remitirlo de nuevo debe fallar
        with self.assertRaises(ValidationError):
            create_laundry_remission(
                user=self.boss,
                lavanderia_id=self.prov.id,
                lotes_seleccionados=[{"lote_id": self.lot1.id, "cantidad": 60}],
                fecha_emision=today,
            )

        # Recibir el lote 1 de vuelta a PLANTA: no reaparece para enviar ni permite re-remitirse
        create_laundry_reception(
            user=self.boss,
            remision_id=remision["id"],
            fecha_recepcion=today,
            factura_remision_externa="FAC-TEST-900",
            lotes_recibidos=[{"lote_id": self.lot1.id, "cantidad_recibida_conforme": 60}],
        )
        available_ids = [l["id"] for l in get_available_lots_for_washing()]
        self.assertNotIn(self.lot1.id, available_ids)
        with self.assertRaises(ValidationError):
            create_laundry_remission(
                user=self.boss,
                lavanderia_id=self.prov.id,
                lotes_seleccionados=[{"lote_id": self.lot1.id, "cantidad": 60}],
                fecha_emision=today,
            )
