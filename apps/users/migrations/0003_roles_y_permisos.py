"""
Tablas relacionales de roles y permisos (HU 1.4 / TE-76) con sus datos iniciales.

Los roles y la matriz rol -> permiso salen del diagrama de casos de uso del
negocio. Los datos quedan congelados aquí a propósito: una migración no debe
depender de constantes que puedan cambiar después.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

MODULES = [
    ("seguridad", "Seguridad y Usuarios"),
    ("inventario", "Inventario de Materias Primas"),
    ("fichas_tecnicas", "Fichas Técnicas"),
    ("produccion", "Producción y Trazabilidad"),
    ("lavanderia", "Procesos Externos (Lavandería)"),
    ("calidad", "Control de Calidad"),
    ("producto_terminado", "Producto Terminado"),
    ("ventas", "Ventas y Despachos"),
    ("reportes", "Reportes"),
]

ROLES = [
    ("ADMIN", "Administrador", "Gestiona usuarios, roles y la configuración del sistema."),
    ("GERENTE", "Gerente", "Consulta indicadores y genera reportes de toda la operación."),
    ("PRODUCCION", "Jefe de Producción", "Fichas técnicas, órdenes de producción, lotes y lavandería."),
    ("ALMACENISTA", "Almacenista", "Proveedores, materias primas y movimientos de inventario."),
    ("TERMINACION", "Personal de Terminación", "Control de calidad: prendas aptas y marras."),
    ("SECRETARIA", "Secretaria", "Ingreso y cuadre del inventario de producto terminado."),
    ("VENDEDOR", "Vendedor", "Facturación, guías de despacho y pagos contraentrega."),
    ("PENDING", "Pendiente de aprobación", "Cuenta registrada que todavía no tiene un rol asignado."),
]

OPERATIONAL = ["inventario", "fichas_tecnicas", "produccion", "lavanderia", "calidad", "producto_terminado", "ventas"]

# ADMIN no aparece: tiene todos los permisos de forma implícita (ver CustomUser).
GRANTS = {
    "GERENTE": ["reportes.ver", "reportes.gestionar"] + [f"{m}.ver" for m in OPERATIONAL],
    "PRODUCCION": [
        "fichas_tecnicas.ver", "fichas_tecnicas.gestionar",
        "produccion.ver", "produccion.gestionar",
        "lavanderia.ver", "lavanderia.gestionar",
        "inventario.ver",
    ],
    "ALMACENISTA": ["inventario.ver", "inventario.gestionar"],
    "TERMINACION": ["calidad.ver", "calidad.gestionar"],
    "SECRETARIA": ["producto_terminado.ver", "producto_terminado.gestionar"],
    "VENDEDOR": ["ventas.ver", "ventas.gestionar", "producto_terminado.ver"],
    "PENDING": [],
}


def seed(apps, schema_editor):
    ModulePermission = apps.get_model("users", "ModulePermission")
    Role = apps.get_model("users", "Role")
    RolePermission = apps.get_model("users", "RolePermission")
    CustomUser = apps.get_model("users", "CustomUser")

    perms = {}
    for module, label in MODULES:
        for action, name in (("ver", f"Ver {label}"), ("gestionar", f"Registrar y modificar en {label}")):
            code = f"{module}.{action}"
            perms[code], _ = ModulePermission.objects.get_or_create(
                code=code, defaults={"name": name, "module": module}
            )
    perms["seguridad.roles"], _ = ModulePermission.objects.get_or_create(
        code="seguridad.roles",
        defaults={"name": "Administrar roles y permisos", "module": "seguridad"},
    )

    roles = {}
    for code, name, description in ROLES:
        roles[code], _ = Role.objects.get_or_create(
            code=code, defaults={"name": name, "description": description, "is_system": True}
        )

    for role_code, codes in GRANTS.items():
        for code in codes:
            RolePermission.objects.get_or_create(role=roles[role_code], permission=perms[code])

    # Antes de convertir las columnas en llaves foráneas, dejar solo valores válidos.
    # _base_manager y no .objects: en el estado histórico .objects es CustomUserManager,
    # que oculta los usuarios con borrado lógico, y la llave foránea de 0004 se valida
    # contra TODAS las filas (un eliminado con requested_area='' la haría fallar).
    users = CustomUser._base_manager.all()
    valid = set(roles)
    users.exclude(role__in=valid).update(role="PENDING")
    users.exclude(requested_area__in=valid).update(requested_area=None)
    users.filter(requested_area__in=["ADMIN", "PENDING"]).update(requested_area=None)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_customuser_document_id_customuser_requested_area"),
    ]

    operations = [
        migrations.CreateModel(
            name="ModulePermission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("code", models.CharField(max_length=60, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("module", models.CharField(max_length=40)),
                ("description", models.CharField(blank=True, max_length=255)),
            ],
            options={"db_table": "seguridad_permiso", "ordering": ["module", "code"]},
        ),
        migrations.CreateModel(
            name="Role",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=60)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("is_system", models.BooleanField(default=False)),
            ],
            options={"db_table": "seguridad_rol", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="RolePermission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "granted_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+", to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("permission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="users.modulepermission")),
                ("role", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="users.role")),
            ],
            options={"db_table": "seguridad_rol_permiso"},
        ),
        migrations.AddField(
            model_name="role",
            name="permissions",
            field=models.ManyToManyField(
                blank=True, related_name="roles", through="users.RolePermission", to="users.modulepermission"
            ),
        ),
        migrations.AddConstraint(
            model_name="rolepermission",
            constraint=models.UniqueConstraint(fields=("role", "permission"), name="uq_rol_permiso"),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
