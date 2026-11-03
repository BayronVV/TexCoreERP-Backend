"""
Permisos de calidad para el Jefe de Producción: `calidad.ver` y `calidad.gestionar` (HU 6.1 / RF19).

Los permisos del módulo ya existen desde la migración 0003 y el Personal de Terminación y el Gerente ya los tienen. RF19
también deja que el Jefe de Producción defina los criterios de calidad, así que se le conceden. ADMIN los tiene todos de
forma implícita. Después se ajustan desde "Roles y permisos". Los datos quedan congelados aquí a propósito.
"""
from django.db import migrations

GRANTS = {"PRODUCCION": ["calidad.ver", "calidad.gestionar"]}


def seed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    Role = apps.get_model("users", "Role")
    RolePermission = apps.get_model("users", "RolePermission")
    for role_code, codes in GRANTS.items():
        role = Role.objects.filter(code=role_code).first()
        if role is None:
            continue
        for code in codes:
            permission = ModulePermission.objects.filter(code=code).first()
            if permission is not None:
                RolePermission.objects.get_or_create(role=role, permission=permission)


def unseed(apps, schema_editor):
    Role = apps.get_model("users", "Role")
    RolePermission = apps.get_model("users", "RolePermission")
    for role_code, codes in GRANTS.items():
        RolePermission.objects.filter(role__code=role_code, permission__code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0009_acceso"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
