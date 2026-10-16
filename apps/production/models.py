"""
Órdenes de producción y lotes (HU 4.2 / RF11 y RF12). Nombres de tabla en español y borrado lógico en todo
(ver docs/convenciones-base-de-datos.md).

- OrdenProduccion: la orden de una referencia. Cuelga de la orden de salida del inventario, que es quien
  descuenta el material y guarda el estado (en proceso, completada o anulada): aquí no se duplica.
- Lote: cada parte en que se divide la orden, con su propio código (OP-0001-L01).
- LoteTalla: cuántas prendas de cada talla y color lleva un lote. Es opcional.
- EtapaLote y EventoEtapa (HU 4.3): las etapas de cada lote con su tiempo neto y el historial de acciones.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from . import catalog


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


class EtapaLote(BaseModel):
    """Una etapa productiva de un lote (corte, confección, terminación...) con su tiempo (HU 4.3 / RF13).

    El tiempo neto es la suma de los intervalos en que la etapa estuvo corriendo: cada pausa cierra un intervalo
    y cada reanudación abre otro, así que las pausas no cuentan. `acumulado_s` guarda los intervalos ya cerrados y
    `reanudada_at` el inicio del intervalo abierto (vacío si no está corriendo). El detalle de cada acción vive en
    `EventoEtapa`.
    """
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name="etapas")
    etapa = models.CharField(max_length=16, choices=catalog.STAGES)
    secuencia = models.PositiveSmallIntegerField(help_text="Posición en el flujo, desde 1")
    estado = models.CharField(max_length=10, choices=catalog.STAGE_STATES, default=catalog.STAGE_PENDING)
    inicio_at = models.DateTimeField(null=True, blank=True)
    fin_at = models.DateTimeField(null=True, blank=True)
    reanudada_at = models.DateTimeField(null=True, blank=True)
    acumulado_s = models.PositiveIntegerField(default=0, help_text="Segundos netos de los intervalos ya cerrados")
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)

    class Meta:
        db_table = "produccion_etapa_lote"
        ordering = ["lote_id", "secuencia"]
        constraints = [
            models.UniqueConstraint(
                fields=["lote", "etapa"], condition=Q(deleted_at__isnull=True), name="uq_produccion_etapa_lote"
            ),
        ]
        indexes = [
            # Monitor de estado (HU 4.5): saber si un lote tiene etapas sin terminar y en qué estado están.
            models.Index(fields=["lote", "estado"], name="ix_prod_etapa_lote_estado"),
            # Solo las etapas en curso o pendientes: es un conjunto pequeño y es el que más se consulta.
            models.Index(
                fields=["estado"], condition=Q(deleted_at__isnull=True) & ~Q(estado="COMPLETADA"), name="ix_prod_etapa_abierta"
            ),
        ]

    def __str__(self):
        return f"{self.lote_id} {self.etapa}"


class EventoEtapa(BaseModel):
    """Historial de una etapa: quién la inició, pausó, reanudó o terminó, y cuándo. Solo se agregan filas, nunca se editan."""
    etapa_lote = models.ForeignKey(EtapaLote, on_delete=models.PROTECT, related_name="eventos")
    accion = models.CharField(max_length=10, choices=catalog.EVENT_ACTIONS)
    de_estado = models.CharField(max_length=10, choices=catalog.STAGE_STATES)
    a_estado = models.CharField(max_length=10, choices=catalog.STAGE_STATES)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)
    momento = models.DateTimeField()
    nota = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "produccion_evento_etapa"
        ordering = ["momento", "id"]
        indexes = [models.Index(fields=["etapa_lote", "momento"], name="ix_prod_evento_etapa_momento")]
