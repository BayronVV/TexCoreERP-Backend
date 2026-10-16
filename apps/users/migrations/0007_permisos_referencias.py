"""
Permisos del catálogo de referencias de jean (HU 3.1): `referencias.ver` y `referencias.gestionar`.

Quién gestiona el catálogo: el Jefe de Producción (diseña y fabrica las referencias). Lo consultan
el Gerente, el Almacenista y el Vendedor. ADMIN los tiene todos de forma implícita. Después se
ajustan desde "Roles y permisos". Los datos quedan congelados aquí a propósito.
"""
from django.db import migrations

PERMISSIONS = [
    ("referencias.ver", "Ver Referencias de Jean"),
    ("referencias.gestionar", "Registrar y modificar en Referencias de Jean"),
]
GRANTS = {
    "PRODUCCION": ["referencias.ver", "referencias.gestionar"],
    "GERENTE": ["referencias.ver"],
    "ALMACENISTA": ["referencias.ver"],
    "VENDEDOR": ["referencias.ver"],
}


def seed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    Role = apps.get_model("users", "Role")
    RolePermission = apps.get_model("users", "RolePermission")
    perms = {}
    for code, name in PERMISSIONS:
        perms[code], _ = ModulePermission.objects.get_or_create(
            code=code, defaults={"name": name, "module": "referencias"}
        )
    for role_code, codes in GRANTS.items():
        role = Role.objects.filter(code=role_code).first()
        if role is None:
            continue
        for code in codes:
            RolePermission.objects.get_or_create(role=role, permission=perms[code])


def unseed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    ModulePermission.objects.filter(code__in=[code for code, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0006_rls_tablas_publicas"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
