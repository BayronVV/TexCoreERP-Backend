"""Vistas de compras: órdenes de compra (crear, aprobar, cancelar, cerrar) y recepción de mercancía."""
from django.db.models import Prefetch, Q
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inventory.views import apply_filters, limited

from . import catalog, services
from .models import LineaCompra, OrdenCompra, Recepcion, RecepcionLinea
from .serializers import (
    MotivoSerializer,
    OrdenCompraInputSerializer,
    OrdenCompraSerializer,
    RecepcionInputSerializer,
    RecepcionSerializer,
)

ORDERS_PERMISSIONS = {"GET": catalog.PURCHASING_VIEW, "POST": catalog.PURCHASING_MANAGE}
ORDER_DETAIL_PERMISSIONS = {"GET": catalog.PURCHASING_VIEW, "PATCH": catalog.PURCHASING_MANAGE}
RECEIPTS_PERMISSIONS = {"GET": catalog.PURCHASING_VIEW, "POST": catalog.RECEIVE_PERMISSION}
LIMIT_PARAM = OpenApiParameter("limit", int, description="Máximo de registros (por defecto 100)")


def order_queryset():
    lines = LineaCompra.objects.select_related("producto")
    receipts = Recepcion.objects.order_by("created_at", "id")  # en orden cronológico
    return OrdenCompra.objects.select_related("proveedor", "creado_por", "aprobado_por").prefetch_related(
        Prefetch("lineas", queryset=lines), Prefetch("recepciones", queryset=receipts)
    )


def receipt_queryset():
    return Recepcion.objects.select_related("proveedor", "orden", "recibido_por").prefetch_related(
        Prefetch("lineas", queryset=RecepcionLinea.objects.select_related("producto"))
    )


def serialize_orders(orders, many=False):
    """Serializa una o varias órdenes calculando lo recibido de todas sus líneas con una sola consulta."""
    items = list(orders) if many else [orders]
    received = services.received_by_line(line.id for order in items for line in order.lineas.all())
    return OrdenCompraSerializer(items if many else orders, many=many, context={"received": received}).data


def get_order(pk):
    order = order_queryset().filter(pk=pk).first()
    if order is None:
        raise Http404("La orden de compra no existe.")
    return order


@extend_schema(tags=["compras"])
class OrdenCompraListCreateView(APIView):
    """Lista las órdenes de compra y crea una en borrador (la crea Producción)."""
    required_permissions = ORDERS_PERMISSIONS

    @extend_schema(
        summary="Listar las órdenes de compra (filtros: estado, proveedor, q, limit)",
        parameters=[
            LIMIT_PARAM, OpenApiParameter("estado", str, description="BORRADOR, APROBADA, RECIBIDA_PARCIAL, RECIBIDA, CERRADA o CANCELADA"),
            OpenApiParameter("proveedor", int, description="Id del proveedor"),
            OpenApiParameter("q", str, description="Código de la orden o razón social del proveedor"),
        ],
        responses={200: OrdenCompraSerializer(many=True)},
        description="Cada orden trae sus líneas con lo recibido y lo pendiente, y su valor estimado (cantidad × precio pactado).",
    )
    def get(self, request):
        queryset = apply_filters(order_queryset(), request.query_params, [("estado", "estado"), ("proveedor", "proveedor_id")])
        text = request.query_params.get("q", "").strip()
        if text:
            queryset = queryset.filter(Q(codigo__icontains=text) | Q(proveedor__razon_social__icontains=text))
        return Response(serialize_orders(limited(queryset, request), many=True))

    @extend_schema(
        summary="Crear una orden de compra en borrador", request=OrdenCompraInputSerializer, responses={201: OrdenCompraSerializer},
        description="Código automático `OC-0001`. Solo materia prima e insumos, sin repetir producto. La orden nace en borrador: "
                    "el Gerente la aprueba y recién entonces se puede recibir contra ella.",
    )
    def post(self, request):
        data = OrdenCompraInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        order = services.create_order(user=request.user, data=data.validated_data)
        return Response(serialize_orders(get_order(order.pk)), status=status.HTTP_201_CREATED)


@extend_schema(tags=["compras"])
class OrdenCompraDetailView(APIView):
    """Consulta una orden de compra y la edita mientras es borrador."""
    required_permissions = ORDER_DETAIL_PERMISSIONS

    @extend_schema(summary="Consultar una orden de compra", responses={200: OrdenCompraSerializer})
    def get(self, request, pk):
        return Response(serialize_orders(get_order(pk)))

    @extend_schema(
        summary="Editar una orden de compra en borrador", request=OrdenCompraInputSerializer, responses={200: OrdenCompraSerializer},
        description="Solo mientras es borrador. Si se envían `lineas`, reemplazan a las anteriores.",
    )
    def patch(self, request, pk):
        data = OrdenCompraInputSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        services.update_order(order_id=pk, data=data.validated_data)
        return Response(serialize_orders(get_order(pk)))


