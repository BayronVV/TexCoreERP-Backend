"""
Inventario de producto terminado (HU 6.2 / RF21). Nombres de tabla en español y borrado lógico en todo
(ver docs/convenciones-base-de-datos.md).

- StockTerminado: cuántas prendas de primera calidad hay de cada variante (referencia, color y talla). Nunca es negativo.
- MovimientoTerminado: el libro del stock. Solo se agregan filas; cada una guarda el saldo antes y después. El saldo y su
  movimiento se escriben siempre en la misma transacción, así que el saldo siempre es la suma del libro.
- AjusteTerminado y AjusteLinea (HU 6.3): el comprobante inalterable de una corrección manual del stock contra el conteo físico.
- IngresoTerminado e IngresoLinea: el ingreso de las aptas de una inspección (HU 6.1), repartidas por talla. Una inspección
  se ingresa una sola vez. Las marras no entran a este saldo.
"""
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models import BaseModel

from . import catalog


class StockTerminado(BaseModel):
    """Prendas de primera calidad disponibles de una variante."""
    variante = models.ForeignKey("references.Variante", on_delete=models.PROTECT, related_name="stock")
    cantidad = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "terminado_stock"
        ordering = ["variante_id"]
        constraints = [
            models.UniqueConstraint(fields=["variante"], condition=Q(deleted_at__isnull=True), name="uq_terminado_stock_variante"),
        ]

    def __str__(self):
        return f"{self.variante_id}: {self.cantidad}"


class IngresoTerminado(BaseModel):
    """Ingreso de las aptas de un lote inspeccionado al inventario final, repartidas por talla."""
    codigo = models.CharField(max_length=20)
    inspeccion = models.ForeignKey("quality.Inspeccion", on_delete=models.PROTECT, related_name="ingresos")
    lote = models.ForeignKey("production.Lote", on_delete=models.PROTECT, related_name="ingresos_terminado")
    aptas = models.PositiveIntegerField(help_text="Aptas de la inspección: lo que se ingresa, tal como estaban al ingresar")
    ubicacion = models.CharField(max_length=80, blank=True, help_text="Dónde queda en la bodega (texto libre, opcional)")
    observaciones = models.CharField(max_length=500, blank=True)
    recibido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)
    fecha = models.DateField()

    class Meta:
        db_table = "terminado_ingreso"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_terminado_ingreso_codigo_activo"),
            models.UniqueConstraint(fields=["inspeccion"], condition=Q(deleted_at__isnull=True), name="uq_terminado_ingreso_inspeccion"),
            models.CheckConstraint(condition=Q(aptas__gte=1), name="ck_terminado_ingreso_aptas"),
        ]
        indexes = [models.Index(fields=["fecha"], name="ix_terminado_ingreso_fecha")]

    def __str__(self):
        return self.codigo


class IngresoLinea(BaseModel):
    """Cuántas prendas de una variante entraron en un ingreso. Guarda talla y color tal como estaban."""
    ingreso = models.ForeignKey(IngresoTerminado, on_delete=models.PROTECT, related_name="lineas")
    variante = models.ForeignKey("references.Variante", on_delete=models.PROTECT, related_name="+")
    talla = models.CharField(max_length=10)
    color = models.CharField(max_length=60)
    cantidad = models.PositiveIntegerField()
    planificada = models.PositiveIntegerField(null=True, blank=True, help_text="Lo planificado de esa variante en el lote (dato, no regla)")

    class Meta:
        db_table = "terminado_ingreso_linea"
        ordering = ["ingreso_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["ingreso", "variante"], condition=Q(deleted_at__isnull=True), name="uq_terminado_linea_variante"),
            models.CheckConstraint(condition=Q(cantidad__gte=1), name="ck_terminado_linea_cantidad"),
        ]


class AjusteTerminado(BaseModel):
    """Comprobante de un ajuste manual: quién corrigió qué contra el conteo físico, cuándo y por qué. No se edita ni se borra."""
    codigo = models.CharField(max_length=20)
    motivo = models.CharField(max_length=20, choices=catalog.ADJUST_REASON_CHOICES)
    observacion = models.CharField(max_length=500)
    realizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)
    fecha = models.DateField()
    token = models.UUIDField(help_text="Lo genera el formulario: el mismo token no ajusta dos veces (doble clic o reintento)")
    unidades_faltantes = models.PositiveIntegerField(help_text="Suma de lo que faltaba (nunca se netea contra los sobrantes)")
    unidades_sobrantes = models.PositiveIntegerField(help_text="Suma de lo que sobraba")

    class Meta:
        db_table = "terminado_ajuste"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_terminado_ajuste_codigo_activo"),
            models.UniqueConstraint(fields=["token"], name="uq_terminado_ajuste_token"),
            models.CheckConstraint(condition=~Q(observacion=""), name="ck_terminado_ajuste_observacion"),
        ]
        indexes = [models.Index(fields=["fecha"], name="ix_terminado_ajuste_fecha")]

    def __str__(self):
        return self.codigo


class AjusteLinea(BaseModel):
    """Una variante corregida: lo que decía el sistema, lo que se contó y la diferencia. Guarda talla y color tal como estaban."""
    ajuste = models.ForeignKey(AjusteTerminado, on_delete=models.PROTECT, related_name="lineas")
    variante = models.ForeignKey("references.Variante", on_delete=models.PROTECT, related_name="+")
    talla = models.CharField(max_length=10)
    color = models.CharField(max_length=60)
    stock_antes = models.PositiveIntegerField()
    stock_contado = models.PositiveIntegerField()
    diferencia = models.IntegerField(help_text="Contado menos el stock anterior: negativa si faltaba, positiva si sobraba")

    class Meta:
        db_table = "terminado_ajuste_linea"
        ordering = ["ajuste_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["ajuste", "variante"], condition=Q(deleted_at__isnull=True), name="uq_terminado_ajuste_linea_variante"),
            models.CheckConstraint(condition=~Q(diferencia=0), name="ck_terminado_ajuste_linea_diferencia"),
            models.CheckConstraint(condition=Q(diferencia=F("stock_contado") - F("stock_antes")), name="ck_terminado_ajuste_linea_cuadra"),
        ]


class MovimientoTerminado(BaseModel):
    """Una fila del libro del stock: de cuánto a cuánto pasó el saldo de una variante y por qué."""
    variante = models.ForeignKey("references.Variante", on_delete=models.PROTECT, related_name="movimientos_terminado")
    tipo = models.CharField(max_length=20, choices=catalog.MOVEMENT_TYPES)
    cantidad = models.IntegerField(help_text="Con signo: positiva suma al saldo y negativa lo resta")
    saldo_antes = models.PositiveIntegerField()
    saldo_despues = models.PositiveIntegerField()
    ingreso = models.ForeignKey(IngresoTerminado, on_delete=models.PROTECT, related_name="movimientos", null=True, blank=True)
    ajuste = models.ForeignKey(AjusteTerminado, on_delete=models.PROTECT, related_name="movimientos", null=True, blank=True)
    lote = models.ForeignKey("production.Lote", on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    usuario =models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)
    motivo = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "terminado_movimiento"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=~Q(cantidad=0), name="ck_terminado_movimiento_cantidad"),
            models.CheckConstraint(condition=Q(saldo_despues=F("saldo_antes") + F("cantidad")), name="ck_terminado_movimiento_saldo"),
        ]
        indexes = [models.Index(fields=["variante", "-created_at"], name="ix_terminado_mov_variante")]
