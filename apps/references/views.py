"""Vistas del catálogo de referencias de jean (HU 3.1): referencias, estados e imágenes del prototipo."""
from django.db.models import Exists, OuterRef, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import generics, serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog, services
from .models import FichaTecnica, ImagenReferencia, Referencia
from .serializers import (
    EstadoInputSerializer,
    ReferenciaInputSerializer,
    ReferenciaSerializer,
)

READ_WRITE = {"GET": catalog.REFERENCES_VIEW, "POST": catalog.REFERENCES_MANAGE}


def references_queryset():
    return (
        Referencia.objects.select_related("creado_por").prefetch_related("variantes", "imagenes")
        .annotate(tiene_ficha=Exists(FichaTecnica.objects.filter(referencia=OuterRef("pk"))))
    )


def fresh(reference):
    """La referencia recargada con sus variantes e imágenes, para devolverla ya actualizada."""
    return get_object_or_404(references_queryset(), pk=reference.pk)


@extend_schema(
    tags=["referencias"], summary="Valores para armar el formulario de referencias",
    responses=inline_serializer("ReferenciaMetadatos", {
        "ajustes": serializers.ListField(child=serializers.DictField()),
        "estados": serializers.ListField(child=serializers.DictField()),
        "lavados": serializers.ListField(child=serializers.DictField()),
        "max_imagenes": serializers.IntegerField(),
        "imagen_max_bytes": serializers.IntegerField(),
        "max_variantes": serializers.IntegerField(),
    }),
)
class MetadatosView(APIView):
    """Valores para armar los formularios de referencias: ajustes, estados, lavados y límites."""
    required_permissions = catalog.REFERENCES_VIEW

    def get(self, request):
        return Response({
            "ajustes": [{"value": v, "label": label} for v, label in catalog.FITS],
            "estados": [{"value": v, "label": label} for v, label in catalog.STATES],
            "lavados": [{"value": v, "label": label} for v, label in catalog.WASHES],
            "max_imagenes": catalog.MAX_IMAGES,
            "imagen_max_bytes": catalog.IMAGE_MAX_BYTES,
            "max_variantes": catalog.MAX_VARIANTS,
        })


