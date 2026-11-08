"""Vistas de ventas: clientes, precios, facturas POS internas (con su PDF y su anulación) y metadatos."""
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inventory.services import next_code
from apps.inventory.views import apply_filters, limited
from apps.references import catalog as reference_catalog
from apps.references.models import Referencia
from apps.shipping.models import Guia

from . import catalog, invoicing
from .models import Cliente, DetalleVenta, FacturaVenta, PrecioReferencia
from .pdf import invoice_pdf
from .serializers import (
    AnularInputSerializer,
    CarteraResumenSerializer,
    ClienteSerializer,
    ConciliarInputSerializer,
    FacturaInputSerializer,
    FacturaSerializer,
    MetadatosVentaSerializer,
    PrecioInputSerializer,
    PrecioReferenciaSerializer,
)

LIMIT_PARAM = OpenApiParameter("limit", int, description="Máximo de registros (por defecto 100)")
VIEW_PERMISSIONS = {"GET": catalog.SALES_VIEW}
CLIENT_PERMISSIONS = {"GET": catalog.SALES_VIEW, "POST": catalog.SALES_MANAGE, "PATCH": catalog.SALES_MANAGE}
PRICE_PERMISSIONS = {"GET": catalog.SALES_VIEW, "PUT": catalog.SALES_PRICES}
INVOICE_PERMISSIONS = {"GET": catalog.SALES_VIEW, "POST": catalog.SALES_MANAGE}
CANCEL_PERMISSIONS = {"POST": catalog.SALES_CANCEL}


def invoice_queryset():
    return FacturaVenta.objects.select_related("vendedor", "anulada_por", "cobrado_por").prefetch_related(
        Prefetch("lineas", queryset=DetalleVenta.objects.order_by("id")),
        Prefetch("guias", queryset=Guia.objects.filter(vigente=True), to_attr="guia_vigente"),
    )


