"""Entradas y salidas de la ficha técnica de consumo por unidad (HU 3.2)."""
from decimal import Decimal

from rest_framework import serializers

from . import catalog
from .fichas import gross_per_garment

GROSS_PLACES = Decimal("0.0001")


class FichaLineaInputSerializer(serializers.Serializer):
    """Un material de la ficha. Los decimales permitidos por cada campo los valida `fichas.clean_lines`."""
    producto = serializers.IntegerField()
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=6)
    merma = serializers.DecimalField(max_digits=8, decimal_places=4, required=False, default=0)
    observaciones = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


class FichaInputSerializer(serializers.Serializer):
    """Ficha completa: la lista de materiales reemplaza a la actual."""
    lavado = serializers.ChoiceField(choices=catalog.WASHES, required=False, allow_blank=True, default="")
    notas = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    lineas = FichaLineaInputSerializer(many=True, allow_empty=True)


def ficha_payload(reference, ficha, lines):
    """La ficha de una referencia como la devuelve la API. Si todavía no existe, `existe` es falso y no hay materiales."""
    wash_names = dict(catalog.WASHES)
    user = ficha.actualizado_por if ficha else None
    return {
        "referencia": {
            "id": reference.id, "codigo": reference.codigo, "nombre": reference.nombre, "estado": reference.estado,
        },
        "existe": ficha is not None,
        "lavado": ficha.lavado if ficha else "",
        "lavado_nombre": wash_names.get(ficha.lavado, "") if ficha else "",
        "notas": ficha.notas if ficha else "",
        "actualizado_por_nombre": (user.get_full_name() or user.email) if user else "",
        "actualizado": ficha.updated_at if ficha else None,
        "documento": (
            {"nombre": ficha.documento_nombre, "tamano": ficha.documento_tamano, "version": ficha.documento_version}
            if ficha and ficha.tiene_documento else None
        ),
        "lineas": [
            {
                "id": line.id, "producto": line.producto_id, "codigo": line.producto.codigo,
                "nombre": line.producto.nombre, "unidad": line.producto.unidad, "cantidad": line.cantidad,
                "merma": line.merma, "consumo_bruto": gross_per_garment(line).quantize(GROSS_PLACES),
                "observaciones": line.observaciones,
            }
            for line in lines
        ],
    }


# Esquemas de respuesta: solo documentan el JSON que ya arman las vistas (OpenAPI).

class FichaLineaSalidaSerializer(serializers.Serializer):
    """Un material de la ficha: consumo por prenda, merma y consumo con merma."""
    id = serializers.IntegerField()
    producto = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    unidad = serializers.CharField()
    cantidad = serializers.DecimalField(max_digits=10, decimal_places=3, help_text="Consumo por prenda")
    merma = serializers.DecimalField(max_digits=5, decimal_places=2, help_text="Porcentaje")
    consumo_bruto = serializers.DecimalField(
        max_digits=14, decimal_places=4, help_text="Cantidad con la merma aplicada, por prenda")
    observaciones = serializers.CharField()


class FichaDocumentoSalidaSerializer(serializers.Serializer):
    """Datos del PDF adjunto a la ficha (nombre, tamaño y versión)."""
    nombre = serializers.CharField()
    tamano = serializers.IntegerField(help_text="Bytes")
    version = serializers.IntegerField()


class FichaSalidaSerializer(serializers.Serializer):
    """Ficha técnica de una referencia con sus materiales; `existe` es falso si todavía no se ha creado."""
    referencia = serializers.DictField()
    existe = serializers.BooleanField()
    lavado = serializers.CharField()
    lavado_nombre = serializers.CharField()
    notas = serializers.CharField()
    actualizado_por_nombre = serializers.CharField()
    actualizado = serializers.DateTimeField(allow_null=True)
    documento = FichaDocumentoSalidaSerializer(allow_null=True)
    lineas = FichaLineaSalidaSerializer(many=True)


class ConsumoLineaSerializer(serializers.Serializer):
    """Por material: lo requerido, lo disponible y lo que falta para producir N prendas."""
    producto = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    unidad = serializers.CharField()
    por_prenda = serializers.DecimalField(max_digits=10, decimal_places=3)
    merma = serializers.DecimalField(max_digits=5, decimal_places=2)
    requerido = serializers.DecimalField(max_digits=14, decimal_places=2)
    disponible = serializers.DecimalField(max_digits=14, decimal_places=2)
    falta = serializers.DecimalField(max_digits=14, decimal_places=2)
    suficiente = serializers.BooleanField()
    observaciones = serializers.CharField()


class ConsumoSalidaSerializer(serializers.Serializer):
    """Resultado del cruce de la ficha con el stock: líneas, faltantes y si es viable."""
    referencia = serializers.DictField()
    cantidad = serializers.IntegerField()
    viable = serializers.BooleanField()
    lineas = ConsumoLineaSerializer(many=True)
    faltantes = ConsumoLineaSerializer(many=True)
