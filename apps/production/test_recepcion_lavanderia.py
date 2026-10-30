"""Pruebas de Recepción, Cotejo de Cantidades y Pérdidas Financieras de Lavandería (TE-58).

Verifica:
1. Consulta de remisiones pendientes en tránsito para recepción.
2. Cotejo de cantidades enviadas vs devueltas y validación de sumas exactas.
3. Exigencia estricta de campos obligatorios para mermas (motivo_merma) y daños (tipo_dano).
4. Retorno de las prendas al estado interno de la planta (estado_inventario = PLANTA).
5. Asentamiento en base de datos vinculado a la factura/remisión de salida original.
6. Cálculo y registro financiero de pérdidas por procesos de terceros.
"""
from decimal import Decimal
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.inventory import catalog as inv_catalog
from apps.inventory.models import Proveedor
from apps.production import catalog
from apps.production.models import (
    Lote,
    RecepcionLavanderia,
    RecepcionLote,
    RecetaLavado,
    RemisionLavanderia,
    RemisionLote,
)
from apps.production.recepcion_services import (
    create_laundry_reception,
    get_laundry_reception_detail,
    get_pending_remissions_for_reception,
    list_laundry_receptions,
)
from apps.production.remisiones_services import create_laundry_remission
from apps.production.test_modelos import ModelBase


