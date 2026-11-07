"""
Ventas y facturación (HU 7.1 / RF23). Nombres de tabla en español y borrado lógico en todo (ver docs/convenciones-base-de-datos.md).

- Cliente: a quién se le vende. Su tipo decide el precio de lista y el descuento máximo.
- PrecioReferencia: costo de fábrica y precios de venta (detal y mayorista) de una referencia, en pesos enteros y antes de IVA.
- FacturaVenta y DetalleVenta: la factura POS interna. Guarda copia del cliente, del precio, del descuento y del IVA del momento,
  así que cambiar precios o datos después no la toca. Nunca se edita ni se borra: se anula y el stock regresa por el libro.
"""
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models import BaseModel

from . import catalog


class Cliente(BaseModel):
    """Persona o empresa a la que se le vende."""
    codigo = models.CharField(max_length=20)
    tipo_documento = models.CharField(max_length=3, choices=catalog.DOCUMENT_TYPES)
    documento = models.CharField(max_length=20)
    dv = models.CharField(max_length=1, blank=True, help_text="Dígito de verificación (solo NIT)")
    nombre = models.CharField(max_length=150)
    tipo = models.CharField(max_length=12, choices=catalog.CLIENT_TYPES, default=catalog.CLIENT_DETAL)
    ciudad = models.CharField(max_length=80)
    direccion = models.CharField(max_length=200)
    telefono = models.CharField(max_length=20)
    correo = models.CharField(max_length=120, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "ventas_cliente"
        ordering = ["nombre", "id"]
        constraints = [
            models.UniqueConstraint(fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_ventas_cliente_codigo_activo"),
            models.UniqueConstraint(
                fields=["tipo_documento", "documento"], condition=Q(deleted_at__isnull=True), name="uq_ventas_cliente_documento"
            ),
        ]

    def __str__(self):
        return f"{self.codigo} {self.nombre}"


class PrecioReferencia(BaseModel):
    """Costo de fábrica y precios de venta de una referencia (pesos enteros, antes de IVA)."""
    referencia = models.ForeignKey("references.Referencia", on_delete=models.PROTECT, related_name="precios")
    costo_fabrica = models.PositiveBigIntegerField(help_text="Piso: ninguna venta, con su descuento, baja de este valor")
    precio_detal = models.PositiveBigIntegerField()
    precio_mayorista = models.PositiveBigIntegerField()
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)

    class Meta:
        db_table = "ventas_precio_referencia"
        ordering = ["referencia_id"]
        constraints = [
            models.UniqueConstraint(fields=["referencia"], condition=Q(deleted_at__isnull=True), name="uq_ventas_precio_referencia"),
            models.CheckConstraint(condition=Q(costo_fabrica__gte=1), name="ck_ventas_precio_costo_positivo"),
            models.CheckConstraint(condition=Q(precio_mayorista__gte=F("costo_fabrica")), name="ck_ventas_precio_mayorista_sobre_costo"),
            models.CheckConstraint(condition=Q(precio_detal__gte=F("precio_mayorista")), name="ck_ventas_precio_detal_sobre_mayorista"),
        ]


class FacturaVenta(BaseModel):
    """Factura POS interna (no es factura electrónica). Inalterable: se anula, no se edita ni se borra."""
    numero = models.CharField(max_length=20)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="facturas")
    cliente_nombre = models.CharField(max_length=150)
    cliente_documento = models.CharField(max_length=40)
    cliente_tipo = models.CharField(max_length=12, choices=catalog.CLIENT_TYPES)
    cliente_ciudad = models.CharField(max_length=80)
    cliente_direccion = models.CharField(max_length=200)
    cliente_telefono = models.CharField(max_length=20)
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)
    fecha = models.DateField()
    estado = models.CharField(max_length=10, choices=catalog.INVOICE_STATES, default=catalog.STATUS_ISSUED)
    modalidad_pago = models.CharField(max_length=15, choices=catalog.PAYMENT_METHODS, default=catalog.PAYMENT_COD)
    estado_cobro = models.CharField(max_length=12, choices=catalog.COLLECT_STATES, default=catalog.COLLECT_PENDING)
    transportadora = models.CharField(max_length=16, choices=catalog.CARRIERS, blank=True)
    numero_guia = models.CharField(max_length=40, blank=True, help_text="Guía de la transportadora (opcional): la consulta la HU 7.2")
    observaciones = models.CharField(max_length=500, blank=True)
    subtotal = models.PositiveBigIntegerField()
    descuento_total = models.PositiveBigIntegerField()
    base_gravable = models.PositiveBigIntegerField()
    iva_tarifa = models.PositiveSmallIntegerField()
    iva_total = models.PositiveBigIntegerField()
    total = models.PositiveBigIntegerField()
    valor_a_recaudar = models.PositiveBigIntegerField()
    token = models.UUIDField(help_text="Lo genera el formulario: el mismo token no factura dos veces (doble clic o reintento)")
    motivo_anulacion = models.CharField(max_length=255, blank=True)
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    anulada_en = models.DateTimeField(null=True, blank=True)
    fecha_cobro = models.DateTimeField(null=True, blank=True, help_text="Fecha y hora de confirmación del recaudo o devolución")
    cobrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    motivo_devolucion = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "ventas_factura"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["numero"], condition=Q(deleted_at__isnull=True), name="uq_ventas_factura_numero_activo"),
            models.UniqueConstraint(fields=["token"], name="uq_ventas_factura_token"),
            models.CheckConstraint(condition=Q(base_gravable=F("subtotal") - F("descuento_total")), name="ck_ventas_factura_base"),
            models.CheckConstraint(condition=Q(total=F("base_gravable") + F("iva_total")), name="ck_ventas_factura_total"),
            models.CheckConstraint(condition=Q(valor_a_recaudar=F("total")), name="ck_ventas_factura_recaudo"),
        ]
        indexes = [models.Index(fields=["fecha"], name="ix_ventas_factura_fecha")]

    def __str__(self):
        return self.numero


