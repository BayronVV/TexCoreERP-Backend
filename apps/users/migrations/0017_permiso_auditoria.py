"""
Permiso para consultar la auditoría de operaciones críticas (HU 1.5): `seguridad.auditoria`.

El Administrador lo tiene de forma implícita y el Gerente por esta migración. Después se ajusta desde
"Roles y permisos". Los datos quedan congelados aquí a propósito.
"""
from django.db import migrations

CODE = "seguridad.auditoria"
NAME = "Consultar la auditoría de operaciones críticas"
GRANTS = ["GERENTE"]


def seed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    Role = apps.get_model("users", "Role")
    RolePermission = apps.get_model("users", "RolePermission")
    perm, _ = ModulePermission.objects.get_or_create(code=CODE, defaults={"name": NAME, "module": "seguridad"})
    for role_code in GRANTS:
        role = Role.objects.filter(code=role_code).first()
        if role is not None:
            RolePermission.objects.get_or_create(role=role, permission=perm)


def unseed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    ModulePermission.objects.filter(code=CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0016_auditoria"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
