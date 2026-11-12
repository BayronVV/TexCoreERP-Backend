"""Endpoints analíticos del tablero de reportes gerenciales."""
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog, services
from .serializers import MetadatosReporteSerializer, ReporteGerencialSerializer

VIEW_PERMISSIONS = {"GET": catalog.REPORTS_VIEW}
REFRESH_PERMISSIONS = {"POST": catalog.REPORTS_VIEW}


@extend_schema(tags=["reportes"])
class ReporteMetadatosView(APIView):
    """Catálogos para los filtros avanzados del tablero gerencial (tipos de jean, referencias, estados de orden y cobro)."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Opciones disponibles para filtros de reportes", responses={200: MetadatosReporteSerializer})
    def get(self, request):
        return Response(MetadatosReporteSerializer(services.get_filter_metadata()).data)


@extend_schema(tags=["reportes"])
class ReporteGerencialView(APIView):
    """
    Endpoint analítico principal que consulta las vistas SQL materializadas y agrupa, suma y formatea
    los indicadores de producción, calidad y ventas según los filtros solicitados por gerencia.
    """
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(
        summary="Consultar tablero analítico gerencial con filtros avanzados",
        parameters=[
            OpenApiParameter("desde", str, description="Fecha inicial (AAAA-MM-DD)"),
            OpenApiParameter("hasta", str, description="Fecha final (AAAA-MM-DD)"),
            OpenApiParameter("tipo_jean", str, description="Silueta / ajuste del jean (SKINNY, SLIM, RECTO, MOM, etc.)"),
            OpenApiParameter("referencia", int, description="ID de la referencia específica"),
            OpenApiParameter("estado_orden", str, description="Estado de la orden de producción (EN_PROCESO, COMPLETADA, ANULADA)"),
            OpenApiParameter("estado_cobro", str, description="Estado de cartera en ventas (POR_COBRAR, PAGADO, DEVOLUCION)"),
            OpenApiParameter("tipo_cliente", str, description="Tipo de cliente (DETAL, MAYORISTA, DISTRIBUIDOR)"),
        ],
        responses={200: ReporteGerencialSerializer},
    )
    def get(self, request):
        data = services.build_management_report(request.query_params)
        return Response(ReporteGerencialSerializer(data).data)


@extend_schema(tags=["reportes"])
class ReporteRefrescarVistasView(APIView):
    """Fuerza la actualización de las vistas SQL materializadas en PostgreSQL (`REFRESH MATERIALIZED VIEW CONCURRENTLY`)."""
    required_permissions = REFRESH_PERMISSIONS

    @extend_schema(
        summary="Refrescar las vistas SQL materializadas de reportes",
        description="En PostgreSQL refresca las vistas materializadas del tablero; en SQLite no hace nada "
                    "(`refreshed` es falso) porque allí son vistas normales.",
        request=None,
        responses={
            200: inline_serializer(
                "ReporteRefrescoRespuesta",
                {
                    "refreshed": serializers.BooleanField(help_text="Verdadero si se refrescaron vistas materializadas"),
                    "detail": serializers.CharField(),
                },
            ),
            403: OpenApiResponse(description="El rol no tiene permiso para ver reportes"),
        },
    )
    def post(self, request):
        """Refresca las vistas materializadas y devuelve si hubo refresco."""
        refreshed = services.refresh_materialized_views()
        return Response({"refreshed": refreshed, "detail": "Vistas analíticas actualizadas correctamente."})

