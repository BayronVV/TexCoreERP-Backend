"""Vistas de envíos: guías, rastreo con Track123, relaciones de despacho, facturas sin guía, devolución física y resumen (HU 7.2)."""
from collections import defaultdict

from django.db.models import Q
from django.http import Http404, HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inventory.views import apply_filters, limited
from apps.sales import catalog as sales_catalog
from apps.sales.serializers import _name

from . import catalog, services, tracking
from .models import Guia, RelacionDespacho
from .pdf import dispatch_pdf
from .serializers import (
    AsignarGuiaInputSerializer,
    EstadoGuiaInputSerializer,
    FacturaSinGuiaSerializer,
    FleteInputSerializer,
    GuiaDetailSerializer,
    GuiaSerializer,
    MetadatosEnvioSerializer,
    RastrearInputSerializer,
    RelacionDetailSerializer,
    RelacionInputSerializer,
    RelacionSerializer,
    metadata,
)

LIMIT_PARAM = OpenApiParameter("limit", int, description="Máximo de registros (por defecto 100)")
VIEW_PERMISSIONS = {"GET": catalog.SHIPPING_VIEW}
MANAGE_PERMISSIONS = {"GET": catalog.SHIPPING_VIEW, "POST": catalog.SHIPPING_MANAGE, "PATCH": catalog.SHIPPING_MANAGE}
RETURN_PERMISSIONS = {"POST": catalog.SHIPPING_RETURN}


def guide_queryset():
    return Guia.objects.select_related("factura", "factura__vendedor", "relacion").prefetch_related("eventos", "eventos__usuario")


def get_guide(pk):
    guide = guide_queryset().filter(pk=pk).first()
    if guide is None:
        raise Http404("La guía no existe.")
    return guide


@extend_schema(tags=["envios"])
class MetadatosEnvioView(APIView):
    """Estados con su color de semáforo, transiciones permitidas, transportadoras (y cuál se rastrea), plazos para anotar la guía."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Opciones y reglas de los envíos", responses={200: MetadatosEnvioSerializer})
    def get(self, request):
        return Response(MetadatosEnvioSerializer(metadata()).data)


@extend_schema(tags=["envios"])
class GuiaListView(APIView):
    """Guías de envío con su semáforo."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(
        summary="Listar las guías (filtros: estado, transportadora, factura, desde, hasta, q, todas, limit)",
        parameters=[
            LIMIT_PARAM, OpenApiParameter("estado", str, description="POR_DESPACHAR, EN_TRANSITO, EN_NOVEDAD, ENTREGADA, DEVUELTA o ANULADA"),
            OpenApiParameter("transportadora", str, description="INTERRAPIDISIMO, ENVIA u OTRA"), OpenApiParameter("factura", int, description="Id de la factura"),
            OpenApiParameter("desde", str, description="Fecha de creación mínima (AAAA-MM-DD)"), OpenApiParameter("hasta", str, description="Fecha de creación máxima"),
            OpenApiParameter("q", str, description="Número de guía, factura o cliente"),
            OpenApiParameter("todas", str, description="1 para incluir las guías reemplazadas o anuladas (por defecto solo las vigentes)"),
        ],
        responses={200: GuiaSerializer(many=True)},
    )
    def get(self, request):
        guides = guide_queryset()
        if request.query_params.get("todas") != "1":
            guides = guides.filter(vigente=True)
        guides = apply_filters(guides, request.query_params, [
            ("estado", "estado"), ("transportadora", "transportadora"), ("factura", "factura_id"),
            ("desde", "created_at__date__gte"), ("hasta", "created_at__date__lte"),
        ])
        q = request.query_params.get("q", "").strip()
        if q:
            guides = guides.filter(Q(numero_guia__icontains=q) | Q(factura__numero__icontains=q) | Q(factura__cliente_nombre__icontains=q))
        return Response(GuiaSerializer(limited(guides, request), many=True).data)


