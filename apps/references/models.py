"""
Catálogo de referencias de jean (HU 3.1). Nombres de tabla en español, borrado lógico en todo
(ver docs/convenciones-base-de-datos.md).

- Referencia: el modelo de jean (diseño, ajuste y estado). No lleva existencias: lo que se
  cuenta en el inventario sigue siendo el `Producto` terminado.
- Variante: una combinación de talla y color con la que se fabrica la referencia.
- ImagenReferencia: fotos del prototipo (hasta `MAX_IMAGES`), una de ellas principal.
- FichaTecnica y FichaLinea (HU 3.2): materiales y consumo por prenda de la referencia.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.models import ActiveManager, ActiveQuerySet, BaseModel

from . import catalog


class Referencia(BaseModel):
    """Un modelo de jean del catálogo de la empresa."""
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=150)
    descripcion = models.CharField(max_length=500, blank=True)
    ajuste = models.CharField(max_length=15, choices=catalog.FITS)
    estado = models.CharField(max_length=15, choices=catalog.STATES, default=catalog.DRAFT)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)

    class Meta:
        db_table = "referencias_referencia"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["codigo"], condition=Q(deleted_at__isnull=True), name="uq_referencia_codigo_activo"
            ),
            models.UniqueConstraint(
                Lower("nombre"), condition=Q(deleted_at__isnull=True), name="uq_referencia_nombre_activo"
            ),
        ]

    def __str__(self):
        return f"{self.codigo} {self.nombre}"


class Variante(BaseModel):
    """Talla y color en que se fabrica una referencia."""
    referencia = models.ForeignKey(Referencia, on_delete=models.PROTECT, related_name="variantes")
    talla = models.CharField(max_length=10)
    color = models.CharField(max_length=60)

    class Meta:
        db_table = "referencias_variante"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                "referencia", "talla", Lower("color"),
                condition=Q(deleted_at__isnull=True), name="uq_variante_referencia_talla_color",
            ),
        ]

    def __str__(self):
        return f"{self.referencia_id} {self.talla} {self.color}"


class ImagenManager(ActiveManager):
    """La imagen pesa: no se trae de la base salvo que se pida."""

    def get_queryset(self):
        return super().get_queryset().defer("imagen")


class ImagenReferencia(BaseModel):
    """Foto del prototipo. Se guarda en la base y se sirve con sesión (como la del catálogo de insumos)."""
    referencia = models.ForeignKey(Referencia, on_delete=models.PROTECT, related_name="imagenes")
    imagen = models.BinaryField(editable=False)
    tipo = models.CharField(max_length=20)
    version = models.PositiveIntegerField(default=1)
    principal = models.BooleanField(default=False)

    objects = ImagenManager()
    all_objects = models.Manager.from_queryset(ActiveQuerySet)()

    class Meta:
        db_table = "referencias_imagen"
        ordering = ["-principal", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["referencia"], condition=Q(principal=True, deleted_at__isnull=True),
                name="uq_imagen_una_principal",
            ),
        ]


class FichaManager(ActiveManager):
    """El PDF pesa: no se trae de la base salvo que se pida."""

    def get_queryset(self):
        return super().get_queryset().defer("documento")


class FichaTecnica(BaseModel):
    """Ficha técnica de consumo por unidad (HU 3.2): qué materiales y cuánto lleva una prenda
    de la referencia. Una por referencia; el consumo vive en `FichaLinea`. Puede adjuntar el PDF de la
    ficha técnica extensa, que trae lo que este módulo todavía no modela (geometral, secuencia de
    confección, tabla de medidas).
    """
    referencia = models.ForeignKey(Referencia, on_delete=models.PROTECT, related_name="fichas")
    lavado = models.CharField(max_length=15, choices=catalog.WASHES, blank=True)
    notas = models.CharField(max_length=500, blank=True)
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True)
    documento = models.BinaryField(null=True, blank=True, editable=False)
    documento_nombre = models.CharField(max_length=120, blank=True)
    documento_tamano = models.PositiveIntegerField(default=0)
    documento_version = models.PositiveIntegerField(default=0)  # sube con cada cambio del PDF

    objects = FichaManager()
    all_objects = models.Manager.from_queryset(ActiveQuerySet)()

    class Meta:
        db_table = "referencias_ficha"
        constraints = [
            models.UniqueConstraint(
                fields=["referencia"], condition=Q(deleted_at__isnull=True), name="uq_ficha_referencia_activa"
            ),
        ]

    def __str__(self):
        return f"Ficha de {self.referencia_id}"

    @property
    def tiene_documento(self) -> bool:
        return self.documento_tamano > 0


class FichaLinea(BaseModel):
    """Un material de la ficha: cuánto se consume por prenda, con su merma (%) cuando aplica
    (p. ej. el desperdicio de corte de la tela).
    """
    ficha = models.ForeignKey(FichaTecnica, on_delete=models.PROTECT, related_name="lineas")
    producto = models.ForeignKey("inventory.Producto", on_delete=models.PROTECT, related_name="+")
    cantidad = models.DecimalField(max_digits=10, decimal_places=3)  # por prenda, en la unidad del producto
    merma = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # %
    observaciones = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "referencias_ficha_linea"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ficha", "producto"], condition=Q(deleted_at__isnull=True), name="uq_ficha_linea_material"
            ),
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_ficha_linea_cantidad_positiva"),
            models.CheckConstraint(
                condition=Q(merma__gte=0, merma__lte=catalog.MAX_WASTE), name="ck_ficha_linea_merma_rango"
            ),
        ]
