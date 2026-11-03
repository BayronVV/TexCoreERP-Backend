"""Serializers de calidad: catálogo de defectos, lotes por inspeccionar e inspecciones con su desglose de marras."""
from django.utils import timezone
from rest_framework import serializers

from .models import Inspeccion, MarraDetalle, TipoDefecto


def _name(user):
    if user is None:
        return ""
    return (f"{user.first_name} {user.last_name}".strip()) or user.username


class DefectoSerializer(serializers.ModelSerializer):
    """Defecto del catálogo."""
    tipo = serializers.SerializerMethodField(help_text="CORREGIBLE (reproceso) o INCORREGIBLE (marra definitiva)")

    class Meta:
        model = TipoDefecto
        fields = ["id", "codigo", "nombre", "descripcion", "corregible", "tipo", "activo"]

    def get_tipo(self, obj) -> str:
        return "CORREGIBLE" if obj.corregible else "INCORREGIBLE"


class DefectoInputSerializer(serializers.Serializer):
    """Alta de un defecto."""
    nombre = serializers.CharField(max_length=200, help_text="Entre 3 y 80 caracteres; no se repite")
    descripcion = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    corregible = serializers.BooleanField(required=False, default=False, help_text="Se puede reprocesar; si no, es marra definitiva")


class DefectoPatchSerializer(serializers.Serializer):
    """Cambios de un defecto: solo se envía lo que cambia."""
    nombre = serializers.CharField(max_length=200, required=False)
    descripcion = serializers.CharField(max_length=255, required=False, allow_blank=True)
    corregible = serializers.BooleanField(required=False)
    activo = serializers.BooleanField(required=False, help_text="Desactivar un defecto lo oculta del formulario sin tocar el historial")


class MarraDetalleSerializer(serializers.ModelSerializer):
    """Marras de un defecto en una inspección, con el nombre y el tipo tal como estaban al inspeccionar."""
    tipo = serializers.SerializerMethodField()

    class Meta:
        model = MarraDetalle
        fields = ["id", "tipo_defecto", "defecto_nombre", "corregible", "tipo", "cantidad", "nota"]

    def get_tipo(self, obj) -> str:
        return "CORREGIBLE" if obj.corregible else "INCORREGIBLE"


class InspeccionSerializer(serializers.ModelSerializer):
    """Inspección de un lote con su desglose de marras."""
    lote_codigo = serializers.CharField(source="lote.codigo", read_only=True)
    orden = serializers.IntegerField(source="lote.orden_id", read_only=True)
    orden_codigo = serializers.CharField(source="lote.orden.codigo", read_only=True)
    referencia_nombre = serializers.CharField(source="lote.orden.referencia.nombre", read_only=True)
    lavanderia_nombre = serializers.SerializerMethodField()
    inspector_nombre = serializers.SerializerMethodField()
    porcentaje_marras = serializers.SerializerMethodField(help_text="Marras sobre lo recibido, en porcentaje con un decimal")
    detalle = MarraDetalleSerializer(many=True, read_only=True)

    class Meta:
        model = Inspeccion
        fields = [
            "id", "codigo", "lote", "lote_codigo", "orden", "orden_codigo", "referencia_nombre", "lavanderia_nombre", "fecha",
            "cantidad_recibida", "aptas", "marras", "porcentaje_marras", "observaciones", "inspector_nombre", "detalle", "created_at",
        ]

    def get_lavanderia_nombre(self, obj) -> str:
        return obj.recepcion_lote.recepcion.remision.lavanderia.razon_social

    def get_inspector_nombre(self, obj) -> str:
        return _name(obj.inspector)

    def get_porcentaje_marras(self, obj) -> str:
        return f"{obj.marras * 100 / obj.cantidad_recibida:.1f}"


class MarraLineaInputSerializer(serializers.Serializer):
    """Una fila del desglose de marras."""
    defecto = serializers.IntegerField(help_text="Id del defecto del catálogo (activo)")
    cantidad = serializers.IntegerField(min_value=1)
    nota = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class InspeccionInputSerializer(serializers.Serializer):
    """Datos de la inspección: el lote, las aptas y el desglose de marras. aptas + marras = lo recibido del lote."""
    lote = serializers.IntegerField()
    aptas = serializers.IntegerField(min_value=0)
    defectos = MarraLineaInputSerializer(many=True, required=False, default=list)
    observaciones = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    fecha = serializers.DateField(required=False, allow_null=True, help_text="Por defecto hoy; no puede ser futura")

    def validate_fecha(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError("La fecha no puede ser futura.")
        return value


class PendienteSerializer(serializers.Serializer):
    """Lote por inspeccionar."""
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    orden = serializers.IntegerField()
    orden_codigo = serializers.CharField()
    referencia_nombre = serializers.CharField()
    lavanderia_nombre = serializers.CharField()
    recepcion_codigo = serializers.CharField()
    fecha_recepcion = serializers.DateField()
    cantidad_recibida = serializers.IntegerField(help_text="Prendas recibidas conformes: lo que se inspecciona")
