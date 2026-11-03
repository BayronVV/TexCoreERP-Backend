"""
Control de calidad (HU 6.1 / RF19 y RF20). Nombres de tabla en español y borrado lógico en todo
(ver docs/convenciones-base-de-datos.md).

- TipoDefecto: el catálogo de defectos (el «criterio de calidad»). Cada uno es corregible (reproceso) o incorregible
  (marra definitiva). Nunca se borra: se desactiva, para no romper el historial.
- Inspeccion y MarraDetalle: lo que se encontró al revisar un lote que volvió de lavandería. Una inspección por lote y
  solo se agrega: no se edita ni se borra. Las aptas más las marras suman exactamente lo recibido.
"""
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from apps.core.models import BaseModel


class TipoDefecto(BaseModel):
    """Un defecto que se puede encontrar en una prenda (costura, tono, mancha, medida...)."""
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=80)
    descripcion = models.CharField(max_length=255, blank=True)
    corregible = models.BooleanField(default=False, help_text="Se puede reprocesar; si no, la prenda es marra definitiva")
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "calidad_defecto"
        ordering = ["nombre", "id"]
        constraints = [
            models.UniqueConstraint(fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_calidad_defecto_codigo_activo"),
            models.UniqueConstraint(Lower("nombre"), condition=Q(deleted_at__isnull=True), name="uq_calidad_defecto_nombre_activo"),
        ]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"


class Inspeccion(BaseModel):
    """Revisión final de un lote que volvió de lavandería: cuántas prendas son aptas y cuántas marras."""
    codigo = models.CharField(max_length=20)
    lote = models.ForeignKey("production.Lote", on_delete=models.PROTECT, related_name="inspecciones")
    recepcion_lote = models.ForeignKey(
        "production.RecepcionLote", on_delete=models.PROTECT, related_name="+",
        help_text="Recepción de lavandería de la que sale la cantidad inspeccionada",
    )
    cantidad_recibida = models.PositiveIntegerField(help_text="Prendas recibidas conformes de lavandería, al momento de inspeccionar")
    aptas = models.PositiveIntegerField(help_text="Primera calidad: pasan al inventario final")
    marras = models.PositiveIntegerField(help_text="Prendas defectuosas: suma de su desglose por defecto")
    observaciones = models.CharField(max_length=500, blank=True)
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)
    fecha = models.DateField()

    class Meta:
        db_table = "calidad_inspeccion"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_calidad_inspeccion_codigo_activo"),
            models.UniqueConstraint(fields=["lote"], condition=Q(deleted_at__isnull=True), name="uq_calidad_inspeccion_lote_activo"),
            models.CheckConstraint(condition=Q(cantidad_recibida__gte=1), name="ck_calidad_inspeccion_recibida"),
            models.CheckConstraint(condition=Q(cantidad_recibida=F("aptas") + F("marras")), name="ck_calidad_inspeccion_suma"),
        ]
        indexes = [models.Index(fields=["fecha"], name="ix_calidad_inspeccion_fecha")]

    def __str__(self):
        return self.codigo


class MarraDetalle(BaseModel):
    """Cuántas marras de un defecto hubo en una inspección. Guarda el nombre y el tipo del defecto tal como estaban."""
    inspeccion = models.ForeignKey(Inspeccion, on_delete=models.PROTECT, related_name="detalle")
    tipo_defecto = models.ForeignKey(TipoDefecto, on_delete=models.PROTECT, related_name="+")
    defecto_nombre = models.CharField(max_length=80)
    corregible = models.BooleanField(default=False)
    cantidad = models.PositiveIntegerField()
    nota = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "calidad_marra_detalle"
        ordering = ["inspeccion_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["inspeccion", "tipo_defecto"], condition=Q(deleted_at__isnull=True), name="uq_calidad_marra_defecto"
            ),
            models.CheckConstraint(condition=Q(cantidad__gte=1), name="ck_calidad_marra_cantidad"),
        ]
