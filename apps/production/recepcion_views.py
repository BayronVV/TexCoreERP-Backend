"""Vistas de la API para Recepción de Lavandería Externa (TE-58).

Maneja:
- Consulta de remisiones pendientes de retorno desde lavandería.
- Cotejo de cantidades recibidas conformes vs mermas y prendas dañadas.
- Registro financiero de pérdidas por procesos de terceros.
- Devolución de prendas a la planta interna.
- Consulta de historial de recepciones generadas.
"""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog, recepcion_services


class RecepcionLoteItemInputSerializer(serializers.Serializer):
    remision_lote_id = serializers.IntegerField(required=False, allow_null=True)
    lote_id = serializers.IntegerField(required=False, allow_null=True)
    cantidad_recibida_conforme = serializers.IntegerField(min_value=0)
    cantidad_merma = serializers.IntegerField(min_value=0, required=False, default=0)
    cantidad_danada = serializers.IntegerField(min_value=0, required=False, default=0)
    motivo_merma = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    tipo_dano = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    costo_unitario_prenda = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=35000
    )
    observaciones = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class RecepcionInputSerializer(serializers.Serializer):
    remision_id = serializers.IntegerField(min_value=1)
    fecha_recepcion = serializers.DateField()
    factura_remision_externa = serializers.CharField(
        max_length=60, required=False, allow_blank=True, default=""
    )
    observaciones = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default=""
    )
    lotes = serializers.ListField(
        child=RecepcionLoteItemInputSerializer(),
        allow_empty=False,
        help_text="Detalle de cotejo por cada lote de la remisión",
    )


@extend_schema(tags=["lavanderia"])
class RemisionesPendientesRecepcionView(APIView):
    """Lista las remisiones despachadas a lavandería pendientes por recibir en planta (TE-58)."""
    required_permissions = catalog.LAUNDRY_VIEW

    @extend_schema(
        summary="Listar remisiones pendientes de recepción (TE-58)",
        description="Devuelve las remisiones en tránsito o en lavandería con el detalle de lotes y cantidades para cotejo.",
    )
    def get(self, request):
        pending = recepcion_services.get_pending_remissions_for_reception()
        return Response(pending)


@extend_schema(tags=["lavanderia"])
class RecepcionLavanderiaListCreateView(APIView):
    """Listado y registro de recepción de prendas devueltas de lavandería (TE-58)."""
    required_permissions = {"GET": catalog.LAUNDRY_VIEW, "POST": catalog.LAUNDRY_MANAGE}

    @extend_schema(
        summary="Listar historial de recepciones de lavandería (TE-58)",
        description="Devuelve el historial de recepciones asentadas con sus mermas, daños y pérdidas liquidadas.",
    )
    def get(self, request):
        recepciones = recepcion_services.list_laundry_receptions()
        return Response(recepciones)

    @extend_schema(
        summary="Asentar recepción, cotejar cantidades y registrar pérdidas (TE-58)",
        description="Coteja cantidades enviadas vs devueltas, exige motivos para mermas y daños, "
                    "devuelve las prendas conformes al estado interno (PLANTA), calcula la pérdida financiera "
                    "y marca la remisión original como RETORNADA.",
        request=RecepcionInputSerializer,
        responses={201: serializers.Serializer},
    )
    def post(self, request):
        serializer = RecepcionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = recepcion_services.create_laundry_reception(
            user=request.user,
            remision_id=data["remision_id"],
            fecha_recepcion=data["fecha_recepcion"],
            factura_remision_externa=data.get("factura_remision_externa", ""),
            lotes_recibidos=data["lotes"],
            observaciones=data.get("observaciones", ""),
        )
        return Response(result, status=status.HTTP_201_CREATED)


@extend_schema(tags=["lavanderia"])
class RecepcionLavanderiaDetailView(APIView):
    """Detalle de un acta de recepción de lavandería (TE-58)."""
    required_permissions = catalog.LAUNDRY_VIEW

    @extend_schema(
        summary="Obtener detalle de un acta de recepción (TE-58)",
        description="Devuelve el comprobante completo de recepción para consulta y ticket de impresión.",
    )
    def get(self, request, pk):
        detail = recepcion_services.get_laundry_reception_detail(pk)
        return Response(detail)
