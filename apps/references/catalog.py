"""Valores fijos del catálogo de referencias de jean (HU 3.1), nombrados una sola vez."""

REFERENCES_VIEW = "referencias.ver"
REFERENCES_MANAGE = "referencias.gestionar"

CODE_PREFIX = "REF"

# Estado de una referencia: nace en borrador, se activa cuando está completa y se descontinúa
# en lugar de borrarse (así el historial de producción y ventas sigue apuntando a ella).
DRAFT = "BORRADOR"
ACTIVE = "ACTIVA"
DISCONTINUED = "DESCONTINUADA"
STATES = [(DRAFT, "Borrador"), (ACTIVE, "Activa"), (DISCONTINUED, "Descontinuada")]
STATE_TRANSITIONS = {
    DRAFT: {ACTIVE},
    ACTIVE: {DISCONTINUED},
    DISCONTINUED: {ACTIVE},
}

# Tipo de ajuste (la silueta) del jean.
FITS = [
    ("SKINNY", "Skinny"),
    ("SLIM", "Slim"),
    ("RECTO", "Recto"),
    ("BOOTCUT", "Bootcut"),
    ("MOM", "Mom"),
    ("WIDE_LEG", "Wide leg"),
    ("JOGGER", "Jogger"),
    ("OTRO", "Otro"),
]

# Fotos del prototipo: se guardan en la base, igual que la imagen del catálogo de insumos.
MAX_IMAGES = 5
IMAGE_MAX_BYTES = 2 * 1024 * 1024
MAX_VARIANTS = 60  # tallas x colores por referencia

# --- Ficha técnica de consumo por unidad (HU 3.2) ---------------------------------------
FICHA_VIEW = "fichas_tecnicas.ver"
FICHA_MANAGE = "fichas_tecnicas.gestionar"

# Tipo de lavado que se pide en lavandería (la ficha lo deja como instrucción; puede quedar sin definir).
WASHES = [
    ("STONE_WASH", "Lavado a la piedra (stone wash)"),
    ("ENZIMATICO", "Lavado enzimático"),
    ("LEJIA", "Lejía"),
    ("OZONO", "Ozono (sustentable)"),
    ("LASER", "Láser (sustentable)"),
    ("OTRO", "Otro"),
]
MAX_FICHA_LINES = 50
MAX_CONSUMPTION = 1000  # por prenda; tela ≤ 5 m en la práctica, pero hay hilo en metros
MAX_WASTE = 50  # % de merma
MAX_GARMENTS = 100000  # prendas por simulación u orden
# PDF de la ficha técnica extensa (geometral, secuencia de confección, tabla de medidas...): se guarda en la base.
DOCUMENT_MAX_BYTES = 5 * 1024 * 1024
