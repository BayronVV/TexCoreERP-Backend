from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers

from . import catalog
from . import remisiones_services


class RemisionLoteItemInputSerializer(serializers.Serializer):
    lote_id = serializers.IntegerField(min_value=1)
    cantidad = serializers.IntegerField(min_value=1)
    receta_id = serializers.CharField(max_length=50, required=False, allow_blank=True)
    receta_nombre = serializers.CharField(max_length=150, required=False, allow_blank=True)
    instrucciones_especiales = serializers.CharField(max_length=500, required=False, allow_blank=True)


class RemisionInputSerializer(serializers.Serializer):
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


@extend_schema(
    tags=["lavanderia"],
    summary="Listar lotes ensamblados listos en planta interna para remisión a lavado (TE-57)",
    description="Devuelve únicamente los lotes que están en la planta interna (estado_inventario = PLANTA). "
                "Cuando un lote se remite, pasa a EN_TRANSITO y se descuenta de esta vista.",
)
class LotesDisponiblesLavadoView(APIView):
    required_permissions = catalog.LAUNDRY_VIEW

    def get(self, request):
        lots = remisiones_services.get_available_lots_for_washing()
        return Response(lots)


@extend_schema(
    tags=["lavanderia"],
    summary="Listar proveedores de lavandería industrial (TE-57)",
    description="Devuelve las lavanderías y plantas de procesos externos registradas en el catálogo de proveedores.",
)
class LavanderiaProveedoresView(APIView):
    required_permissions = catalog.LAUNDRY_VIEW

    def get(self, request):
        provs = remisiones_services.get_laundry_providers()
        return Response(provs)


@extend_schema(
    tags=["lavanderia"],
    summary="Listar recetas y especificaciones técnicas de lavado (TE-57)",
    description="Devuelve el catálogo de recetas de lavado disponibles con sus descripciones, temperaturas y tarifas sugeridas.",
)
class RecetasLavadoView(APIView):
    required_permissions = catalog.LAUNDRY_VIEW

    def get(self, request):
        recipes = remisiones_services.get_wash_recipes()
        return Response(recipes)


@extend_schema(tags=["lavanderia"])
class RemisionLavanderiaListCreateView(APIView):
    required_permissions = {"GET": catalog.LAUNDRY_VIEW, "POST": catalog.LAUNDRY_MANAGE}

    @extend_schema(
        summary="Listar el historial de remisiones de salida a lavado (TE-57)",
        description="Devuelve las remisiones generadas con sus detalles de lotes, transportador y fechas estimadas.",
    )
    def get(self, request):
        remisiones = remisiones_services.list_laundry_remissions()
        return Response(remisiones)

    @extend_schema(
        summary="Crear y despachar una remisión a lavandería (TE-57)",
        description="Genera el consecutivo oficial de salida (REM-LAV-YYYY-XXXX), descuenta los lotes de la planta interna "
                    "cambiando su estado a EN_TRANSITO, guarda la guía física y devuelve los datos completos para impresión.",
        request=RemisionInputSerializer,
        responses={201: serializers.Serializer},
    )
    def post(self, request):
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
