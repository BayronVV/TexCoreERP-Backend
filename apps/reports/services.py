"""
Servicios analíticos de reportes gerenciales.
Consulta las vistas SQL materializadas (`reportes_mv_produccion_ordenes` y `reportes_mv_ventas_referencias`)
para agrupar, sumar y formatear los indicadores solicitados por la gerencia sin sobrecargar las tablas transaccionales.
"""
from contextlib import nullcontext
import logging

from django.db import DatabaseError, connection, transaction
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce

from apps.core.listing import parse_date_range, parse_int_param, seller_options
from apps.inventory import catalog as inventory_catalog
from apps.references import catalog as reference_catalog
from apps.references.models import Referencia
from apps.sales import catalog as sales_catalog
from apps.sales.models import DetalleVenta, SaldoFinanciero
from apps.shipping import catalog as shipping_catalog
from apps.shipping.models import Guia

from .models import VistaProduccionOrden, VistaVentasReferencia

logger = logging.getLogger(__name__)
_VIEWS_DIRTY = False

FIT_NAMES = dict(reference_catalog.FITS)
ORDER_STATE_NAMES = dict(inventory_catalog.ORDER_STATUSES)
COLLECT_STATE_NAMES = dict(sales_catalog.COLLECT_STATES)
CLIENT_TYPE_NAMES = dict(sales_catalog.CLIENT_TYPES)
INVOICE_STATE_NAMES = dict(sales_catalog.INVOICE_STATES)


def mark_views_dirty():
    """Marca las vistas materializadas de reportes como pendientes de refresco."""
    global _VIEWS_DIRTY
    _VIEWS_DIRTY = True


def clear_views_dirty():
    """Limpia la marca de pendiente una vez refrescadas o sincronizadas las vistas."""
    global _VIEWS_DIRTY
    _VIEWS_DIRTY = False


def are_views_dirty():
    """Indica si hubo cambios en tablas fuente desde el último refresco de vistas."""
    return _VIEWS_DIRTY


def refresh_materialized_views(*, raise_on_error=False):
    """
    Refresca las vistas SQL materializadas en PostgreSQL.
    En SQLite son vistas regulares que se evalúan al instante, por lo que no requieren refresco.
    Dentro de bloques atómicos (por ejemplo TestCase) PostgreSQL exige refrescar sin CONCURRENTLY.
    """
    if connection.vendor != "postgresql":
        clear_views_dirty()
        return False
    concurrently = "" if connection.in_atomic_block else "CONCURRENTLY "
    ctx = transaction.atomic() if connection.in_atomic_block else nullcontext()
    try:
        with ctx, connection.cursor() as cursor:
            cursor.execute(f"REFRESH MATERIALIZED VIEW {concurrently}reportes_mv_produccion_ordenes;")
            cursor.execute(f"REFRESH MATERIALIZED VIEW {concurrently}reportes_mv_ventas_referencias;")
    except DatabaseError:
        logger.exception("Error al refrescar vistas SQL materializadas de reportes.")
        if raise_on_error:
            raise
        return False
    clear_views_dirty()
    return True


def _run_scheduled_refresh():
    refresh_materialized_views(raise_on_error=False)


def schedule_views_refresh(**kwargs):
    """Marca las vistas como pendientes y agenda un único refresco al confirmar la transacción en PostgreSQL."""
    mark_views_dirty()
    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        return
    queued = getattr(connection, "run_on_commit", ())
    if any(entry[1] is _run_scheduled_refresh for entry in queued):
        return
    transaction.on_commit(_run_scheduled_refresh)


def validate_report_params(params):
    """Valida los parámetros de consulta del tablero gerencial antes de ejecutar filtros SQL."""
    desde_date, hasta_date = parse_date_range(params)
    referencia_id = parse_int_param(params, "referencia", minimum=1)
    vendedor_id = parse_int_param(params, "vendedor", minimum=1)

    return {
        "desde": desde_date.isoformat() if desde_date else "",
        "hasta": hasta_date.isoformat() if hasta_date else "",
        "tipo_jean": (params.get("tipo_jean") or "").strip(),
        "referencia_id": referencia_id,
        "estado_orden": (params.get("estado_orden") or "").strip(),
        "estado_cobro": (params.get("estado_cobro") or "").strip(),
        "tipo_cliente": (params.get("tipo_cliente") or "").strip(),
        "vendedor_id": vendedor_id,
        "transportadora": (params.get("transportadora") or "").strip().upper(),
    }


