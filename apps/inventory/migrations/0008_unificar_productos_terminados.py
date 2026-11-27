# Migración de datos TE-170 (HU 6.5): unifica inventario PT con Producto Terminado.
from django.db import migrations

from apps.inventory.finished_link import unify_existing_finished_products


def unify_finished_products(apps, schema_editor):
    Producto = apps.get_model("inventory", "Producto")
    Consecutivo = apps.get_model("inventory", "Consecutivo")
    Referencia = apps.get_model("references", "Referencia")
    Variante = apps.get_model("references", "Variante")
    unify_existing_finished_products(Producto, Consecutivo, Referencia, Variante)


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0007_producto_referencia_unificacion"),
        ("references", "0003_ficha_documento"),
    ]

    operations = [
        migrations.RunPython(unify_finished_products, migrations.RunPython.noop),
    ]
