"""
Permisos del módulo de compras: `compras.ver`, `compras.gestionar` y `compras.aprobar`.

Quién hace qué en una orden de compra de materiales: el Jefe de Producción la crea y la edita mientras es borrador
(`compras.gestionar`); el Gerente la aprueba (`compras.aprobar`); el Almacenista la consulta y recibe la mercancía con su
permiso de inventario (`inventario.gestionar`, que ya tiene). ADMIN los tiene todos de forma implícita. Después se ajustan
desde "Roles y permisos". Los datos quedan congelados aquí a propósito.
"""
from django.db import migrations

PERMISSIONS = [
    ("compras.ver", "Ver Compras"),
    ("compras.gestionar", "Crear y modificar órdenes de compra"),
    ("compras.aprobar", "Aprobar órdenes de compra"),
]
GRANTS = {
    "PRODUCCION": ["compras.ver", "compras.gestionar"],
    "GERENTE": ["compras.ver", "compras.aprobar"],
    "ALMACENISTA": ["compras.ver"],
}


def seed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    Role = apps.get_model("users", "Role")
    RolePermission = apps.get_model("users", "RolePermission")
    perms = {}
    for code, name in PERMISSIONS:
        perms[code], _ = ModulePermission.objects.get_or_create(code=code, defaults={"name": name, "module": "compras"})
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
        ("users", "0007_permisos_referencias"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
