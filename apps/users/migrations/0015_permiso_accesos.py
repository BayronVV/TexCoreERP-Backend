"""
Permiso para consultar los accesos al sistema (HU 1.5): `seguridad.accesos`.

Solo el Administrador lo tiene (de forma implícita); se puede conceder a otro rol desde "Roles y permisos".
Los datos quedan congelados aquí a propósito.
"""
from django.db import migrations

CODE = "seguridad.accesos"
NAME = "Consultar los accesos al sistema (inicios de sesión, fallos y bloqueos)"


def seed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    ModulePermission.objects.get_or_create(code=CODE, defaults={"name": NAME, "module": "seguridad"})


def unseed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    ModulePermission.objects.filter(code=CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0014_bloqueo_por_intentos"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