@extend_schema(tags=["envios"])
class GuiaDetailView(APIView):
    """Detalle de una guía con su historial y la línea de tiempo de la transportadora (sin llamar a la API)."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Detalle de una guía", responses={200: GuiaDetailSerializer})
    def get(self, request, pk):
        return Response(GuiaDetailSerializer(get_guide(pk)).data)


@extend_schema(tags=["envios"])
class FacturaGuiaView(APIView):
    """Anota o reemplaza la guía de una factura emitida (el número se genera en la transportadora)."""
    required_permissions = {"POST": catalog.SHIPPING_NOTE}

    @extend_schema(summary="Asignar la guía de una factura", request=AsignarGuiaInputSerializer, responses={201: GuiaSerializer})
    def post(self, request, pk):
        data = AsignarGuiaInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        guide = services.assign_guide(
            invoice_id=pk, carrier=data.validated_data["transportadora"], number=data.validated_data["numero_guia"], user=request.user,
        )
        return Response(GuiaSerializer(get_guide(guide.pk)).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["envios"])
class GuiaEstadoView(APIView):
    """Cambia el estado de una guía a mano (novedad y devolución exigen una nota)."""
    required_permissions = {"POST": catalog.SHIPPING_MANAGE}

    @extend_schema(summary="Cambiar el estado de una guía", request=EstadoGuiaInputSerializer, responses={200: GuiaDetailSerializer})
    def post(self, request, pk):
        data = EstadoGuiaInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.change_state(guide_id=pk, new_state=data.validated_data["estado"], note=data.validated_data["nota"], user=request.user)
        return Response(GuiaDetailSerializer(get_guide(pk)).data)


@extend_schema(tags=["envios"])
class GuiaFleteView(APIView):
    """Registra el costo del flete; en una guía devuelta es el flete que se le descuenta al vendedor."""
    required_permissions = {"PATCH": catalog.SHIPPING_MANAGE}

    @extend_schema(summary="Registrar el flete de una guía", request=FleteInputSerializer, responses={200: GuiaDetailSerializer})
    def patch(self, request, pk):
        data = FleteInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.register_freight(guide_id=pk, value=data.validated_data["valor_flete"], user=request.user)
        return Response(GuiaDetailSerializer(get_guide(pk)).data)


@extend_schema(tags=["envios"])
class GuiaDevolucionView(APIView):
    """La guía devuelta ya llegó a la bodega: registra la devolución en cartera y reingresa las prendas al inventario (una sola vez)."""
    required_permissions = RETURN_PERMISSIONS

    @extend_schema(summary="Registrar la devolución física en cartera", request=None, responses={200: GuiaDetailSerializer})
    def post(self, request, pk):
        services.return_to_stock(guide_id=pk, user=request.user)
        return Response(GuiaDetailSerializer(get_guide(pk)).data)


@extend_schema(tags=["envios"])
class GuiaRastrearView(APIView):
    """Consulta a Track123 el estado real de una guía de Interrapidísimo y lo aplica. Nunca es automático: registrar gasta cuota."""
    required_permissions = {"POST": catalog.SHIPPING_MANAGE}

    @extend_schema(summary="Consultar el estado de la guía en la transportadora (Track123)", request=RastrearInputSerializer, responses={200: GuiaDetailSerializer})
    def post(self, request, pk):
        data = RastrearInputSerializer(data=request.data or {})
        data.is_valid(raise_exception=True)
        _, warning = tracking.refresh_tracking(guide_id=pk, user=request.user, force=data.validated_data["forzar"])
        body = GuiaDetailSerializer(get_guide(pk)).data
        body["aviso"] = warning
        return Response(body)


@extend_schema(tags=["envios"])
class RastreoEstadoView(APIView):
    """Si el rastreo está habilitado y cuánta cuota de registros queda (leerla no gasta)."""
    required_permissions = {"GET": catalog.SHIPPING_MANAGE}

    @extend_schema(summary="Estado del rastreo y cuota de Track123", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(tracking.tracking_status())


@extend_schema(tags=["envios"])
class PendientesView(APIView):
    """Facturas emitidas sin guía vigente, de la más antigua a la más reciente: la guía debe anotarse lo antes posible."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Facturas sin guía", responses={200: FacturaSinGuiaSerializer(many=True)})
    def get(self, request):
        return Response(FacturaSinGuiaSerializer(limited(services.invoices_without_guide(), request), many=True).data)