@extend_schema(tags=["ventas"])
class MetadatosVentaView(APIView):
    """Tipos de cliente con su lista de precios y descuento máximo, transportadoras, estados de cobro, IVA y leyenda."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Opciones y reglas de la venta", responses={200: MetadatosVentaSerializer})
    def get(self, request):
        return Response({
            "tipos_cliente": [
                {"codigo": code, "nombre": name, "lista_precios": catalog.PRICE_LIST[code], "descuento_maximo": catalog.MAX_DISCOUNT[code]}
                for code, name in catalog.CLIENT_TYPES
            ],
            "tipos_documento": [{"codigo": code, "nombre": name} for code, name in catalog.DOCUMENT_TYPES],
            "transportadoras": [{"codigo": code, "nombre": name} for code, name in catalog.CARRIERS],
            "estados_cobro": [{"codigo": code, "nombre": name} for code, name in catalog.COLLECT_STATES],
            "iva_tarifa": catalog.IVA_RATE, "aviso": catalog.INVOICE_NOTICE, "motivo_anulacion_minimo": catalog.MIN_CANCEL_REASON,
        })


@extend_schema(tags=["ventas"])
class ClienteListCreateView(APIView):
    """Lista los clientes y registra uno nuevo."""
    required_permissions = CLIENT_PERMISSIONS

    @extend_schema(
        summary="Listar los clientes (filtros: tipo, activo, q, limit)",
        parameters=[
            LIMIT_PARAM, OpenApiParameter("tipo", str, description="DETAL, MAYORISTA o DISTRIBUIDOR"),
            OpenApiParameter("activo", str, description="`true` o `false`"), OpenApiParameter("q", str, description="Código, nombre o documento"),
        ],
        responses={200: ClienteSerializer(many=True)},
    )
    def get(self, request):
        clients = Cliente.objects.all()
        activo = request.query_params.get("activo", "").lower()
        if activo in ("true", "false"):
            clients = clients.filter(activo=activo == "true")
        clients = apply_filters(clients, request.query_params, [("tipo", "tipo")])
        q = request.query_params.get("q", "").strip()
        if q:
            clients = clients.filter(Q(codigo__icontains=q) | Q(nombre__icontains=q) | Q(documento__icontains=q))
        return Response(ClienteSerializer(limited(clients, request), many=True).data)

    @extend_schema(summary="Registrar un cliente", request=ClienteSerializer, responses={201: ClienteSerializer})
    @transaction.atomic
    def post(self, request):
        data = ClienteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        client = data.save(codigo=next_code(catalog.CLIENT_PREFIX))
        return Response(ClienteSerializer(client).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["ventas"])
class ClienteDetailView(APIView):
    """Consulta y modifica un cliente. No se borra: se desactiva con `activo`."""
    required_permissions = CLIENT_PERMISSIONS

    def get_object(self, pk):
        client = Cliente.objects.filter(pk=pk).first()
        if client is None:
            raise Http404("El cliente no existe.")
        return client

    @extend_schema(summary="Consultar un cliente", responses={200: ClienteSerializer})
    def get(self, request, pk):
        return Response(ClienteSerializer(self.get_object(pk)).data)

    @extend_schema(summary="Modificar o desactivar un cliente", request=ClienteSerializer, responses={200: ClienteSerializer})
    def patch(self, request, pk):
        data = ClienteSerializer(self.get_object(pk), data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(ClienteSerializer(data.save()).data)


@extend_schema(tags=["ventas"])
class PrecioListView(APIView):
    """Costo de fábrica y precios de las referencias activas (vacíos si todavía no se registran)."""
    required_permissions = PRICE_PERMISSIONS

    @extend_schema(
        summary="Listar los precios por referencia", parameters=[OpenApiParameter("q", str, description="Código o nombre de la referencia")],
        responses={200: PrecioReferenciaSerializer(many=True)},
    )
    def get(self, request):
        references = Referencia.objects.filter(estado=reference_catalog.ACTIVE).order_by("codigo")
        q = request.query_params.get("q", "").strip()
        if q:
            references = references.filter(Q(codigo__icontains=q) | Q(nombre__icontains=q))
        prices = {p.referencia_id: p for p in PrecioReferencia.objects.all()}
        rows = []
        for reference in references:
            price = prices.get(reference.id)
            rows.append({
                "referencia": reference.id, "codigo": reference.codigo, "nombre": reference.nombre, "estado": reference.estado,
                "costo_fabrica": price.costo_fabrica if price else None, "precio_detal": price.precio_detal if price else None,
                "precio_mayorista": price.precio_mayorista if price else None,
            })
        return Response(PrecioReferenciaSerializer(rows, many=True).data)


@extend_schema(tags=["ventas"])
class PrecioDetailView(APIView):
    """Registra o actualiza el costo de fábrica y los precios de una referencia."""
    required_permissions = PRICE_PERMISSIONS

    @extend_schema(summary="Registrar o actualizar los precios de una referencia", request=PrecioInputSerializer, responses={200: PrecioReferenciaSerializer})
    @transaction.atomic
    def put(self, request, referencia):
        reference = Referencia.objects.filter(pk=referencia).first()
        if reference is None:
            raise Http404("La referencia no existe.")
        data = PrecioInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        price, _ = PrecioReferencia.objects.update_or_create(referencia=reference, defaults={**data.validated_data, "actualizado_por": request.user})
        return Response(PrecioReferenciaSerializer({
            "referencia": reference.id, "codigo": reference.codigo, "nombre": reference.nombre, "estado": reference.estado,
            "costo_fabrica": price.costo_fabrica, "precio_detal": price.precio_detal, "precio_mayorista": price.precio_mayorista,
        }).data)


@extend_schema(tags=["ventas"])
class FacturaListCreateView(APIView):
    """Lista las facturas y emite una nueva (RF23)."""
    required_permissions = INVOICE_PERMISSIONS

    @extend_schema(
        summary="Listar las facturas (filtros: cliente, estado, estado_cobro, transportadora, desde, hasta, q, limit)",
        parameters=[
            LIMIT_PARAM, OpenApiParameter("cliente", int, description="Id del cliente"),
            OpenApiParameter("estado", str, description="EMITIDA o ANULADA"),
            OpenApiParameter("estado_cobro", str, description="POR_COBRAR, PAGADO o DEVOLUCION"),
            OpenApiParameter("transportadora", str, description="INTERRAPIDISIMO, ENVIA u OTRA"),
            OpenApiParameter("desde", str, description="Fecha mínima (AAAA-MM-DD)"), OpenApiParameter("hasta", str, description="Fecha máxima"),
            OpenApiParameter("q", str, description="Número de factura, cliente o documento"),
        ],
        responses={200: FacturaSerializer(many=True)},
    )
    def get(self, request):
        invoices = apply_filters(
            invoice_queryset(), request.query_params, [
                ("cliente", "cliente_id"), ("estado", "estado"), ("estado_cobro", "estado_cobro"),
                ("transportadora", "transportadora"), ("desde", "fecha__gte"), ("hasta", "fecha__lte"),
            ],
        )
        q = request.query_params.get("q", "").strip()
        if q:
            invoices = invoices.filter(Q(numero__icontains=q) | Q(cliente_nombre__icontains=q) | Q(cliente_documento__icontains=q))
        return Response(FacturaSerializer(limited(invoices, request), many=True).data)

    @extend_schema(
        summary="Emitir una factura POS interna y descontar el inventario", request=FacturaInputSerializer, responses={201: FacturaSerializer},
        description="Valida el stock de cada talla y color (si faltan, responde 400 con todas las faltantes y no guarda nada), calcula descuento, "
                    "IVA y total en el servidor y descuenta el inventario en la misma transacción. El descuento lo decide el vendedor, hasta el "
                    "máximo del tipo de cliente, y el precio con descuento no puede bajar del costo de fábrica. El mismo token no factura dos "
                    "veces (409 con la factura ya creada). No es factura electrónica.",
    )
    def post(self, request):
        data = FacturaInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        invoice = invoicing.issue_invoice(
            user=request.user, cliente=values["cliente"], lineas=values["lineas"], token=values["token"],
            transportadora=values.get("transportadora", ""), numero_guia=values.get("numero_guia", ""), observaciones=values.get("observaciones", ""),
        )
        return Response(FacturaSerializer(invoice_queryset().get(pk=invoice.pk)).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["ventas"])
class FacturaDetailView(APIView):
    """Consulta una factura. No tiene PATCH ni DELETE: es inalterable (se anula)."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Consultar una factura", responses={200: FacturaSerializer})
    def get(self, request, pk):
        invoice = invoice_queryset().filter(pk=pk).first()
        if invoice is None:
            raise Http404("La factura no existe.")
        return Response(FacturaSerializer(invoice).data)


