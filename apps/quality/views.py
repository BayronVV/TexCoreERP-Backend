"""Vistas de calidad: catálogo de defectos, lotes por inspeccionar e inspecciones (solo se agregan, no se editan)."""
from django.db.models import Prefetch, Q
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inventory.views import apply_filters, limited
from apps.production.models import RecepcionLote

from . import catalog, services
from .models import Inspeccion, MarraDetalle, TipoDefecto
from .serializers import (
    DefectoInputSerializer,
    DefectoPatchSerializer,
    DefectoSerializer,
    InspeccionInputSerializer,
    InspeccionSerializer,
    PendienteSerializer,
)

LIMIT_PARAM = OpenApiParameter("limit", int, description="Máximo de registros (por defecto 100)")
DEFECTS_PERMISSIONS = {"GET": catalog.QUALITY_VIEW, "POST": catalog.QUALITY_MANAGE}
DEFECT_PERMISSIONS = {"GET": catalog.QUALITY_VIEW, "PATCH": catalog.QUALITY_MANAGE}
INSPECTIONS_PERMISSIONS = {"GET": catalog.QUALITY_VIEW, "POST": catalog.QUALITY_MANAGE}
READ_ONLY_PERMISSIONS = {"GET": catalog.QUALITY_VIEW}


def inspection_queryset():
    return Inspeccion.objects.select_related(
        "lote__orden__referencia", "inspector", "recepcion_lote__recepcion__remision__lavanderia"
    ).prefetch_related(Prefetch("detalle", queryset=MarraDetalle.objects.order_by("id")))


@extend_schema(tags=["calidad"])
class DefectoListCreateView(APIView):
    """Lista el catálogo de defectos y crea uno nuevo (RF19)."""
    required_permissions = DEFECTS_PERMISSIONS

    @extend_schema(
        summary="Listar los defectos (filtros: activo, q, limit)",
        parameters=[
            LIMIT_PARAM, OpenApiParameter("activo", bool, description="true o false; sin él salen todos"),
            OpenApiParameter("q", str, description="Código o nombre del defecto"),
        ],
        responses={200: DefectoSerializer(many=True)},
    )
    def get(self, request):
        defects = TipoDefecto.objects.all()
        active = request.query_params.get("activo")
        if active in ("true", "1"):
            defects = defects.filter(activo=True)
        elif active in ("false", "0"):
            defects = defects.filter(activo=False)
        q = request.query_params.get("q", "").strip()
        if q:
            defects = defects.filter(Q(codigo__icontains=q) | Q(nombre__icontains=q))
        return Response(DefectoSerializer(limited(defects, request), many=True).data)

    @extend_schema(
        summary="Crear un defecto del catálogo", request=DefectoInputSerializer, responses={201: DefectoSerializer},
        description="El nombre no se repite (sin importar mayúsculas). Un defecto es corregible (reproceso) o incorregible (marra definitiva).",
    )
    def post(self, request):
        data = DefectoInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        defect = services.create_defect(**data.validated_data)
        return Response(DefectoSerializer(defect).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["calidad"])
class DefectoDetailView(APIView):
    """Consulta un defecto y lo modifica o lo desactiva. No se borra: así no se rompe el historial."""
    required_permissions = DEFECT_PERMISSIONS

    def get_defect(self, pk):
        defect = TipoDefecto.objects.filter(pk=pk).first()
        if defect is None:
            raise Http404("El defecto no existe.")
        return defect

    @extend_schema(summary="Consultar un defecto", responses={200: DefectoSerializer})
    def get(self, request, pk):
        return Response(DefectoSerializer(self.get_defect(pk)).data)

    @extend_schema(
        summary="Modificar, activar o desactivar un defecto", request=DefectoPatchSerializer, responses={200: DefectoSerializer},
        description="Las inspecciones ya registradas conservan el nombre y el tipo que el defecto tenía al inspeccionar.",
    )
    def patch(self, request, pk):
        defect = self.get_defect(pk)
        data = DefectoPatchSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(DefectoSerializer(services.update_defect(defect, data.validated_data)).data)


