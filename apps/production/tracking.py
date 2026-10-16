"""
Control de tiempos por etapa (HU 4.3 / RF13 y RF15): cada lote recorre sus etapas una tras otra y el sistema mide el tiempo
neto de cada una, sin contar las pausas.

- Las funciones puras (`lot_state`, `order_state`, `available_actions`, `net_seconds`) no tocan la base: se prueban solas.
- `act_on_lot` aplica una acción (iniciar, pausar, reanudar, completar) a la etapa en curso del lote. Bloquea el lote
  mientras actúa, así dos personas pulsando a la vez no se pisan, y deja la acción en el historial de la etapa.

Reglas: las etapas siguen el orden de `catalog.STAGES` y solo empieza una cuando la anterior terminó; un lote tiene una
sola etapa en curso a la vez; una orden anulada no admite acciones. El tiempo de una etapa es la suma de los intervalos
en que estuvo corriendo (cada pausa cierra uno y cada reanudación abre otro). El estado del lote y el de la orden no se
guardan: salen de sus etapas.
"""
from django.db import transaction
from django.utils import timezone

from apps.inventory import catalog as inventory_catalog
from apps.inventory.services import fail

from . import catalog
from .models import EtapaLote, EventoEtapa, Lote

# Qué estado de etapa admite cada acción y en cuál queda.
TRANSITIONS = {
    catalog.ACTION_START: ({catalog.STAGE_PENDING}, catalog.STAGE_RUNNING),
    catalog.ACTION_PAUSE: ({catalog.STAGE_RUNNING}, catalog.STAGE_PAUSED),
    catalog.ACTION_RESUME: ({catalog.STAGE_PAUSED}, catalog.STAGE_RUNNING),
    catalog.ACTION_COMPLETE: ({catalog.STAGE_RUNNING, catalog.STAGE_PAUSED}, catalog.STAGE_DONE),
}


# --- Funciones puras ----------------------------------------------------------------------------------------------

def net_seconds(stage, now=None):
    """Segundos netos de una etapa: los intervalos cerrados más el que está corriendo hasta `now`, si lo hay."""
    total = stage.acumulado_s
    if stage.reanudada_at is not None:
        total += max(0, int(((now or timezone.now()) - stage.reanudada_at).total_seconds()))
    return total


def lot_state(stage_states, cancelled=False):
    """Estado de un lote según el de sus etapas: planeada si ninguna empezó, en proceso si alguna corre o ya hay
    avance entre etapas, en pausa si la etapa en curso está pausada, terminada si todas terminaron.
    """
    if cancelled:
        return catalog.STATE_CANCELLED
    states = list(stage_states)
    if states and all(state == catalog.STAGE_DONE for state in states):
        return catalog.STATE_DONE
    if catalog.STAGE_RUNNING in states:
        return catalog.STATE_RUNNING
    if catalog.STAGE_PAUSED in states:
        return catalog.STATE_PAUSED
    if catalog.STAGE_DONE in states:
        return catalog.STATE_RUNNING  # entre una etapa y la siguiente: el lote ya está en producción
    return catalog.STATE_PLANNED


def order_state(lot_states):
    """Estado de una orden según el de sus lotes. Los lotes cancelados no cuentan; si todos lo están, la orden se cancela.
    Una orden está en proceso si algún lote corre (o hay avance sin terminar todo), en pausa si ninguno corre pero alguno
    está pausado, y terminada solo cuando todos los lotes terminaron.
    """
    states = list(lot_states)
    if not states:
        return catalog.STATE_PLANNED
    active = [state for state in states if state != catalog.STATE_CANCELLED]
    if not active:
        return catalog.STATE_CANCELLED
    if all(state == catalog.STATE_DONE for state in active):
        return catalog.STATE_DONE
    if catalog.STATE_RUNNING in active:
        return catalog.STATE_RUNNING
    if catalog.STATE_PAUSED in active:
        return catalog.STATE_PAUSED
    if catalog.STATE_DONE in active:
        return catalog.STATE_RUNNING  # unos lotes terminaron y otros todavía no empiezan
    return catalog.STATE_PLANNED


def current_stage(stages):
    """La etapa en curso (corriendo o pausada) o, si no hay, la siguiente pendiente. `None` si todas terminaron."""
    for stage in stages:
        if stage.estado in (catalog.STAGE_RUNNING, catalog.STAGE_PAUSED):
            return stage
    return next((stage for stage in stages if stage.estado == catalog.STAGE_PENDING), None)