@extend_schema(tags=["ventas"])
class FacturaPdfView(APIView):
    """Descarga el PDF de la factura."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Descargar el PDF de una factura", responses={(200, "application/pdf"): bytes})
    def get(self, request, pk):
        invoice = invoice_queryset().filter(pk=pk).first()
        if invoice is None:
            raise Http404("La factura no existe.")
        response = HttpResponse(invoice_pdf(invoice), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{invoice.numero}.pdf"'
        return response


@extend_schema(tags=["ventas"])
class FacturaAnularView(APIView):
    """Anula una factura emitida: las unidades vuelven al inventario y el número no se reutiliza."""
    required_permissions = CANCEL_PERMISSIONS

    @extend_schema(
        summary="Anular una factura", request=AnularInputSerializer, responses={200: FacturaSerializer},
        description="Pide un motivo. Reingresa cada línea con un movimiento DEVOLUCION_VENTA. Si ya estaba anulada responde 409.",
    )
    def post(self, request, pk):
        data = AnularInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invoice = invoicing.cancel_invoice(user=request.user, factura_id=pk, motivo=data.validated_data["motivo"])
        return Response(FacturaSerializer(invoice_queryset().get(pk=invoice.pk)).data)


@extend_schema(tags=["ventas"])
class CarteraResumenView(APIView):
    """Totales consolidados de cartera y saldo financiero de la empresa (HU 7.3)."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Resumen de cartera y saldo financiero", responses={200: CarteraResumenSerializer})
    def get(self, request):
        return Response(CarteraResumenSerializer(invoicing.get_cartera_summary()).data)


@extend_schema(tags=["ventas"])
class FacturaConciliarView(APIView):
    """Acción rápida para cambiar el estado de cartera a Pagado o Devolución (HU 7.3)."""
    required_permissions = INVOICE_PERMISSIONS

    @extend_schema(
        summary="Conciliar recaudo o devolución de una factura",
        request=ConciliarInputSerializer,
        responses={200: FacturaSerializer},
        description="Cambia el estado de cobro a PAGADO (suma el recaudo al saldo financiero de la empresa) o a DEVOLUCION "
                    "(reingresa las prendas a producto terminado por devolución contraentrega). Solo se permite sobre facturas emitidas por cobrar.",
    )
    def post(self, request, pk):
        data = ConciliarInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invoice = invoicing.reconcile_collection(
            user=request.user,
            factura_id=pk,
            nuevo_estado=data.validated_data["estado_cobro"],
            motivo=data.validated_data.get("motivo", ""),
            observaciones=data.validated_data.get("observaciones", ""),
        )
        return Response(FacturaSerializer(invoice_queryset().get(pk=invoice.pk)).data)
