"""Valores fijos del inventario de producto terminado (HU 6.2 / RF21), nombrados una sola vez."""

FINISHED_VIEW = "producto_terminado.ver"
FINISHED_MANAGE = "producto_terminado.gestionar"  # ingresa producto terminado (Secretaria y Administrador)
FINISHED_ADJUST = "producto_terminado.ajustar"  # corrige descuadres del conteo físico (Secretaria y Administrador)

ENTRY_PREFIX = "IPT"  # no "PT": ese prefijo ya es el de los productos de la categoría Producto terminado del inventario

MAX_ENTRY_LINES = 100  # variantes (talla y color) distintas en un solo ingreso

# Tipo de movimiento del libro de producto terminado. Solo se agregan filas: una corrección es otro movimiento.
# La entrada por producción (HU 6.2) y el ajuste manual (HU 6.3) ya escriben en él; la salida por venta y su anulación (HU 7.1) también.
ENTRY_PRODUCTION = "ENTRADA_PRODUCCION"
ADJUSTMENT = "AJUSTE"
SALE_EXIT = "SALIDA_VENTA"
SALE_RETURN = "DEVOLUCION_VENTA"  # reingreso por anular una factura (HU 7.1)
MOVEMENT_TYPES = [
    (ENTRY_PRODUCTION, "Entrada de producción"),
    (ADJUSTMENT, "Ajuste manual"),
    (SALE_EXIT, "Salida por venta"),
    (SALE_RETURN, "Reingreso por anulación de venta"),
]
MOVEMENT_TYPE_NAMES = dict(MOVEMENT_TYPES)

# --- Ajuste manual (HU 6.3 / RF22) ---------------------------------------------------------------------------------
ADJUST_PREFIX = "AJT"
MAX_ADJUST_LINES = 200  # variantes distintas en un solo ajuste
MIN_OBSERVATION = 10  # caracteres de la observación, siempre obligatoria
LARGE_ADJUSTMENT = 20  # una línea que cambia MÁS de estas unidades exige más justificación (MSG-ERR-18)
MIN_OBSERVATION_LARGE = 30
OTHER = "OTRO"

# Motivos de un catálogo cerrado, con el signo que admiten: "-" solo resta, "+" solo suma, "+-" ambos.
ADJUST_REASONS = [
    ("ERROR_CONTEO", "Error de conteo", "+-"),
    ("MUESTRA_COMERCIAL", "Muestra comercial", "-"),
    ("PERDIDA", "Pérdida", "-"),
    ("PRENDA_DANADA", "Prenda dañada", "-"),
    ("SOBRANTE", "Sobrante o hallazgo", "+"),
    (OTHER, "Otro", "+-"),
]
ADJUST_REASON_CHOICES = [(code, name) for code, name, _ in ADJUST_REASONS]
ADJUST_REASON_NAMES = dict(ADJUST_REASON_CHOICES)
ADJUST_REASON_SIGNS = {code: sign for code, _, sign in ADJUST_REASONS}