def get_filter_metadata():
    """Catálogos disponibles para los filtros avanzados del tablero gerencial."""
    referencias = list(
        Referencia.objects.order_by("codigo").values("id", "codigo", "nombre", "ajuste", "estado")
    )
    for ref in referencias:
        ref["ajuste_nombre"] = FIT_NAMES.get(ref["ajuste"], ref["ajuste"])

    return {
        "tipos_jean": [{"codigo": code, "nombre": name} for code, name in reference_catalog.FITS],
        "estados_orden": [{"codigo": code, "nombre": name} for code, name in inventory_catalog.ORDER_STATUSES],
        "estados_cobro": [{"codigo": code, "nombre": name} for code, name in sales_catalog.COLLECT_STATES],
        "tipos_cliente": [{"codigo": code, "nombre": name} for code, name in sales_catalog.CLIENT_TYPES],
        "vendedores": seller_options(),
        "transportadoras": [{"codigo": code, "nombre": name} for code, name in sales_catalog.CARRIERS],
        "referencias": referencias,
    }


def _returns_by_seller(filters):
    """Agrupa las guías devueltas vigentes por vendedor y suma el flete a su cargo (reporte informativo)."""
    qs = Guia.objects.filter(
        vigente=True,
        estado=shipping_catalog.RETURNED,
        factura__deleted_at__isnull=True,
        factura__estado=sales_catalog.STATUS_ISSUED,
    )
    if filters["desde"]:
        qs = qs.filter(factura__fecha__gte=filters["desde"])
    if filters["hasta"]:
        qs = qs.filter(factura__fecha__lte=filters["hasta"])
    if filters["vendedor_id"] is not None:
        qs = qs.filter(factura__vendedor_id=filters["vendedor_id"])
    if filters["transportadora"]:
        qs = qs.filter(transportadora=filters["transportadora"])
    if filters["tipo_cliente"]:
        qs = qs.filter(factura__cliente_tipo=filters["tipo_cliente"])
    if filters["estado_cobro"]:
        qs = qs.filter(factura__estado_cobro=filters["estado_cobro"])
    if filters["referencia_id"] is not None or filters["tipo_jean"]:
        lines_sub = DetalleVenta.objects.all()
        if filters["referencia_id"] is not None:
            lines_sub = lines_sub.filter(variante__referencia_id=filters["referencia_id"])
        if filters["tipo_jean"]:
            lines_sub = lines_sub.filter(variante__referencia__ajuste=filters["tipo_jean"])
        qs = qs.filter(factura_id__in=lines_sub.values("factura_id"))

    aggregated = (
        qs.values(
            "factura__vendedor_id",
            "factura__vendedor__first_name",
            "factura__vendedor__last_name",
            "factura__vendedor__email",
            "factura__vendedor__username",
        )
        .annotate(
            guias_devueltas=Count("id"),
            flete_vendedor=Coalesce(Sum("flete_vendedor"), 0),
        )
    )
    rows = []
    for item in aggregated:
        full_name = f"{item['factura__vendedor__first_name'] or ''} {item['factura__vendedor__last_name'] or ''}".strip()
        seller_name = full_name or item["factura__vendedor__email"] or item["factura__vendedor__username"] or "Sin vendedor"
        rows.append({
            "vendedor_id": item["factura__vendedor_id"],
            "vendedor_nombre": seller_name,
            "guias_devueltas": item["guias_devueltas"] or 0,
            "flete_vendedor": item["flete_vendedor"] or 0,
        })
    rows.sort(key=lambda r: (-r["flete_vendedor"], -r["guias_devueltas"], r["vendedor_nombre"]))
    return rows


