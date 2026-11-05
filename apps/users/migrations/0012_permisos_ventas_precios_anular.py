"""
Permisos `ventas.precios` y `ventas.anular` (HU 7.1 / RF23).

`ventas.ver` y `ventas.gestionar` ya existen desde la migración 0003 (el Vendedor emite facturas y registra clientes; el Gerente
solo consulta). Administrar los precios y el costo de fábrica, y anular una factura, son decisiones más delicadas y quedan para
el Gerente; ADMIN los tiene todos de forma implícita. Después se ajustan desde "Roles y permisos". Los datos quedan congelados aquí
a propósito.
"""
from django.db import migrations

PERMISSIONS = [
    ("ventas.precios", "Administrar precios y costo de fábrica"),
    ("ventas.anular", "Anular facturas de venta"),
]
GRANTS = {"GERENTE": ["ventas.precios", "ventas.anular"]}


def seed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    Role = apps.get_model("users", "Role")
    RolePermission = apps.get_model("users", "RolePermission")
    perms = {}
    for code, name in PERMISSIONS:
        perms[code], _ = ModulePermission.objects.get_or_create(code=code, defaults={"name": name, "module": "ventas"})
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
        ("users", "0011_permiso_ajustar_producto_terminado"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
