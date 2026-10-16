from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inventory.views import apply_filters, limited
from apps.references import fichas

from . import catalog, services
from .models import OrdenProduccion
from .serializers import (
    AnulacionProduccionSerializer,
    OrdenProduccionInputSerializer,
    OrdenProduccionSerializer,
    SimulacionInputSerializer,
    SimulacionSalidaSerializer,
)


@extend_schema(
    tags=["produccion"], summary="Simular la producción de una referencia contra el stock (HU 4.1, TE-110)",
    request=SimulacionInputSerializer, responses=SimulacionSalidaSerializer,
    description="Verifica si hay material para fabricar N prendas antes de crear una orden. Devuelve `viable`, por material lo "
                "requerido, lo disponible y lo que falta, el **máximo producible** con el stock actual y su **cuello de "
                "botella**. Si se envían `lotes`, indica hasta qué lote alcanza el stock (acumulado, porque comparten el "
                "mismo material). Es solo lectura: no reserva ni descuenta stock, y la orden vuelve a verificarlo al crearse. "
                "La referencia debe estar activa y tener ficha técnica.",
)
class SimulacionView(APIView):
    # Es un POST porque lleva una lista de lotes, pero solo calcula: no escribe nada, así que basta con poder ver.
    required_permissions = {"POST": catalog.PRODUCTION_VIEW}

    def post(self, request):
        data = SimulacionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        garments = fichas.parse_garments(data.validated_data["cantidad"])
        reference = services.get_reference(data.validated_data["referencia"])
        result = services.simulate(reference, garments, data.validated_data.get("lotes"))
        return Response(SimulacionSalidaSerializer(result).data)


ORDERS_READ_WRITE = {"GET": catalog.PRODUCTION_VIEW, "POST": catalog.PRODUCTION_MANAGE}


def order_queryset():
    return OrdenProduccion.objects.select_related(
        "orden_salida__producto_resultado", "referencia", "creado_por"
    ).prefetch_related("lotes__tallas", "orden_salida__lineas__producto")


@extend_schema(tags=["produccion"])
class OrdenProduccionListCreateView(generics.ListAPIView):
    required_permissions = ORDERS_READ_WRITE
    serializer_class = OrdenProduccionSerializer
    pagination_class = None

    @extend_schema(summary="Listar las órdenes de producción (filtros: estado, referencia, limit)")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = apply_filters(
            order_queryset(), self.request.query_params,
            (("estado", "orden_salida__estado"), ("referencia", "referencia_id")),
        )
        return limited(queryset, self.request)

    @extend_schema(
        summary="Crear una orden de producción con sus lotes y tallas (HU 4.2, TE-114)",
        request=OrdenProduccionInputSerializer, responses={201: OrdenProduccionSerializer},
        description="Crea la orden y la divide en lotes (`OP-0001-L01`...), con tallas opcionales por lote. En una sola "
                    "transacción descuenta del almacén el material que pide la ficha técnica de la referencia (con merma) y "
                    "registra la salida en el kardex; si falta material responde 400 con `faltantes` y no queda nada. Sin "
                    "`lotes` se crea un único lote. No exige `inventario.gestionar`: las cantidades salen de la ficha.",
    )
    def post(self, request):
        data = OrdenProduccionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        order = services.create_production_order(
            user=request.user, referencia_id=values.pop("referencia"), cantidad=values.pop("cantidad"),
            producto_resultado_id=values.pop("producto_resultado"), **values,
        )
        return Response(OrdenProduccionSerializer(order_queryset().get(pk=order.pk)).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["produccion"], summary="Consultar una orden de producción con sus lotes y tallas")
class OrdenProduccionDetailView(generics.RetrieveAPIView):
    required_permissions = catalog.PRODUCTION_VIEW
    serializer_class = OrdenProduccionSerializer

    def get_queryset(self):
        return order_queryset()


@extend_schema(
    tags=["produccion"], summary="Anular una orden de producción en proceso",
    description="Devuelve al almacén el material descontado. Exige el motivo.",
    request=AnulacionProduccionSerializer, responses={200: OrdenProduccionSerializer},
)
class OrdenProduccionAnularView(APIView):
    required_permissions = catalog.PRODUCTION_MANAGE

    def post(self, request, pk):
        data = AnulacionProduccionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.cancel_production_order(user=request.user, order_id=pk, motivo=data.validated_data["motivo"])
        return Response(OrdenProduccionSerializer(order_queryset().get(pk=pk)).data)
