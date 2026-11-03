"""Valores fijos del inventario de producto terminado (HU 6.2 / RF21), nombrados una sola vez."""

FINISHED_VIEW = "producto_terminado.ver"
FINISHED_MANAGE = "producto_terminado.gestionar"  # ingresa producto terminado (Secretaria y Administrador)

ENTRY_PREFIX = "IPT"  # no "PT": ese prefijo ya es el de los productos de la categoría Producto terminado del inventario

MAX_ENTRY_LINES = 100  # variantes (talla y color) distintas en un solo ingreso

# Tipo de movimiento del libro de producto terminado. Solo se agregan filas: una corrección es otro movimiento.
# Hoy solo existe la entrada por producción (HU 6.2); el ajuste manual (HU 6.3) y la salida por venta (HU 7.1) usan el mismo libro.
ENTRY_PRODUCTION = "ENTRADA_PRODUCCION"
ADJUSTMENT = "AJUSTE"
SALE_EXIT = "SALIDA_VENTA"
MOVEMENT_TYPES = [
    (ENTRY_PRODUCTION, "Entrada de producción"),
    (ADJUSTMENT, "Ajuste manual"),
    (SALE_EXIT, "Salida por venta"),
]
MOVEMENT_TYPE_NAMES = dict(MOVEMENT_TYPES)
