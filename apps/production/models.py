"""
Órdenes de producción y lotes (HU 4.2 / RF11 y RF12). Nombres de tabla en español y borrado lógico en todo
(ver docs/convenciones-base-de-datos.md).

- OrdenProduccion: la orden de una referencia. Cuelga de la orden de salida del inventario, que es quien
  descuenta el material y guarda el estado (en proceso, completada o anulada): aquí no se duplica.
- Lote: cada parte en que se divide la orden, con su propio código (OP-0001-L01).
- LoteTalla: cuántas prendas de cada talla y color lleva un lote. Es opcional.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class OrdenProduccion(BaseModel):
    """Orden para fabricar una cantidad de prendas de una referencia (RF11). Su código es el de la orden de salida."""
    orden_salida = models.OneToOneField("inventory.OrdenSalida", on_delete=models.PROTECT, related_name="produccion")
    codigo = models.CharField(max_length=20)
    referencia = models.ForeignKey("references.Referencia", on_delete=models.PROTECT, related_name="ordenes_produccion")
    cantidad = models.PositiveIntegerField(help_text="Prendas a fabricar en total")
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)

    class Meta:
        db_table = "produccion_orden"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_produccion_orden_codigo_activo"
            ),
            models.CheckConstraint(condition=Q(cantidad__gte=1), name="ck_produccion_orden_cantidad"),
        ]

    def __str__(self):
        return self.codigo


class Lote(BaseModel):
    """Parte de una orden de producción con identificador único (RF12)."""
    orden = models.ForeignKey(OrdenProduccion, on_delete=models.PROTECT, related_name="lotes")
    numero = models.PositiveSmallIntegerField(help_text="Posición dentro de la orden, desde 1")
    codigo = models.CharField(max_length=24)
    cantidad = models.PositiveIntegerField(help_text="Prendas del lote")

    class Meta:
        db_table = "produccion_lote"
        ordering = ["orden_id", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["orden", "numero"], condition=Q(deleted_at__isnull=True), name="uq_produccion_lote_numero"
            ),
            models.UniqueConstraint(
                fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_produccion_lote_codigo_activo"
            ),
            models.CheckConstraint(condition=Q(cantidad__gte=1), name="ck_produccion_lote_cantidad"),
        ]

    def __str__(self):
        return self.codigo


class LoteTalla(BaseModel):
    """Prendas de una talla y color dentro de un lote. Talla y color se copian de la variante: si luego se
    archiva o cambia, el lote conserva lo que se pidió.
    """
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name="tallas")
    variante = models.ForeignKey("references.Variante", on_delete=models.PROTECT, related_name="+")
    talla = models.CharField(max_length=10)
    color = models.CharField(max_length=60)
    cantidad = models.PositiveIntegerField()

    class Meta:
        db_table = "produccion_lote_talla"
        ordering = ["lote_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["lote", "variante"], condition=Q(deleted_at__isnull=True), name="uq_produccion_lote_variante"
            ),
            models.CheckConstraint(condition=Q(cantidad__gte=1), name="ck_produccion_lote_talla_cantidad"),
        ]
