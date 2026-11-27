"""
Permiso para conciliar la cartera (HU 7.5): `ventas.conciliar`.

Confirma recaudos contraentrega y ve el saldo financiero. Lo tienen el Gerente y la Secretaria; el Vendedor factura pero no confirma su
propio pago (segregación de funciones). La Secretaria recibe también `ventas.ver` para abrir la cartera. ADMIN lo tiene de forma implícita.
Los datos quedan congelados aquí a propósito.
"""
from django.db import migrations

CODE = "ventas.conciliar"
NAME = "Confirmar recaudos contraentrega y ver el saldo financiero"
GRANTS = {"GERENTE": [CODE], "SECRETARIA": ["ventas.ver", CODE]}


def seed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    Role = apps.get_model("users", "Role")
    RolePermission = apps.get_model("users", "RolePermission")
    ModulePermission.objects.get_or_create(code=CODE, defaults={"name": NAME, "module": "ventas"})
    for role_code, codes in GRANTS.items():
        role = Role.objects.filter(code=role_code).first()
        if role is None:
            continue
        for code in codes:
            perm = ModulePermission.objects.filter(code=code).first()
            if perm is not None:
                RolePermission.objects.get_or_create(role=role, permission=perm)


def unseed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    ModulePermission.objects.filter(code=CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0017_permiso_auditoria"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
