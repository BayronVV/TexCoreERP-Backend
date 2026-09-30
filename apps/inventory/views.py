from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog, services
from .models import Evidencia, Movimiento, OrdenSalida, Producto
from .serializers import (
    AnulacionInputSerializer,
    EvidenciaSerializer,
    IngresoInputSerializer,
    MovimientoSerializer,
    OrdenInputSerializer,
    OrdenSerializer,
    ProductoInputSerializer,
    ProductoSerializer,
)

READ_WRITE = {"GET": catalog.INVENTORY_VIEW, "POST": catalog.INVENTORY_MANAGE}
LIST_LIMIT = 200


def limited(queryset, request):
    try:
        limit = min(max(int(request.query_params.get("limit", 100)), 1), LIST_LIMIT)
    except ValueError:
        limit = 100
    return queryset[:limit]


def apply_filters(queryset, params, mapping):
    """Filtros simples por query string; un valor mal formado responde 400, no 500."""
    for param, lookup in mapping:
        value = params.get(param)
        if not value:
            continue
        try:
            queryset = queryset.filter(**{lookup: value})
            str(queryset.query)  # fuerza la conversión del valor
        except (ValueError, TypeError, DjangoValidationError):
            raise ValidationError({param: ["Valor inválido."]})
    return queryset


class AlertListView(APIView):
    required_permissions = catalog.INVENTORY_VIEW

    def get(self, request):
        alerts = services.stock_alerts()
        return Response({"count": len(alerts), "alerts": alerts})


class ProductoListCreateView(generics.ListAPIView):
    required_permissions = READ_WRITE
    serializer_class = ProductoSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = Producto.objects.all()
        kind = self.request.query_params.get("tipo")
        if kind:
            queryset = queryset.filter(tipo__in=kind.split(","))
        return queryset

    def post(self, request):
        data = ProductoInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        product = services.create_product(**data.validated_data)
        return Response(ProductoSerializer(product).data, status=status.HTTP_201_CREATED)


class ProductoDetailView(generics.RetrieveUpdateDestroyAPIView):
    required_permissions = {
        "GET": catalog.INVENTORY_VIEW,
        "PATCH": catalog.INVENTORY_MANAGE,
        "DELETE": catalog.INVENTORY_MANAGE,
    }
    serializer_class = ProductoSerializer
    queryset = Producto.objects.all()
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        if instance.stock_actual > 0:
            raise ValidationError({"detail": ["No se puede eliminar un producto con existencias."]})
        if OrdenSalida.objects.filter(estado=catalog.STATUS_OPEN, producto_resultado=instance).exists():
            raise ValidationError({"detail": ["Hay una orden en proceso que produce este producto."]})
        instance.delete()


class MovimientoListView(generics.ListAPIView):
    required_permissions = catalog.INVENTORY_VIEW
    serializer_class = MovimientoSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = Movimiento.objects.select_related("producto", "orden", "registrado_por").prefetch_related(
            "evidencias", "orden__evidencias"
        )
        queryset = apply_filters(
            queryset,
            self.request.query_params,
            (("tipo", "tipo"), ("producto", "producto_id"), ("orden", "orden_id"),
             ("desde", "fecha__gte"), ("hasta", "fecha__lte")),
        )
        return limited(queryset, self.request)


class IngresoCreateView(APIView):
    required_permissions = catalog.INVENTORY_MANAGE

    def post(self, request):
        data = IngresoInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        movement = services.register_entry(
            user=request.user, producto_id=values.pop("producto"), orden_id=values.pop("orden"), **values
        )
        movement = Movimiento.objects.select_related("producto", "orden", "registrado_por").get(pk=movement.pk)
        return Response(MovimientoSerializer(movement).data, status=status.HTTP_201_CREATED)


class OrdenListCreateView(generics.ListAPIView):
    required_permissions = READ_WRITE
    serializer_class = OrdenSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = OrdenSalida.objects.select_related("producto_resultado", "registrado_por").prefetch_related(
            "lineas__producto", "evidencias"
        )
        queryset = apply_filters(
            queryset,
            self.request.query_params,
            (("tipo", "tipo"), ("estado", "estado"), ("producto_resultado", "producto_resultado_id")),
        )
        return limited(queryset, self.request)

    def post(self, request):
        data = OrdenInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        order = services.create_order(
            user=request.user, producto_resultado_id=values.pop("producto_resultado"), **values
        )
        return Response(OrdenSerializer(order).data, status=status.HTTP_201_CREATED)


class OrdenDetailView(generics.RetrieveAPIView):
    required_permissions = catalog.INVENTORY_VIEW
    serializer_class = OrdenSerializer
    queryset = OrdenSalida.objects.all()


class OrdenAnularView(APIView):
    required_permissions = catalog.INVENTORY_MANAGE

    def post(self, request, pk):
        data = AnulacionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        order = services.cancel_order(user=request.user, order_id=pk, motivo=data.validated_data["motivo"])
        return Response(OrdenSerializer(order).data)


class EvidenciaUploadView(APIView):
    required_permissions = catalog.INVENTORY_MANAGE
    parser_classes = [MultiPartParser]

    def owner(self, pk):
        raise NotImplementedError

    def post(self, request, pk):
        owner = self.owner(pk)
        saved = services.attach_evidence(user=request.user, files=request.FILES.getlist("archivos"), **owner)
        return Response(EvidenciaSerializer(saved, many=True).data, status=status.HTTP_201_CREATED)


class MovimientoEvidenciaView(EvidenciaUploadView):
    def owner(self, pk):
        return {"movement": get_object_or_404(Movimiento, pk=pk)}


class OrdenEvidenciaView(EvidenciaUploadView):
    def owner(self, pk):
        return {"order": get_object_or_404(OrdenSalida, pk=pk)}


class EvidenciaArchivoView(APIView):
    """Descarga autenticada: los archivos no cuelgan de una URL pública."""

    required_permissions = catalog.INVENTORY_VIEW

    def get(self, request, pk):
        evidence = get_object_or_404(Evidencia, pk=pk)
        response = FileResponse(evidence.archivo.open("rb"), content_type=evidence.content_type)
        response["Content-Disposition"] = "inline"
        response["Cache-Control"] = "private, no-store"
        return response
