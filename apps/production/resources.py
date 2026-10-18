"""
Asignación de recursos (HU 4.4 / RF14): operarios y máquinas asignados a cada etapa de un lote.

- Catálogo: `create_operator`, `update_operator`, `create_machine` y `update_machine`. Nada se borra: un operario o una
  máquina con historial se desactiva.
- Asignación: `assign` pone, cambia o quita el operario y la máquina de una etapa; `unlink` quita uno o ambos. Cada etapa
  tiene como máximo una asignación abierta: cambiarla la cierra y abre otra, y terminar la etapa o anular la orden también
  la cierra, así queda el historial de quién trabajó y cuándo (`close_for_stage`, `close_for_order`).
- Reglas: se **bloquea** asignar un operario o una máquina inactivos o que no están habilitados para esa etapa, una máquina
  en mantenimiento o fuera de servicio, una etapa ya terminada o una orden anulada. Si el recurso ya está en otra etapa en
  curso solo se **avisa**: en un taller las máquinas se comparten por turnos y bloquear dejaría el trabajo fuera del sistema.
- «Ocupado» no se guarda: sale de las asignaciones abiertas de las etapas en curso (`busy_by_operator`, `busy_by_machine`).
"""
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from apps.inventory import catalog as inventory_catalog
from apps.inventory.services import fail, next_code

from . import catalog
from .models import AsignacionEtapa, Lote, Maquina, Operario

IN_COURSE = (catalog.STAGE_RUNNING, catalog.STAGE_PAUSED)


# --- Consultas ----------------------------------------------------------------------------------------------------

def open_assignments(prefix="etapas__"):
    """Prefetch de la asignación abierta de cada etapa, para leerla en `etapa.asignacion_abierta` sin una consulta por etapa."""
    queryset = AsignacionEtapa.objects.filter(fin_at__isnull=True).select_related("operario", "maquina")
    return Prefetch(f"{prefix}asignaciones", queryset=queryset, to_attr="asignacion_abierta")


def open_assignment_of(stage):
    """La asignación abierta de la etapa (o `None`), usando el prefetch si ya está cargado."""
    if hasattr(stage, "asignacion_abierta"):
        return stage.asignacion_abierta[0] if stage.asignacion_abierta else None
    return AsignacionEtapa.objects.filter(etapa_lote=stage, fin_at__isnull=True).select_related("operario", "maquina").first()


def _busy(field):
    """`{id del recurso: ["OP-0001-L01 · Corte", ...]}` de las etapas en curso que lo tienen asignado."""
    rows = AsignacionEtapa.objects.filter(
        fin_at__isnull=True, etapa_lote__estado__in=IN_COURSE, **{f"{field}__isnull": False}
    ).select_related("etapa_lote__lote").order_by("id")
    busy = {}
    for row in rows:
        stage = row.etapa_lote
        busy.setdefault(getattr(row, f"{field}_id"), []).append(f"{stage.lote.codigo} · {catalog.STAGE_NAMES[stage.etapa]}")
    return busy


def busy_by_operator():
    return _busy("operario")


def busy_by_machine():
    return _busy("maquina")


# --- Validación del catálogo --------------------------------------------------------------------------------------

def _clean_stages(value, label):
    """Lista de etapas válidas, sin repetir y en el orden del flujo. Debe haber al menos una."""
    if not isinstance(value, (list, tuple)) or not value:
        fail(f"Indica al menos una etapa {label}.", "etapas")
    unknown = [item for item in value if item not in catalog.STAGE_ORDER]
    if unknown:
        fail(f"Etapa no válida: {unknown[0]}. Usa {', '.join(catalog.STAGE_ORDER)}.", "etapas")
    return [stage for stage in catalog.STAGE_ORDER if stage in value]


def _unique_document(document, exclude_id=None):
    if not document:
        return
    clash = Operario.objects.filter(documento=document)
    if exclude_id:
        clash = clash.exclude(pk=exclude_id)
    if clash.exists():
        fail("Ya hay un operario con ese documento.", "documento")


def _still_assigned(label, name, reason, busy_in, assigned="asignado"):
    """Aviso de que un recurso que dejó de estar disponible sigue asignado a etapas en curso."""
    return [f"{label} {name} {reason} pero sigue {assigned} a {', '.join(busy_in)}."] if busy_in else []


