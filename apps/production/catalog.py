"""Valores fijos de la planificación de producción (HU 4.1), nombrados una sola vez."""

PRODUCTION_VIEW = "produccion.ver"
PRODUCTION_MANAGE = "produccion.gestionar"  # crea y anula órdenes (HU 4.2) y controla los tiempos de los lotes (HU 4.3)

MAX_LOTS = 50  # lotes en los que se divide el total de una simulación

# --- Control de tiempos por etapa (HU 4.3 / RF13 y RF15) ---

# Etapas de producción por las que pasa cada lote, en orden. Una etapa solo empieza cuando la anterior terminó.
# Fuera de esta lista, a propósito: la lavandería (proceso externo, subcontratado: Procesos Externos, RF17 y RF18) y el
# control de calidad y el empaque (módulos propios: Control de Calidad, RF19 y RF20, y Producto Terminado).
STAGE_CUTTING = "CORTE"
STAGE_SEWING = "CONFECCION"
STAGE_FINISHING = "TERMINACION"
STAGES = [
    (STAGE_CUTTING, "Corte"),
    (STAGE_SEWING, "Confección"),
    (STAGE_FINISHING, "Terminación"),
]
STAGE_ORDER = [code for code, _ in STAGES]

# Estado de una etapa.
STAGE_PENDING = "PENDIENTE"
STAGE_RUNNING = "EN_PROCESO"
STAGE_PAUSED = "PAUSADA"
STAGE_DONE = "COMPLETADA"
STAGE_STATES = [
    (STAGE_PENDING, "Pendiente"),
    (STAGE_RUNNING, "En proceso"),
    (STAGE_PAUSED, "Pausada"),
    (STAGE_DONE, "Completada"),
]

# Acciones sobre un lote (los botones Play, Pausa y Stop) y cómo quedan registradas en el historial.
ACTION_START = "iniciar"
ACTION_PAUSE = "pausar"
ACTION_RESUME = "reanudar"
ACTION_COMPLETE = "completar"
ACTIONS = [ACTION_START, ACTION_PAUSE, ACTION_RESUME, ACTION_COMPLETE]
EVENT_ACTIONS = [
    (ACTION_START, "Inicio"),
    (ACTION_PAUSE, "Pausa"),
    (ACTION_RESUME, "Reanudación"),
    (ACTION_COMPLETE, "Fin"),
]

# Estado derivado de un lote y de una orden (RF15). No se guarda: sale de sus etapas y de la anulación de la orden.
STATE_PLANNED = "PLANEADA"
STATE_RUNNING = "EN_PROCESO"
STATE_PAUSED = "EN_PAUSA"
STATE_DONE = "TERMINADA"
STATE_CANCELLED = "CANCELADA"
STATES = [
    (STATE_PLANNED, "Planeada"),
    (STATE_RUNNING, "En proceso"),
    (STATE_PAUSED, "En pausa"),
    (STATE_DONE, "Terminada"),
    (STATE_CANCELLED, "Cancelada"),
]
STATE_NAMES = dict(STATES)
STAGE_NAMES = dict(STAGES)
STAGE_STATE_NAMES = dict(STAGE_STATES)

# --- Asignación de recursos (HU 4.4 / RF14): operarios y máquinas ---

OPERATOR_PREFIX = "OPE"
MACHINE_PREFIX = "MAQ"

# Cómo se le paga a un operario. Es solo informativo: la nómina no se maneja aquí.
PAY_PIECE = "PIEZA"
PAY_TIME = "TIEMPO"
PAY_SALARY = "SALARIO"
PAY_TYPES = [(PAY_PIECE, "Por pieza"), (PAY_TIME, "Por tiempo"), (PAY_SALARY, "Salario")]

# Tipos de máquina de una confección de jeans.
MACHINE_TYPES = [
    ("PLANA", "Plana de una aguja"),
    ("PLANA_DOBLE", "Plana de dos agujas"),
    ("FILETEADORA", "Fileteadora"),
    ("COLLARIN", "Collarín"),
    ("PRESILLADORA", "Presilladora"),
    ("OJALADORA", "Ojaladora"),
    ("BOTONADORA", "Botonadora"),
    ("REMACHADORA", "Remachadora"),
    ("CORTADORA", "Cortadora de tela"),
    ("OTRA", "Otra"),
]

# Estado de una máquina. «Ocupada» no se guarda: sale de las asignaciones abiertas de las etapas en curso.
MACHINE_AVAILABLE = "DISPONIBLE"
MACHINE_MAINTENANCE = "MANTENIMIENTO"
MACHINE_OUT = "FUERA_SERVICIO"
MACHINE_STATES = [
    (MACHINE_AVAILABLE, "Disponible"),
    (MACHINE_MAINTENANCE, "En mantenimiento"),
    (MACHINE_OUT, "Fuera de servicio"),
]

PAY_TYPE_NAMES = dict(PAY_TYPES)
MACHINE_TYPE_NAMES = dict(MACHINE_TYPES)
MACHINE_STATE_NAMES = dict(MACHINE_STATES)

# Qué recurso se quita al desvincular.
RESOURCE_OPERATOR = "operario"
RESOURCE_MACHINE = "maquina"
RESOURCE_BOTH = "ambos"
