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


class RecepcionLineaSerializer(serializers.ModelSerializer):
    """Un producto recibido en una recepción, con su lote, su costo y el movimiento del kardex."""
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    unidad = serializers.CharField(source="producto.unidad", read_only=True)

    class Meta:
        model = RecepcionLinea
        fields = ["id", "linea_compra", "producto", "producto_codigo", "producto_nombre", "unidad", "cantidad", "lote", "costo_unitario", "movimiento"]


class RecepcionResumenSerializer(serializers.ModelSerializer):
    """Resumen de una recepción dentro de la orden de compra a la que pertenece."""
    recibido_por_nombre = serializers.SerializerMethodField()
    lineas = RecepcionLineaSerializer(many=True, read_only=True)

    class Meta:
        model = Recepcion
        fields = ["id", "codigo", "fecha", "documento", "recibido_por_nombre", "created_at", "lineas"]

    def get_recibido_por_nombre(self, obj) -> str:
        return _name(obj.recibido_por)


class OrdenCompraSerializer(serializers.ModelSerializer):
    """Orden de compra con sus líneas, su avance de recepción, historial y valor estimado (cantidad × precio pactado)."""
    proveedor_nombre = serializers.CharField(source="proveedor.razon_social", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    creado_por_nombre = serializers.SerializerMethodField()
    aprobado_por_nombre = serializers.SerializerMethodField()
    cerrado_por_nombre = serializers.SerializerMethodField()
    lineas = LineaCompraSerializer(many=True, read_only=True)
    recepciones = RecepcionResumenSerializer(many=True, read_only=True)
    ingresos = serializers.SerializerMethodField(help_text="Ingresos al almacén (kardex) originados por las recepciones de esta orden")
    historial = serializers.SerializerMethodField(help_text="Trazabilidad cronológica de creación, aprobación, recepciones y cierre")
    valor_estimado = serializers.SerializerMethodField(help_text="Suma de cantidad × precio pactado de las líneas con precio")
    lineas_sin_precio = serializers.SerializerMethodField()
    recibible = serializers.SerializerMethodField(help_text="Se puede recibir mercancía contra ella (aprobada o con recepciones parciales)")

    class Meta:
        model = OrdenCompra
        fields = [
            "id", "codigo", "proveedor", "proveedor_nombre", "fecha", "fecha_esperada", "condiciones_pago", "notas", "estado",
            "estado_nombre", "creado_por", "creado_por_nombre", "aprobado_por", "aprobado_por_nombre", "aprobada_at",
            "cerrado_por", "cerrado_por_nombre", "motivo_cierre", "cerrada_at", "valor_estimado", "lineas_sin_precio",
            "recibible", "lineas", "recepciones", "ingresos", "historial", "created_at",
        ]

    def get_creado_por_nombre(self, obj) -> str:
        return _name(obj.creado_por)

    def get_aprobado_por_nombre(self, obj) -> str:
        return _name(obj.aprobado_por)

    def get_cerrado_por_nombre(self, obj) -> str:
        return _name(obj.cerrado_por)

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_ingresos(self, obj):
        items = []
        for receipt in obj.recepciones.all():
            receiver_name = _name(receipt.recibido_por)
            for line in receipt.lineas.all():
                items.append({
                    "id": line.id,
                    "movimiento": line.movimiento_id,
                    "recepcion": receipt.id,
                    "recepcion_codigo": receipt.codigo,
                    "documento": receipt.documento,
                    "fecha": str(receipt.fecha),
                    "producto": line.producto_id,
                    "producto_codigo": line.producto.codigo,
                    "producto_nombre": line.producto.nombre,
                    "unidad": line.producto.unidad,
                    "cantidad": str(line.cantidad),
                    "lote": line.lote,
                    "costo_unitario": str(line.costo_unitario) if line.costo_unitario is not None else None,
                    "recibido_por_nombre": receiver_name,
                    "created_at": receipt.created_at.isoformat() if receipt.created_at else str(receipt.fecha),
                })
        return items

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_historial(self, obj):
        events = [
            {
                "evento": "CREADA",
                "titulo": "Orden creada en borrador",
                "usuario": _name(obj.creado_por),
                "fecha": obj.created_at.isoformat() if obj.created_at else str(obj.fecha),
                "detalle": f"Fecha de orden {obj.fecha}",
            }
        ]
        if obj.aprobada_at or obj.aprobado_por_id:
            events.append({
                "evento": "APROBADA",
                "titulo": "Orden aprobada",
                "usuario": _name(obj.aprobado_por),
                "fecha": obj.aprobada_at.isoformat() if obj.aprobada_at else str(obj.fecha),
                "detalle": "",
            })
        for receipt in obj.recepciones.all():
            events.append({
                "evento": "RECEPCION",
                "titulo": f"Recepción {receipt.codigo}",
                "usuario": _name(receipt.recibido_por),
                "fecha": receipt.created_at.isoformat() if receipt.created_at else str(receipt.fecha),
                "detalle": f"Documento {receipt.documento}",
            })
        if obj.cerrada_at or obj.estado in {catalog.CANCELLED, catalog.CLOSED}:
            events.append({
                "evento": obj.estado,
                "titulo": "Orden cancelada" if obj.estado == catalog.CANCELLED else "Orden cerrada",
                "usuario": _name(obj.cerrado_por),
                "fecha": obj.cerrada_at.isoformat() if obj.cerrada_at else str(obj.fecha),
                "detalle": obj.motivo_cierre,
            })
        return events

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


class OrdenCompraFaltantesInputSerializer(serializers.Serializer):
    """Datos para generar una orden de compra en borrador a partir de los faltantes de producción."""
    referencia = serializers.IntegerField()
    cantidad = serializers.JSONField(help_text="Prendas a producir para calcular los faltantes")
    proveedor = serializers.IntegerField(required=False, allow_null=True, default=None)
    fecha = serializers.DateField(required=False, allow_null=True, default=None)
    fecha_esperada = serializers.DateField(required=False, allow_null=True, default=None)
    condiciones_pago = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    notas = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


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
