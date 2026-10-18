"""
Órdenes de compra de materiales y recepción de mercancía. Nombres de tabla en español y borrado lógico en todo
(ver docs/convenciones-base-de-datos.md).

- OrdenCompra y LineaCompra: lo que se le pide a un proveedor (materia prima e insumos), con su estado y su aprobación.
- Recepcion y RecepcionLinea: lo que llegó. Cada fila de una recepción enlaza con el movimiento del kardex que crea el
  ingreso al almacén (`inventory.services.register_entry`); el kardex y el stock siguen siendo de inventario.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from . import catalog


class OrdenCompra(BaseModel):
    """Pedido de materiales a un proveedor. No es factura ni remisión: confirma lo pedido."""
    codigo = models.CharField(max_length=20)
    proveedor = models.ForeignKey("inventory.Proveedor", on_delete=models.PROTECT, related_name="ordenes_compra")
    fecha = models.DateField(help_text="Fecha de la orden")
    fecha_esperada = models.DateField(null=True, blank=True, help_text="Cuándo se espera la mercancía")
    condiciones_pago = models.CharField(max_length=120, blank=True)
    notas = models.CharField(max_length=500, blank=True)
    estado = models.CharField(max_length=16, choices=catalog.ORDER_STATES, default=catalog.DRAFT)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True)
    aprobada_at = models.DateTimeField(null=True, blank=True)
    # Al cancelarla o cerrarla a mano se exige el motivo.
    motivo_cierre = models.CharField(max_length=255, blank=True)
    cerrada_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "compras_orden"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_compras_orden_codigo_activo"),
        ]
        indexes = [
            models.Index(fields=["estado"], name="ix_compras_orden_estado"),
            models.Index(fields=["proveedor", "-created_at"], name="ix_compras_orden_proveedor"),
        ]

    def __str__(self):
        return self.codigo


class LineaCompra(BaseModel):
    """Un material pedido en la orden. La cantidad recibida no se guarda aquí: se suma de las recepciones."""
    orden = models.ForeignKey(OrdenCompra, on_delete=models.PROTECT, related_name="lineas")
    producto = models.ForeignKey("inventory.Producto", on_delete=models.PROTECT, related_name="+")
    cantidad_pedida = models.DecimalField(max_digits=12, decimal_places=2)
    precio_pactado = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        help_text="Costo por unidad acordado con el proveedor (opcional). El costo real se anota al recibir.",
    )

    class Meta:
        db_table = "compras_linea"
        ordering = ["orden_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["orden", "producto"], condition=Q(deleted_at__isnull=True), name="uq_compras_linea_producto"
            ),
            models.CheckConstraint(condition=Q(cantidad_pedida__gt=0), name="ck_compras_linea_cantidad"),
            models.CheckConstraint(
                condition=Q(precio_pactado__isnull=True) | Q(precio_pactado__gt=0), name="ck_compras_linea_precio"
            ),
        ]


class Recepcion(BaseModel):
    """Entrega de mercancía recibida en el almacén: con una orden de compra o suelta (varios productos de un proveedor)."""
    codigo = models.CharField(max_length=20)
    orden = models.ForeignKey(OrdenCompra, on_delete=models.PROTECT, related_name="recepciones", null=True, blank=True)
    proveedor = models.ForeignKey("inventory.Proveedor", on_delete=models.PROTECT, related_name="recepciones")
    documento = models.CharField(max_length=40, help_text="Número de la remisión o la factura del proveedor")
    fecha = models.DateField()
    observaciones = models.CharField(max_length=500, blank=True)
    recibido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)

    class Meta:
        db_table = "compras_recepcion"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_compras_recepcion_codigo_activo"),
        ]
        indexes = [models.Index(fields=["orden"], name="ix_compras_recepcion_orden")]

    def __str__(self):
        return self.codigo


class RecepcionLinea(BaseModel):
    """Un producto recibido en una recepción, con su lote y su costo real, enlazado al movimiento del kardex."""
    recepcion = models.ForeignKey(Recepcion, on_delete=models.PROTECT, related_name="lineas")
    linea_compra = models.ForeignKey(LineaCompra, on_delete=models.PROTECT, related_name="recibidos", null=True, blank=True)
    producto = models.ForeignKey("inventory.Producto", on_delete=models.PROTECT, related_name="+")
    movimiento = models.OneToOneField("inventory.Movimiento", on_delete=models.PROTECT, related_name="recepcion_linea")
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    lote = models.CharField(max_length=60)
    costo_unitario = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = "compras_recepcion_linea"
        ordering = ["recepcion_id", "id"]
        constraints = [models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_compras_recepcion_cantidad")]
        indexes = [models.Index(fields=["linea_compra"], name="ix_compras_recep_linea")]
