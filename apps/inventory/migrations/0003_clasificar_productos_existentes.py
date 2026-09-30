"""Da categoría a los productos que se crearon antes del catálogo (HU 2.2).

Hasta ahora un producto solo tenía tipo (materia prima, insumo, genérico, terminado).
La categoría es más fina, así que se deduce del tipo y, para materias primas e
insumos, de palabras del nombre. Lo que no encaja queda como "Otros insumos" o
"Telas"; se puede corregir desde el catálogo mientras el producto no tenga movimientos.
"""
from django.db import migrations

BY_TYPE = {"GENERICO": "PANTALON_GENERICO", "TERMINADO": "PRODUCTO_TERMINADO"}

SUPPLY_KEYWORDS = [
    ("CIERRE", ("cierre", "cremallera")),
    ("BOTON_REMACHE", ("boton", "botón", "remache")),
    ("ETIQUETA_EMPAQUE", ("etiqueta", "marquilla", "bolsa", "empaque", "gancho")),
    ("QUIMICO", ("quimic", "químic")),
]


def categoria_para(tipo, nombre):
    if tipo in BY_TYPE:
        return BY_TYPE[tipo]
    name = nombre.lower()
    if tipo == "MATERIA_PRIMA":
        return "HILO" if ("hilo" in name or "hilaza" in name) else "TELA"
    for categoria, words in SUPPLY_KEYWORDS:
        if any(word in name for word in words):
            return categoria
    return "OTRO_INSUMO"


def clasificar(apps, schema_editor):
    Producto = apps.get_model("inventory", "Producto")
    # El estado histórico usa el manager por defecto: incluye los eliminados lógicamente.
    for product in Producto._default_manager.filter(categoria=""):
        product.categoria = categoria_para(product.tipo, product.nombre)
        product.save(update_fields=["categoria"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_proveedores_y_catalogo"),
    ]

    operations = [
        migrations.RunPython(clasificar, migrations.RunPython.noop),
    ]
