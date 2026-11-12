"""Vistas de la API para remisiones de salida a lavandería externa (TE-57).

Maneja:
- Consulta de lotes ensamblados disponibles en la planta interna.
- Catálogos de lavanderías (proveedores) y recetas de lavado.
- Creación y listado de remisiones de salida con su consecutivo oficial.
"""
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog
from . import remisiones_services

FORBIDDEN_VIEW = OpenApiResponse(description="El rol no tiene permiso para consultar lavandería")
FORBIDDEN_MANAGE = OpenApiResponse(description="El rol no tiene permiso para gestionar lavandería")


@extend_schema_serializer(component_name="RemisionLoteItemInput")
class RemisionLoteItemInputSerializer(serializers.Serializer):
    """Lote seleccionado para la remisión, con la cantidad a enviar y su receta de lavado."""
    lote_id = serializers.IntegerField(min_value=1)
    cantidad = serializers.IntegerField(min_value=1)
    receta_id = serializers.CharField(max_length=50, required=False, allow_blank=True)
    receta_nombre = serializers.CharField(max_length=150, required=False, allow_blank=True)
    instrucciones_especiales = serializers.CharField(max_length=500, required=False, allow_blank=True)


@extend_schema_serializer(component_name="RemisionLavanderiaInput")
class RemisionInputSerializer(serializers.Serializer):
    """Datos para despachar una remisión de salida a lavandería."""
    lavanderia_id = serializers.IntegerField(min_value=1)
    fecha_emision = serializers.DateField()
    fecha_entrega_estimada = serializers.DateField(required=False, allow_null=True)
    transportador_nombre = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    vehiculo_placa = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    tulas_bultos = serializers.IntegerField(min_value=1, required=False, default=1)
    peso_kg = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0)
    observaciones = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    lotes = serializers.ListField(
        child=RemisionLoteItemInputSerializer(),
        allow_empty=False,
        help_text="Lista de lotes ensamblados seleccionados para la remisión",
    )


class LoteDisponibleLavadoSerializer(serializers.Serializer):
    """Lote ensamblado en planta interna que puede remitirse a lavado."""
    id = serializers.IntegerField()
    codigo_lote = serializers.CharField()
    op_codigo = serializers.CharField(help_text="Código de la orden de producción")
    referencia = serializers.CharField()
    referencia_codigo = serializers.CharField()
    ficha_tecnica = serializers.CharField()
    tela = serializers.CharField()
    color_crudo = serializers.CharField()
    unidades_ensambladas = serializers.IntegerField()
    unidades_disponibles = serializers.IntegerField()
    curva_tallas = serializers.DictField(child=serializers.IntegerField(), help_text="Cantidad por talla")
    taller_confeccion = serializers.CharField()
    fecha_ensamble = serializers.DateField()
    receta_sugerida = serializers.CharField(help_text="Código de la receta de lavado sugerida")
    receta_sugerida_nombre = serializers.CharField()
    observacion_confeccion = serializers.CharField()
    estado_inventario = serializers.CharField()


class LavanderiaProveedorSerializer(serializers.Serializer):
    """Proveedor de lavandería industrial del catálogo."""
    id = serializers.IntegerField()
    razon_social = serializers.CharField()
    nit = serializers.CharField(help_text="NIT con dígito de verificación")
    ciudad = serializers.CharField()
    direccion = serializers.CharField()
    contacto = serializers.CharField()
    telefono = serializers.CharField()
    tarifa_base_unidad = serializers.IntegerField()
    tiempo_promedio_dias = serializers.IntegerField()
    calificacion_calidad = serializers.CharField()


class RecetaLavadoSerializer(serializers.Serializer):
    """Receta técnica de lavado."""
    id = serializers.CharField(help_text="Igual al código de la receta")
    db_id = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    categoria = serializers.CharField()
    descripcion = serializers.CharField()
    temperatura_proceso = serializers.CharField()
    duracion_horas = serializers.IntegerField()
    tarifa_sugerida = serializers.FloatField()


class RemisionLoteDetalleSerializer(serializers.Serializer):
    """Lote incluido en una remisión de salida."""
    id = serializers.IntegerField()
    codigo_lote = serializers.CharField()
    op_codigo = serializers.CharField()
    referencia = serializers.CharField()
    ficha_tecnica = serializers.CharField()
    color_crudo = serializers.CharField()
    cantidad_a_enviar = serializers.IntegerField()
    receta_id = serializers.CharField()
    receta_nombre = serializers.CharField()
    instrucciones_especiales = serializers.CharField()