def build_management_report(params, auto_refresh=False):
    """
    Construye el reporte analítico consolidado aplicando los filtros avanzados:
    - `desde` / `hasta`: rango de fechas (AAAA-MM-DD)
    - `tipo_jean`: silueta / ajuste del jean (SKINNY, SLIM, RECTO, MOM, etc.)
    - `referencia`: ID de una referencia específica
    - `estado_orden`: estado de la orden de producción (EN_PROCESO, COMPLETADA, ANULADA)
    - `estado_cobro`: estado de cartera de las ventas (POR_COBRAR, PAGADO, DEVOLUCION)
    - `tipo_cliente`: tipo de cliente en ventas (DETAL, MAYORISTA, DISTRIBUIDOR)
    - `vendedor`: ID del vendedor de la factura
    - `transportadora`: transportadora de la factura / guía
    """
    filters = validate_report_params(params)

    if auto_refresh or are_views_dirty():
        refresh_materialized_views(raise_on_error=False)
        clear_views_dirty()

    desde = filters["desde"]
    hasta = filters["hasta"]
    tipo_jean = filters["tipo_jean"]
    referencia_id = filters["referencia_id"]
    estado_orden = filters["estado_orden"]
    estado_cobro = filters["estado_cobro"]
    tipo_cliente = filters["tipo_cliente"]
    vendedor_id = filters["vendedor_id"]
    transportadora = filters["transportadora"]

    # 1. Filtrado sobre la vista materializada de Producción
    prod_qs = VistaProduccionOrden.objects.all()
    if desde:
        prod_qs = prod_qs.filter(fecha_salida__gte=desde)
    if hasta:
        prod_qs = prod_qs.filter(fecha_salida__lte=hasta)
    if tipo_jean:
        prod_qs = prod_qs.filter(tipo_jean=tipo_jean)
    if referencia_id is not None:
        prod_qs = prod_qs.filter(referencia_id=referencia_id)
    if estado_orden:
        prod_qs = prod_qs.filter(estado_orden=estado_orden)

    # 2. Filtrado sobre la vista materializada de Ventas (solo facturas emitidas salvo que se pida otra cosa)
    sales_qs = VistaVentasReferencia.objects.filter(estado_factura=sales_catalog.STATUS_ISSUED)
    if desde:
        sales_qs = sales_qs.filter(fecha__gte=desde)
    if hasta:
        sales_qs = sales_qs.filter(fecha__lte=hasta)
    if tipo_jean:
        sales_qs = sales_qs.filter(tipo_jean=tipo_jean)
    if referencia_id is not None:
        sales_qs = sales_qs.filter(referencia_id=referencia_id)
    if estado_cobro:
        sales_qs = sales_qs.filter(estado_cobro=estado_cobro)
    if tipo_cliente:
        sales_qs = sales_qs.filter(cliente_tipo=tipo_cliente)
    if vendedor_id is not None:
        sales_qs = sales_qs.filter(vendedor_id=vendedor_id)
    if transportadora:
        sales_qs = sales_qs.filter(transportadora=transportadora)

    # --- Desglose de órdenes de producción ---
    ordenes_rows = []
    for row in prod_qs.order_by("-fecha_salida", "-orden_id"):
        inspeccionadas = row.prendas_aptas + row.prendas_marras
        tasa_calidad = round((row.prendas_aptas / inspeccionadas) * 100, 1) if inspeccionadas > 0 else 100.0
        cumplimiento = (
            round((row.prendas_en_lotes / row.prendas_planificadas) * 100, 1)
            if row.prendas_planificadas > 0
            else 0.0
        )
        ordenes_rows.append({
            "orden_id": row.orden_id,
            "codigo": row.codigo,
            "fecha_salida": row.fecha_salida.isoformat() if row.fecha_salida else "",
            "estado_orden": row.estado_orden,
            "estado_orden_nombre": ORDER_STATE_NAMES.get(row.estado_orden, row.estado_orden),
            "responsable": row.responsable,
            "referencia_id": row.referencia_id,
            "referencia_codigo": row.referencia_codigo,
            "referencia_nombre": row.referencia_nombre,
            "tipo_jean": row.tipo_jean,
            "tipo_jean_nombre": FIT_NAMES.get(row.tipo_jean, row.tipo_jean),
            "prendas_planificadas": row.prendas_planificadas,
            "total_lotes": row.total_lotes,
            "prendas_en_lotes": row.prendas_en_lotes,
            "prendas_aptas": row.prendas_aptas,
            "prendas_marras": row.prendas_marras,
            "tasa_calidad_pct": tasa_calidad,
            "avance_lotes_pct": cumplimiento,
        })

    # --- Agrupación de ventas por referencia y tipo de jean ---
    ventas_agrupadas = (
        sales_qs.values(
            "referencia_id",
            "referencia_codigo",
            "referencia_nombre",
            "tipo_jean",
        )
        .annotate(
            facturas_count=Count("factura_id", distinct=True),
            unidades_vendidas=Sum("unidades"),
            subtotal_bruto=Sum("subtotal"),
            descuento_total=Sum("descuento"),
            base_gravable=Sum("base_gravable"),
            iva_total=Sum("iva"),
            ingresos_totales=Sum("total"),
            costo_total=Sum("costo_estimado"),
        )
        .order_by("-ingresos_totales", "referencia_codigo")
    )

    ventas_por_referencia = []
    for item in ventas_agrupadas:
        base = item["base_gravable"] or 0
        costo = item["costo_total"] or 0
        utilidad = base - costo
        margen = round((utilidad / base) * 100, 1) if base > 0 else 0.0
        ventas_por_referencia.append({
            "referencia_id": item["referencia_id"],
            "referencia_codigo": item["referencia_codigo"],
            "referencia_nombre": item["referencia_nombre"],
            "tipo_jean": item["tipo_jean"],
            "tipo_jean_nombre": FIT_NAMES.get(item["tipo_jean"], item["tipo_jean"]),
            "facturas_count": item["facturas_count"] or 0,
            "unidades_vendidas": item["unidades_vendidas"] or 0,
            "subtotal_bruto": item["subtotal_bruto"] or 0,
            "descuento_total": item["descuento_total"] or 0,
            "base_gravable": base,
            "iva_total": item["iva_total"] or 0,
            "ingresos_totales": item["ingresos_totales"] or 0,
            "costo_estimado": costo,
            "utilidad_bruta": utilidad,
            "margen_pct": margen,
        })

    # --- Detalle de líneas de venta filtradas (para exportación detallada) ---
    ventas_detalle = []
    for v in sales_qs.order_by("-fecha", "-linea_id")[:250]:
        ventas_detalle.append({
            "linea_id": v.linea_id,
            "factura_id": v.factura_id,
            "numero_factura": v.numero_factura,
            "fecha": v.fecha.isoformat() if v.fecha else "",
            "cliente_nombre": v.cliente_nombre,
            "cliente_tipo": v.cliente_tipo,
            "cliente_tipo_nombre": CLIENT_TYPE_NAMES.get(v.cliente_tipo, v.cliente_tipo),
            "vendedor_nombre": v.vendedor_nombre,
            "transportadora": v.transportadora,
            "estado_cobro": v.estado_cobro,
            "estado_cobro_nombre": COLLECT_STATE_NAMES.get(v.estado_cobro, v.estado_cobro),
            "referencia_codigo": v.referencia_codigo,
            "referencia_nombre": v.referencia_nombre,
            "tipo_jean": v.tipo_jean,
            "tipo_jean_nombre": FIT_NAMES.get(v.tipo_jean, v.tipo_jean),
            "talla": v.talla,
            "color": v.color,
            "unidades": v.unidades,
            "subtotal": v.subtotal,
            "descuento": v.descuento,
            "base_gravable": v.base_gravable,
            "iva": v.iva,
            "total": v.total,
        })

    # --- Consolidado por Tipo de Jean (Silueta) cruzando Producción y Ventas ---
    prod_por_tipo = {
        r["tipo_jean"]: r
        for r in prod_qs.values("tipo_jean").annotate(
            ordenes_count=Count("orden_id"),
            prendas_planificadas=Sum("prendas_planificadas"),
            prendas_aptas=Sum("prendas_aptas"),
            prendas_marras=Sum("prendas_marras"),
        )
    }
    ventas_por_tipo = {
        r["tipo_jean"]: r
        for r in sales_qs.values("tipo_jean").annotate(
            unidades_vendidas=Sum("unidades"),
            ingresos_totales=Sum("total"),
            base_gravable=Sum("base_gravable"),
            costo_estimado=Sum("costo_estimado"),
        )
    }

    tipos_activos = sorted(
        set(prod_por_tipo.keys()) | set(ventas_por_tipo.keys()),
        key=lambda code: FIT_NAMES.get(code, code),
    )
    consolidado_tipo_jean = []
    for code in tipos_activos:
        p = prod_por_tipo.get(code, {})
        s = ventas_por_tipo.get(code, {})
        base = s.get("base_gravable") or 0
        costo = s.get("costo_estimado") or 0
        consolidado_tipo_jean.append({
            "tipo_jean": code,
            "tipo_jean_nombre": FIT_NAMES.get(code, code),
            "ordenes_count": p.get("ordenes_count") or 0,
            "prendas_planificadas": p.get("prendas_planificadas") or 0,
            "prendas_aptas": p.get("prendas_aptas") or 0,
            "prendas_marras": p.get("prendas_marras") or 0,
            "unidades_vendidas": s.get("unidades_vendidas") or 0,
            "ingresos_totales": s.get("ingresos_totales") or 0,
            "utilidad_bruta": base - costo,
        })

    # --- Indicadores Globales (KPIs) ---
    prod_totals = prod_qs.aggregate(
        total_ordenes=Count("orden_id"),
        prendas_planificadas=Sum("prendas_planificadas"),
        prendas_aptas=Sum("prendas_aptas"),
        prendas_marras=Sum("prendas_marras"),
    )
    sales_totals = sales_qs.aggregate(
        facturas_emitidas=Count("factura_id", distinct=True),
        unidades_vendidas=Sum("unidades"),
        ingresos_totales=Sum("total"),
        base_gravable=Sum("base_gravable"),
        costo_estimado=Sum("costo_estimado"),
    )
    recaudado_total = (
        sales_qs.filter(estado_cobro=sales_catalog.COLLECT_PAID).aggregate(val=Sum("total"))["val"] or 0
    )
    pendiente_cobro = (
        sales_qs.filter(estado_cobro=sales_catalog.COLLECT_PENDING).aggregate(val=Sum("total"))["val"] or 0
    )

    caja = SaldoFinanciero.objects.order_by("id").first()
    saldo_empresa = caja.saldo_actual if caja else 0

    aptas_tot = prod_totals["prendas_aptas"] or 0
    marras_tot = prod_totals["prendas_marras"] or 0
    inspeccionadas_tot = aptas_tot + marras_tot
    calidad_global = round((aptas_tot / inspeccionadas_tot) * 100, 1) if inspeccionadas_tot > 0 else 100.0

    base_tot = sales_totals["base_gravable"] or 0
    costo_tot = sales_totals["costo_estimado"] or 0
    devoluciones_por_vendedor = _returns_by_seller(filters)
    devoluciones_guias = sum(r["guias_devueltas"] for r in devoluciones_por_vendedor)
    flete_devoluciones_total = sum(r["flete_vendedor"] for r in devoluciones_por_vendedor)

    kpis = {
        "total_ordenes": prod_totals["total_ordenes"] or 0,
        "prendas_planificadas": prod_totals["prendas_planificadas"] or 0,
        "prendas_aptas": aptas_tot,
        "prendas_marras": marras_tot,
        "tasa_calidad_pct": calidad_global,
        "facturas_emitidas": sales_totals["facturas_emitidas"] or 0,
        "unidades_vendidas": sales_totals["unidades_vendidas"] or 0,
        "ingresos_totales": sales_totals["ingresos_totales"] or 0,
        "utilidad_bruta": base_tot - costo_tot,
        "recaudado_periodo": recaudado_total,
        "pendiente_recaudo_periodo": pendiente_cobro,
        "saldo_financiero_empresa": saldo_empresa,
        "devoluciones_guias": devoluciones_guias,
        "flete_devoluciones_total": flete_devoluciones_total,
    }

    return {
        "filtros_aplicados": {
            "desde": desde,
            "hasta": hasta,
            "tipo_jean": tipo_jean,
            "referencia": referencia_id,
            "estado_orden": estado_orden,
            "estado_cobro": estado_cobro,
            "tipo_cliente": tipo_cliente,
            "vendedor": vendedor_id,
            "transportadora": transportadora,
        },
        "kpis": kpis,
        "consolidado_tipo_jean": consolidado_tipo_jean,
        "ordenes_produccion": ordenes_rows,
        "ventas_por_referencia": ventas_por_referencia,
        "ventas_detalle": ventas_detalle,
        "devoluciones_por_vendedor": devoluciones_por_vendedor,
    }