def _is_id(value):
    return isinstance(value, int) and not isinstance(value, bool)


# --- Operarios ----------------------------------------------------------------------------------------------------

@transaction.atomic
def create_operator(*, data):
    """Crea un operario con su código OPE-0001. Devuelve el operario."""
    stages = _clean_stages(data["etapas"], "en la que puede trabajar")
    _unique_document(data.get("documento", ""))
    return Operario.objects.create(
        codigo=next_code(catalog.OPERATOR_PREFIX), nombres=data["nombres"], documento=data.get("documento", ""),
        etapas=stages, tipo_pago=data.get("tipo_pago", catalog.PAY_TIME), activo=data.get("activo", True),
    )


@transaction.atomic
def update_operator(operator, *, data):
    """Edita un operario. Devuelve `(operario, advertencias)`; desactivar uno que sigue en una etapa en curso avisa."""
    if "etapas" in data:
        data = {**data, "etapas": _clean_stages(data["etapas"], "en la que puede trabajar")}
    if "documento" in data:
        _unique_document(data["documento"], exclude_id=operator.pk)
    for field, value in data.items():
        setattr(operator, field, value)
    operator.save()
    warnings = []
    if data.get("activo") is False:
        warnings = _still_assigned("El operario", operator.nombres, "se desactivó", busy_by_operator().get(operator.pk, []))
    return operator, warnings


# --- Máquinas -----------------------------------------------------------------------------------------------------

@transaction.atomic
def create_machine(*, data):
    """Crea una máquina con su código MAQ-0001. Devuelve la máquina."""
    stages = _clean_stages(data["etapas"], "en la que se usa")
    return Maquina.objects.create(
        codigo=next_code(catalog.MACHINE_PREFIX), tipo=data["tipo"], marca_modelo=data.get("marca_modelo", ""),
        serial=data.get("serial", ""), ubicacion=data.get("ubicacion", ""),
        estado=data.get("estado", catalog.MACHINE_AVAILABLE), etapas=stages,
        observaciones=data.get("observaciones", ""), activo=data.get("activo", True),
    )


@transaction.atomic
def update_machine(machine, *, data):
    """Edita una máquina. Devuelve `(máquina, advertencias)`; pasarla a mantenimiento, dejarla fuera de servicio o
    desactivarla mientras está en una etapa en curso avisa, pero no cierra nada por su cuenta.
    """
    if "etapas" in data:
        data = {**data, "etapas": _clean_stages(data["etapas"], "en la que se usa")}
    for field, value in data.items():
        setattr(machine, field, value)
    machine.save()
    warnings = []
    unavailable = data.get("estado", catalog.MACHINE_AVAILABLE) != catalog.MACHINE_AVAILABLE or data.get("activo") is False
    if unavailable:
        warnings = _still_assigned("La máquina", machine.codigo, "ya no está disponible", busy_by_machine().get(machine.pk, []), "asignada")
    return machine, warnings


# --- Asignación a las etapas --------------------------------------------------------------------------------------

def close_for_stage(stage, now=None):
    """Cierra la asignación abierta de la etapa (al terminarla)."""
    now = now or timezone.now()
    AsignacionEtapa.objects.filter(etapa_lote=stage, fin_at__isnull=True).update(fin_at=now, updated_at=now)


def close_for_order(order, now=None):
    """Cierra las asignaciones abiertas de todos los lotes de la orden (al anularla)."""
    now = now or timezone.now()
    AsignacionEtapa.objects.filter(etapa_lote__lote__orden=order, fin_at__isnull=True).update(fin_at=now, updated_at=now)


def _resolve_operator(operator_id, stage_code):
    operator = Operario.objects.filter(pk=operator_id).first() if _is_id(operator_id) else None
    if operator is None:
        fail("El operario no existe.", "operario")
    if not operator.activo:
        fail(f"El operario {operator.nombres} está inactivo.", "operario")
    if stage_code not in operator.etapas:
        fail(f"El operario {operator.nombres} no está habilitado para {catalog.STAGE_NAMES[stage_code]}.", "operario")
    return operator