@extend_schema(
    tags=["compras"], summary="Aprobar una orden de compra", request=None, responses={200: OrdenCompraSerializer},
    description="La aprueba el Gerente. Pasa de borrador a aprobada y desde ese momento el almacenista puede recibir contra ella.",
)
class OrdenCompraAprobarView(APIView):
    """El Gerente aprueba una orden de compra en borrador."""
    required_permissions = catalog.PURCHASING_APPROVE

    def post(self, request, pk):
        services.approve_order(user=request.user, order_id=pk)
        return Response(serialize_orders(get_order(pk)))


@extend_schema(
    tags=["compras"], summary="Cancelar una orden de compra", request=MotivoSerializer, responses={200: OrdenCompraSerializer},
    description="Solo una orden en borrador o aprobada que todavía no tiene recepciones. Exige el motivo.",
)
class OrdenCompraCancelarView(APIView):
    """Cancela una orden de compra que todavía no tiene recepciones (exige el motivo)."""
    required_permissions = catalog.PURCHASING_MANAGE

    def post(self, request, pk):
        data = MotivoSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.cancel_order(order_id=pk, motivo=data.validated_data["motivo"])
        return Response(serialize_orders(get_order(pk)))


@extend_schema(
    tags=["compras"], summary="Cerrar una orden de compra con recepciones parciales", request=MotivoSerializer,
    responses={200: OrdenCompraSerializer},
    description="Cuando lo pendiente ya no va a llegar. Solo una orden con recepciones parciales; exige el motivo.",
)
class OrdenCompraCerrarView(APIView):
    """Cierra una orden con recepciones parciales cuando lo pendiente ya no va a llegar (exige el motivo)."""
    required_permissions = catalog.PURCHASING_MANAGE

    def post(self, request, pk):
        data = MotivoSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.close_order(order_id=pk, motivo=data.validated_data["motivo"])
        return Response(serialize_orders(get_order(pk)))


@extend_schema(tags=["compras"])
class RecepcionListCreateView(APIView):
    """Lista las recepciones y registra una nueva con varios productos en una sola transacción (la hace el Almacenista)."""
    required_permissions = RECEIPTS_PERMISSIONS

    @extend_schema(
        summary="Listar las recepciones de mercancía (filtros: orden, proveedor, limit)",
        parameters=[LIMIT_PARAM, OpenApiParameter("orden", int, description="Id de la orden de compra"),
                    OpenApiParameter("proveedor", int, description="Id del proveedor")],
        responses={200: RecepcionSerializer(many=True)},
    )
    def get(self, request):
        queryset = apply_filters(receipt_queryset(), request.query_params, [("orden", "orden_id"), ("proveedor", "proveedor_id")])
        return Response(RecepcionSerializer(limited(queryset, request), many=True).data)

    @extend_schema(
        summary="Recibir mercancía en el almacén (varios productos a la vez)", request=RecepcionInputSerializer,
        responses={201: RecepcionSerializer},
        description="La registra el almacenista. Con `orden`, cada fila es una línea de la orden aprobada y se puede recibir hasta lo "
                    "pendiente más un 5 % de tolerancia; sin `orden`, es una entrega suelta de un proveedor. Cada fila lleva cantidad, "
                    "lote y, si se conoce, el costo real por unidad (alimenta el costo promedio ponderado). Todo se guarda en una sola "
                    "transacción: si una fila falla no queda ninguna. Quien creó la orden no puede recibirla.",
    )
    def post(self, request):
        data = RecepcionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        receipt = services.receive_goods(user=request.user, data=data.validated_data)
        return Response(RecepcionSerializer(receipt_queryset().get(pk=receipt.pk)).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["compras"], summary="Estados y reglas de las órdenes de compra", responses={200: OpenApiTypes.OBJECT})
class ComprasMetadatosView(APIView):
    """Estados de la orden y la tolerancia de exceso, para que las pantallas no los dupliquen."""
    required_permissions = catalog.PURCHASING_VIEW

    def get(self, request):
        return Response({
            "estados": [{"codigo": code, "nombre": name} for code, name in catalog.ORDER_STATES],
            "tolerancia_exceso": str(catalog.OVERAGE_TOLERANCE),
            "max_lineas": catalog.MAX_LINES,
        })