@extend_schema_view(
    get=extend_schema(tags=["referencias"], summary="Listar referencias de jean (HU 3.1)",
        parameters=[OpenApiParameter("estado", str, description="Estados separados por coma"),
                    OpenApiParameter("ajuste", str, description="Ajustes separados por coma"),
                    OpenApiParameter("talla", str, description="Talla exacta"),
                    OpenApiParameter("color", str, description="Color (contiene el texto)"),
                    OpenApiParameter("q", str, description="Busca en código, nombre, descripción y color")]),
    post=extend_schema(tags=["referencias"], summary="Registrar una referencia",
        request=ReferenciaInputSerializer, responses={201: ReferenciaSerializer},
        description="Nace en borrador con código `REF-0001`. Las imágenes se suben después con `POST /referencias/{id}/imagenes/`."),
)
class ReferenciaListCreateView(generics.ListAPIView):
    """Lista las referencias de jean (con filtros) y registra una nueva en borrador."""
    required_permissions = READ_WRITE
    serializer_class = ReferenciaSerializer
    pagination_class = None

    def get_queryset(self):
        params = self.request.query_params
        queryset = references_queryset()
        if params.get("estado"):
            queryset = queryset.filter(estado__in=params["estado"].split(","))
        if params.get("ajuste"):
            queryset = queryset.filter(ajuste__in=params["ajuste"].split(","))
        if params.get("talla"):
            queryset = queryset.filter(variantes__talla=params["talla"].strip().upper())
        if params.get("color"):
            queryset = queryset.filter(variantes__color__icontains=params["color"].strip())
        text = params.get("q", "").strip()
        if text:
            queryset = queryset.filter(
                Q(nombre__icontains=text) | Q(codigo__icontains=text)
                | Q(descripcion__icontains=text) | Q(variantes__color__icontains=text)
            )
        return queryset.distinct()

    def post(self, request):
        serializer = ReferenciaInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reference = services.create_reference(
            user=request.user, data=data, variants=data.pop("variantes", []),
        )
        return Response(ReferenciaSerializer(fresh(reference)).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(tags=["referencias"], summary="Consultar una referencia"),
    patch=extend_schema(tags=["referencias"], summary="Editar una referencia",
        request=ReferenciaInputSerializer, responses=ReferenciaSerializer,
        description="Si se envía `variantes`, esa lista reemplaza a la actual. Una referencia activa no puede quedarse sin variantes."),
    delete=extend_schema(tags=["referencias"], summary="Archivar una referencia",
        description="No se archiva una referencia activa: primero se descontinúa."),
)
class ReferenciaDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Consulta, edita o archiva una referencia de jean."""
    required_permissions = {
        "GET": catalog.REFERENCES_VIEW,
        "PATCH": catalog.REFERENCES_MANAGE,
        "DELETE": catalog.REFERENCES_MANAGE,
    }
    serializer_class = ReferenciaSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return references_queryset()

    def patch(self, request, *args, **kwargs):
        reference = self.get_object()
        serializer = ReferenciaInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        services.update_reference(reference, data, variants=data.pop("variantes", None))
        return Response(ReferenciaSerializer(fresh(reference)).data)

    def perform_destroy(self, instance):
        services.archive_reference(instance)


@extend_schema(
    tags=["referencias"], summary="Cambiar el estado de una referencia",
    request=EstadoInputSerializer, responses=ReferenciaSerializer,
    description="Borrador → activa → descontinuada (y de vuelta a activa). Para activarla hacen falta al menos una talla/color y una imagen.",
)
class ReferenciaEstadoView(APIView):
    """Cambia el estado de una referencia: borrador, activa o descontinuada."""
    required_permissions = {"POST": catalog.REFERENCES_MANAGE}

    def post(self, request, pk):
        reference = get_object_or_404(Referencia, pk=pk)
        serializer = EstadoInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_state(reference, serializer.validated_data["estado"])
        return Response(ReferenciaSerializer(fresh(reference)).data)


@extend_schema(
    tags=["referencias"], summary="Subir imágenes del prototipo",
    request={"multipart/form-data": inline_serializer("ReferenciaImagenesForm", {
        "imagen": serializers.ListField(child=serializers.ImageField())})},
    responses={201: ReferenciaSerializer},
    description="Campo `imagen` (se puede repetir para subir varias). Máximo 5 por referencia y 2 MB cada una; JPG, PNG o WEBP. La primera queda como principal.",
)
class ReferenciaImagenesView(APIView):
    """Sube las fotos del prototipo de una referencia (hasta cinco)."""
    required_permissions = {"POST": catalog.REFERENCES_MANAGE}
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        reference = get_object_or_404(Referencia, pk=pk)
        services.add_images(reference, request.FILES.getlist("imagen"))
        return Response(ReferenciaSerializer(fresh(reference)).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(tags=["referencias"], summary="Descargar una imagen del prototipo",
        description="Con `ETag`: responde 304 si `If-None-Match` coincide.",
        responses={(200, "image/*"): OpenApiTypes.BINARY, 304: None, 404: None}),
    delete=extend_schema(tags=["referencias"], summary="Quitar una imagen", responses=ReferenciaSerializer),
)
class ImagenArchivoView(APIView):
    """Descarga (con `ETag`) o quita una foto del prototipo."""
    required_permissions = {"GET": catalog.REFERENCES_VIEW, "DELETE": catalog.REFERENCES_MANAGE}

    def get(self, request, pk):
        image = get_object_or_404(ImagenReferencia, pk=pk)
        etag = f'"ref-{image.pk}-{image.version}"'
        if request.headers.get("If-None-Match") == etag:
            return HttpResponse(status=304)
        response = HttpResponse(bytes(image.imagen), content_type=image.tipo)
        response["ETag"] = etag
        response["Cache-Control"] = "private, max-age=0, must-revalidate"
        return response

    def delete(self, request, pk):
        image = get_object_or_404(ImagenReferencia, pk=pk)
        reference = services.remove_image(image)
        return Response(ReferenciaSerializer(fresh(reference)).data)


@extend_schema(
    tags=["referencias"], summary="Marcar una imagen como principal",
    request=None, responses=ReferenciaSerializer,
)
class ImagenPrincipalView(APIView):
    """Marca una foto como la principal de su referencia."""
    required_permissions = {"POST": catalog.REFERENCES_MANAGE}

    def post(self, request, pk):
        image = get_object_or_404(ImagenReferencia, pk=pk)
        reference = services.set_main_image(image)
        return Response(ReferenciaSerializer(fresh(reference)).data)