class DetalleVenta(BaseModel):
    """Una variante vendida: cantidad, precio, descuento e IVA del momento. Guarda referencia, talla y color tal como estaban."""
    factura = models.ForeignKey(FacturaVenta, on_delete=models.PROTECT, related_name="lineas")
    variante = models.ForeignKey("references.Variante", on_delete=models.PROTECT, related_name="+")
    referencia_codigo = models.CharField(max_length=20)
    referencia_nombre = models.CharField(max_length=150)
    talla = models.CharField(max_length=10)
    color = models.CharField(max_length=60)
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.PositiveBigIntegerField()
    descuento_pct = models.PositiveSmallIntegerField(default=0)
    costo_fabrica = models.PositiveBigIntegerField(help_text="Copia del costo de fábrica al vender (auditoría del piso)")
    subtotal = models.PositiveBigIntegerField()
    descuento = models.PositiveBigIntegerField()
    base = models.PositiveBigIntegerField()
    iva = models.PositiveBigIntegerField()
    total = models.PositiveBigIntegerField()

    class Meta:
        db_table = "ventas_factura_linea"
        ordering = ["factura_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["factura", "variante"], condition=Q(deleted_at__isnull=True), name="uq_ventas_linea_variante"),
            models.CheckConstraint(condition=Q(cantidad__gte=1), name="ck_ventas_linea_cantidad"),
            models.CheckConstraint(condition=Q(descuento_pct__lte=100), name="ck_ventas_linea_descuento_pct"),
            models.CheckConstraint(condition=Q(subtotal=F("precio_unitario") * F("cantidad")), name="ck_ventas_linea_subtotal"),
            models.CheckConstraint(condition=Q(base=F("subtotal") - F("descuento")), name="ck_ventas_linea_base"),
            models.CheckConstraint(condition=Q(total=F("base") + F("iva")), name="ck_ventas_linea_total"),
        ]


class SaldoFinanciero(BaseModel):
    """
    Saldo financiero general de la empresa (pesos colombianos enteros).
    Acumula el dinero disponible por recaudos de facturación contraentrega (HU 7.3).
    """
    nombre = models.CharField(max_length=100, default="Caja General")
    saldo_actual = models.BigIntegerField(default=0)

    class Meta:
        db_table = "ventas_saldo_financiero"
        verbose_name = "Saldo financiero"

    def __str__(self):
        return f"{self.nombre}: ${self.saldo_actual}"


class MovimientoCartera(BaseModel):
    """
    Libro de movimientos del saldo financiero por conciliación de cartera (HU 7.3).
    Registra cada entrada de dinero por recaudo confirmado o registro de devolución.
    """
    factura = models.ForeignKey(FacturaVenta, on_delete=models.PROTECT, related_name="movimientos_cartera")
    tipo = models.CharField(max_length=20, choices=catalog.FINANCIAL_LEDGER_TYPES)
    monto = models.BigIntegerField(help_text="Monto recaudado en pesos enteros (cero si es devolución)")
    saldo_antes = models.BigIntegerField()
    saldo_despues = models.BigIntegerField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    observaciones = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "ventas_movimiento_cartera"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.tipo} {self.factura.numero}: ${self.monto}"

