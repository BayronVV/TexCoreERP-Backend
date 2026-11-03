"""
Permiso `producto_terminado.ajustar` (HU 6.3 / RF22): corregir descuadres entre el conteo físico y el sistema.

Ajustar el inventario es más delicado que ingresar producción, así que tiene su propio permiso y se puede dar o quitar
desde "Roles y permisos" sin tocar el ingreso. Lo reciben la Secretaria y, de forma implícita, ADMIN; Gerente y Vendedor
solo consultan (`producto_terminado.ver`). Los datos quedan congelados aquí a propósito.
"""
from django.db import migrations

CODE = "producto_terminado.ajustar"
NAME = "Ajustar el inventario de producto terminado"
GRANTS = ["SECRETARIA"]


def seed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    Role = apps.get_model("users", "Role")
    RolePermission = apps.get_model("users", "RolePermission")
    permission, _ = ModulePermission.objects.get_or_create(code=CODE, defaults={"name": NAME, "module": "producto_terminado"})
    for role_code in GRANTS:
        role = Role.objects.filter(code=role_code).first()
        if role is not None:
            RolePermission.objects.get_or_create(role=role, permission=permission)


def unseed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    ModulePermission.objects.filter(code=CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0010_permisos_calidad_produccion"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
