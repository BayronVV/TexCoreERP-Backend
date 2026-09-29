"""
Convierte CustomUser.role y requested_area en llaves foráneas a seguridad_rol.

Va en su propia migración (y transacción) porque 0003 actualiza filas de
users_customuser, y Postgres no deja alterar una tabla con eventos de
triggers pendientes en la misma transacción.
"""
import django.contrib.auth.models
import django.db.models.deletion
from django.db import migrations, models

import apps.users.models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_roles_y_permisos"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="role",
            field=models.ForeignKey(
                db_column="role", default="PENDING", on_delete=django.db.models.deletion.PROTECT,
                related_name="users", to="users.role", to_field="code",
            ),
        ),
        migrations.AlterField(
            model_name="customuser",
            name="requested_area",
            field=models.ForeignKey(
                blank=True, db_column="requested_area", null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to="users.role", to_field="code",
            ),
        ),
        migrations.AlterModelManagers(
            name="customuser",
            managers=[
                ("objects", apps.users.models.CustomUserManager()),
                ("all_objects", django.contrib.auth.models.UserManager()),
            ],
        ),
    ]