@extend_schema(tags=["envios"])
class RelacionListCreateView(APIView):
    """Relaciones de despacho: los paquetes que una transportadora recoge juntos."""
    required_permissions = MANAGE_PERMISSIONS

    @extend_schema(summary="Listar las relaciones de despacho", parameters=[LIMIT_PARAM, OpenApiParameter("transportadora", str)], responses={200: RelacionSerializer(many=True)})
    def get(self, request):
        relations = apply_filters(
            RelacionDespacho.objects.select_related("creada_por").prefetch_related("guias"), request.query_params, [("transportadora", "transportadora")],
        )
        return Response(RelacionSerializer(limited(relations, request), many=True).data)

    @extend_schema(
        summary="Crear la relación y despachar sus guías",
        description="Todas las guías deben estar por despachar y ser de la misma transportadora; pasan a EN_TRANSITO en una sola transacción. "
                    "Un `token` repetido responde 409 con la relación ya creada.",
        request=RelacionInputSerializer, responses={201: RelacionDetailSerializer},
    )
    def post(self, request):
        data = RelacionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        relation = services.create_dispatch(
            user=request.user, carrier=values["transportadora"], guide_ids=values["guias"], token=values["token"], when=values.get("fecha"),
            responsible=values["responsable"], notes=values["observaciones"],
        )
        return Response(RelacionDetailSerializer(self._load(relation.pk)).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _load(pk):
        return RelacionDespacho.objects.select_related("creada_por").prefetch_related("guias", "guias__factura", "guias__factura__vendedor", "guias__relacion").get(pk=pk)


@extend_schema(tags=["envios"])
class RelacionDetailView(APIView):
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Detalle de una relación de despacho", responses={200: RelacionDetailSerializer})
    def get(self, request, pk):
        relation = RelacionListCreateView._load(pk) if RelacionDespacho.objects.filter(pk=pk).exists() else None
        if relation is None:
            raise Http404("La relación no existe.")
        return Response(RelacionDetailSerializer(relation).data)


@extend_schema(tags=["envios"])
class RelacionPdfView(APIView):
    """Descarga el PDF de la relación para firmarla al entregar los paquetes a la transportadora."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Descargar el PDF de una relación de despacho", responses={(200, "application/pdf"): bytes})
    def get(self, request, pk):
        relation = RelacionDespacho.objects.filter(pk=pk).first()
        if relation is None:
            raise Http404("La relación no existe.")
        response = HttpResponse(dispatch_pdf(relation), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{relation.codigo}.pdf"'
        return response


@extend_schema(tags=["envios"])
class ResumenView(APIView):
    """Conteos por estado y semáforo, facturas sin guía, novedades abiertas y devoluciones por vendedor con su flete."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Resumen de envíos", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        guides = list(guide_queryset().filter(vigente=True))
        counts = {code: 0 for code, _ in catalog.GUIDE_STATES}
        for guide in guides:
            counts[guide.estado] += 1
        pending = list(services.invoices_without_guide())
        hours = [services.hours_without_guide(invoice) for invoice in pending]
        by_seller = defaultdict(lambda: {"guias": 0, "flete": 0})
        for guide in guides:
            if guide.estado == catalog.RETURNED:
                row = by_seller[_name(guide.factura.vendedor) or "Sin vendedor"]
                row["guias"] += 1
                row["flete"] += guide.flete_vendedor
        incidents = [g for g in guides if g.estado == catalog.INCIDENT]
        return Response({
            "estados": [{"codigo": code, "nombre": name, "color": catalog.STATE_COLORS[code], "cantidad": counts[code]} for code, name in catalog.GUIDE_STATES if code != catalog.VOIDED],
            "sin_guia": {
                "total": len(pending),
                "con_atencion": sum(1 for h in hours if services.urgency(h) == "atencion"),
                "vencidas": sum(1 for h in hours if services.urgency(h) == "vencida"),
            },
            "novedades": GuiaSerializer(incidents[:10], many=True).data,
            "devoluciones_por_vendedor": [{"vendedor": name, **row} for name, row in sorted(by_seller.items())],
            "por_cobrar_entregadas": sum(1 for g in guides if g.estado == catalog.DELIVERED and g.factura.estado_cobro == sales_catalog.COLLECT_PENDING),
        })
