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
