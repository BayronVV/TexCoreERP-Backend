"""Vistas de la API para Recepción de Lavandería Externa (TE-58).

Maneja:
- Consulta de remisiones pendientes de retorno desde lavandería.
- Cotejo de cantidades recibidas conformes vs mermas y prendas dañadas.
- Registro financiero de pérdidas por procesos de terceros.
- Devolución de prendas a la planta interna.
- Consulta de historial de recepciones generadas.
"""
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog, recepcion_services


@extend_schema_serializer(component_name="RecepcionLoteItemInput")
class RecepcionLoteItemInputSerializer(serializers.Serializer):
    """Cotejo de un lote: cantidades conformes, mermas y prendas dañadas."""
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


@extend_schema_serializer(component_name="RecepcionLavanderiaInput")
class RecepcionInputSerializer(serializers.Serializer):
    """Datos para asentar la recepción de una remisión devuelta por la lavandería."""
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


class RemisionPendienteLoteSerializer(serializers.Serializer):
    """Lote de una remisión pendiente, con los datos para el cotejo."""
    remision_lote_id = serializers.IntegerField()
    lote_id = serializers.IntegerField()
    codigo_lote = serializers.CharField()
    lote_codigo = serializers.CharField()
    op_codigo = serializers.CharField()
    referencia = serializers.CharField()
    receta_id = serializers.CharField()
    receta_nombre = serializers.CharField()
    tarifa_lavado = serializers.FloatField()
    cantidad_enviada = serializers.IntegerField()
    costo_unitario_estimado = serializers.FloatField()


class RemisionPendienteRecepcionSerializer(serializers.Serializer):
    """Remisión despachada a lavandería que aún no se recibe en planta."""
    remision_id = serializers.IntegerField()
    codigo = serializers.CharField()
    fecha_emision = serializers.DateField()
    fecha_entrega_estimada = serializers.CharField(help_text="Fecha ISO o cadena vacía si no se definió")
    dias_en_proceso = serializers.IntegerField()
    lavanderia_id = serializers.IntegerField(allow_null=True)
    lavanderia_nombre = serializers.CharField()
    lavanderia_contacto = serializers.CharField()
    transportador_nombre = serializers.CharField()
    vehiculo_placa = serializers.CharField()
    total_lotes = serializers.IntegerField()
    total_prendas = serializers.IntegerField()
    estado = serializers.CharField()
    lotes = RemisionPendienteLoteSerializer(many=True)


class RecepcionLoteDetalleSerializer(serializers.Serializer):
    """Resultado del cotejo de un lote dentro de un acta de recepción."""
    id = serializers.IntegerField()
    recepcion_id = serializers.IntegerField()
    remision_lote_id = serializers.IntegerField(allow_null=True)
    lote_id = serializers.IntegerField()
    codigo_lote = serializers.CharField()
    op_codigo = serializers.CharField()
    referencia = serializers.CharField()
    ficha_tecnica = serializers.CharField()
    receta_nombre = serializers.CharField()
    cantidad_enviada = serializers.IntegerField()
    cantidad_recibida_conforme = serializers.IntegerField()
    cantidad_merma = serializers.IntegerField()
    cantidad_danada = serializers.IntegerField()
    motivo_merma = serializers.CharField()
    tipo_dano = serializers.CharField()
    costo_unitario_prenda = serializers.FloatField()
    costo_perdida = serializers.FloatField()
    observaciones = serializers.CharField()


class RecepcionLavanderiaSerializer(serializers.Serializer):
    """Acta de recepción de lavandería con totales, pérdidas y detalle por lote."""
    id = serializers.IntegerField()
    codigo = serializers.CharField(help_text="Consecutivo REC-LAV-AAAA-XXXX")
    remision_id = serializers.IntegerField()
    remision_codigo = serializers.CharField()
    remision_fecha_emision = serializers.DateField()
    factura_remision_externa = serializers.CharField()
    fecha_recepcion = serializers.DateField()
    lavanderia_id = serializers.IntegerField(allow_null=True)
    lavanderia_nombre = serializers.CharField()
    lavanderia_nit = serializers.CharField()
    lavanderia_contacto = serializers.CharField()
    total_enviado = serializers.IntegerField()
    total_recibido_conforme = serializers.IntegerField()
    total_merma = serializers.IntegerField()
    total_danadas = serializers.IntegerField()
    costo_total_perdida = serializers.FloatField()
    costo_servicio_lavado = serializers.FloatField()
    estado = serializers.CharField()
    responsable = serializers.CharField()
    observaciones = serializers.CharField()
    lotes_detalle = RecepcionLoteDetalleSerializer(many=True)


FORBIDDEN_VIEW = OpenApiResponse(description="El rol no tiene permiso para consultar lavandería")
FORBIDDEN_MANAGE = OpenApiResponse(description="El rol no tiene permiso para gestionar lavandería")


@extend_schema(tags=["lavanderia"])
class RemisionesPendientesRecepcionView(APIView):
    """Lista las remisiones despachadas a lavandería pendientes por recibir en planta (TE-58)."""
    required_permissions = catalog.LAUNDRY_VIEW

    @extend_schema(
        summary="Listar remisiones pendientes de recepción (TE-58)",
        description="Devuelve las remisiones en tránsito o en lavandería con el detalle de lotes y cantidades para cotejo.",
        responses={200: RemisionPendienteRecepcionSerializer(many=True), 403: FORBIDDEN_VIEW},
    )
    def get(self, request):
        """Lista las remisiones pendientes de recepción."""
        pending = recepcion_services.get_pending_remissions_for_reception()
        return Response(pending)


@extend_schema(tags=["lavanderia"])
class RecepcionLavanderiaListCreateView(APIView):
    """Listado y registro de recepción de prendas devueltas de lavandería (TE-58)."""
    required_permissions = {"GET": catalog.LAUNDRY_VIEW, "POST": catalog.LAUNDRY_MANAGE}

    @extend_schema(
        summary="Listar historial de recepciones de lavandería (TE-58)",
        description="Devuelve el historial de recepciones asentadas con sus mermas, daños y pérdidas liquidadas.",
        responses={200: RecepcionLavanderiaSerializer(many=True), 403: FORBIDDEN_VIEW},
    )
    def get(self, request):
        """Lista el historial de actas de recepción."""
        recepciones = recepcion_services.list_laundry_receptions()
        return Response(recepciones)

    @extend_schema(
        summary="Asentar recepción, cotejar cantidades y registrar pérdidas (TE-58)",
        description="Coteja cantidades enviadas vs devueltas, exige motivos para mermas y daños, "
                    "devuelve las prendas conformes al estado interno (PLANTA), calcula la pérdida financiera "
                    "y marca la remisión original como RETORNADA.",
        request=RecepcionInputSerializer,
        responses={
            201: RecepcionLavanderiaSerializer,
            400: OpenApiResponse(
                description="Datos inválidos: remisión inexistente o ya recibida, lotes que no pertenecen a la remisión, "
                            "cantidades que no cuadran con lo enviado o mermas/daños sin motivo"
            ),
            403: FORBIDDEN_MANAGE,
        },
    )
    def post(self, request):
        """Valida el cotejo y asienta el acta de recepción."""
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
        responses={
            200: RecepcionLavanderiaSerializer,
            400: OpenApiResponse(description="El acta de recepción solicitada no existe"),
            403: FORBIDDEN_VIEW,
        },
        operation_id="lavanderia_recepciones_detalle",
    )
    def get(self, request, pk):
        """Devuelve el acta de recepción con el id indicado."""
        detail = recepcion_services.get_laundry_reception_detail(pk)
        return Response(detail)
