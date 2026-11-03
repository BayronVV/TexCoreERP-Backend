"""Serializers de producto terminado: ingresos, inspecciones pendientes, existencias en matriz y movimientos."""
from django.utils import timezone
from rest_framework import serializers

from . import catalog
from .models import IngresoLinea, IngresoTerminado, MovimientoTerminado


def _name(user):
    if user is None:
        return ""
    return (f"{user.first_name} {user.last_name}".strip()) or user.username


class IngresoLineaSerializer(serializers.ModelSerializer):
    """Prendas de una talla y color en un ingreso, con lo que estaba planificado en el lote."""
    diferencia = serializers.SerializerMethodField(help_text="Ingresado menos planificado (vacío si el lote no tenía desglose por talla)")

    class Meta:
        model = IngresoLinea
        fields = ["id", "variante", "talla", "color", "cantidad", "planificada", "diferencia"]

    def get_diferencia(self, obj) -> int | None:
        return None if obj.planificada is None else obj.cantidad - obj.planificada


class IngresoSerializer(serializers.ModelSerializer):
    """Ingreso de las aptas de una inspección al inventario final."""
    inspeccion_codigo = serializers.CharField(source="inspeccion.codigo", read_only=True)
    lote_codigo = serializers.CharField(source="lote.codigo", read_only=True)
    orden_codigo = serializers.CharField(source="lote.orden.codigo", read_only=True)
    referencia = serializers.IntegerField(source="lote.orden.referencia_id", read_only=True)
    referencia_nombre = serializers.CharField(source="lote.orden.referencia.nombre", read_only=True)
    recibido_por_nombre = serializers.SerializerMethodField()
    lineas = IngresoLineaSerializer(many=True, read_only=True)

    class Meta:
        model = IngresoTerminado
        fields = [
            "id", "codigo", "inspeccion", "inspeccion_codigo", "lote", "lote_codigo", "orden_codigo", "referencia", "referencia_nombre",
            "fecha", "aptas", "ubicacion", "observaciones", "recibido_por_nombre", "lineas", "created_at",
        ]

    def get_recibido_por_nombre(self, obj) -> str:
        return _name(obj.recibido_por)


class LineaIngresoInputSerializer(serializers.Serializer):
    """Una fila del reparto por talla."""
    variante = serializers.IntegerField(help_text="Id de la variante (talla y color) de la referencia del lote")
    cantidad = serializers.IntegerField(min_value=1)


class IngresoTerminadoInputSerializer(serializers.Serializer):
    """Datos del ingreso: la inspección y el reparto de sus aptas por talla (la suma debe ser exactamente las aptas)."""
    inspeccion = serializers.IntegerField()
    lineas = LineaIngresoInputSerializer(many=True)
    ubicacion = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    observaciones = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    fecha = serializers.DateField(required=False, allow_null=True, help_text="Por defecto hoy; no puede ser futura")

    def validate_fecha(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError("La fecha no puede ser futura.")
        return value


class PendienteIngresoSerializer(serializers.Serializer):
    """Inspección por ingresar, con las variantes de su referencia y lo planificado en el lote."""
    inspeccion = serializers.IntegerField()
    inspeccion_codigo = serializers.CharField()
    lote = serializers.IntegerField()
    lote_codigo = serializers.CharField()
    orden_codigo = serializers.CharField()
    referencia = serializers.IntegerField()
    referencia_nombre = serializers.CharField()
    fecha = serializers.DateField()
    aptas = serializers.IntegerField(help_text="Prendas aptas por ingresar: el reparto por talla debe sumar esto")
    marras = serializers.IntegerField(help_text="Solo informativo: las marras no entran a este saldo")
    variantes = serializers.ListField(child=serializers.DictField(), help_text="`{id, talla, color}` de la referencia")
    planificado = serializers.ListField(child=serializers.DictField(), help_text="`{variante, cantidad}` planificado en el lote")


class MovimientoTerminadoSerializer(serializers.ModelSerializer):
    """Una fila del libro de producto terminado."""
    referencia = serializers.IntegerField(source="variante.referencia_id", read_only=True)
    referencia_nombre = serializers.CharField(source="variante.referencia.nombre", read_only=True)
    talla = serializers.CharField(source="variante.talla", read_only=True)
    color = serializers.CharField(source="variante.color", read_only=True)
    tipo_nombre = serializers.SerializerMethodField()
    ingreso_codigo = serializers.SerializerMethodField()
    lote_codigo = serializers.SerializerMethodField()
    usuario_nombre = serializers.SerializerMethodField()

    class Meta:
        model = MovimientoTerminado
        fields = [
            "id", "variante", "referencia", "referencia_nombre", "talla", "color", "tipo", "tipo_nombre", "cantidad", "saldo_antes",
            "saldo_despues", "ingreso_codigo", "lote_codigo", "usuario_nombre", "motivo", "created_at",
        ]

    def get_tipo_nombre(self, obj) -> str:
        return catalog.MOVEMENT_TYPE_NAMES.get(obj.tipo, obj.tipo)

    def get_ingreso_codigo(self, obj) -> str:
        return obj.ingreso.codigo if obj.ingreso else ""

    def get_lote_codigo(self, obj) -> str:
        return obj.lote.codigo if obj.lote else ""

    def get_usuario_nombre(self, obj) -> str:
        return _name(obj.usuario)


class ExistenciasReferenciaSerializer(serializers.Serializer):
    """Existencias de una referencia: filas por color y columnas por talla."""
    referencia = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    tallas = serializers.ListField(child=serializers.CharField(), help_text="Tallas en orden: las numéricas por valor y después las demás")
    colores = serializers.ListField(
        child=serializers.DictField(), help_text="`{color, tallas: {talla: {variante, cantidad}}, total}` por color",
    )
    total = serializers.IntegerField()
