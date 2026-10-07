from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import catalog, services
from .models import Evidencia, Movimiento, OrdenSalida, Producto, Proveedor


def category_name(obj):
    data = catalog.CATEGORIES.get(obj.categoria)
    return data["label"] if data else obj.get_tipo_display()


class ProductoSerializer(serializers.ModelSerializer):
    """Vista de inventario: con existencias. Es de solo lectura; el catálogo es quien edita."""

    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)
    categoria_nombre = serializers.SerializerMethodField()
    bajo_minimo = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = [
            "id", "codigo", "nombre", "tipo", "tipo_nombre", "categoria", "categoria_nombre", "unidad",
            "stock_actual", "stock_minimo", "bajo_minimo", "descripcion", "ancho_util", "color",
            "composicion", "tiene_imagen", "imagen_version",
        ]
        read_only_fields = fields

    def get_categoria_nombre(self, obj) -> str:
        return category_name(obj)

    def get_bajo_minimo(self, obj) -> bool:
        return obj.stock_minimo > 0 and obj.stock_actual <= obj.stock_minimo


class CatalogoSerializer(serializers.ModelSerializer):
    """Vista de catálogo. No expone `stock_actual` ni `bajo_minimo`: las existencias solo se
    cambian (y se consultan) desde los movimientos de inventario."""

    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)
    categoria_nombre = serializers.SerializerMethodField()
    unidades_permitidas = serializers.SerializerMethodField()
    nombre = serializers.CharField(max_length=150)
    categoria = serializers.ChoiceField(choices=catalog.CATEGORY_CHOICES)
    unidad = serializers.ChoiceField(choices=catalog.UNITS)
    stock_minimo = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, default=Decimal("0")
    )
    descripcion = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    ancho_util = serializers.DecimalField(
        max_digits=4, decimal_places=2, required=False, allow_null=True, default=None
    )
    color = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    composicion = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")

    class Meta:
        model = Producto
        fields = [
            "id", "codigo", "nombre", "tipo", "tipo_nombre", "categoria", "categoria_nombre", "unidad",
            "unidades_permitidas", "stock_minimo", "descripcion", "ancho_util", "color", "composicion",
            "tiene_imagen", "imagen_version", "created_at",
        ]
        read_only_fields = ["id", "codigo", "tipo", "tiene_imagen", "imagen_version", "created_at"]

    def get_categoria_nombre(self, obj) -> str:
        return category_name(obj)

    def get_unidades_permitidas(self, obj) -> list[str]:
        data = catalog.CATEGORIES.get(obj.categoria)
        return data["units"] if data else [u for u, _ in catalog.UNITS]

    def validate_nombre(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Escribe el nombre.")
        return value

    def create(self, validated_data):
        return services.create_product(**validated_data)

    def update(self, instance, validated_data):
        # En una edición parcial solo se toca lo que llegó (los defaults no cuentan).
        return services.update_product(instance, **{k: v for k, v in validated_data.items() if k in self.initial_data})


class ProveedorSerializer(serializers.ModelSerializer):
    """Proveedor (HU 2.1) con NIT formateado e insumos vinculados (se deducen del kardex)."""
    categoria_nombre = serializers.SerializerMethodField()
    nit_formateado = serializers.SerializerMethodField()
    insumos_vinculados = serializers.IntegerField(read_only=True, default=0)
    archivado = serializers.SerializerMethodField()
    # El NIT se escribe como lo teclea la persona (con o sin puntos); se guarda normalizado.
    nit = serializers.CharField(max_length=20)
    razon_social = serializers.CharField(max_length=150)
    categoria = serializers.ChoiceField(choices=catalog.SUPPLIER_CATEGORY_CHOICES)
    contacto = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    telefono = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    correo = serializers.EmailField(max_length=120, required=False, allow_blank=True, default="")
    ciudad = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    direccion = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    class Meta:
        model = Proveedor
        fields = [
            "id", "nit", "nit_dv", "nit_formateado", "razon_social", "categoria", "categoria_nombre",
            "contacto", "telefono", "correo", "ciudad", "direccion", "insumos_vinculados", "archivado",
            "created_at",
        ]
        read_only_fields = ["id", "nit_dv", "created_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["nit"] = instance.nit  # sin puntos ni dígito de verificación
        return data

    def get_categoria_nombre(self, obj) -> str:
        return dict(catalog.SUPPLIER_CATEGORY_CHOICES).get(obj.categoria, obj.categoria)

    def get_nit_formateado(self, obj) -> str:
        body = f"{int(obj.nit):,}".replace(",", ".") if obj.nit.isdigit() else obj.nit
        return f"{body}-{obj.nit_dv}" if obj.nit_dv else body

    def get_archivado(self, obj) -> bool:
        return obj.deleted_at is not None

    def validate_razon_social(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Escribe la razón social.")
        return value

    def create(self, validated_data):
        return services.save_supplier(**validated_data)

    def update(self, instance, validated_data):
        return services.save_supplier(instance, **{k: v for k, v in validated_data.items() if k in self.initial_data})


class EvidenciaSerializer(serializers.ModelSerializer):
    """Metadatos de una evidencia; el archivo se descarga con sesión."""
    class Meta:
        model = Evidencia
        fields = ["id", "nombre_original", "content_type", "tamano", "created_at"]


class MovimientoSerializer(serializers.ModelSerializer):
    """Movimiento del kardex con su producto, proveedor, usuario y evidencias."""
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)
    unidad = serializers.CharField(source="producto.unidad", read_only=True)
    orden_codigo = serializers.CharField(source="orden.codigo", read_only=True, default=None)
    registrado_por_nombre = serializers.SerializerMethodField()
    evidencias = serializers.SerializerMethodField()

    class Meta:
        model = Movimiento
        fields = [
            "id", "producto", "producto_codigo", "producto_nombre", "unidad", "tipo", "motivo",
            "cantidad", "stock_antes", "stock_despues", "fecha", "proveedor", "proveedor_nombre", "orden_compra",
            "lote", "orden", "orden_codigo", "observaciones", "registrado_por_nombre",
            "evidencias", "created_at",
        ]

    def get_registrado_por_nombre(self, obj) -> str:
        return (obj.registrado_por.get_full_name() or obj.registrado_por.email) if obj.registrado_por else ""

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_evidencias(self, obj):
        # Las evidencias de una salida se adjuntan a la orden, no a cada línea:
        # las filas de salida y anulación muestran las de su orden. El retorno
        # (ingreso) tiene las suyas propias.
        items = list(obj.evidencias.all())
        if obj.orden_id and obj.motivo != catalog.REASON_ORDER_RETURN:
            items += list(obj.orden.evidencias.all())
        return EvidenciaSerializer(items, many=True).data


class OrdenSerializer(serializers.ModelSerializer):
    """Orden de salida con sus líneas y evidencias."""
    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    producto_resultado_nombre = serializers.CharField(source="producto_resultado.nombre", read_only=True)
    registrado_por_nombre = serializers.SerializerMethodField()
    lineas = serializers.SerializerMethodField()
    evidencias = EvidenciaSerializer(many=True, read_only=True)

    class Meta:
        model = OrdenSalida
        fields = [
            "id", "codigo", "tipo", "tipo_nombre", "estado", "estado_nombre", "fecha_salida",
            "responsable", "destino", "ficha_tecnica", "producto_resultado",
            "producto_resultado_nombre", "cantidad_prendas", "observaciones", "lineas",
            "evidencias", "registrado_por_nombre", "completada_at", "anulada_at",
            "motivo_anulacion", "created_at",
        ]

    def get_registrado_por_nombre(self, obj) -> str:
        return (obj.registrado_por.get_full_name() or obj.registrado_por.email) if obj.registrado_por else ""

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_lineas(self, obj):
        return [
            {
                "producto": line.producto_id,
                "codigo": line.producto.codigo,
                "nombre": line.producto.nombre,
                "unidad": line.producto.unidad,
                "cantidad": line.cantidad,
            }
            for line in obj.lineas.all()
        ]


# --- Entradas de escritura (validan forma; las reglas de negocio están en services) ---

class OptionalIdField(serializers.IntegerField):
    """Id opcional: una cadena vacía (campo sin elegir en el formulario) cuenta como ausente."""

    def to_internal_value(self, data):
        if isinstance(data, str) and not data.strip():
            return None
        return super().to_internal_value(data)


class IngresoInputSerializer(serializers.Serializer):
    """Datos para registrar un ingreso (`POST /api/inventario/ingresos/`)."""
    producto = serializers.IntegerField()
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=2)
    fecha = serializers.DateField()
    proveedor = OptionalIdField(required=False, allow_null=True, default=None)
    orden_compra = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    lote = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    orden = OptionalIdField(required=False, allow_null=True, default=None)
    observaciones = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class LineaInputSerializer(serializers.Serializer):
    """Una línea de la cesta: producto y cantidad."""
    producto = serializers.IntegerField()
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=2)


class OrdenInputSerializer(serializers.Serializer):
    """Datos para crear una orden con su cesta de materiales."""
    tipo = serializers.ChoiceField(choices=catalog.ORDER_TYPES)
    fecha_salida = serializers.DateField()
    responsable = serializers.CharField(max_length=120)
    destino = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    ficha_tecnica = serializers.CharField(max_length=60)
    producto_resultado = serializers.IntegerField()
    cantidad_prendas = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, default=None
    )
    observaciones = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    lineas = LineaInputSerializer(many=True, allow_empty=False, max_length=50)

    def validate_responsable(self, value):
        if not value.strip():
            raise serializers.ValidationError("Escribe quién se encarga.")
        return value

    def validate_ficha_tecnica(self, value):
        if not value.strip():
            raise serializers.ValidationError("Escribe la ficha técnica.")
        return value


class AnulacionInputSerializer(serializers.Serializer):
    """Motivo obligatorio para anular una orden."""
    motivo = serializers.CharField(max_length=255)