class RecepcionLavanderiaTests(ModelBase):
    def setUp(self):
        super().setUp()
        self.order = self.make_order(code="OP-0088", quantity=100)
        self.lot1 = self.make_lot(self.order, number=1, quantity=60)
        self.lot2 = self.make_lot(self.order, number=2, quantity=40)

        self.prov = Proveedor.objects.create(
            nit="900888777",
            nit_dv="2",
            razon_social="Lavandería Cóndor S.A.S.",
            categoria=inv_catalog.CAT_LAUNDRY,
            ciudad="Itagüí",
            contacto="Gustavo Mejía",
            telefono="3114567890",
        )

        self.receta = RecetaLavado.objects.create(
            codigo="REC-DENIM-01",
            nombre="Stone Wash Regular",
            categoria="Efectos",
            temperatura_proceso="60 °C",
            duracion_horas=24,
            tarifa_sugerida=Decimal("3500.00"),
        )

        # Despachar remisión de salida con el lote 1 (60 prendas)
        self.today = timezone.localdate()
        self.remision_data = create_laundry_remission(
            user=self.boss,
            lavanderia_id=self.prov.id,
            lotes_seleccionados=[
                {
                    "lote_id": self.lot1.id,
                    "cantidad": 60,
                    "receta_id": "REC-DENIM-01",
                    "instrucciones_especiales": "Proceso estándar",
                }
            ],
            fecha_emision=self.today,
            transportador_nombre="Carlos Conductor",
            vehiculo_placa="ABC-999",
            tulas_bultos=2,
            peso_kg=35,
            observaciones="Remisión de prueba para TE-58",
        )
        self.remision = RemisionLavanderia.objects.get(codigo=self.remision_data["codigo"])
        self.remision_lote = self.remision.lotes_detalle.first()

    def test_remisiones_pendientes_retorna_remisiones_en_transito(self):
        pending = get_pending_remissions_for_reception()
        pending_ids = [p["remision_id"] for p in pending]
        self.assertIn(self.remision.id, pending_ids)

        rem_entry = next(p for p in pending if p["remision_id"] == self.remision.id)
        self.assertEqual(rem_entry["total_prendas"], 60)
        self.assertEqual(rem_entry["lavanderia_nombre"], "Lavandería Cóndor S.A.S.")
        self.assertEqual(len(rem_entry["lotes"]), 1)
        self.assertEqual(rem_entry["lotes"][0]["lote_codigo"], self.lot1.codigo)

    def test_recepcion_exitosa_cotejo_cuadra_y_devuelve_lote_a_planta(self):
        # Cotejo: 60 enviadas = 55 conformes + 3 mermas + 2 dañadas
        reception = create_laundry_reception(
            user=self.boss,
            remision_id=self.remision.id,
            fecha_recepcion=self.today,
            factura_remision_externa="FAC-LAV-8841",
            lotes_recibidos=[
                {
                    "remision_lote_id": self.remision_lote.id,
                    "cantidad_recibida_conforme": 55,
                    "cantidad_merma": 3,
                    "motivo_merma": "Extravío en tinas de lavado",
                    "cantidad_danada": 2,
                    "tipo_dano": "Decoloración irregular / veteado químico",
                    "costo_unitario_prenda": "35000.00",
                    "observaciones": "Revisado por control de calidad en mesa de recepción.",
                }
            ],
            observaciones="Recepción conforme con novedades asentadas.",
        )

        # 1. Consecutivo generado
        self.assertTrue(reception["codigo"].startswith(f"REC-LAV-{self.today.year}-"))
        self.assertEqual(reception["factura_remision_externa"], "FAC-LAV-8841")
        self.assertEqual(reception["total_enviado"], 60)
        self.assertEqual(reception["total_recibido_conforme"], 55)
        self.assertEqual(reception["total_merma"], 3)
        self.assertEqual(reception["total_danadas"], 2)

        # 2. Pérdida financiera registrada: (3 mermas + 2 dañadas) * 35.000 = $ 175.000 COP
        expected_loss = float(Decimal("5") * Decimal("35000.00"))
        self.assertEqual(reception["costo_total_perdida"], expected_loss)

        # 3. Costo servicio de lavado liquidado: 55 conformes * 3.500 = $ 192.500 COP
        expected_service = float(Decimal("55") * Decimal("35000.00"))  # tarifa es 3500
        self.assertEqual(reception["costo_servicio_lavado"], float(Decimal("55") * Decimal("3500.00")))

        # 4. Estado de remisión original pasa a RETORNADA
        self.remision.refresh_from_db()
        self.assertEqual(self.remision.estado, catalog.REMISSION_RETURNED)

        # 5. Las prendas vuelven al estado interno de planta (LOT_INV_INTERNAL = PLANTA)
        self.lot1.refresh_from_db()
        self.assertEqual(self.lot1.estado_inventario, catalog.LOT_INV_INTERNAL)
        self.assertEqual(self.lot1.cantidad, 55)  # Se ajustó a las prendas conformes recibidas

        # 6. Ya no aparece en remisiones pendientes de recepción
        pending = get_pending_remissions_for_reception()
        pending_ids = [p["remision_id"] for p in pending]
        self.assertNotIn(self.remision.id, pending_ids)

        # 7. Aparece en el historial de recepciones
        history = list_laundry_receptions()
        history_codes = [h["codigo"] for h in history]
        self.assertIn(reception["codigo"], history_codes)

        # 8. Detalle individual consultable
        detail = get_laundry_reception_detail(reception["id"])
        self.assertEqual(detail["codigo"], reception["codigo"])
        self.assertEqual(detail["remision_codigo"], self.remision.codigo)

    def test_falla_si_cantidades_no_coinciden_con_enviadas(self):
        # Se enviaron 60, pero reportan 50 conformes y 0 mermas/daños (suma 50 != 60)
        with self.assertRaises(ValidationError):
            create_laundry_reception(
                user=self.boss,
                remision_id=self.remision.id,
                fecha_recepcion=self.today,
                lotes_recibidos=[
                    {
                        "remision_lote_id": self.remision_lote.id,
                        "cantidad_recibida_conforme": 50,
                        "cantidad_merma": 0,
                        "cantidad_danada": 0,
                    }
                ],
            )

    def test_falla_si_merma_mayor_a_cero_sin_motivo_obligatorio(self):
        # 58 conformes + 2 mermas suman 60, pero motivo_merma está vacío
        with self.assertRaises(ValidationError):
            create_laundry_reception(
                user=self.boss,
                remision_id=self.remision.id,
                fecha_recepcion=self.today,
                lotes_recibidos=[
                    {
                        "remision_lote_id": self.remision_lote.id,
                        "cantidad_recibida_conforme": 58,
                        "cantidad_merma": 2,
                        "motivo_merma": "   ",  # Inválido: obligatorio
                        "cantidad_danada": 0,
                    }
                ],
            )

    def test_falla_si_danadas_mayor_a_cero_sin_tipo_dano_obligatorio(self):
        # 57 conformes + 3 dañadas suman 60, pero tipo_dano está vacío
        with self.assertRaises(ValidationError):
            create_laundry_reception(
                user=self.boss,
                remision_id=self.remision.id,
                fecha_recepcion=self.today,
                lotes_recibidos=[
                    {
                        "remision_lote_id": self.remision_lote.id,
                        "cantidad_recibida_conforme": 57,
                        "cantidad_merma": 0,
                        "cantidad_danada": 3,
                        "tipo_dano": "",  # Inválido: obligatorio
                    }
                ],
            )

    def test_no_se_puede_recibir_remision_ya_retornada(self):
        # Primera recepción completa exitosa
        create_laundry_reception(
            user=self.boss,
            remision_id=self.remision.id,
            fecha_recepcion=self.today,
            lotes_recibidos=[
                {
                    "remision_lote_id": self.remision_lote.id,
                    "cantidad_recibida_conforme": 60,
                    "cantidad_merma": 0,
                    "cantidad_danada": 0,
                }
            ],
        )

        # Intentar recibir de nuevo la misma remisión debe fallar
        with self.assertRaises(ValidationError):
            create_laundry_reception(
                user=self.boss,
                remision_id=self.remision.id,
                fecha_recepcion=self.today,
                lotes_recibidos=[
                    {
                        "remision_lote_id": self.remision_lote.id,
                        "cantidad_recibida_conforme": 60,
                        "cantidad_merma": 0,
                        "cantidad_danada": 0,
                    }
                ],
            )
