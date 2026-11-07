"""
Servicios analíticos de reportes gerenciales.
Consulta las vistas SQL materializadas (`reportes_mv_produccion_ordenes` y `reportes_mv_ventas_referencias`)
para agrupar, sumar y formatear los indicadores solicitados por la gerencia sin sobrecargar las tablas transaccionales.
"""
from django.db import connection
from django.db.models import Count, Sum

from apps.inventory import catalog as inventory_catalog
from apps.references import catalog as reference_catalog
from apps.references.models import Referencia
from apps.sales import catalog as sales_catalog
from apps.sales.models import SaldoFinanciero

from .models import VistaProduccionOrden, VistaVentasReferencia

FIT_NAMES = dict(reference_catalog.FITS)
ORDER_STATE_NAMES = dict(inventory_catalog.ORDER_STATUSES)
COLLECT_STATE_NAMES = dict(sales_catalog.COLLECT_STATES)
CLIENT_TYPE_NAMES = dict(sales_catalog.CLIENT_TYPES)
INVOICE_STATE_NAMES = dict(sales_catalog.INVOICE_STATES)


def refresh_materialized_views():
    """
    Refresca las vistas SQL materializadas en PostgreSQL.
    En SQLite son vistas regulares que se evalúan al instante, por lo que no requieren refresco.
    """
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cursor:
        cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY reportes_mv_produccion_ordenes;")
        cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY reportes_mv_ventas_referencias;")
    return True


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
        "referencias": referencias,
    }


def build_management_report(params, auto_refresh=True):
    """
    Construye el reporte analítico consolidado aplicando los filtros avanzados:
    - `desde` / `hasta`: rango de fechas (AAAA-MM-DD)
    - `tipo_jean`: silueta / ajuste del jean (SKINNY, SLIM, RECTO, MOM, etc.)
    - `referencia`: ID de una referencia específica
    - `estado_orden`: estado de la orden de producción (EN_PROCESO, COMPLETADA, ANULADA)
    - `estado_cobro`: estado de cartera de las ventas (POR_COBRAR, PAGADO, DEVOLUCION)
    - `tipo_cliente`: tipo de cliente en ventas (DETAL, MAYORISTA, DISTRIBUIDOR)
    """
    if auto_refresh and connection.vendor == "postgresql":
        refresh_materialized_views()

    desde = (params.get("desde") or "").strip()
    hasta = (params.get("hasta") or "").strip()
    tipo_jean = (params.get("tipo_jean") or "").strip()
    referencia_id = (params.get("referencia") or "").strip()
    estado_orden = (params.get("estado_orden") or "").strip()
    estado_cobro = (params.get("estado_cobro") or "").strip()
    tipo_cliente = (params.get("tipo_cliente") or "").strip()

    # 1. Filtrado sobre la vista materializada de Producción
    prod_qs = VistaProduccionOrden.objects.all()
    if desde:
        prod_qs = prod_qs.filter(fecha_salida__gte=desde)
    if hasta:
        prod_qs = prod_qs.filter(fecha_salida__lte=hasta)
    if tipo_jean:
        prod_qs = prod_qs.filter(tipo_jean=tipo_jean)
    if referencia_id and referencia_id.isdigit():
        prod_qs = prod_qs.filter(referencia_id=int(referencia_id))
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
    if referencia_id and referencia_id.isdigit():
        sales_qs = sales_qs.filter(referencia_id=int(referencia_id))
    if estado_cobro:
        sales_qs = sales_qs.filter(estado_cobro=estado_cobro)
    if tipo_cliente:
        sales_qs = sales_qs.filter(cliente_tipo=tipo_cliente)

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
    }

    return {
        "filtros_aplicados": {
            "desde": desde,
            "hasta": hasta,
            "tipo_jean": tipo_jean,
            "referencia": int(referencia_id) if referencia_id.isdigit() else None,
            "estado_orden": estado_orden,
            "estado_cobro": estado_cobro,
            "tipo_cliente": tipo_cliente,
        },
        "kpis": kpis,
        "consolidado_tipo_jean": consolidado_tipo_jean,
        "ordenes_produccion": ordenes_rows,
        "ventas_por_referencia": ventas_por_referencia,
        "ventas_detalle": ventas_detalle,
    }

