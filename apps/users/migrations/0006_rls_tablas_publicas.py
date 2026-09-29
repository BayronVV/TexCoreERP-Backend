"""
Activa Row Level Security (sin políticas) en las tablas del esquema public.

Supabase publica el esquema public por su Data API (PostgREST / GraphQL) con los
roles anon y authenticated, y sus privilegios por defecto les dan SELECT, INSERT,
UPDATE y DELETE sobre toda tabla nueva (incluida users_customuser, con los hashes
de contraseña). Con RLS activo y sin políticas esos roles no ven ni modifican
ninguna fila. El backend se conecta como dueño de las tablas (postgres) y el dueño
no está sujeto a RLS (no se usa FORCE), así que sigue funcionando igual.

- Solo actúa en PostgreSQL; en SQLite (pruebas) no hace nada.
- Solo toca tablas cuyo dueño es el usuario de la conexión: activarle RLS a una
  tabla ajena podría dejar al backend sin acceso, así que se omite y se avisa.
  Como el esquema se crea solo con migraciones de Django, esas tablas son las de
  Django (auth_*, django_*, users_*, seguridad_*...).
- Es idempotente. Las tablas que creen migraciones futuras quedan cubiertas por
  apps/core/db_security.py, que se ejecuta al final de cada `migrate`.
- La reversa no desactiva RLS a propósito: volver atrás no debe reabrir la Data API.
"""
from django.db import migrations

TABLAS_SIN_RLS = """
    select c.relname, pg_has_role(current_user, c.relowner, 'USAGE') as es_dueno
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relkind in ('r', 'p')
      and not c.relrowsecurity
    order by c.relname
"""


def habilitar_rls(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(TABLAS_SIN_RLS)
        tablas = cursor.fetchall()
    omitidas = []
    for tabla, es_dueno in tablas:
        if es_dueno:
            schema_editor.execute(f"ALTER TABLE public.{schema_editor.quote_name(tabla)} ENABLE ROW LEVEL SECURITY")
        else:
            omitidas.append(tabla)
    if omitidas:
        print(
            "\n  AVISO: RLS no se activó en tablas de public que no son del usuario de la "
            f"conexión (revisar a mano): {', '.join(omitidas)}"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_token_recuperacion"),
    ]

    operations = [
        migrations.RunPython(habilitar_rls, migrations.RunPython.noop),
    ]