@extend_schema(tags=["calidad"])
class PendientesView(APIView):
    """Lotes que volvieron de lavandería y todavía no se inspeccionan."""
    required_permissions = READ_ONLY_PERMISSIONS

    @extend_schema(
        summary="Listar los lotes por inspeccionar", parameters=[LIMIT_PARAM], responses={200: PendienteSerializer(many=True)},
        description="Lotes en planta con una recepción de lavandería con prendas conformes, sin inspección y de una orden no "
                    "anulada. `cantidad_recibida` es lo recibido conforme en su recepción más reciente.",
    )
    def get(self, request):
        lots = list(limited(services.pending_lots(), request))
        receptions = RecepcionLote.objects.filter(pk__in=[lot.recepcion_lote_id for lot in lots]).select_related(
            "recepcion__remision__lavanderia"
        ).in_bulk()
        rows = []
        for lot in lots:
            reception = receptions[lot.recepcion_lote_id].recepcion
            rows.append({
                "id": lot.id, "codigo": lot.codigo, "orden": lot.orden_id, "orden_codigo": lot.orden.codigo,
                "referencia_nombre": lot.orden.referencia.nombre, "lavanderia_nombre": reception.remision.lavanderia.razon_social,
                "recepcion_codigo": reception.codigo, "fecha_recepcion": reception.fecha_recepcion,
                "cantidad_recibida": lot.por_inspeccionar,
            })
        return Response(PendienteSerializer(rows, many=True).data)


@extend_schema(tags=["calidad"])
class InspeccionListCreateView(APIView):
    """Lista las inspecciones y registra una nueva (RF20)."""
    required_permissions = INSPECTIONS_PERMISSIONS

    @extend_schema(
        summary="Listar las inspecciones (filtros: lote, orden, desde, hasta, q, limit)",
        parameters=[
            LIMIT_PARAM, OpenApiParameter("lote", int, description="Id del lote"), OpenApiParameter("orden", int, description="Id de la orden"),
            OpenApiParameter("desde", str, description="Fecha mínima (AAAA-MM-DD)"), OpenApiParameter("hasta", str, description="Fecha máxima"),
            OpenApiParameter("q", str, description="Código de la inspección, del lote o de la orden"),
        ],
        responses={200: InspeccionSerializer(many=True)},
    )
    def get(self, request):
        inspections = apply_filters(
            inspection_queryset(), request.query_params,
            [("lote", "lote_id"), ("orden", "lote__orden_id"), ("desde", "fecha__gte"), ("hasta", "fecha__lte")],
        )
        q = request.query_params.get("q", "").strip()
        if q:
            inspections = inspections.filter(Q(codigo__icontains=q) | Q(lote__codigo__icontains=q) | Q(lote__orden__codigo__icontains=q))
        return Response(InspeccionSerializer(limited(inspections, request), many=True).data)

    @extend_schema(
        summary="Registrar la inspección de un lote", request=InspeccionInputSerializer, responses={201: InspeccionSerializer},
        description="Las aptas más la suma de las marras deben ser exactamente lo recibido conforme del lote. Una inspección por "
                    "lote: si ya existe, responde 409. No se edita ni se borra.",
    )
    def post(self, request):
        data = InspeccionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        inspection = services.register_inspection(
            user=request.user, lote_id=values["lote"], aptas=values["aptas"], defectos=values.get("defectos"),
            observaciones=values.get("observaciones", ""), fecha=values.get("fecha"),
        )
        return Response(InspeccionSerializer(inspection_queryset().get(pk=inspection.pk)).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["calidad"])
class InspeccionDetailView(APIView):
    """Consulta una inspección. No tiene PATCH ni DELETE: el registro es inalterable."""
    required_permissions = READ_ONLY_PERMISSIONS

    @extend_schema(summary="Consultar una inspección", responses={200: InspeccionSerializer})
    def get(self, request, pk):
        inspection = inspection_queryset().filter(pk=pk).first()
        if inspection is None:
            raise Http404("La inspección no existe.")
        return Response(InspeccionSerializer(inspection).data)
