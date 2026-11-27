"""Vistas de inventario: catálogo, proveedores, ingresos, kardex, órdenes de salida, evidencias y alertas (HU 2.1 a 2.4)."""
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import generics, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.listing import (
    PAGINATION_PARAMS,
    paginate_or_limit,
    parse_date_range,
    parse_int_param,
    user_search_q,
)
from . import catalog, finished_link, services
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

LIMIT_PARAM = OpenApiParameter("limit", int, description="Máximo de filas (1 a 200, por defecto 100)")
READ_WRITE = {"GET": catalog.INVENTORY_VIEW, "POST": catalog.INVENTORY_MANAGE}
LIST_LIMIT = 200
logger = logging.getLogger(__name__)


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
            if param in ("desde", "hasta"):
                raise ValidationError({param: [f"La fecha '{param}' no es válida. Usa el formato AAAA-MM-DD."]})
            raise ValidationError({param: ["Valor inválido."]})
    return queryset


@extend_schema(
    tags=["inventario"], summary="Categorías, unidades y reglas del catálogo",
    responses={200: OpenApiTypes.OBJECT},
)
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
                    "creable_manualmente": code != catalog.CAT_FINISHED,
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


@extend_schema(
    tags=["inventario"], summary="Alertas de stock mínimo (HU 2.4)",
    description="Productos con existencias en el mínimo o por debajo (`warning`) o sin existencias (`critical`).",
    responses=inline_serializer("Alertas", {
        "count": serializers.IntegerField(),
        "alerts": serializers.ListField(child=serializers.DictField())}),
)
class AlertListView(APIView):
    """Productos cuyo saldo llegó al mínimo o se agotó (alertas de stock)."""
    required_permissions = catalog.INVENTORY_VIEW

    def get(self, request):
        alerts = services.stock_alerts()
        return Response({"count": len(alerts), "alerts": alerts})


@extend_schema_view(get=extend_schema(
    tags=["inventario"], summary="Productos con existencias",
    parameters=[
        OpenApiParameter("tipo", str, description="Tipos separados por coma: MATERIA_PRIMA, INSUMO, GENERICO, TERMINADO"),
        OpenApiParameter("incluir_heredados", bool, description="true para incluir productos PT heredados sin referencia"),
    ],
))
class ProductoListView(generics.ListAPIView):
    """Productos con sus existencias, para Inventario (ingresos, salidas y existencias).
    Para PRODUCTO_TERMINADO enlazado el saldo se calcula en vivo desde Producto Terminado (TE-170)."""

    required_permissions = catalog.INVENTORY_VIEW
    serializer_class = ProductoSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = Producto.objects.select_related("referencia")
        if self.request.query_params.get("incluir_heredados") not in ("1", "true"):
            queryset = queryset.filter(heredado=False)
        kind = self.request.query_params.get("tipo")
        if kind:
            queryset = queryset.filter(tipo__in=kind.split(","))
        return queryset

    def list(self, request, *args, **kwargs):
        products = finished_link.annotate_products_with_live_stock(self.filter_queryset(self.get_queryset()))
        serializer = self.get_serializer(products, many=True)
        return Response(serializer.data)


# --- Catálogo de telas e insumos (HU 2.2) ---------------------------------------

@extend_schema_view(
    get=extend_schema(tags=["catalogo"], summary="Listar el catálogo (sin existencias)",
        parameters=[OpenApiParameter("categoria", str, description="Categorías separadas por coma (TELA, HILO...)"),
                    OpenApiParameter("q", str, description="Busca en nombre, código y color"),
                    OpenApiParameter("heredados", bool, description="true para consultar los productos PT heredados")]),
    post=extend_schema(tags=["catalogo"], summary="Crear un producto (HU 2.2)",
        description="La categoría fija el tipo y las unidades permitidas. Las telas exigen `ancho_util` (0 a 5 m) y las telas e hilos, composición que sume 100 %."),
)
class CatalogoListCreateView(generics.ListAPIView):
    """Catálogo de telas e insumos: lista con filtros y alta de productos (HU 2.2)."""
    required_permissions = READ_WRITE
    serializer_class = CatalogoSerializer
    pagination_class = None

    def get_queryset(self):
        only_legacy = self.request.query_params.get("heredados") in ("1", "true")
        queryset = Producto.objects.select_related("referencia").filter(heredado=only_legacy).order_by("categoria", "nombre")
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


