"""Valores fijos del módulo de inventario, nombrados una sola vez."""

INVENTORY_VIEW = "inventario.ver"
INVENTORY_MANAGE = "inventario.gestionar"

# Tipos de producto
RAW_MATERIAL = "MATERIA_PRIMA"  # tela, hilo
SUPPLY = "INSUMO"  # cierres, botones, etiquetas, remaches
GENERIC_PANTS = "GENERICO"  # pantalón sin lavar ni acabados, sale de producción
FINISHED_PANTS = "TERMINADO"  # jean de un modelo concreto, vuelve de lavandería

PRODUCT_TYPES = [
    (RAW_MATERIAL, "Materia prima"),
    (SUPPLY, "Insumo"),
    (GENERIC_PANTS, "Pantalón genérico"),
    (FINISHED_PANTS, "Producto terminado"),
]
PURCHASED_TYPES = {RAW_MATERIAL, SUPPLY}  # se compran: llevan proveedor y lote
MADE_TYPES = {GENERIC_PANTS, FINISHED_PANTS}  # se fabrican: entran desde una orden

UNITS = [
    ("m", "Metros"),
    ("kg", "Kilogramos"),
    ("rollo", "Rollos"),
    ("caja", "Cajas"),
    ("unidad", "Unidades"),
]
WHOLE_UNITS = {"rollo", "caja", "unidad"}  # no admiten decimales

# Movimientos
ENTRY = "INGRESO"
EXIT = "SALIDA"
MOVEMENT_TYPES = [(ENTRY, "Ingreso"), (EXIT, "Salida")]

REASON_PURCHASE = "COMPRA"
REASON_ORDER_RETURN = "RETORNO_ORDEN"
REASON_ORDER_EXIT = "SALIDA_ORDEN"
REASON_CANCELLATION = "ANULACION"
MOVEMENT_REASONS = [
    (REASON_PURCHASE, "Compra a proveedor"),
    (REASON_ORDER_RETURN, "Retorno de una orden"),
    (REASON_ORDER_EXIT, "Salida por orden"),
    (REASON_CANCELLATION, "Anulación de orden"),
]

# Órdenes de salida. CALIDAD (prefijo CC) queda pendiente de aprobación.
ORDER_PRODUCTION = "PRODUCCION"
ORDER_LAUNDRY = "LAVANDERIA"
ORDER_TYPES = [(ORDER_PRODUCTION, "Producción"), (ORDER_LAUNDRY, "Lavandería")]
ORDER_PREFIX = {ORDER_PRODUCTION: "OP", ORDER_LAUNDRY: "LV"}

STATUS_OPEN = "EN_PROCESO"
STATUS_DONE = "COMPLETADA"
STATUS_CANCELLED = "ANULADA"
ORDER_STATUSES = [
    (STATUS_OPEN, "En proceso"),
    (STATUS_DONE, "Completada"),
    (STATUS_CANCELLED, "Anulada"),
]

# Qué puede salir en cada tipo de orden y qué producto entra al terminar.
ORDER_RULES = {
    ORDER_PRODUCTION: {"input_types": PURCHASED_TYPES, "output_type": GENERIC_PANTS},
    ORDER_LAUNDRY: {"input_types": PURCHASED_TYPES | {GENERIC_PANTS}, "output_type": FINISHED_PANTS},
}

# Evidencias
EVIDENCE_MAX_BYTES = 5 * 1024 * 1024
EVIDENCE_MAX_PER_RECORD = 10