class RemisionLavanderiaSerializer(serializers.Serializer):
    """Remisión de salida a lavandería con el detalle para impresión del ticket."""
    id = serializers.IntegerField()
    codigo = serializers.CharField(help_text="Consecutivo REM-LAV-AAAA-XXXX")
    fecha_emision = serializers.DateField()
    fecha_entrega_estimada = serializers.CharField(help_text="Fecha ISO o cadena vacía si no se definió")
    lavanderia_id = serializers.IntegerField(allow_null=True)
    lavanderia_nombre = serializers.CharField()
    contacto_lavanderia = serializers.CharField()
    lotes_nombres = serializers.ListField(child=serializers.CharField())
    lotes_detalle = RemisionLoteDetalleSerializer(many=True)
    total_lotes = serializers.IntegerField()
    total_prendas = serializers.IntegerField()
    receta_nombre = serializers.CharField()
    costo_estimado = serializers.FloatField()
    transportador_nombre = serializers.CharField()
    vehiculo_placa = serializers.CharField()
    tulas_bultos = serializers.IntegerField()
    peso_kg = serializers.FloatField()
    estado = serializers.CharField()
    responsable_despacho = serializers.CharField()
    observaciones = serializers.CharField()


@extend_schema(
    tags=["lavanderia"],
    summary="Listar lotes ensamblados listos en planta interna para remisión a lavado (TE-57)",
    description="Devuelve únicamente los lotes que están en la planta interna (estado_inventario = PLANTA). "
                "Cuando un lote se remite, pasa a EN_TRANSITO y se descuenta de esta vista.",
    responses={200: LoteDisponibleLavadoSerializer(many=True), 403: FORBIDDEN_VIEW},
)
class LotesDisponiblesLavadoView(APIView):
    """Lotes ensamblados en planta interna listos para remitir a lavado (TE-57)."""
    required_permissions = catalog.LAUNDRY_VIEW

    def get(self, request):
        """Lista los lotes ensamblados disponibles en la planta interna."""
        lots = remisiones_services.get_available_lots_for_washing()
        return Response(lots)


@extend_schema(
    tags=["lavanderia"],
    summary="Listar proveedores de lavandería industrial (TE-57)",
    description="Devuelve las lavanderías y plantas de procesos externos registradas en el catálogo de proveedores.",
    responses={200: LavanderiaProveedorSerializer(many=True), 403: FORBIDDEN_VIEW},
)
class LavanderiaProveedoresView(APIView):
    """Catálogo de lavanderías industriales (TE-57)."""
    required_permissions = catalog.LAUNDRY_VIEW

    def get(self, request):
        """Lista las lavanderías del catálogo de proveedores."""
        provs = remisiones_services.get_laundry_providers()
        return Response(provs)


@extend_schema(
    tags=["lavanderia"],
    summary="Listar recetas y especificaciones técnicas de lavado (TE-57)",
    description="Devuelve el catálogo de recetas de lavado disponibles con sus descripciones, temperaturas y tarifas sugeridas.",
    responses={200: RecetaLavadoSerializer(many=True), 403: FORBIDDEN_VIEW},
)
class RecetasLavadoView(APIView):
    """Catálogo de recetas de lavado (TE-57)."""
    required_permissions = catalog.LAUNDRY_VIEW

    def get(self, request):
        """Lista las recetas de lavado vigentes."""
        recipes = remisiones_services.get_wash_recipes()
        return Response(recipes)


@extend_schema(tags=["lavanderia"])
class RemisionLavanderiaListCreateView(APIView):
    """Historial y creación de remisiones de salida a lavandería (TE-57)."""
    required_permissions = {"GET": catalog.LAUNDRY_VIEW, "POST": catalog.LAUNDRY_MANAGE}

    @extend_schema(
        summary="Listar el historial de remisiones de salida a lavado (TE-57)",
        description="Devuelve las remisiones generadas con sus detalles de lotes, transportador y fechas estimadas.",
        responses={200: RemisionLavanderiaSerializer(many=True), 403: FORBIDDEN_VIEW},
    )
    def get(self, request):
        """Lista el historial de remisiones de salida."""
        remisiones = remisiones_services.list_laundry_remissions()
        return Response(remisiones)

    @extend_schema(
        summary="Crear y despachar una remisión a lavandería (TE-57)",
        description="Genera el consecutivo oficial de salida (REM-LAV-YYYY-XXXX), descuenta los lotes de la planta interna "
                    "cambiando su estado a EN_TRANSITO, guarda la guía física y devuelve los datos completos para impresión.",
        request=RemisionInputSerializer,
        responses={
            201: RemisionLavanderiaSerializer,
            400: OpenApiResponse(
                description="Datos inválidos: lotes repetidos o inexistentes, lavandería inactiva, "
                            "lote fuera de la planta interna o cantidad mayor a la disponible"
            ),
            403: FORBIDDEN_MANAGE,
        },
    )
    def post(self, request):
        """Valida la petición y crea la remisión de salida con sus lotes."""
        serializer = RemisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = remisiones_services.create_laundry_remission(
            user=request.user,
            lavanderia_id=data["lavanderia_id"],
            lotes_seleccionados=data["lotes"],
            fecha_emision=data["fecha_emision"],
            fecha_entrega_estimada=data.get("fecha_entrega_estimada"),
            transportador_nombre=data.get("transportador_nombre", ""),
            vehiculo_placa=data.get("vehiculo_placa", ""),
            tulas_bultos=data.get("tulas_bultos", 1),
            peso_kg=data.get("peso_kg", 0),
            observaciones=data.get("observaciones", ""),
        )
        return Response(result, status=status.HTTP_201_CREATED)
