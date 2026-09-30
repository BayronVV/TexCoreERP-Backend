from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog, services
from .models import Evidencia, Movimiento, OrdenSalida, Producto, Proveedor
from .serializers import (
    AnulacionInputSerializer,
    CatalogoSerializer,
    EvidenciaSerializer,
    IngresoInputSerializer,
    MovimientoSerializer,
    OrdenInputSerializer,
    OrdenSerializer,
    ProductoSerializer,
    ProveedorSerializer,
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


class MetadatosView(APIView):
    """Categorías, unidades y reglas del catálogo, para que las pantallas no las dupliquen."""

    required_permissions = catalog.INVENTORY_VIEW

    def get(self, request):
        return Response({
            "categorias": [
                {
                    "codigo": code,
                    "nombre": data["label"],
                    "tipo": data["tipo"],
                    "unidades": data["units"],
                    "compra": data["tipo"] in catalog.PURCHASED_TYPES,
                    "requiere_ancho_util": code in catalog.WIDTH_REQUIRED,
                    "requiere_composicion": code in catalog.COMPOSITION_REQUIRED,
                }
                for code, data in catalog.CATEGORIES.items()
            ],
            "unidades": [
                {"codigo": code, "nombre": name, "entera": code in catalog.WHOLE_UNITS}
                for code, name in catalog.UNITS
            ],
            "ancho_util_max": catalog.MAX_FABRIC_WIDTH,
            "imagen_max_bytes": catalog.IMAGE_MAX_BYTES,
        })


class AlertListView(APIView):
    required_permissions = catalog.INVENTORY_VIEW

    def get(self, request):
        alerts = services.stock_alerts()
        return Response({"count": len(alerts), "alerts": alerts})


class ProductoListView(generics.ListAPIView):
    """Productos con sus existencias, para Inventario (ingresos, salidas y existencias).
    Solo lectura: los productos se crean y editan en el catálogo."""

    required_permissions = catalog.INVENTORY_VIEW
    serializer_class = ProductoSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = Producto.objects.all()
        kind = self.request.query_params.get("tipo")
        if kind:
            queryset = queryset.filter(tipo__in=kind.split(","))
        return queryset


# --- Catálogo de telas e insumos (HU 2.2) ---------------------------------------

class CatalogoListCreateView(generics.ListAPIView):
    required_permissions = READ_WRITE
    serializer_class = CatalogoSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = Producto.objects.all().order_by("categoria", "nombre")
        category = self.request.query_params.get("categoria")
        if category:
            queryset = queryset.filter(categoria__in=category.split(","))
        text = self.request.query_params.get("q", "").strip()
        if text:
            queryset = queryset.filter(Q(nombre__icontains=text) | Q(codigo__icontains=text) | Q(color__icontains=text))
        return queryset

    def post(self, request):
        serializer = CatalogoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        return Response(CatalogoSerializer(product).data, status=status.HTTP_201_CREATED)


class CatalogoDetailView(generics.RetrieveUpdateDestroyAPIView):
    required_permissions = {
        "GET": catalog.INVENTORY_VIEW,
        "PATCH": catalog.INVENTORY_MANAGE,
        "DELETE": catalog.INVENTORY_MANAGE,
    }
    serializer_class = CatalogoSerializer
    queryset = Producto.objects.all()
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        services.archive_product(instance)


class CatalogoImagenView(APIView):
    """Imagen de referencia del producto. Se guarda en la base y se sirve con sesión."""

    required_permissions = {
        "GET": catalog.INVENTORY_VIEW,
        "POST": catalog.INVENTORY_MANAGE,
        "DELETE": catalog.INVENTORY_MANAGE,
    }
    parser_classes = [MultiPartParser]

    def get(self, request, pk):
        product = get_object_or_404(Producto, pk=pk)
        if not product.tiene_imagen:
            raise Http404
        etag = f'"{product.pk}-{product.imagen_version}"'
        if request.headers.get("If-None-Match") == etag:
            return HttpResponse(status=304)
        response = HttpResponse(bytes(product.imagen), content_type=product.imagen_tipo)
        response["ETag"] = etag
        response["Cache-Control"] = "private, max-age=0, must-revalidate"
        return response

    def post(self, request, pk):
        product = get_object_or_404(Producto, pk=pk)
        product = services.set_product_image(product, request.FILES.get("imagen"))
        return Response(CatalogoSerializer(product).data, status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        product = get_object_or_404(Producto, pk=pk)
        return Response(CatalogoSerializer(services.clear_product_image(product)).data)


# --- Proveedores (HU 2.1) --------------------------------------------------------

def suppliers_queryset(archived=False):
    queryset = Proveedor.all_objects.filter(deleted_at__isnull=not archived)
    # Insumos distintos que se han recibido de este proveedor (se deduce del kardex).
    return queryset.annotate(
        insumos_vinculados=Count(
            "movimientos__producto", filter=Q(movimientos__deleted_at__isnull=True), distinct=True
        )
    )


class ProveedorListCreateView(generics.ListAPIView):
    required_permissions = READ_WRITE
    serializer_class = ProveedorSerializer
    pagination_class = None

    def get_queryset(self):
        params = self.request.query_params
        queryset = suppliers_queryset(archived=params.get("archivados") in ("1", "true"))
        category = params.get("categoria")
        if category:
            queryset = queryset.filter(categoria__in=category.split(","))
        text = params.get("q", "").strip()
        if text:
            digits = "".join(ch for ch in text if ch.isdigit())
            match = Q(razon_social__icontains=text) | Q(contacto__icontains=text) | Q(ciudad__icontains=text)
            if digits:
                match |= Q(nit__icontains=digits)
            queryset = queryset.filter(match)
        return queryset

    def post(self, request):
        serializer = ProveedorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        supplier = serializer.save()
        return Response(ProveedorSerializer(supplier).data, status=status.HTTP_201_CREATED)


class ProveedorDetailView(generics.RetrieveUpdateDestroyAPIView):
    required_permissions = {
        "GET": catalog.INVENTORY_VIEW,
        "PATCH": catalog.INVENTORY_MANAGE,
        "DELETE": catalog.INVENTORY_MANAGE,
    }
    serializer_class = ProveedorSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        # Editar y eliminar solo aplican a los activos; los archivados se consultan y restauran.
        if self.request.method in ("PATCH", "DELETE"):
            return suppliers_queryset(archived=False)
        return Proveedor.all_objects.annotate(
            insumos_vinculados=Count(
                "movimientos__producto", filter=Q(movimientos__deleted_at__isnull=True), distinct=True
            )
        )


class ProveedorRestaurarView(APIView):
    required_permissions = catalog.INVENTORY_MANAGE

    def post(self, request, pk):
        supplier = get_object_or_404(suppliers_queryset(archived=True), pk=pk)
        services.restore_supplier(supplier)
        return Response(ProveedorSerializer(get_object_or_404(suppliers_queryset(), pk=pk)).data)


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
            user=request.user, producto_id=values.pop("producto"), orden_id=values.pop("orden"),
            proveedor_id=values.pop("proveedor"), **values
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
