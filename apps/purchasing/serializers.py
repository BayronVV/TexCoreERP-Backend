"""Serializers de compras: órdenes con lo recibido y lo pendiente por línea, y recepciones con sus filas."""
from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import catalog, services
from .models import LineaCompra, OrdenCompra, Recepcion, RecepcionLinea

CENTS = Decimal("0.01")


def _name(user):
    return (user.get_full_name() or user.email) if user else ""


class LineaCompraSerializer(serializers.ModelSerializer):
    """Material pedido con lo recibido y lo que falta. `recibido` sale de las recepciones (lo calcula la vista de la orden)."""
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    unidad = serializers.CharField(source="producto.unidad", read_only=True)
    cantidad_recibida = serializers.SerializerMethodField()
    pendiente = serializers.SerializerMethodField()
    maximo_a_recibir = serializers.SerializerMethodField(help_text="Lo pendiente más la tolerancia de exceso (5 %)")
    completa = serializers.SerializerMethodField()

    class Meta:
        model = LineaCompra
        fields = [
            "id", "producto", "producto_codigo", "producto_nombre", "unidad", "cantidad_pedida", "precio_pactado",
            "cantidad_recibida", "pendiente", "maximo_a_recibir", "completa",
        ]

    def _received(self, obj):
        received = self.context.get("received")
        if received is None:
            received = services.received_by_line([obj.id])
        return received

    def get_cantidad_recibida(self, obj) -> str:
        return str(self._received(obj).get(obj.id, Decimal(0)).quantize(CENTS))

    def get_pendiente(self, obj) -> str:
        return str(services.pending_quantity(obj, self._received(obj)).quantize(CENTS))

    def get_maximo_a_recibir(self, obj) -> str:
        return str(services.allowed_quantity(obj, self._received(obj)))

    def get_completa(self, obj) -> bool:
        return services.pending_quantity(obj, self._received(obj)) == 0


class RecepcionResumenSerializer(serializers.ModelSerializer):
    """Resumen de una recepción dentro de la orden de compra a la que pertenece."""
    class Meta:
        model = Recepcion
        fields = ["id", "codigo", "fecha", "documento"]


class OrdenCompraSerializer(serializers.ModelSerializer):
    """Orden de compra con sus líneas, su avance de recepción y su valor estimado (cantidad × precio pactado)."""
    proveedor_nombre = serializers.CharField(source="proveedor.razon_social", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    creado_por_nombre = serializers.SerializerMethodField()
    aprobado_por_nombre = serializers.SerializerMethodField()
    lineas = LineaCompraSerializer(many=True, read_only=True)
    recepciones = RecepcionResumenSerializer(many=True, read_only=True)
    valor_estimado = serializers.SerializerMethodField(help_text="Suma de cantidad × precio pactado de las líneas con precio")
    lineas_sin_precio = serializers.SerializerMethodField()
    recibible = serializers.SerializerMethodField(help_text="Se puede recibir mercancía contra ella (aprobada o con recepciones parciales)")

    class Meta:
        model = OrdenCompra
        fields = [
            "id", "codigo", "proveedor", "proveedor_nombre", "fecha", "fecha_esperada", "condiciones_pago", "notas", "estado",
            "estado_nombre", "creado_por_nombre", "aprobado_por_nombre", "aprobada_at", "motivo_cierre", "cerrada_at",
            "valor_estimado", "lineas_sin_precio", "recibible", "lineas", "recepciones", "created_at",
        ]

    def get_creado_por_nombre(self, obj) -> str:
        return _name(obj.creado_por)

    def get_aprobado_por_nombre(self, obj) -> str:
        return _name(obj.aprobado_por)

    def get_valor_estimado(self, obj) -> str:
        total = sum((line.cantidad_pedida * line.precio_pactado for line in obj.lineas.all() if line.precio_pactado), Decimal(0))
        return str(total.quantize(CENTS))

    def get_lineas_sin_precio(self, obj) -> int:
        return sum(1 for line in obj.lineas.all() if line.precio_pactado is None)

    def get_recibible(self, obj) -> bool:
        return obj.estado in catalog.RECEIVABLE_STATES


class OrdenCompraInputSerializer(serializers.Serializer):
    """Datos de la orden. En `PATCH` solo se envía lo que cambia; las líneas, si se envían, reemplazan a las anteriores."""
    proveedor = serializers.IntegerField()
    fecha = serializers.DateField(required=False, allow_null=True, help_text="Por defecto hoy; no puede ser futura")
    fecha_esperada = serializers.DateField(required=False, allow_null=True)
    condiciones_pago = serializers.CharField(max_length=120, required=False, allow_blank=True)
    notas = serializers.CharField(max_length=500, required=False, allow_blank=True)
    lineas = serializers.JSONField(help_text="`[{producto, cantidad, precio_pactado?}]`: materia prima o insumos, sin repetir producto")


class MotivoSerializer(serializers.Serializer):
    """Motivo obligatorio para cancelar o cerrar una orden de compra."""
    motivo = serializers.CharField(max_length=255)


class RecepcionInputSerializer(serializers.Serializer):
    """Datos para registrar una recepción: orden o proveedor, documento, fecha y filas con cantidad, lote y costo."""
    orden = serializers.IntegerField(required=False, allow_null=True, help_text="Orden de compra aprobada (vacío para una recepción suelta)")
    proveedor = serializers.IntegerField(required=False, allow_null=True, help_text="Solo en una recepción suelta; con orden sale de la orden")
    documento = serializers.CharField(max_length=40, help_text="Número de la remisión o la factura del proveedor")
    fecha = serializers.DateField(required=False, allow_null=True, help_text="Por defecto hoy; no puede ser futura")
    observaciones = serializers.CharField(max_length=500, required=False, allow_blank=True)
    lineas = serializers.JSONField(
        help_text="`[{linea, cantidad, lote, costo_unitario?}]` con orden (la línea de la orden) o `[{producto, cantidad, lote, costo_unitario?}]` suelta"
    )


class RecepcionLineaSerializer(serializers.ModelSerializer):
    """Un producto recibido en una recepción, con su lote, su costo y el movimiento del kardex."""
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    unidad = serializers.CharField(source="producto.unidad", read_only=True)

    class Meta:
        model = RecepcionLinea
        fields = ["id", "linea_compra", "producto", "producto_codigo", "producto_nombre", "unidad", "cantidad", "lote", "costo_unitario", "movimiento"]


class RecepcionSerializer(serializers.ModelSerializer):
    """Una recepción de mercancía con sus filas."""
    proveedor_nombre = serializers.CharField(source="proveedor.razon_social", read_only=True)
    orden_codigo = serializers.SerializerMethodField()
    recibido_por_nombre = serializers.SerializerMethodField()
    lineas = RecepcionLineaSerializer(many=True, read_only=True)
    orden_estado = serializers.SerializerMethodField(help_text="Estado de la orden después de esta recepción (vacío si es suelta)")

    class Meta:
        model = Recepcion
        fields = [
            "id", "codigo", "orden", "orden_codigo", "orden_estado", "proveedor", "proveedor_nombre", "documento", "fecha",
            "observaciones", "recibido_por_nombre", "lineas", "created_at",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_orden_codigo(self, obj):
        return obj.orden.codigo if obj.orden else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_orden_estado(self, obj):
        return obj.orden.estado if obj.orden else None

    def get_recibido_por_nombre(self, obj) -> str:
        return _name(obj.recibido_por)
