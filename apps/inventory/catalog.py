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
    ("l", "Litros"),
    ("rollo", "Rollos"),
    ("caja", "Cajas"),
    ("unidad", "Unidades"),
]
WHOLE_UNITS = {"rollo", "caja", "unidad"}  # no admiten decimales

# Categorías del catálogo. Cada una fija el tipo de producto (que gobierna las reglas
# de movimientos), las unidades de medida compatibles (MSG-ERR-08) y qué datos textiles
# son obligatorios. `prefix` es el de los códigos automáticos (TEL-0001).
CAT_FABRIC = "TELA"
CAT_THREAD = "HILO"
CAT_ZIPPER = "CIERRE"
CAT_BUTTON = "BOTON_REMACHE"
CAT_LABEL = "ETIQUETA_EMPAQUE"
CAT_CHEMICAL = "QUIMICO"
CAT_OTHER = "OTRO_INSUMO"
CAT_GENERIC = "PANTALON_GENERICO"
CAT_FINISHED = "PRODUCTO_TERMINADO"

CATEGORIES = {
    CAT_FABRIC: {"label": "Telas y tejidos denim", "tipo": RAW_MATERIAL, "prefix": "TEL", "units": ["m", "rollo"]},
    CAT_THREAD: {"label": "Hilos e hilazas de confección", "tipo": RAW_MATERIAL, "prefix": "HIL", "units": ["kg", "unidad"]},
    CAT_ZIPPER: {"label": "Cremalleras y cierres", "tipo": SUPPLY, "prefix": "CIE", "units": ["unidad", "caja"]},
    CAT_BUTTON: {"label": "Botones metálicos y remaches", "tipo": SUPPLY, "prefix": "BOT", "units": ["unidad", "caja"]},
    CAT_LABEL: {"label": "Etiquetas, marquillas y empaque", "tipo": SUPPLY, "prefix": "ETQ", "units": ["unidad", "caja"]},
    CAT_CHEMICAL: {"label": "Químicos de lavandería", "tipo": SUPPLY, "prefix": "QUI", "units": ["kg", "l"]},
    CAT_OTHER: {"label": "Otros insumos", "tipo": SUPPLY, "prefix": "INS", "units": [u for u, _ in UNITS]},
    CAT_GENERIC: {"label": "Pantalón genérico (en crudo)", "tipo": GENERIC_PANTS, "prefix": "PG", "units": ["unidad"]},
    CAT_FINISHED: {"label": "Producto terminado", "tipo": FINISHED_PANTS, "prefix": "PT", "units": ["unidad"]},
}
CATEGORY_CHOICES = [(code, data["label"]) for code, data in CATEGORIES.items()]
# Las que se compran a un proveedor: las de su clasificación (RF04).
PURCHASABLE_CATEGORIES = [c for c, d in CATEGORIES.items() if d["tipo"] in PURCHASED_TYPES]
SUPPLIER_CATEGORY_CHOICES = [(c, CATEGORIES[c]["label"]) for c in PURCHASABLE_CATEGORIES]
# Tela e hilo se describen con su composición (100% algodón, 80% algodón / 20% nylon...).
COMPOSITION_REQUIRED = {CAT_FABRIC, CAT_THREAD}
WIDTH_REQUIRED = {CAT_FABRIC}  # ancho útil del rollo en metros (corte computarizado)
MAX_FABRIC_WIDTH = 5  # metros

# Imagen de referencia del catálogo (se guarda en la base para que no dependa del disco)
IMAGE_MAX_BYTES = 2 * 1024 * 1024

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
