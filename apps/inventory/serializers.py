from decimal import Decimal

from rest_framework import serializers

from . import catalog
from .models import Evidencia, Movimiento, OrdenSalida, Producto


class ProductoSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)
    bajo_minimo = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = [
            "id", "codigo", "nombre", "tipo", "tipo_nombre", "unidad", "stock_actual",
            "stock_minimo", "bajo_minimo", "descripcion",
        ]
        read_only_fields = ["id", "codigo", "stock_actual"]

    def get_bajo_minimo(self, obj):
        return obj.stock_minimo > 0 and obj.stock_actual <= obj.stock_minimo

    def validate_nombre(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Escribe el nombre.")
        return value

    def validate_stock_minimo(self, value):
        if value < 0:
            raise serializers.ValidationError("El mínimo no puede ser negativo.")
        return value

    def validate(self, attrs):
        # Tipo y unidad no cambian: los movimientos ya registrados dependen de ellos.
        if self.instance:
            for field in ("tipo", "unidad"):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({field: "No se puede cambiar después de crear el producto."})
        return attrs


class EvidenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Evidencia
        fields = ["id", "nombre_original", "content_type", "tamano", "created_at"]


class MovimientoSerializer(serializers.ModelSerializer):
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
            "cantidad", "stock_antes", "stock_despues", "fecha", "proveedor", "orden_compra",
            "lote", "orden", "orden_codigo", "observaciones", "registrado_por_nombre",
            "evidencias", "created_at",
        ]

    def get_registrado_por_nombre(self, obj):
        return (obj.registrado_por.get_full_name() or obj.registrado_por.email) if obj.registrado_por else ""

    def get_evidencias(self, obj):
        # Las evidencias de una salida se adjuntan a la orden, no a cada línea:
        # las filas de salida y anulación muestran las de su orden. El retorno
        # (ingreso) tiene las suyas propias.
        items = list(obj.evidencias.all())
        if obj.orden_id and obj.motivo != catalog.REASON_ORDER_RETURN:
            items += list(obj.orden.evidencias.all())
        return EvidenciaSerializer(items, many=True).data


class OrdenSerializer(serializers.ModelSerializer):
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

    def get_registrado_por_nombre(self, obj):
        return (obj.registrado_por.get_full_name() or obj.registrado_por.email) if obj.registrado_por else ""

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

class IngresoInputSerializer(serializers.Serializer):
    producto = serializers.IntegerField()
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=2)
    fecha = serializers.DateField()
    proveedor = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    orden_compra = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    lote = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    orden = serializers.IntegerField(required=False, allow_null=True, default=None)
    observaciones = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class LineaInputSerializer(serializers.Serializer):
    producto = serializers.IntegerField()
    cantidad = serializers.DecimalField(max_digits=12, decimal_places=2)


class OrdenInputSerializer(serializers.Serializer):
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
    motivo = serializers.CharField(max_length=255)


class ProductoInputSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=150)
    tipo = serializers.ChoiceField(choices=catalog.PRODUCT_TYPES)
    unidad = serializers.ChoiceField(choices=catalog.UNITS)
    stock_minimo = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, default=Decimal("0")
    )
    descripcion = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate_nombre(self, value):
        if not value.strip():
            raise serializers.ValidationError("Escribe el nombre.")
        return value
