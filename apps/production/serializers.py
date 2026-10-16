from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.references.ficha_serializers import ConsumoLineaSerializer

from .models import Lote, LoteTalla, OrdenProduccion


class SimulacionInputSerializer(serializers.Serializer):
    """Qué se quiere producir. La cantidad y los lotes se validan en `services` para devolver los errores con el
    mismo formato que el resto de la API (`{campo: [mensaje]}`).
    """
    referencia = serializers.IntegerField()
    cantidad = serializers.JSONField(help_text="Prendas a producir: entero de 1 a 100000")
    lotes = serializers.JSONField(
        required=False, allow_null=True,
        help_text="Tamaño de cada lote, p. ej. [50, 50, 100]. Deben sumar exactamente la cantidad.",
    )


class CuelloDeBotellaSerializer(serializers.Serializer):
    producto = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    unidad = serializers.CharField()
    disponible = serializers.DecimalField(max_digits=14, decimal_places=2)
    maximo = serializers.IntegerField(help_text="Prendas que alcanzan con este material")


class LoteSimuladoSerializer(serializers.Serializer):
    numero = serializers.IntegerField()
    cantidad = serializers.IntegerField()
    acumulado = serializers.IntegerField(help_text="Prendas de los lotes 1..n juntos")
    cubierto = serializers.BooleanField(help_text="Alcanza el stock para los lotes 1..n juntos")
    faltantes = serializers.ListField(child=serializers.CharField(), help_text="Materiales que no alcanzan")


class SimulacionSalidaSerializer(serializers.Serializer):
    referencia = serializers.DictField()
    cantidad = serializers.IntegerField()
    viable = serializers.BooleanField(help_text="Hay material para todo el total")
    lineas = ConsumoLineaSerializer(many=True)
    faltantes = ConsumoLineaSerializer(many=True)
    maximo_producible = serializers.IntegerField(help_text="Prendas que se pueden fabricar con el stock actual")
    cuello_de_botella = CuelloDeBotellaSerializer(help_text="El material que limita ese máximo")
    lotes = LoteSimuladoSerializer(many=True, allow_null=True)
    lotes_cubiertos = serializers.IntegerField(allow_null=True)


# --- Órdenes de producción y lotes (HU 4.2) ---

class OrdenProduccionInputSerializer(serializers.Serializer):
    """Datos para crear la orden. Las cantidades de material no se envían: salen de la ficha técnica."""
    referencia = serializers.IntegerField()
    cantidad = serializers.JSONField(help_text="Prendas a producir: entero de 1 a 100000")
    producto_resultado = serializers.IntegerField(help_text="Pantalón genérico que resulta de la producción")
    fecha_salida = serializers.DateField(required=False, allow_null=True, default=None)
    responsable = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    observaciones = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    lotes = serializers.JSONField(
        required=False, allow_null=True,
        help_text="Lotes `[{cantidad, tallas: [{variante, cantidad}]}]`. Sin lotes se crea uno solo con todo el total.",
    )


class LoteTallaSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoteTalla
        fields = ["variante", "talla", "color", "cantidad"]


class LoteSerializer(serializers.ModelSerializer):
    tallas = LoteTallaSerializer(many=True, read_only=True)

    class Meta:
        model = Lote
        fields = ["id", "numero", "codigo", "cantidad", "tallas"]


class OrdenProduccionSerializer(serializers.ModelSerializer):
    """Orden con sus lotes y tallas. El estado y la anulación se leen de la salida de inventario."""
    estado = serializers.CharField(source="orden_salida.estado", read_only=True)
    estado_nombre = serializers.CharField(source="orden_salida.get_estado_display", read_only=True)
    fecha_salida = serializers.DateField(source="orden_salida.fecha_salida", read_only=True)
    responsable = serializers.CharField(source="orden_salida.responsable", read_only=True)
    observaciones = serializers.CharField(source="orden_salida.observaciones", read_only=True)
    producto_resultado = serializers.IntegerField(source="orden_salida.producto_resultado_id", read_only=True)
    producto_resultado_nombre = serializers.CharField(source="orden_salida.producto_resultado.nombre", read_only=True)
    motivo_anulacion = serializers.CharField(source="orden_salida.motivo_anulacion", read_only=True)
    anulada_at = serializers.DateTimeField(source="orden_salida.anulada_at", read_only=True)
    referencia_codigo = serializers.CharField(source="referencia.codigo", read_only=True)
    referencia_nombre = serializers.CharField(source="referencia.nombre", read_only=True)
    creado_por_nombre = serializers.SerializerMethodField()
    materiales = serializers.SerializerMethodField()
    lotes = LoteSerializer(many=True, read_only=True)

    class Meta:
        model = OrdenProduccion
        fields = [
            "id", "codigo", "orden_salida", "estado", "estado_nombre", "referencia", "referencia_codigo",
            "referencia_nombre", "cantidad", "fecha_salida", "responsable", "observaciones", "producto_resultado",
            "producto_resultado_nombre", "motivo_anulacion", "anulada_at", "creado_por_nombre", "created_at",
            "materiales", "lotes",
        ]

    def get_creado_por_nombre(self, obj) -> str:
        return (obj.creado_por.get_full_name() or obj.creado_por.email) if obj.creado_por else ""

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_materiales(self, obj):
        """Lo que se descontó del almacén por esta orden (las líneas de la salida)."""
        return [
            {"producto": line.producto_id, "codigo": line.producto.codigo, "nombre": line.producto.nombre,
             "unidad": line.producto.unidad, "cantidad": str(line.cantidad)}
            for line in obj.orden_salida.lineas.all()
        ]


class AnulacionProduccionSerializer(serializers.Serializer):
    motivo = serializers.CharField(max_length=255)
