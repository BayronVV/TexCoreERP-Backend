"""
Permisos del módulo de envíos (HU 7.2): ver, anotar guías, gestionar y registrar devoluciones.

- `envios.ver`: Vendedor, Almacenista, Secretaria y Gerente consultan guías, relaciones y el semáforo.
- `envios.anotar`: quien factura o prepara el paquete anota el número de guía (Vendedor, Almacenista y Secretaria).
- `envios.gestionar`: bodega y secretaría arman relaciones, cambian estados, registran el flete y consultan el rastreo (que gasta cuota).
- `envios.devolucion`: Almacenista y Gerente registran en cartera la devolución física de un paquete.
ADMIN los tiene todos de forma implícita. Después se ajustan desde "Roles y permisos". Los datos quedan congelados aquí a propósito.
"""
from django.db import migrations

PERMISSIONS = [
    ("envios.ver", "Consultar guías, relaciones de despacho y su semáforo"),
    ("envios.anotar", "Anotar el número de guía de una factura"),
    ("envios.gestionar", "Armar relaciones de despacho, cambiar estados de guías, registrar flete y consultar el rastreo"),
    ("envios.devolucion", "Registrar en cartera la devolución física de un paquete"),
]
GRANTS = {
    "VENDEDOR": ["envios.ver", "envios.anotar"],
    "ALMACENISTA": ["envios.ver", "envios.anotar", "envios.gestionar", "envios.devolucion"],
    "SECRETARIA": ["envios.ver", "envios.anotar", "envios.gestionar"],
    "GERENTE": ["envios.ver", "envios.devolucion"],
}


def seed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    Role = apps.get_model("users", "Role")
    RolePermission = apps.get_model("users", "RolePermission")
    perms = {}
    for code, name in PERMISSIONS:
        perms[code], _ = ModulePermission.objects.get_or_create(code=code, defaults={"name": name, "module": "envios"})
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
        ("users", "0012_permisos_ventas_precios_anular"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
