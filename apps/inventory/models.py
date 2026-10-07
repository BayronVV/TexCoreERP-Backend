"""
Inventario (HU 2.3 y 2.4). Nombres de tabla en español, borrado lógico en todo
(ver docs/convenciones-base-de-datos.md).

- Proveedor: a quién se le compra (RF04). Se clasifica por la categoría que suministra.
- Producto: el catálogo (RF05) y, a la vez, lo que tiene existencias (tela, botones,
  pantalón genérico, jean terminado). Su saldo vive en `stock_actual` y solo cambia
  con movimientos: el catálogo no lo muestra ni lo edita.
- Movimiento: kardex. Cada cambio de saldo deja una fila con saldo antes y después.
- OrdenSalida: documento OP/LV con varias líneas. Descuenta el inventario al
  crearse y, cuando lo fabricado regresa, se cierra con un ingreso.
- Evidencia: foto o PDF adjunto a un movimiento o a una orden.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import ActiveManager, ActiveQuerySet, BaseModel

from . import catalog


class Consecutivo(models.Model):
    """Último número usado por cada prefijo (OP, LV, MP...). Se bloquea al asignar."""

    clave = models.CharField(max_length=10, unique=True)
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "inventario_consecutivo"


class Proveedor(BaseModel):
    """Proveedor de telas e insumos (HU 2.1). El NIT es único entre los proveedores activos."""
    # NIT sin puntos ni dígito de verificación; el DV va aparte. Es único entre los activos.
    nit = models.CharField(max_length=10)
    nit_dv = models.CharField(max_length=1, blank=True)
    razon_social = models.CharField(max_length=150)
    categoria = models.CharField(max_length=20, choices=catalog.SUPPLIER_CATEGORY_CHOICES)
    contacto = models.CharField(max_length=120, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    correo = models.EmailField(max_length=120, blank=True)
    ciudad = models.CharField(max_length=80, blank=True)
    direccion = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "inventario_proveedor"
        ordering = ["razon_social"]
        constraints = [
            models.UniqueConstraint(
                fields=["nit"], condition=Q(deleted_at__isnull=True), name="uq_proveedor_nit_activo"
            ),
        ]

    def __str__(self):
        return self.razon_social


class ProductoManager(ActiveManager):
    """La imagen de referencia pesa; no se trae de la base salvo que se pida."""

    def get_queryset(self):
        return super().get_queryset().defer("imagen")


class ProductoAllManager(models.Manager.from_queryset(ActiveQuerySet)):
    """Incluye eliminados (borrado lógico), también sin traer la imagen."""

    def get_queryset(self):
        return super().get_queryset().defer("imagen")


class Producto(BaseModel):
    """Producto del catálogo (HU 2.2): materia prima, insumo, pantalón genérico o terminado.
    La categoría fija el tipo; `stock_actual` solo cambia mediante movimientos.
    """
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=150)
    tipo = models.CharField(max_length=15, choices=catalog.PRODUCT_TYPES)
    # Vacía solo en productos anteriores al catálogo; la migración 0003 los clasifica.
    categoria = models.CharField(max_length=20, choices=catalog.CATEGORY_CHOICES, blank=True)
    unidad = models.CharField(max_length=10, choices=catalog.UNITS)
    stock_actual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    descripcion = models.CharField(max_length=255, blank=True)
    # Ancho útil del rollo en metros (lo necesita el corte computarizado). Solo telas.
    ancho_util = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    color = models.CharField(max_length=60, blank=True)
    composicion = models.CharField(max_length=120, blank=True)
    imagen = models.BinaryField(null=True, blank=True, editable=False)
    imagen_tipo = models.CharField(max_length=20, blank=True)
    imagen_version = models.PositiveIntegerField(default=0)  # sube con cada cambio de imagen

    objects = ProductoManager()
    all_objects = ProductoAllManager()

    class Meta:
        db_table = "inventario_producto"
        ordering = ["tipo", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_producto_codigo_activo"
            ),
            models.CheckConstraint(condition=Q(stock_actual__gte=0), name="ck_producto_stock_no_negativo"),
            models.CheckConstraint(condition=Q(stock_minimo__gte=0), name="ck_producto_minimo_no_negativo"),
        ]

    def __str__(self):
        return f"{self.codigo} {self.nombre}"

    @property
    def tiene_imagen(self) -> bool:
        return bool(self.imagen_tipo)


class OrdenSalida(BaseModel):
    """Orden de producción (OP) o de lavandería (LV) que saca materiales del almacén (HU 2.3)."""
    codigo = models.CharField(max_length=20)
    tipo = models.CharField(max_length=12, choices=catalog.ORDER_TYPES)
    estado = models.CharField(max_length=12, choices=catalog.ORDER_STATUSES, default=catalog.STATUS_OPEN)
    fecha_salida = models.DateField()
    responsable = models.CharField(max_length=120)
    destino = models.CharField(max_length=120, blank=True)
    # Hasta que exista el módulo de fichas técnicas es un código escrito a mano.
    ficha_tecnica = models.CharField(max_length=60)
    producto_resultado = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="ordenes_resultado")
    # Producción: pantalones que se planea fabricar (opcional). Lavandería: los que se envían.
    cantidad_prendas = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    observaciones = models.TextField(blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True
    )
    completada_at = models.DateTimeField(null=True, blank=True)
    anulada_at = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "inventario_orden"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_orden_codigo_activo"
            ),
        ]

    def __str__(self):
        return self.codigo


class OrdenLinea(BaseModel):
    """Línea de la cesta de una orden: un producto y la cantidad que sale."""
    orden = models.ForeignKey(OrdenSalida, on_delete=models.PROTECT, related_name="lineas")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="+")
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "inventario_orden_linea"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_orden_linea_cantidad_positiva"),
            models.UniqueConstraint(
                fields=["orden", "producto"], condition=Q(deleted_at__isnull=True), name="uq_orden_linea_producto"
            ),
        ]


class Movimiento(BaseModel):
    """Fila del kardex: cada ingreso o salida con el saldo antes y después, el usuario y la fecha."""
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=8, choices=catalog.MOVEMENT_TYPES)
    motivo = models.CharField(max_length=15, choices=catalog.MOVEMENT_REASONS)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    stock_antes = models.DecimalField(max_digits=12, decimal_places=2)
    stock_despues = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField()
    # Compras: el proveedor elegido y su nombre al momento de la compra (si el proveedor
    # cambia de razón social o se archiva, el historial sigue diciendo lo que se registró).
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, null=True, blank=True, related_name="movimientos")
    proveedor_nombre = models.CharField(max_length=150, blank=True)
    orden_compra = models.CharField(max_length=40, blank=True)
    lote = models.CharField(max_length=60, blank=True)
    orden = models.ForeignKey(OrdenSalida, on_delete=models.PROTECT, null=True, blank=True, related_name="movimientos")
    observaciones = models.TextField(blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True
    )

    class Meta:
        db_table = "inventario_movimiento"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["producto", "-created_at"], name="ix_mov_producto_fecha")]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_movimiento_cantidad_positiva"),
        ]


def _evidence_path(instance, filename):
    # Nombre aleatorio: el original no se usa en disco (evita colisiones y rutas raras).
    return f"evidencias/{uuid.uuid4().hex}{filename[filename.rfind('.'):]}"


class Evidencia(BaseModel):
    """Foto o PDF adjunto a un movimiento o a una orden."""
    movimiento = models.ForeignKey(Movimiento, on_delete=models.PROTECT, null=True, blank=True, related_name="evidencias")
    orden = models.ForeignKey(OrdenSalida, on_delete=models.PROTECT, null=True, blank=True, related_name="evidencias")
    archivo = models.FileField(upload_to=_evidence_path)
    nombre_original = models.CharField(max_length=120)
    content_type = models.CharField(max_length=40)
    tamano = models.PositiveIntegerField()
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)

    class Meta:
        db_table = "inventario_evidencia"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(movimiento__isnull=False, orden__isnull=True)
                    | Q(movimiento__isnull=True, orden__isnull=False)
                ),
                name="ck_evidencia_un_solo_dueno",
            ),
        ]
