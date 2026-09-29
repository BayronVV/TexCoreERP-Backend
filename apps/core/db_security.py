"""
Cierra el esquema public de Supabase a la Data API (PostgREST / GraphQL).

Supabase da a los roles `anon` y `authenticated` acceso a toda tabla nueva de
public, así que cualquiera con la anon key podría leer, por ejemplo, los hashes
de users_customuser. En TexCore solo el backend habla con la base, por lo que
después de cada `migrate` se:

1. activa RLS (sin políticas) en las tablas de public que son del usuario de la
   conexión; el dueño no está sujeto a RLS, así que Django sigue funcionando;
2. quitan los privilegios de anon/authenticated sobre tablas y secuencias, y los
   privilegios que Supabase les daría sobre las tablas que se creen después.

Es idempotente. En SQLite (pruebas) no hace nada.
"""

PUBLIC_ROLES = ("anon", "authenticated")

OWNED_TABLES_WITHOUT_RLS = """
    select c.relname
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relkind in ('r', 'p')
      and not c.relrowsecurity
      and pg_has_role(current_user, c.relowner, 'USAGE')
"""


def harden_public_schema(connection):
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(OWNED_TABLES_WITHOUT_RLS)
        for (table,) in cursor.fetchall():
            cursor.execute(f"ALTER TABLE public.{connection.ops.quote_name(table)} ENABLE ROW LEVEL SECURITY")

        cursor.execute("select rolname from pg_roles where rolname = any(%s)", [list(PUBLIC_ROLES)])
        roles = ", ".join(connection.ops.quote_name(name) for (name,) in cursor.fetchall())
        if not roles:
            return  # Postgres fuera de Supabase: no existen esos roles.
        cursor.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {roles}")
        cursor.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {roles}")
        cursor.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {roles}")
        cursor.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {roles}")