@extend_schema_view(
    get=extend_schema(tags=["catalogo"], summary="Consultar un producto"),
    patch=extend_schema(tags=["catalogo"], summary="Editar un producto",
        description="La categoría y la unidad no cambian si el producto ya tiene movimientos."),
    delete=extend_schema(tags=["catalogo"], summary="Archivar un producto",
        description="Solo sin existencias y sin órdenes en proceso que lo produzcan."),
)
class CatalogoDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Consulta, edita o elimina un producto del catálogo (sin tocar existencias)."""
    required_permissions = {
        "GET": catalog.INVENTORY_VIEW,
        "PATCH": catalog.INVENTORY_MANAGE,
        "DELETE": catalog.INVENTORY_MANAGE,
    }
    serializer_class = CatalogoSerializer
    queryset = Producto.objects.select_related("referencia")
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        services.archive_product(instance)


@extend_schema_view(
    get=extend_schema(tags=["catalogo"], summary="Descargar la imagen de referencia",
        description="Con `ETag`: responde 304 si `If-None-Match` coincide.",
        responses={(200, "image/*"): OpenApiTypes.BINARY, 304: None, 404: None}),
    post=extend_schema(tags=["catalogo"], summary="Subir o reemplazar la imagen (máx. 2 MB)",
        request={"multipart/form-data": inline_serializer("ImagenSubida", {"imagen": serializers.ImageField()})},
        responses={201: CatalogoSerializer}),
    delete=extend_schema(tags=["catalogo"], summary="Quitar la imagen", responses={200: CatalogoSerializer}),
)
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


@extend_schema_view(
    get=extend_schema(tags=["proveedores"], summary="Listar proveedores (HU 2.1)",
        parameters=[OpenApiParameter("archivados", bool, description="true para ver los archivados"),
                    OpenApiParameter("categoria", str, description="Categorías separadas por coma"),
                    OpenApiParameter("q", str, description="Busca en razón social, contacto, ciudad y NIT")]),
    post=extend_schema(tags=["proveedores"], summary="Registrar un proveedor",
        description="El NIT se normaliza (6 a 10 dígitos y dígito de verificación) y no puede repetirse entre proveedores activos."),
)
class ProveedorListCreateView(generics.ListAPIView):
    """Directorio de proveedores: lista con filtros y alta (HU 2.1)."""
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


@extend_schema_view(
    get=extend_schema(tags=["proveedores"], summary="Consultar un proveedor (activo o archivado)"),
    patch=extend_schema(tags=["proveedores"], summary="Editar un proveedor activo"),
    delete=extend_schema(tags=["proveedores"], summary="Archivar un proveedor",
        description="Borrado lógico: el historial de ingresos conserva el nombre del proveedor."),
)
class ProveedorDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Consulta, edita o archiva un proveedor."""
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


@extend_schema(tags=["proveedores"], summary="Restaurar un proveedor archivado", request=None,
    responses={200: ProveedorSerializer})
class ProveedorRestaurarView(APIView):
    """Reactiva un proveedor archivado si su NIT sigue libre."""
    required_permissions = catalog.INVENTORY_MANAGE

    def post(self, request, pk):
        supplier = get_object_or_404(suppliers_queryset(archived=True), pk=pk)
        services.restore_supplier(supplier)
        return Response(ProveedorSerializer(get_object_or_404(suppliers_queryset(), pk=pk)).data)


