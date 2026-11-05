"""Valores fijos de ventas y facturación (HU 7.1 / RF23), nombrados una sola vez."""

SALES_VIEW = "ventas.ver"
SALES_MANAGE = "ventas.gestionar"  # crea clientes y emite facturas (Vendedor y Administrador)
SALES_PRICES = "ventas.precios"  # administra precios y costo de fábrica (Gerente y Administrador)
SALES_CANCEL = "ventas.anular"  # anula facturas (Gerente y Administrador)

INVOICE_PREFIX = "FV"
CLIENT_PREFIX = "CLI"
MAX_INVOICE_LINES = 100  # variantes distintas en una sola factura
MIN_CANCEL_REASON = 10  # caracteres del motivo de anulación

# El comprobante es de TexCore, no una factura electrónica ante la DIAN (fuera del alcance del proyecto).
INVOICE_NOTICE = "Factura POS interna. No es factura electrónica."

# IVA general (porcentaje entero). Se guarda en cada factura, así que cambiarlo no toca las ya emitidas.
IVA_RATE = 19

# Tipos de cliente. `price_list` dice qué precio de la referencia se le aplica y `max_discount` el descuento máximo (%) que el
# vendedor puede darle. Aun dentro del tope, el precio con descuento nunca baja del costo de fábrica.
CLIENT_DETAL = "DETAL"
CLIENT_WHOLESALE = "MAYORISTA"
CLIENT_DISTRIBUTOR = "DISTRIBUIDOR"
CLIENT_TYPES = [(CLIENT_DETAL, "Detal"), (CLIENT_WHOLESALE, "Mayorista"), (CLIENT_DISTRIBUTOR, "Distribuidor")]
CLIENT_TYPE_NAMES = dict(CLIENT_TYPES)
PRICE_LIST = {CLIENT_DETAL: "detal", CLIENT_WHOLESALE: "mayorista", CLIENT_DISTRIBUTOR: "mayorista"}
MAX_DISCOUNT = {CLIENT_DETAL: 5, CLIENT_WHOLESALE: 15, CLIENT_DISTRIBUTOR: 20}

DOC_NIT = "NIT"
DOC_CC = "CC"
DOC_CE = "CE"
DOCUMENT_TYPES = [(DOC_NIT, "NIT"), (DOC_CC, "Cédula de ciudadanía"), (DOC_CE, "Cédula de extranjería")]

# Toda la venta es contraentrega: la transportadora recauda y gira después (RF25 / HU 7.3).
PAYMENT_COD = "CONTRAENTREGA"
PAYMENT_METHODS = [(PAYMENT_COD, "Contraentrega")]
COLLECT_PENDING = "POR_COBRAR"
COLLECT_STATES = [(COLLECT_PENDING, "Por cobrar")]

CARRIERS = [("INTERRAPIDISIMO", "Interrapidísimo"), ("ENVIA", "Envía"), ("OTRA", "Otra")]
CARRIER_NAMES = dict(CARRIERS)

STATUS_ISSUED = "EMITIDA"
STATUS_CANCELLED = "ANULADA"
INVOICE_STATES = [(STATUS_ISSUED, "Emitida"), (STATUS_CANCELLED, "Anulada")]
