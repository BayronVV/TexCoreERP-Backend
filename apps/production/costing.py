"""
Motor de cálculo de costos de producción (HU 4.6 / RF16, TE-130).

Funciones puras y probadas por separado para costear una orden de producción:
- Costo de mano de obra = (segundos netos / 60) × tarifa por minuto. Redondeo a 2 decimales solo al final.
- Costo de materiales = cantidad × costo unitario (foto en OrdenLinea).
- Prorrateo de materiales: el material se descuenta por orden completa; a cada lote se le asigna en proporción a
  sus prendas (total_materiales × prendas_del_lote / prendas_de_la_orden).
- Consulta eficiente: tarifas en memoria con una sola consulta, sin N+1 sobre lotes ni líneas.
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from apps.inventory import catalog as inventory_catalog
from apps.production import catalog, tracking
from apps.production.models import TarifaManoObra

CENTS = Decimal("0.01")
RATE_DECIMALS = Decimal("0.0001")


def round_cents(value: Decimal) -> Decimal:
    """Redondea un importe en dinero a centavos con ROUND_HALF_UP."""
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def format_cents(value: Decimal) -> str:
    """Formatea dinero a texto con 2 decimales fijos."""
    return f"{round_cents(value):.2f}"


def format_rate(value: Decimal) -> str:
    """Formatea costos unitarios o tarifas a texto con 4 decimales fijos."""
    return f"{value.quantize(RATE_DECIMALS, rounding=ROUND_HALF_UP):.4f}"


def calculate_stage_cost(net_seconds: int, minute_rate: Decimal | None) -> tuple[Decimal, bool]:
    """Calcula el costo de mano de obra de una etapa a partir de sus segundos netos y tarifa por minuto.

    Retorna (costo_redondeado, sin_tarifa).
    Si no hay tarifa y los segundos netos son > 0, marca sin_tarifa=True y costo=0.00.
    Si segundos netos == 0, el costo es 0.00 y sin_tarifa=False (no penaliza etapas no iniciadas).
    """
    if net_seconds <= 0:
        return Decimal("0.00"), False

    if minute_rate is None:
        return Decimal("0.00"), True

    # (segundos / 60) * tarifa_minuto; redondeo solo al final
    exact = (Decimal(net_seconds) / Decimal(60)) * minute_rate
    return round_cents(exact), False


def calculate_material_line_cost(quantity: Decimal, unit_cost: Decimal | None) -> tuple[Decimal, bool]:
    """Calcula el costo de una línea de material: cantidad * costo_unitario.

    Retorna (costo_redondeado, sin_costo).
    Si unit_cost es None, marca sin_costo=True y costo=0.00.
    """
    if unit_cost is None:
        return Decimal("0.00"), True

    exact = quantity * unit_cost
    return round_cents(exact), False


def find_applicable_rate(stage_code: str, target_date: date, rates: list[TarifaManoObra]) -> TarifaManoObra | None:
    """Encuentra la tarifa vigente para una etapa en una fecha dada.

    Busca en una lista ordenada por etapa y -vigente_desde la primera tarifa con
    etapa == stage_code y vigente_desde <= target_date.
    """
    for rate in rates:
        if rate.etapa == stage_code and rate.vigente_desde <= target_date:
            return rate
    return None


def calculate_order_costs(order, rates: list[TarifaManoObra] | None = None, now: datetime | None = None) -> dict:
    """Calcula la liquidación financiera completa de una orden de producción.

    Devuelve la estructura exacta esperada por GET /api/produccion/ordenes/<id>/costos/.
    """
    if now is None:
        now = timezone.now()
    today = now.date()

    if rates is None:
        rates = list(TarifaManoObra.objects.filter(deleted_at__isnull=True).order_by("etapa", "-vigente_desde", "-id"))

    is_cancelled = order.orden_salida.estado == inventory_catalog.STATUS_CANCELLED

    # Estado de producción derivado
    if is_cancelled:
        estado_produccion = catalog.STATE_CANCELLED
    else:
        estado_produccion = tracking.order_state(
            tracking.lot_state([st.estado for st in lot.etapas.all()]) for lot in order.lotes.all()
        )

    orden_info = {
        "id": order.id,
        "codigo": order.codigo,
        "referencia_codigo": order.referencia.codigo,
        "referencia_nombre": order.referencia.nombre,
        "cantidad": order.cantidad,
        "estado_produccion": estado_produccion,
        "anulada": is_cancelled,
    }

    warnings: list[str] = []
    missing_stage_tariffs: set[str] = set()
    materials_without_cost_names: list[str] = []

    # 1. Materiales
    material_lines = []
    total_materials = Decimal("0.00")

    lines_queryset = order.orden_salida.lineas.all()
    for line in lines_queryset:
        qty = Decimal(str(line.cantidad))
        unit_cost = line.costo_unitario
        cost, sin_costo = calculate_material_line_cost(qty, unit_cost)

        if not is_cancelled:
            total_materials += cost

        if sin_costo:
            materials_without_cost_names.append(line.producto.nombre)

        material_lines.append({
            "producto": line.producto_id,
            "codigo": line.producto.codigo,
            "nombre": line.producto.nombre,
            "unidad": line.producto.unidad,
            "cantidad": str(line.cantidad),
            "costo_unitario": None if unit_cost is None else format_rate(unit_cost),
            "costo": "0.00" if is_cancelled else format_cents(cost),
            "sin_costo": sin_costo,
        })

    # 2. Mano de obra
    lots_summary = []
    stages_summary_map: dict[str, dict] = {
        stage_code: {"segundos_netos": 0, "costo": Decimal("0.00")}
        for stage_code, _ in catalog.STAGES
    }
    total_labor = Decimal("0.00")
    order_garments = Decimal(order.cantidad) if order.cantidad > 0 else Decimal(1)

    all_stages_complete_and_priced = True

    for lot in order.lotes.all():
        lot_garments = Decimal(lot.cantidad)
        if not is_cancelled and total_materials > 0:
            assigned_materials = round_cents(total_materials * lot_garments / order_garments)
        else:
            assigned_materials = Decimal("0.00")

        lot_stages = []
        lot_labor_total = Decimal("0.00")

        for stage in lot.etapas.all():
            net_secs = tracking.net_seconds(stage, now=now)
            target_date = stage.fin_at.date() if stage.fin_at else today
            applicable_rate = find_applicable_rate(stage.etapa, target_date, rates)

            rate_value = applicable_rate.costo_minuto if applicable_rate else None
            stage_cost, sin_tarifa = calculate_stage_cost(net_secs, rate_value)

            if sin_tarifa:
                missing_stage_tariffs.add(catalog.STAGE_NAMES.get(stage.etapa, stage.etapa))
                all_stages_complete_and_priced = False

            if not is_cancelled:
                lot_labor_total += stage_cost
                stages_summary_map[stage.etapa]["segundos_netos"] += net_secs
                stages_summary_map[stage.etapa]["costo"] += stage_cost

            is_provisional = stage.reanudada_at is not None or stage.estado == catalog.STAGE_RUNNING

            lot_stages.append({
                "etapa": stage.etapa,
                "etapa_nombre": catalog.STAGE_NAMES.get(stage.etapa, stage.etapa),
                "estado": stage.estado,
                "segundos_netos": net_secs,
                "tarifa_minuto": None if rate_value is None else format_rate(rate_value),
                "costo": "0.00" if is_cancelled else format_cents(stage_cost),
                "sin_tarifa": sin_tarifa,
                "provisional": is_provisional,
            })

        if not is_cancelled:
            total_labor += lot_labor_total

        lots_summary.append({
            "lote": lot.id,
            "codigo": lot.codigo,
            "cantidad": lot.cantidad,
            "materiales_asignados": format_cents(assigned_materials),
            "etapas": lot_stages,
            "total": "0.00" if is_cancelled else format_cents(lot_labor_total),
        })

    # Resumen por etapa
    by_stage = [
        {
            "etapa": stage_code,
            "etapa_nombre": catalog.STAGE_NAMES.get(stage_code, stage_code),
            "segundos_netos": stages_summary_map[stage_code]["segundos_netos"],
            "costo": "0.00" if is_cancelled else format_cents(stages_summary_map[stage_code]["costo"]),
        }
        for stage_code, _ in catalog.STAGES
    ]

    # Advertencias
    for stage_name in sorted(missing_stage_tariffs):
        warnings.append(f"Falta la tarifa de la etapa {stage_name}.")

    for mat_name in materials_without_cost_names:
        warnings.append(f"El material {mat_name} no tiene costo.")

    completo = (len(materials_without_cost_names) == 0) and all_stages_complete_and_priced

    # Totales y porcentajes
    if is_cancelled:
        total_materials = Decimal("0.00")
        total_labor = Decimal("0.00")

    grand_total = total_materials + total_labor
    cost_per_garment = round_cents(grand_total / order_garments) if order.cantidad > 0 else Decimal("0.00")

    if grand_total > 0:
        materials_pct = round_cents((total_materials / grand_total) * Decimal(100))
        labor_pct = round_cents((total_labor / grand_total) * Decimal(100))
    else:
        materials_pct = Decimal("0.00")
        labor_pct = Decimal("0.00")

    return {
        "orden": orden_info,
        "completo": completo,
        "advertencias": warnings,
        "materiales": {
            "lineas": material_lines,
            "total": format_cents(total_materials),
        },
        "mano_obra": {
            "por_lote": lots_summary,
            "por_etapa": by_stage,
            "total": format_cents(total_labor),
        },
        "totales": {
            "materiales": format_cents(total_materials),
            "mano_obra": format_cents(total_labor),
            "total": format_cents(grand_total),
            "costo_por_prenda": format_cents(cost_per_garment),
        },
        "distribucion": {
            "materiales_pct": f"{materials_pct:.2f}",
            "mano_obra_pct": f"{labor_pct:.2f}",
        },
    }
