"""Vistas de ventas: clientes, precios, facturas POS internas (con su PDF y su anulación) y metadatos."""
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.listing import (
    PAGINATION_PARAMS,
    paginate_or_limit,
    parse_date_range,
    parse_int_param,
    seller_options,
)
from apps.inventory.services import next_code
from apps.inventory.views import apply_filters, limited
from apps.references import catalog as reference_catalog
from apps.references.models import Referencia
from apps.shipping.models import Guia

from . import catalog, invoicing, pricing
from .models import Cliente, DetalleVenta, FacturaVenta, HistorialPrecioReferencia, PrecioReferencia
from .pdf import invoice_pdf
from .serializers import (
    AnularInputSerializer,
    AplicarCostoInputSerializer,
    CarteraResumenSerializer,
    ClienteSerializer,
    ConciliarInputSerializer,
    FacturaInputSerializer,
    FacturaSerializer,
    HistorialPrecioSerializer,
    MetadatosVentaSerializer,
    PrecioInputSerializer,
    PrecioReferenciaBasicoSerializer,
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
            "vendedores": seller_options(),
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


def _can_manage_prices(user) -> bool:
    """True si el usuario puede administrar precios y ver el costo calculado desde producción."""
    return bool(user and getattr(user, "is_authenticated", False) and user.has_permission_code(catalog.SALES_PRICES))


@extend_schema(tags=["ventas"])
class PrecioListView(APIView):
    """Costo de fábrica y precios de las referencias activas (con cálculo de producción para `ventas.precios`)."""
    required_permissions = PRICE_PERMISSIONS

    @extend_schema(
        summary="Listar los precios por referencia", parameters=[OpenApiParameter("q", str, description="Código o nombre de la referencia")],
        responses={200: PrecioReferenciaSerializer(many=True)},
    )
    def get(self, request):
        references = list(Referencia.objects.filter(estado=reference_catalog.ACTIVE).order_by("codigo"))
        q = request.query_params.get("q", "").strip()
        if q:
            q_lower = q.lower()
            references = [r for r in references if q_lower in r.codigo.lower() or q_lower in r.nombre.lower()]
        prices = {p.referencia_id: p for p in PrecioReferencia.objects.all()}
        can_manage = _can_manage_prices(request.user)
        calcs = pricing.calculate_references_costs([r.id for r in references]) if can_manage else None
        rows = [
            pricing.build_price_row(
                reference,
                prices.get(reference.id),
                calc=calcs.get(reference.id) if calcs is not None else None,
            )
            for reference in references
        ]
        serializer_cls = PrecioReferenciaSerializer if can_manage else PrecioReferenciaBasicoSerializer
        return Response(serializer_cls(rows, many=True).data)


@extend_schema(tags=["ventas"])
class PrecioDetailView(APIView):
    """Registra o actualiza el costo de fábrica y los precios de una referencia."""
    required_permissions = PRICE_PERMISSIONS

    @extend_schema(summary="Registrar o actualizar los precios de una referencia", request=PrecioInputSerializer, responses={200: PrecioReferenciaSerializer})
    def put(self, request, referencia):
        reference = Referencia.objects.filter(pk=referencia).first()
        if reference is None:
            raise Http404("La referencia no existe.")
        data = PrecioInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        price = pricing.save_reference_price(
            user=request.user,
            reference=reference,
            costo_fabrica=values["costo_fabrica"],
            precio_mayorista=values["precio_mayorista"],
            precio_detal=values["precio_detal"],
            origen=catalog.PRICE_SOURCE_MANUAL,
            motivo=values.get("motivo", ""),
        )
        calc = pricing.calculate_references_costs([reference.id])[reference.id]
        return Response(PrecioReferenciaSerializer(pricing.build_price_row(reference, price, calc=calc)).data)


@extend_schema(tags=["ventas"])
class PrecioAplicarCostoView(APIView):
    """Aplica como costo de fábrica el valor calculado desde las órdenes terminadas de producción (HU 4.7)."""
    required_permissions = {"POST": catalog.SALES_PRICES}

    @extend_schema(
        summary="Aplicar el costo calculado desde producción a una referencia",
        request=AplicarCostoInputSerializer,
        responses={200: PrecioReferenciaSerializer},
        description="Adopta el costo promedio ponderado por prendas aptas calculado de órdenes terminadas con costos completos. "
                    "Rechaza con 400 si el cálculo está incompleto o supera el precio mayorista sin actualizarlo.",
    )
    def post(self, request, referencia):
        reference = Referencia.objects.filter(pk=referencia).first()
        if reference is None:
            raise Http404("La referencia no existe.")
        data = AplicarCostoInputSerializer(data=request.data or {})
        data.is_valid(raise_exception=True)
        values = data.validated_data
        price, calc = pricing.apply_calculated_cost(
            user=request.user,
            reference=reference,
            precio_mayorista=values.get("precio_mayorista"),
            precio_detal=values.get("precio_detal"),
            motivo=values.get("motivo", ""),
        )
        return Response(PrecioReferenciaSerializer(pricing.build_price_row(reference, price, calc=calc)).data)


@extend_schema(tags=["ventas"])
class PrecioHistorialView(APIView):
    """Historial de cambios de costo de fábrica y precios de venta de una referencia (HU 4.7)."""
    required_permissions = {"GET": catalog.SALES_PRICES}

    @extend_schema(
        summary="Consultar el historial de precios y costos de una referencia",
        responses={200: HistorialPrecioSerializer(many=True)},
    )
    def get(self, request, referencia):
        reference = Referencia.objects.filter(pk=referencia).first()
        if reference is None:
            raise Http404("La referencia no existe.")
        history = (
            HistorialPrecioReferencia.objects.filter(precio_referencia__referencia=reference)
            .select_related("usuario")
            .order_by("-created_at", "-id")
        )
        return Response(HistorialPrecioSerializer(history, many=True).data)


@extend_schema(tags=["ventas"])
class FacturaListCreateView(APIView):
    """Lista las facturas y emite una nueva (RF23)."""
    required_permissions = INVOICE_PERMISSIONS

    @extend_schema(
        summary="Listar las facturas (filtros combinables y paginación)",
        parameters=[
            LIMIT_PARAM, *PAGINATION_PARAMS,
            OpenApiParameter("cliente", int, description="Id del cliente"),
            OpenApiParameter("vendedor", int, description="Id del vendedor"),
            OpenApiParameter("referencia", int, description="Id de la referencia vendida"),
            OpenApiParameter("estado", str, description="EMITIDA o ANULADA"),
            OpenApiParameter("estado_cobro", str, description="POR_COBRAR, PAGADO o DEVOLUCION"),
            OpenApiParameter("transportadora", str, description="INTERRAPIDISIMO, ENVIA u OTRA"),
            OpenApiParameter("desde", str, description="Fecha mínima (AAAA-MM-DD)"), OpenApiParameter("hasta", str, description="Fecha máxima"),
            OpenApiParameter("q", str, description="Número de factura, cliente, documento o guía"),
        ],
        responses={200: FacturaSerializer(many=True)},
    )
    def get(self, request):
        desde, hasta = parse_date_range(request.query_params)
        cliente_id = parse_int_param(request.query_params, "cliente", minimum=1)
        vendedor_id = parse_int_param(request.query_params, "vendedor", minimum=1)
        referencia_id = parse_int_param(request.query_params, "referencia", minimum=1)

        invoices = invoice_queryset()
        if cliente_id is not None:
            invoices = invoices.filter(cliente_id=cliente_id)
        if vendedor_id is not None:
            invoices = invoices.filter(vendedor_id=vendedor_id)
        if referencia_id is not None:
            invoices = invoices.filter(
                id__in=DetalleVenta.objects.filter(variante__referencia_id=referencia_id).values("factura_id")
            )
        if desde is not None:
            invoices = invoices.filter(fecha__gte=desde)
        if hasta is not None:
            invoices = invoices.filter(fecha__lte=hasta)

        invoices = apply_filters(
            invoices, request.query_params, [
                ("estado", "estado"), ("estado_cobro", "estado_cobro"), ("transportadora", "transportadora"),
            ],
        )
        q = request.query_params.get("q", "").strip()
        if q:
            invoices = invoices.filter(
                Q(numero__icontains=q)
                | Q(cliente_nombre__icontains=q)
                | Q(cliente_documento__icontains=q)
                | Q(numero_guia__icontains=q)
            )
        return paginate_or_limit(invoices, request, FacturaSerializer)

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
