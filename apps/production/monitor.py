"""
Monitor de estado (HU 4.5 / RF15): los lotes en producción agrupados en las columnas Planeada, En proceso, En pausa y Terminada.

El estado de un lote no se guarda: sale de sus etapas (`tracking.lot_state`). Para que el tablero sea rápido aunque haya muchos
lotes, la consulta separa dos grupos:

- **Lotes activos** (alguna etapa sin terminar): pocos por naturaleza. Se cargan con sus etapas en dos consultas y se
  clasifican en Python con la misma función que usa el resto del sistema, así el tablero nunca discrepa de la pantalla de
  seguimiento.
- **Lotes terminados** (todas sus etapas terminadas): crecen sin límite con el tiempo. No se cargan todos: solo los que
  terminaron en los últimos `done_days` días, se cuentan en la base y se traen como máximo `limit`.

Los lotes de órdenes anuladas no aparecen, salvo que se pidan (`include_cancelled`): entonces salen en una columna aparte, al
final, sin acciones. Cada columna devuelve su total real y, como máximo, `limit` tarjetas.

**Alertas** (valores orientativos, ajustables aquí): un lote *detenido* (en pausa, o entre dos etapas sin iniciar la siguiente)
pide atención a las 2 horas sin movimiento y es crítico a las 8, que es más o menos una jornada de trabajo.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.db.models import Exists, OuterRef, Subquery
from django.utils import timezone

from apps.inventory import catalog as inventory_catalog

from . import catalog, tracking
from .models import EtapaLote, EventoEtapa, Lote

COLUMNS = [catalog.STATE_PLANNED, catalog.STATE_RUNNING, catalog.STATE_PAUSED, catalog.STATE_DONE]
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
DEFAULT_DONE_DAYS = 7  # la columna Terminada solo muestra lo reciente
MAX_DONE_DAYS = 90

ALERT_NONE = None
ALERT_ATTENTION = "ATENCION"
ALERT_CRITICAL = "CRITICA"
ATTENTION_AFTER_S = 2 * 3600
CRITICAL_AFTER_S = 8 * 3600
_EPOCH = datetime.min.replace(tzinfo=dt_timezone.utc)


def stalled_seconds(state, stage_states, last_movement, now):
    """Segundos que lleva detenido un lote, o `None` si no está detenido: en pausa, o en proceso sin ninguna etapa corriendo
    (terminó una etapa y falta iniciar la siguiente). Se cuenta desde su último movimiento.
    """
    stalled = state == catalog.STATE_PAUSED or (state == catalog.STATE_RUNNING and catalog.STAGE_RUNNING not in stage_states)
    if not stalled or last_movement is None:
        return None
    return max(0, int((now - last_movement).total_seconds()))


def alert_level(seconds):
    """Nivel de alerta de un lote detenido `seconds` segundos: ninguno, atención (desde 2 h) o crítica (desde 8 h)."""
    if seconds is None or seconds < ATTENTION_AFTER_S:
        return ALERT_NONE
    return ALERT_CRITICAL if seconds >= CRITICAL_AFTER_S else ALERT_ATTENTION


def _base(order_id=None, reference_id=None, cancelled=False):
    """Lotes vivos de órdenes no anuladas (o solo de las anuladas), con lo que necesita una tarjeta y su último movimiento."""
    last_event = EventoEtapa.objects.filter(etapa_lote__lote=OuterRef("pk")).order_by("-momento", "-id").values("momento")[:1]
    lots = Lote.objects.filter(orden__deleted_at__isnull=True)
    if cancelled:
        lots = lots.filter(orden__orden_salida__estado=inventory_catalog.STATUS_CANCELLED)
    else:
        lots = lots.exclude(orden__orden_salida__estado=inventory_catalog.STATUS_CANCELLED)
    lots = lots.select_related("orden__orden_salida", "orden__referencia").annotate(ultimo_movimiento=Subquery(last_event))
    if order_id is not None:
        lots = lots.filter(orden_id=order_id)
    if reference_id is not None:
        lots = lots.filter(orden__referencia_id=reference_id)
    return lots


def _sort_key(state):
    """Orden de las tarjetas de una columna: lo que más espera, primero."""
    def waiting_since(lot):
        return lot.ultimo_movimiento or lot.orden.created_at or _EPOCH

    if state == catalog.STATE_PLANNED:
        return lambda lot: (lot.orden.created_at.timestamp() if lot.orden.created_at else 0, lot.orden_id, lot.numero)
    return lambda lot: (waiting_since(lot).timestamp(), lot.id)


def build_board(*, limit=DEFAULT_LIMIT, order_id=None, reference_id=None, done_days=DEFAULT_DONE_DAYS,
                include_cancelled=False, now=None):
    """Las columnas del tablero: `{estado, nombre, total, lotes}` con a lo sumo `limit` lotes cada una (más la de canceladas,
    si se pide) y el resumen de alertas de todos los lotes activos.

    Los lotes llevan precargadas sus etapas (`lot.etapas.all()`) y el atributo `ultimo_movimiento`, listos para serializar.
    """
    now = now or timezone.now()
    has_open = Exists(EtapaLote.objects.filter(lote=OuterRef("pk")).exclude(estado=catalog.STAGE_DONE))
    has_any = Exists(EtapaLote.objects.filter(lote=OuterRef("pk")))
    prefetch = ("etapas__responsable",)

    active = list(_base(order_id, reference_id).filter(has_open | ~has_any).prefetch_related(*prefetch))
    done = _base(order_id, reference_id).filter(
        has_any, ~has_open, ultimo_movimiento__gte=now - timedelta(days=done_days)
    )
    done_total = done.count()
    done_cards = list(done.order_by("-ultimo_movimiento", "-id").prefetch_related(*prefetch)[:limit])

    grouped = {state: [] for state in COLUMNS}
    alerts = {"atencion": 0, "critica": 0}
    for lot in active:
        stage_states = [stage.estado for stage in lot.etapas.all()]
        state = tracking.lot_state(stage_states)
        grouped[state].append(lot)
        level = alert_level(stalled_seconds(state, stage_states, lot.ultimo_movimiento, now))
        if level == ALERT_ATTENTION:
            alerts["atencion"] += 1
        elif level == ALERT_CRITICAL:
            alerts["critica"] += 1
    grouped[catalog.STATE_DONE] = done_cards

    columns = []
    for state in COLUMNS:
        lots = grouped[state]
        total = done_total if state == catalog.STATE_DONE else len(lots)
        if state != catalog.STATE_DONE:
            lots = sorted(lots, key=_sort_key(state))
        columns.append({"estado": state, "nombre": catalog.STATE_NAMES[state], "total": total, "lotes": lots[:limit]})

    if include_cancelled:
        cancelled = _base(order_id, reference_id, cancelled=True)
        cards = cancelled.order_by("-orden__orden_salida__anulada_at", "-id").prefetch_related(*prefetch)[:limit]
        columns.append({
            "estado": catalog.STATE_CANCELLED, "nombre": catalog.STATE_NAMES[catalog.STATE_CANCELLED],
            "total": cancelled.count(), "lotes": list(cards),
        })
    return {"generado_at": now, "limite": limit, "terminadas_dias": done_days, "alertas": alerts, "columnas": columns}
