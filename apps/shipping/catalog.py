"""Catálogo de guías de envío y despachos (HU 7.2): estados, transiciones, permisos, plazos y rastreo con Track123."""
from apps.sales import catalog as sales_catalog

# --- Permisos ----------------------------------------------------------------------------------------------------------
SHIPPING_VIEW = "envios.ver"
SHIPPING_NOTE = "envios.anotar"  # anotar el número de guía de una factura (Vendedor, Almacenista, Secretaria)
SHIPPING_MANAGE = "envios.gestionar"  # asignar guías, armar relaciones, cambiar estados, flete y consultar el rastreo
SHIPPING_RETURN = "envios.devolucion"  # registrar en cartera la devolución física de un paquete

# --- Estados de la guía (el «verde, amarillo y rojo» de la empresa) -------------------------------------------------------
PENDING = "POR_DESPACHAR"
IN_TRANSIT = "EN_TRANSITO"
INCIDENT = "EN_NOVEDAD"
DELIVERED = "ENTREGADA"
RETURNED = "DEVUELTA"
VOIDED = "ANULADA"
GUIDE_STATES = [
    (PENDING, "Por despachar"),
    (IN_TRANSIT, "En tránsito"),
    (INCIDENT, "Con novedad"),
    (DELIVERED, "Entregada"),
    (RETURNED, "Devuelta"),
    (VOIDED, "Anulada"),
]
STATE_NAMES = dict(GUIDE_STATES)
# Semáforo para la pantalla: gris, azul, amarillo, verde, rojo.
STATE_COLORS = {PENDING: "gris", IN_TRANSIT: "azul", INCIDENT: "amarillo", DELIVERED: "verde", RETURNED: "rojo", VOIDED: "gris"}
FINAL_STATES = {DELIVERED, RETURNED, VOIDED}
DISPATCHED_STATES = {IN_TRANSIT, INCIDENT, DELIVERED, RETURNED}  # el paquete ya salió de la bodega

# Transiciones permitidas. Todo lo demás se rechaza.
TRANSITIONS = {
    PENDING: {IN_TRANSIT, VOIDED},
    IN_TRANSIT: {DELIVERED, INCIDENT, RETURNED},
    INCIDENT: {IN_TRANSIT, DELIVERED, RETURNED},
    DELIVERED: set(),
    RETURNED: set(),
    VOIDED: set(),
}
NOTE_REQUIRED = {INCIDENT, RETURNED}  # una novedad o una devolución siempre explican qué pasó
MIN_NOTE = 5

# --- Origen de un cambio de estado --------------------------------------------------------------------------------------
ORIGIN_MANUAL = "MANUAL"
ORIGIN_TRACK123 = "TRACK123"
ORIGIN_SYSTEM = "SISTEMA"
ORIGINS = [(ORIGIN_MANUAL, "Manual"), (ORIGIN_TRACK123, "Track123"), (ORIGIN_SYSTEM, "Sistema")]

# --- Transportadoras y número de guía -------------------------------------------------------------------------------------
CARRIERS = sales_catalog.CARRIERS
CARRIER_NAMES = sales_catalog.CARRIER_NAMES
MAX_GUIDE_LENGTH = 40
INTERRAPIDISIMO_FORMAT = r"^\d{12}$"  # las guías de referencia tienen 12 dígitos; solo advierte, no bloquea
DISPATCH_PREFIX = "RD"
MAX_DISPATCH_GUIDES = 100

# --- Plazo para anotar la guía (la empresa la genera antes de facturar; si falta, se persigue) ---------------------------------
ATTENTION_HOURS = 4  # desde aquí la factura sin guía pide atención
OVERDUE_HOURS = 24  # desde aquí está vencida

# --- Rastreo con Track123 ---------------------------------------------------------------------------------------------------
# Solo Interrapidísimo está verificado: la autodetección de Track123 falló en 2 de 3 guías reales, así que el código va explícito.
TRACKING_COURIERS = {"INTERRAPIDISIMO": "inter-rapidisimo-inter-rapidsimo"}
TRACKING_OK_CODE = "00000"
TRACKING_AUTH_CODES = {"B0001", "A0230", "A0231", "A0300", "A0301", "A0200", "A0201", "A0202", "A0203"}
TRACKING_RATE_CODES = {"A0706", "B0210"}
TRACKING_NOT_REGISTERED = "trackNo not registered"
TRACKING_ALREADY_REGISTERED_CODE = "A0400"

# transitStatus de Track123 → estado de nuestra guía. El «devuelto» no existe en Track123: viene dentro de ABNORMAL.
TRACK_DELIVERED = {"DELIVERED"}
TRACK_RETURNED_SUB = {"ABNORMAL_05", "ABNORMAL_06", "ABNORMAL_07"}  # el destinatario rechaza / lo recibió el remitente / va de regreso
TRACK_INCIDENT = {"DELIVERY_FAILED", "ABNORMAL"}
TRACK_INCIDENT_SUB = {"WAITING_DELIVERY_03"}  # entrega aplazada o con nota del mensajero
TRACK_IN_TRANSIT = {"INFO_RECEIVED", "IN_TRANSIT", "WAITING_DELIVERY"}
TRACK_NO_DATA = {"INIT", "NO_RECORD", "EXPIRED", ""}

TRACK_SUB_NAMES = {
    "DELIVERED_01": "Entregado", "DELIVERED_02": "Recogido por el destinatario", "DELIVERED_03": "Entregado con firma",
    "DELIVERED_04": "Entregado a un tercero", "IN_TRANSIT_01": "En camino", "IN_TRANSIT_02": "En centro de clasificación",
    "IN_TRANSIT_04": "Recogido por la transportadora", "IN_TRANSIT_07": "En la oficina de destino",
    "WAITING_DELIVERY_01": "En reparto", "WAITING_DELIVERY_02": "Listo para recoger en el punto",
    "WAITING_DELIVERY_03": "Entrega aplazada", "DELIVERY_FAILED_01": "Entrega fallida: problema con la dirección",
    "DELIVERY_FAILED_02": "Entrega fallida: nadie en casa", "DELIVERY_FAILED_03": "Entrega fallida: destinatario no localizado",
    "DELIVERY_FAILED_04": "Entrega fallida: otro motivo", "ABNORMAL_01": "Paquete sin reclamar", "ABNORMAL_02": "Retenido",
    "ABNORMAL_03": "Dañado, perdido o descartado", "ABNORMAL_04": "Pedido cancelado", "ABNORMAL_05": "El destinatario rechazó el paquete",
    "ABNORMAL_06": "Devolución recibida por el remitente", "ABNORMAL_07": "En camino de regreso al remitente", "ABNORMAL_08": "Otra novedad",
}
