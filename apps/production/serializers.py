from rest_framework import serializers

from apps.references.ficha_serializers import ConsumoLineaSerializer


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
