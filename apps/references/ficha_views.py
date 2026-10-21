"""Vistas de la ficha técnica de consumo por unidad (HU 3.2): ficha, PDF, consumo contra el stock y referencias para una orden."""
from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inventory import catalog as inventory_catalog

from . import catalog, fichas
from .ficha_serializers import (
    ConsumoSalidaSerializer,
    FichaInputSerializer,
    FichaSalidaSerializer,
    ficha_payload,
)
from .models import FichaTecnica, Referencia


def current_ficha(reference):
    """La ficha vigente de la referencia (o None) con quien la actualizó por última vez."""
    return FichaTecnica.objects.select_related("actualizado_por").filter(referencia=reference).first()


def payload_for(reference):
    """La ficha lista para responder: los decimales salen como texto con sus decimales exactos, como en el resto de la API."""
    return FichaSalidaSerializer(
        ficha_payload(reference, current_ficha(reference), fichas.ficha_lines(reference))
    ).data


@extend_schema_view(
    get=extend_schema(tags=["fichas"], summary="Consultar la ficha técnica de una referencia (HU 3.2)",
        responses=FichaSalidaSerializer,
        description="Si todavía no tiene ficha responde `existe: false` y sin materiales."),
    put=extend_schema(tags=["fichas"], summary="Guardar la ficha técnica de consumo por unidad",
        request=FichaInputSerializer, responses=FichaSalidaSerializer,
        description="La lista `lineas` es la ficha completa y reemplaza a la actual. Cada material debe ser materia prima o "
                    "insumo y no repetirse. La cantidad es por prenda (con hasta 3 decimales; entera si la unidad es "
                    "unidad, caja o rollo) y la merma es un porcentaje de 0 a 50 con hasta 2 decimales."),
    delete=extend_schema(tags=["fichas"], summary="Quitar la ficha técnica", responses={204: None},
        description="No se puede si la referencia tiene órdenes en proceso."),
)
class FichaView(APIView):
    """Consulta, guarda o quita la ficha técnica de consumo por unidad de una referencia (HU 3.2)."""
    required_permissions = {
        "GET": catalog.FICHA_VIEW, "PUT": catalog.FICHA_MANAGE, "DELETE": catalog.FICHA_MANAGE,
    }

    def get(self, request, pk):
        reference = get_object_or_404(Referencia, pk=pk)
        return Response(payload_for(reference))

    def put(self, request, pk):
        reference = get_object_or_404(Referencia, pk=pk)
        serializer = FichaInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        fichas.save_ficha(
            user=request.user, reference=reference, data=data,
            lines=[dict(line) for line in data.pop("lineas")],
        )
        return Response(payload_for(reference))

    def delete(self, request, pk):
        reference = get_object_or_404(Referencia, pk=pk)
        fichas.delete_ficha(reference)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["fichas"], summary="Referencias activas para elegir en una orden de salida",
    responses=inline_serializer("ReferenciaParaOrden", {
        "id": serializers.IntegerField(), "codigo": serializers.CharField(), "nombre": serializers.CharField(),
        "ajuste_nombre": serializers.CharField(), "tiene_ficha": serializers.BooleanField(),
        "materiales": serializers.IntegerField(), "lavado": serializers.CharField(),
        "lavado_nombre": serializers.CharField(),
    }, many=True),
    description="Alimenta la lista desplegable del formulario de salidas. Una orden de producción exige que la referencia "
                "tenga ficha técnica (`tiene_ficha`); una de lavandería no.",
)
class ReferenciasParaOrdenView(APIView):
    """Referencias activas para elegir en una orden, con indicación de si tienen ficha técnica."""
    required_permissions = inventory_catalog.INVENTORY_VIEW

    def get(self, request):
        wash_names = dict(catalog.WASHES)
        sheets = FichaTecnica.objects.filter(referencia=OuterRef("pk"))
        queryset = (
            Referencia.objects.filter(estado=catalog.ACTIVE)
            .annotate(
                tiene_ficha=Exists(sheets),
                materiales=Count("fichas__lineas", filter=Q(fichas__lineas__deleted_at__isnull=True)
                                 & Q(fichas__deleted_at__isnull=True)),
            )
            .order_by("nombre")
        )
        washes = dict(FichaTecnica.objects.values_list("referencia_id", "lavado"))
        return Response([
            {
                "id": r.id, "codigo": r.codigo, "nombre": r.nombre, "ajuste_nombre": r.get_ajuste_display(),
                "tiene_ficha": r.tiene_ficha, "materiales": r.materiales,
                "lavado": washes.get(r.id, ""), "lavado_nombre": wash_names.get(washes.get(r.id, ""), ""),
            }
            for r in queryset
        ])