def _resolve_machine(machine_id, stage_code):
    machine = Maquina.objects.filter(pk=machine_id).first() if _is_id(machine_id) else None
    if machine is None:
        fail("La máquina no existe.", "maquina")
    if not machine.activo:
        fail(f"La máquina {machine.codigo} está inactiva.", "maquina")
    if machine.estado != catalog.MACHINE_AVAILABLE:
        fail(f"La máquina {machine.codigo} está {catalog.MACHINE_STATE_NAMES[machine.estado].lower()}.", "maquina")
    if stage_code not in machine.etapas:
        fail(f"La máquina {machine.codigo} no se usa en {catalog.STAGE_NAMES[stage_code]}.", "maquina")
    return machine


def _busy_warnings(operator, machine, stage):
    """Avisos de que el operario o la máquina ya están en otra etapa en curso (no bloquean)."""
    warnings = []
    for resource, label, name, field, assigned in (
        (operator, "El operario", getattr(operator, "nombres", ""), "operario", "asignado"),
        (machine, "La máquina", getattr(machine, "codigo", ""), "maquina", "asignada"),
    ):
        if resource is None:
            continue
        others = AsignacionEtapa.objects.filter(
            fin_at__isnull=True, etapa_lote__estado__in=IN_COURSE, **{field: resource}
        ).exclude(etapa_lote=stage).select_related("etapa_lote__lote")
        places = [f"{row.etapa_lote.lote.codigo} ({catalog.STAGE_NAMES[row.etapa_lote.etapa]})" for row in others]
        if places:
            warnings.append(f"{label} {name} ya está {assigned} a {', '.join(places)}.")
    return warnings


@transaction.atomic
def assign(*, user, lot_id, stage_code, changes, now=None):
    """Pone, cambia o quita el operario y la máquina de una etapa del lote. `changes` trae las claves `operario` y/o
    `maquina` (un id, o `None` para quitarlo); la que no viene se deja como está. Devuelve `(lote, advertencias)`.
    """
    lot = Lote.objects.select_for_update().filter(pk=lot_id).first()
    if lot is None:
        fail("El lote no existe.", "lote")
    order = lot.orden
    if order.orden_salida.estado == inventory_catalog.STATUS_CANCELLED:
        fail(f"La orden {order.codigo} está anulada: no se pueden asignar recursos.", "orden")
    if stage_code not in catalog.STAGE_ORDER:
        fail(f"La etapa debe ser una de: {', '.join(catalog.STAGE_ORDER)}.", "etapa")
    stage = lot.etapas.filter(etapa=stage_code).first()
    if stage is None:
        fail("El lote no tiene esa etapa.", "etapa")
    if stage.estado == catalog.STAGE_DONE:
        fail(f"La etapa {catalog.STAGE_NAMES[stage_code]} ya terminó: no se puede cambiar su asignación.", "etapa")

    current = AsignacionEtapa.objects.filter(etapa_lote=stage, fin_at__isnull=True).first()
    current_operator = current.operario_id if current else None
    current_machine = current.maquina_id if current else None
    operator_id = changes.get("operario", current_operator)
    machine_id = changes.get("maquina", current_machine)
    if (current_operator, current_machine) == (operator_id, machine_id):
        return lot, []  # nada que cambiar

    operator = _resolve_operator(operator_id, stage_code) if operator_id is not None else None
    machine = _resolve_machine(machine_id, stage_code) if machine_id is not None else None
    now = now or timezone.now()
    if current:
        current.fin_at = now
        current.save(update_fields=["fin_at", "updated_at"])
    if operator is None and machine is None:
        return lot, []  # se quitó todo: la etapa queda sin asignación
    AsignacionEtapa.objects.create(
        etapa_lote=stage, operario=operator, maquina=machine, inicio_at=now, asignada_por=user
    )
    return lot, _busy_warnings(operator, machine, stage)


def unlink(*, user, lot_id, stage_code, resource, now=None):
    """Quita de la etapa el operario, la máquina o ambos. Devuelve `(lote, advertencias)`."""
    if resource == catalog.RESOURCE_OPERATOR:
        changes = {"operario": None}
    elif resource == catalog.RESOURCE_MACHINE:
        changes = {"maquina": None}
    elif resource == catalog.RESOURCE_BOTH:
        changes = {"operario": None, "maquina": None}
    else:
        fail(f"El recurso debe ser uno de: {catalog.RESOURCE_OPERATOR}, {catalog.RESOURCE_MACHINE}, {catalog.RESOURCE_BOTH}.", "recurso")
    return assign(user=user, lot_id=lot_id, stage_code=stage_code, changes=changes, now=now)