@extend_schema_view(get=extend_schema(
    tags=["movimientos"], summary="Historial de movimientos (kardex) con filtros combinables y paginación",
    parameters=[
        LIMIT_PARAM, *PAGINATION_PARAMS,
        OpenApiParameter("tipo", str, description="INGRESO o SALIDA"),
        OpenApiParameter("producto", int, description="Id del producto"),
        OpenApiParameter("referencia", int, description="Id de la referencia asociada a la orden"),
        OpenApiParameter("orden", str, description="Id o código de la orden"),
        OpenApiParameter("orden_compra", str, description="Código de la orden de compra (p. ej. OC-0001)"),
        OpenApiParameter("lote", str, description="Código o número de lote"),
        OpenApiParameter("estado", str, description="Estado de la orden de salida (EN_PROCESO, COMPLETADA, ANULADA)"),
        OpenApiParameter("responsable", str, description="Responsable de la orden o usuario que registró"),
        OpenApiParameter("desde", OpenApiTypes.DATE, description="Fecha mínima"),
        OpenApiParameter("hasta", OpenApiTypes.DATE, description="Fecha máxima"),
        OpenApiParameter("q", str, description="Producto, código, lote, orden, proveedor o nota"),
    ],
    responses={200: MovimientoSerializer(many=True)},
))
class MovimientoListView(APIView):
    """Kardex: cada cambio de saldo con saldo antes y después."""
    required_permissions = catalog.INVENTORY_VIEW
    serializer_class = MovimientoSerializer

    def get(self, request):
        desde, hasta = parse_date_range(request.query_params)
        producto_id = parse_int_param(request.query_params, "producto", minimum=1)
        referencia_id = parse_int_param(request.query_params, "referencia", minimum=1)

        queryset = Movimiento.objects.select_related(
            "producto", "orden", "orden__referencia", "registrado_por", "recepcion_linea__recepcion"
        ).prefetch_related(
            "evidencias", "orden__evidencias"
        )
        if producto_id is not None:
            queryset = queryset.filter(producto_id=producto_id)
        if referencia_id is not None:
            queryset = queryset.filter(orden__referencia_id=referencia_id)

        orden_raw = (request.query_params.get("orden") or "").strip()
        if orden_raw:
            if orden_raw.isdigit():
                queryset = queryset.filter(orden_id=int(orden_raw))
            else:
                queryset = queryset.filter(orden__codigo__icontains=orden_raw)

        lote_raw = (request.query_params.get("lote") or "").strip()
        if lote_raw:
            queryset = queryset.filter(lote__icontains=lote_raw)

        estado_raw = (request.query_params.get("estado") or "").strip()
        if estado_raw:
            queryset = queryset.filter(orden__estado=estado_raw)

        responsable_raw = (request.query_params.get("responsable") or "").strip()
        if responsable_raw:
            if responsable_raw.isdigit():
                queryset = queryset.filter(registrado_por_id=int(responsable_raw))
            else:
                queryset = queryset.filter(
                    Q(orden__responsable__icontains=responsable_raw)
                    | user_search_q("registrado_por", responsable_raw)
                )

        if desde is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if hasta is not None:
            queryset = queryset.filter(fecha__lte=hasta)

        queryset = apply_filters(
            queryset,
            request.query_params,
            (("tipo", "tipo"), ("orden_compra", "orden_compra")),
        )
        q = (request.query_params.get("q") or "").strip()
        if q:
            queryset = queryset.filter(
                Q(producto__codigo__icontains=q)
                | Q(producto__nombre__icontains=q)
                | Q(lote__icontains=q)
                | Q(orden__codigo__icontains=q)
                | Q(orden_compra__icontains=q)
                | Q(proveedor_nombre__icontains=q)
                | Q(nota__icontains=q)
            )
        return paginate_or_limit(queryset, request, MovimientoSerializer)


@extend_schema(
    tags=["movimientos"], summary="Registrar un ingreso (HU 2.3)",
    description="**Materias primas e insumos:** compra con proveedor de la lista y lote obligatorios. "
    "**Pantalón genérico:** solo entra cerrando la orden de producción (`orden` OP) que lo fabricó; "
    "la orden pasa a COMPLETADA. El ingreso de producto terminado se registra desde Producto Terminado tras calidad "
    "(HU 5.3 / TE-171). `proveedor` y `orden` vacíos se tratan como ausentes (TE-168).",
    request=IngresoInputSerializer, responses={201: MovimientoSerializer},
)
class IngresoCreateView(APIView):
    """Registra un ingreso al almacén (compra a proveedor o retorno de una orden de producción)."""
    required_permissions = catalog.INVENTORY_MANAGE

    def post(self, request):
        data = IngresoInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        movement = services.register_entry(
            user=request.user, producto_id=values.pop("producto"), orden_id=values.pop("orden"),
            proveedor_id=values.pop("proveedor"), **values
        )
        movement = Movimiento.objects.select_related("producto", "orden", "registrado_por", "recepcion_linea__recepcion").get(pk=movement.pk)
        return Response(MovimientoSerializer(movement).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(tags=["ordenes"], summary="Listar órdenes de salida",
        parameters=[LIMIT_PARAM, OpenApiParameter("tipo", str, description="PRODUCCION (OP) o LAVANDERIA (LV, solo consulta histórica de órdenes anteriores)"),
                    OpenApiParameter("estado", str, description="EN_PROCESO, COMPLETADA o ANULADA"),
                    OpenApiParameter("producto_resultado", int, description="Id del producto que se obtiene")]),
    post=extend_schema(tags=["ordenes"], summary="Crear una orden de producción con su cesta de materiales",
        description="Solo admite órdenes `PRODUCCION` (OP). Intentar crear una orden `LAVANDERIA` (LV) responde `400` "
                    "indicando que el envío a lavandería se hace desde Producción → Lavandería (HU 5.3 / TE-171). "
                    "Valida el stock de cada línea; si falta material responde 400 con `faltantes`.",
        request=OrdenInputSerializer, responses={201: OrdenSerializer}),
)
class OrdenListCreateView(generics.ListAPIView):
    """Lista las órdenes de salida (OP e historial LV de solo lectura) y crea órdenes de producción (OP)."""
    required_permissions = READ_WRITE
    serializer_class = OrdenSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = OrdenSalida.objects.select_related("producto_resultado", "registrado_por", "referencia").prefetch_related(
            "lineas__producto", "evidencias"
        )
        queryset = apply_filters(
            queryset,
            self.request.query_params,
            (("tipo", "tipo"), ("estado", "estado"), ("producto_resultado", "producto_resultado_id"),
             ("referencia", "referencia_id")),
        )
        return limited(queryset, self.request)

    def post(self, request):
        data = OrdenInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        order = services.create_order(
            user=request.user, producto_resultado_id=values.pop("producto_resultado"),
            referencia_id=values.pop("referencia"), **values,
        )
        return Response(OrdenSerializer(order).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["ordenes"], summary="Consultar una orden")
