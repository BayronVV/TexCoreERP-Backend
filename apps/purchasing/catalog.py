"""Valores fijos del módulo de compras (órdenes de compra y recepción de mercancía), nombrados una sola vez."""
from decimal import Decimal

PURCHASING_VIEW = "compras.ver"
PURCHASING_MANAGE = "compras.gestionar"  # crea, edita, cancela y cierra órdenes de compra (Jefe de Producción)
PURCHASING_APPROVE = "compras.aprobar"  # aprueba la orden (Gerente)
RECEIVE_PERMISSION = "inventario.gestionar"  # recibir la mercancía es un ingreso al almacén: solo el almacenista

ORDER_PREFIX = "OC"
RECEIPT_PREFIX = "RC"

# Estado de la orden de compra. Se guarda: cambia con la aprobación, cada recepción, la cancelación y el cierre manual.
DRAFT = "BORRADOR"
APPROVED = "APROBADA"
PARTIAL = "RECIBIDA_PARCIAL"
RECEIVED = "RECIBIDA"
CLOSED = "CERRADA"
CANCELLED = "CANCELADA"
ORDER_STATES = [
    (DRAFT, "Borrador"),
    (APPROVED, "Aprobada"),
    (PARTIAL, "Recibida parcial"),
    (RECEIVED, "Recibida"),
    (CLOSED, "Cerrada"),
    (CANCELLED, "Cancelada"),
]
ORDER_STATE_NAMES = dict(ORDER_STATES)

RECEIVABLE_STATES = {APPROVED, PARTIAL}  # solo se recibe contra una orden aprobada o con recepciones parciales
FINAL_STATES = {RECEIVED, CLOSED, CANCELLED}

# Cuánto más de lo pendiente se puede recibir de una línea (los proveedores a veces envían de más). Es fijo en el código.
OVERAGE_TOLERANCE = Decimal("0.05")
MAX_LINES = 100  # productos distintos en una orden o filas en una recepción