@extend_schema(
    tags=["fichas"], summary="Consumo de una referencia para N prendas contra el stock (TE-109)",
    parameters=[OpenApiParameter("cantidad", int, required=True, description="Prendas a producir (1 a 100000)")],
    responses=ConsumoSalidaSerializer,
    description="Cruza la ficha técnica con el saldo de almacén: por material devuelve lo que se necesita (con la merma "
                "aplicada una sola vez y redondeado hacia arriba), lo disponible y lo que falta. `viable` es verdadero "
                "si no falta nada. Es una simulación: no reserva stock.",
)
class ConsumoView(APIView):
    """Consumo de una referencia para N prendas cruzado con el stock del almacén (simulación)."""
    required_permissions = inventory_catalog.INVENTORY_VIEW

    def get(self, request, pk):
        reference = get_object_or_404(Referencia, pk=pk, estado=catalog.ACTIVE)
        garments = fichas.parse_garments(request.query_params.get("cantidad"))
        result = fichas.compute_requirements(reference, garments)
        body = {"referencia": {"id": reference.id, "codigo": reference.codigo, "nombre": reference.nombre}, **result}
        return Response(ConsumoSalidaSerializer(body).data)


@extend_schema_view(
    get=extend_schema(tags=["fichas"], summary="Descargar el PDF de la ficha técnica extensa",
        description="Con `ETag`: responde 304 si `If-None-Match` coincide.",
        responses={(200, "application/pdf"): OpenApiTypes.BINARY, 304: None, 404: None}),
    post=extend_schema(tags=["fichas"], summary="Adjuntar o reemplazar el PDF de la ficha técnica extensa",
        request={"multipart/form-data": inline_serializer("FichaDocumentoForm", {"documento": serializers.FileField()})},
        responses={201: FichaSalidaSerializer},
        description="Campo `documento`: un PDF de máximo 5 MB, detectado por su contenido. La ficha debe existir. "
                    "Sirve para el geometral, la secuencia de confección y la tabla de medidas hasta que tengan su módulo."),
    delete=extend_schema(tags=["fichas"], summary="Quitar el PDF de la ficha técnica", responses=FichaSalidaSerializer),
)
class FichaDocumentoView(APIView):
    """Descarga, adjunta o quita el PDF de la ficha técnica extensa."""
    required_permissions = {"GET": catalog.FICHA_VIEW, "POST": catalog.FICHA_MANAGE, "DELETE": catalog.FICHA_MANAGE}
    parser_classes = [MultiPartParser]

    def get(self, request, pk):
        reference = get_object_or_404(Referencia, pk=pk)
        ficha = current_ficha(reference)
        if ficha is None or not ficha.tiene_documento:
            raise Http404
        etag = f'"ficha-{ficha.pk}-{ficha.documento_version}"'
        if request.headers.get("If-None-Match") == etag:
            return HttpResponse(status=304)
        response = HttpResponse(bytes(ficha.documento), content_type="application/pdf")
        response["ETag"] = etag
        response["Cache-Control"] = "private, max-age=0, must-revalidate"
        response["Content-Disposition"] = f'inline; filename="{reference.codigo}-ficha-tecnica.pdf"'
        return response

    def post(self, request, pk):
        reference = get_object_or_404(Referencia, pk=pk)
        fichas.set_document(reference, request.FILES.get("documento"))
        return Response(payload_for(reference), status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        reference = get_object_or_404(Referencia, pk=pk)
        fichas.clear_document(reference)
        return Response(payload_for(reference))