class OrdenDetailView(generics.RetrieveAPIView):
    """Consulta una orden de salida con sus líneas y evidencias."""
    required_permissions = catalog.INVENTORY_VIEW
    serializer_class = OrdenSerializer
    queryset = OrdenSalida.objects.all()


@extend_schema(
    tags=["ordenes"], summary="Anular una orden en proceso",
    description="Devuelve al inventario los materiales de la cesta. Exige el motivo.",
    request=AnulacionInputSerializer, responses={200: OrdenSerializer},
)
class OrdenAnularView(APIView):
    """Anula una orden de salida en proceso y devuelve el stock."""
    required_permissions = catalog.INVENTORY_MANAGE

    def post(self, request, pk):
        data = AnulacionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        order = services.cancel_order(user=request.user, order_id=pk, motivo=data.validated_data["motivo"])
        return Response(OrdenSerializer(order).data)


EVIDENCIAS_BODY = {
    "multipart/form-data": inline_serializer(
        "EvidenciasSubidas", {"archivos": serializers.ListField(child=serializers.FileField())}
    )
}


class EvidenciaUploadView(APIView):
    """Base para adjuntar fotos o PDF (validados por su contenido) a un movimiento o a una orden."""
    required_permissions = catalog.INVENTORY_MANAGE
    parser_classes = [MultiPartParser]

    def owner(self, pk):
        raise NotImplementedError

    def post(self, request, pk):
        owner = self.owner(pk)
        saved = services.attach_evidence(user=request.user, files=request.FILES.getlist("archivos"), **owner)
        return Response(EvidenciaSerializer(saved, many=True).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["evidencias"], summary="Adjuntar evidencias a un movimiento (JPG, PNG, WEBP o PDF)",
    request=EVIDENCIAS_BODY, responses={201: EvidenciaSerializer(many=True)})
class MovimientoEvidenciaView(EvidenciaUploadView):
    """Adjunta evidencias a un movimiento del kardex."""
    def owner(self, pk):
        return {"movement": get_object_or_404(Movimiento, pk=pk)}


@extend_schema(tags=["evidencias"], summary="Adjuntar evidencias a una orden (JPG, PNG, WEBP o PDF)",
    request=EVIDENCIAS_BODY, responses={201: EvidenciaSerializer(many=True)})
class OrdenEvidenciaView(EvidenciaUploadView):
    """Adjunta evidencias a una orden de salida."""
    def owner(self, pk):
        return {"order": get_object_or_404(OrdenSalida, pk=pk)}


@extend_schema(
    tags=["evidencias"],
    summary="Descargar una evidencia",
    responses={
        (200, "application/octet-stream"): OpenApiTypes.BINARY,
        404: OpenApiResponse(description="La evidencia o su archivo físico no está disponible en el servidor"),
    },
)
class EvidenciaArchivoView(APIView):
    """Descarga autenticada: los archivos no cuelgan de una URL pública."""

    required_permissions = catalog.INVENTORY_VIEW

    def get(self, request, pk):
        evidence = get_object_or_404(Evidencia, pk=pk)
        if not evidence.archivo:
            return Response(
                {"detail": "El archivo de la evidencia ya no está disponible en el servidor."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            file_handle = evidence.archivo.open("rb")
        except (FileNotFoundError, OSError, ValueError) as exc:
            logger.warning("Archivo de evidencia %s (%s) no encontrado en disco: %s", evidence.pk, evidence.archivo.name, exc)
            return Response(
                {"detail": "El archivo de la evidencia ya no está disponible en el servidor."},
                status=status.HTTP_404_NOT_FOUND,
            )
        response = FileResponse(file_handle, content_type=evidence.content_type)
        response["Content-Disposition"] = "inline"
        response["Cache-Control"] = "private, no-store"
        return response
