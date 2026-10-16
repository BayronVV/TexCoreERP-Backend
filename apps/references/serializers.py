from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import catalog
from .models import ImagenReferencia, Referencia, Variante


class VarianteSerializer(serializers.ModelSerializer):
    """Combinación de talla y color de una referencia."""

    class Meta:
        model = Variante
        fields = ["id", "talla", "color"]
        read_only_fields = fields


class VarianteInputSerializer(serializers.Serializer):
    talla = serializers.CharField(max_length=10)
    color = serializers.CharField(max_length=60)


class ImagenSerializer(serializers.ModelSerializer):
    """Datos de una foto del prototipo; el archivo se descarga aparte con sesión."""

    class Meta:
        model = ImagenReferencia
        fields = ["id", "principal", "version", "tipo"]
        read_only_fields = fields


class ReferenciaSerializer(serializers.ModelSerializer):
    """Referencia con sus variantes e imágenes, lista para mostrar en el catálogo."""
    ajuste_nombre = serializers.CharField(source="get_ajuste_display", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    variantes = VarianteSerializer(many=True, read_only=True)
    imagenes = ImagenSerializer(many=True, read_only=True)
    tallas = serializers.SerializerMethodField()
    colores = serializers.SerializerMethodField()
    imagen_principal = serializers.SerializerMethodField()
    creado_por_nombre = serializers.SerializerMethodField()
    tiene_ficha = serializers.BooleanField(read_only=True)

    class Meta:
        model = Referencia
        fields = [
            "id", "codigo", "nombre", "descripcion", "ajuste", "ajuste_nombre", "estado", "estado_nombre",
            "variantes", "tallas", "colores", "imagenes", "imagen_principal",
            "tiene_ficha", "creado_por_nombre", "created_at", "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_tallas(self, obj) -> list:
        """Tallas distintas, de la más pequeña a la más grande cuando son numéricas."""
        sizes = {v.talla for v in obj.variantes.all()}
        return sorted(sizes, key=lambda s: (0, int(s), s) if s.isdigit() else (1, 0, s))

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_colores(self, obj) -> list:
        """Colores distintos (sin distinguir mayúsculas; se muestra la primera escritura), en orden alfabético."""
        by_key = {}
        for variant in obj.variantes.all():
            by_key.setdefault(variant.color.lower(), variant.color)  # gana la primera escritura
        return [by_key[key] for key in sorted(by_key)]

    @extend_schema_field(ImagenSerializer(allow_null=True))
    def get_imagen_principal(self, obj):
        """La imagen principal, o la primera si por algún motivo no hay marcada."""
        images = list(obj.imagenes.all())
        main = next((i for i in images if i.principal), images[0] if images else None)
        return ImagenSerializer(main).data if main else None

    def get_creado_por_nombre(self, obj) -> str:
        user = obj.creado_por
        return (user.get_full_name() or user.email) if user else ""


class ReferenciaInputSerializer(serializers.Serializer):
    """Datos para crear o editar una referencia. `variantes` reemplaza la lista completa."""
    nombre = serializers.CharField(max_length=150)
    descripcion = serializers.CharField(max_length=500, required=False, allow_blank=True)
    ajuste = serializers.ChoiceField(choices=catalog.FITS)
    variantes = VarianteInputSerializer(many=True, required=False)


class EstadoInputSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(choices=catalog.STATES)
