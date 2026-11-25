"""Cálculo del costo de fábrica desde producción y trazabilidad de precios (HU 4.7 / TE-174).

Conecta producción (materiales y mano de obra de HU 4.6), lavandería (servicio de HU 5.2 / HU 5.4) y control de
calidad (prendas aptas de HU 6.1) con el piso de venta en Ventas (HU 7.1):

    costo_por_prenda = (materiales + mano_obra + servicio_lavanderia) / prendas_aptas

Sugiere el costo promedio ponderado por prendas aptas de las órdenes terminadas en los últimos 90 días con costos
completos, registra cada cambio en `HistorialPrecioReferencia` y nunca sobrescribe automáticamente un precio
ni altera facturas ya emitidas.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from apps.inventory import catalog as inventory_catalog
from apps.inventory.services import fail
from apps.production import catalog as production_catalog
from apps.production import costing, tracking
from apps.production.models import OrdenProduccion, TarifaManoObra

from . import catalog
from .models import HistorialPrecioReferencia, PrecioReferencia

ONE_PESO = Decimal("1")


def round_cop(amount: Decimal, units: int) -> int:
    """Redondea un valor en pesos sobre `units` prendas al peso entero más cercano (mitad hacia arriba)."""
    return int((amount / Decimal(units)).quantize(ONE_PESO, rounding=ROUND_HALF_UP))


def _laundry_for_lot(lot) -> tuple[Decimal | None, int]:
    """Devuelve (costo_servicio_lavado, prendas_conformes) de la recepción activa más reciente del lote."""
    receptions = list(lot.recepciones_lavado.all())
    if not receptions:
        return None, 0
    latest = max(receptions, key=lambda row: row.id)
    conforme = int(latest.cantidad_recibida_conforme or 0)
    rem_lote = latest.remision_lote
    tarifa = rem_lote.receta.tarifa_sugerida if rem_lote and rem_lote.receta else Decimal("0.00")
    return costing.round_cents(Decimal(conforme) * tarifa), conforme


def evaluate_order_factory_cost(order, rates, today, window_days: int = catalog.COST_WINDOW_DAYS) -> dict | None:
    """Evalúa una orden terminada para el cálculo del costo de fábrica, o devuelve `None` si no aplica."""
    if order.orden_salida.estado == inventory_catalog.STATUS_CANCELLED:
        return None

    lots = list(order.lotes.all())
    if not lots:
        return None

    lot_states = [
        tracking.lot_state([st.estado for st in lot.etapas.all()])
        for lot in lots
    ]
    if tracking.order_state(lot_states) != production_catalog.STATE_DONE:
        return None

    total_lavanderia = Decimal("0.00")
    total_aptas = 0
    closing_dates = []

    for lot in lots:
        service_cost, conforme = _laundry_for_lot(lot)
        if service_cost is None:
            return None
        total_lavanderia += service_cost

        inspections = list(lot.inspecciones.all())
        if conforme > 0 and not inspections:
            return None
        for ins in inspections:
            total_aptas += int(ins.aptas or 0)
            closing_dates.append(ins.fecha)

    if total_aptas <= 0:
        return None

    fecha_cierre = max(closing_dates) if closing_dates else order.orden_salida.fecha_salida
    if fecha_cierre < (today - timedelta(days=window_days)):
        return None

    summary = costing.calculate_order_costs(order, rates=rates)
    materiales = costing.round_cents(Decimal(summary["totales"]["materiales"]))
    mano_obra = costing.round_cents(Decimal(summary["totales"]["mano_obra"]))
    lavanderia = costing.round_cents(total_lavanderia)
    costo_total = costing.round_cents(materiales + mano_obra + lavanderia)

    faltantes: list[str] = list(summary["advertencias"])
    for lot_row in summary["mano_obra"]["por_lote"]:
        for stage_row in lot_row["etapas"]:
            if stage_row["tarifa_minuto"] is None:
                msg = f"Falta la tarifa de la etapa {stage_row['etapa_nombre']}."
                if msg not in faltantes:
                    faltantes.append(msg)

    completa = len(faltantes) == 0
    return {
        "orden_id": order.id,
        "codigo": order.codigo,
        "fecha_cierre": fecha_cierre.isoformat(),
        "prendas_aptas": total_aptas,
        "materiales": costing.format_cents(materiales),
        "mano_obra": costing.format_cents(mano_obra),
        "lavanderia": costing.format_cents(lavanderia),
        "costo_total": costing.format_cents(costo_total),
        "costo_por_prenda": round_cop(costo_total, total_aptas) if completa else None,
        "completa": completa,
        "faltantes": faltantes,
        "_costo_total_dec": costo_total,
    }


def calculate_references_costs(
    reference_ids: list[int],
    *,
    window_days: int = catalog.COST_WINDOW_DAYS,
    today=None,
) -> dict[int, dict]:
    """Calcula el costo sugerido desde producción por cada `referencia_id` sin consultas N+1."""
    if not reference_ids:
        return {}

    ref_date = today or timezone.localdate()
    rates = list(
        TarifaManoObra.objects.filter(deleted_at__isnull=True).order_by("etapa", "-vigente_desde", "-id")
    )
    orders_qs = (
        OrdenProduccion.objects.filter(referencia_id__in=reference_ids)
        .exclude(orden_salida__estado=inventory_catalog.STATUS_CANCELLED)
        .select_related("orden_salida", "referencia")
        .prefetch_related(
            "orden_salida__lineas__producto",
            "lotes__etapas",
            "lotes__recepciones_lavado__remision_lote__receta",
            "lotes__inspecciones",
        )
        .order_by("-id")
    )

    by_ref: dict[int, list[dict]] = {ref_id: [] for ref_id in reference_ids}
    for order in orders_qs:
        evaluated = evaluate_order_factory_cost(order, rates, ref_date, window_days=window_days)
        if evaluated is not None:
            by_ref.setdefault(order.referencia_id, []).append(evaluated)

    result: dict[int, dict] = {}
    for ref_id in reference_ids:
        orders = sorted(
            by_ref.get(ref_id, []),
            key=lambda row: (row["fecha_cierre"], row["orden_id"]),
            reverse=True,
        )
        complete = [o for o in orders if o["completa"]]
        incomplete = [o for o in orders if not o["completa"]]
        faltantes = [
            f"{o['codigo']}: {msg}"
            for o in incomplete
            for msg in o["faltantes"]
        ]

        if complete:
            total_cost = sum((o["_costo_total_dec"] for o in complete), Decimal("0.00"))
            total_aptas = sum(o["prendas_aptas"] for o in complete)
            costo_calculado = round_cop(total_cost, total_aptas)
            estado = catalog.CALC_STATUS_OK
        elif incomplete:
            total_aptas = sum(o["prendas_aptas"] for o in incomplete)
            costo_calculado = None
            estado = catalog.CALC_STATUS_INCOMPLETE
        else:
            total_aptas = 0
            costo_calculado = None
            estado = catalog.CALC_STATUS_NO_ORDERS

        clean_orders = [
            {k: v for k, v in o.items() if k != "_costo_total_dec"}
            for o in orders
        ]
        result[ref_id] = {
            "estado": estado,
            "costo_calculado": costo_calculado,
            "ventana_dias": window_days,
            "total_prendas_aptas": total_aptas,
            "ordenes_completas": len(complete),
            "ordenes_incompletas": len(incomplete),
            "faltantes": faltantes,
            "ordenes": clean_orders,
        }
    return result


def build_price_row(reference, price: PrecioReferencia | None, calc: dict | None = None) -> dict:
    """Arma la fila de precios para la API; agrega datos de producción solo cuando `calc` viene dado."""
    current_cost = price.costo_fabrica if price else None
    wholesale = price.precio_mayorista if price else None
    retail = price.precio_detal if price else None

    row = {
        "referencia": reference.id,
        "codigo": reference.codigo,
        "nombre": reference.nombre,
        "estado": reference.estado,
        "costo_fabrica": current_cost,
        "precio_detal": retail,
        "precio_mayorista": wholesale,
    }
    if calc is not None:
        calculated = calc["costo_calculado"]
        diff = (calculated - current_cost) if (calculated is not None and current_cost is not None) else None
        outdated = bool(calculated is not None and (current_cost is None or calculated > current_cost))
        below_cost = bool(calculated is not None and wholesale is not None and calculated > wholesale)
        row.update({
            "costo_calculado": calculated,
            "diferencia_costo": diff,
            "costo_desactualizado": outdated,
            "precio_bajo_costo": below_cost,
            "calculo_produccion": calc,
        })
    return row


@transaction.atomic
def save_reference_price(
    *,
    user,
    reference,
    costo_fabrica: int,
    precio_mayorista: int,
    precio_detal: int,
    origen: str = catalog.PRICE_SOURCE_MANUAL,
    ordenes_respaldo: list[str] | None = None,
    motivo: str = "",
) -> PrecioReferencia:
    """Guarda o actualiza el precio de una referencia y registra el cambio en el historial."""
    if costo_fabrica < 1:
        fail("El costo de fábrica debe ser mayor a cero.", "costo_fabrica")
    if precio_mayorista < costo_fabrica:
        fail("El precio mayorista no puede ser menor al costo de fábrica.", "precio_mayorista")
    if precio_detal < precio_mayorista:
        fail("El precio de detal no puede ser menor al mayorista.", "precio_detal")

    existing = PrecioReferencia.objects.select_for_update().filter(referencia=reference).first()
    old_cost = existing.costo_fabrica if existing else None
    old_wholesale = existing.precio_mayorista if existing else None
    old_retail = existing.precio_detal if existing else None

    price, created = PrecioReferencia.objects.update_or_create(
        referencia=reference,
        defaults={
            "costo_fabrica": costo_fabrica,
            "precio_mayorista": precio_mayorista,
            "precio_detal": precio_detal,
            "actualizado_por": user,
        },
    )

    changed = (
        created
        or old_cost != costo_fabrica
        or old_wholesale != precio_mayorista
        or old_retail != precio_detal
    )
    if changed:
        HistorialPrecioReferencia.objects.create(
            precio_referencia=price,
            costo_fabrica_anterior=old_cost,
            costo_fabrica_nuevo=costo_fabrica,
            precio_mayorista_anterior=old_wholesale,
            precio_mayorista_nuevo=precio_mayorista,
            precio_detal_anterior=old_retail,
            precio_detal_nuevo=precio_detal,
            origen=origen,
            ordenes_respaldo=list(ordenes_respaldo or []),
            motivo=str(motivo or "").strip()[:255],
            usuario=user,
        )
    return price


@transaction.atomic
def apply_calculated_cost(
    *,
    user,
    reference,
    precio_mayorista: int | None = None,
    precio_detal: int | None = None,
    motivo: str = "",
    window_days: int = catalog.COST_WINDOW_DAYS,
) -> tuple[PrecioReferencia, dict]:
    """Aplica el costo calculado de producción al piso de venta tras validar coherencia de precios."""
    calc = calculate_references_costs([reference.id], window_days=window_days)[reference.id]
    new_cost = calc["costo_calculado"]
    if new_cost is None:
        if calc["estado"] == catalog.CALC_STATUS_INCOMPLETE:
            fail(
                "No se puede aplicar el costo porque las órdenes tienen costos incompletos: "
                + " ".join(calc["faltantes"]),
                "costo_calculado",
            )
        fail(
            f"No hay órdenes terminadas con costos completos en los últimos {window_days} días para esta referencia.",
            "costo_calculado",
        )

    existing = PrecioReferencia.objects.select_for_update().filter(referencia=reference).first()
    target_mayorista = precio_mayorista if precio_mayorista is not None else (existing.precio_mayorista if existing else None)
    target_detal = precio_detal if precio_detal is not None else (existing.precio_detal if existing else None)

    if target_mayorista is None or target_detal is None:
        fail(
            "Debes definir el precio mayorista y el precio detal antes de aplicar el costo calculado.",
            "precio_mayorista",
        )

    if target_mayorista < new_cost:
        cost_txt = f"${new_cost:,}".replace(",", ".")
        wh_txt = f"${target_mayorista:,}".replace(",", ".")
        fail(
            f"El costo calculado ({cost_txt}) supera el precio mayorista vigente ({wh_txt}). "
            "Sube el precio mayorista antes de aplicar este costo.",
            "precio_mayorista",
        )
    if target_detal < target_mayorista:
        fail("El precio de detal no puede ser menor al mayorista.", "precio_detal")

    backing_orders = [o["codigo"] for o in calc["ordenes"] if o["completa"]]
    price = save_reference_price(
        user=user,
        reference=reference,
        costo_fabrica=new_cost,
        precio_mayorista=target_mayorista,
        precio_detal=target_detal,
        origen=catalog.PRICE_SOURCE_PRODUCTION,
        ordenes_respaldo=backing_orders,
        motivo=motivo or f"Costo calculado desde producción ({len(backing_orders)} orden/órdenes)",
    )
    return price, calc