def available_actions(stage_states, cancelled=False):
    """Acciones que el lote admite ahora (los botones habilitados). Ninguna si está cancelado o terminado."""
    if cancelled:
        return []
    states = list(stage_states)
    actions = []
    if catalog.STAGE_RUNNING not in states and catalog.STAGE_PAUSED not in states and catalog.STAGE_PENDING in states:
        actions.append(catalog.ACTION_START)
    if catalog.STAGE_RUNNING in states:
        actions.append(catalog.ACTION_PAUSE)
    if catalog.STAGE_PAUSED in states:
        actions.append(catalog.ACTION_RESUME)
    if catalog.STAGE_RUNNING in states or catalog.STAGE_PAUSED in states:
        actions.append(catalog.ACTION_COMPLETE)
    return actions


# --- Escritura ----------------------------------------------------------------------------------------------------

def create_stages(lots):
    """Crea las etapas (todas pendientes) de los lotes recién creados, con un solo INSERT."""
    EtapaLote.objects.bulk_create([
        EtapaLote(lote=lot, etapa=stage, secuencia=number, estado=catalog.STAGE_PENDING)
        for lot in lots
        for number, stage in enumerate(catalog.STAGE_ORDER, start=1)
    ])


@transaction.atomic
def act_on_lot(*, user, lot_id, action, note="", now=None):
    """Aplica `action` (iniciar, pausar, reanudar, completar) a la etapa en curso del lote y devuelve el lote.

    Iniciar arranca la siguiente etapa pendiente; pausar y completar actúan sobre la que corre (completar también sobre
    una pausada); reanudar vuelve a correr la pausada. Cualquier otra combinación responde 400 con el motivo.
    """
    if action not in catalog.ACTIONS:
        fail(f"La acción debe ser una de: {', '.join(catalog.ACTIONS)}.", "accion")
    lot = Lote.objects.select_for_update().filter(pk=lot_id).first()
    if lot is None:
        fail("El lote no existe.", "lote")
    order = lot.orden
    if order.orden_salida.estado == inventory_catalog.STATUS_CANCELLED:
        fail(f"La orden {order.codigo} está anulada: no se pueden registrar tiempos.", "orden")

    stages = list(lot.etapas.all())
    if not stages:  # lote anterior a la historia que se escapó del relleno de la migración
        create_stages([lot])
        stages = list(lot.etapas.all())
    states = [stage.estado for stage in stages]
    allowed, target = TRANSITIONS[action]
    stage = _stage_for(action, stages)
    if stage is None or stage.estado not in allowed:
        fail(_why_not(action, states), "accion")

    now = now or timezone.now()
    before = stage.estado
    if action == catalog.ACTION_START:
        stage.inicio_at, stage.reanudada_at, stage.responsable = now, now, user
    elif action == catalog.ACTION_RESUME:
        stage.reanudada_at = now
    else:  # pausar o completar: se cierra el intervalo que estaba corriendo
        if stage.reanudada_at is not None:
            stage.acumulado_s += max(0, int((now - stage.reanudada_at).total_seconds()))
        stage.reanudada_at = None
        if action == catalog.ACTION_COMPLETE:
            stage.fin_at = now
    stage.estado = target
    stage.save()
    EventoEtapa.objects.create(
        etapa_lote=stage, accion=action, de_estado=before, a_estado=target, usuario=user, momento=now,
        nota=note.strip()[:255],
    )
    return lot


def _stage_for(action, stages):
    """La etapa sobre la que actúa la acción: la siguiente pendiente al iniciar, la que está en curso en las demás."""
    if action == catalog.ACTION_START:
        if any(stage.estado in (catalog.STAGE_RUNNING, catalog.STAGE_PAUSED) for stage in stages):
            return None
        return next((stage for stage in stages if stage.estado == catalog.STAGE_PENDING), None)
    return next((stage for stage in stages if stage.estado in (catalog.STAGE_RUNNING, catalog.STAGE_PAUSED)), None)


def _why_not(action, states):
    """Motivo, en palabras de la persona, por el que la acción no se puede aplicar ahora."""
    if all(state == catalog.STAGE_DONE for state in states):
        return "Todas las etapas del lote ya terminaron."
    if action == catalog.ACTION_START:
        if catalog.STAGE_PAUSED in states:
            return "Hay una etapa en pausa: reanúdala o termínala antes de iniciar otra."
        return "Ya hay una etapa en proceso: termínala antes de iniciar otra."
    if action == catalog.ACTION_PAUSE:
        if catalog.STAGE_PAUSED in states:
            return "La etapa ya está en pausa."
        return "No hay una etapa en proceso para pausar."
    if action == catalog.ACTION_RESUME:
        if catalog.STAGE_RUNNING in states:
            return "La etapa ya está en proceso."
        return "No hay una etapa en pausa para reanudar."
    return "No hay una etapa en curso para terminar."
