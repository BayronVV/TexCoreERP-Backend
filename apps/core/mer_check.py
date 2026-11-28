"""El modelo de datos publicado coincide con el esquema real de la base (TE-188).

Compara, tabla por tabla, lo que dicen los modelos de Django (de los que salen el MER en notación de Chen y el modelo físico de
`docs/modelo-de-datos.md`) con lo que la base tiene de verdad, leído por introspección:

- la tabla existe y su clave primaria es la del modelo;
- cada clave foránea existe con su tabla y columna destino, y la base no tiene claves foráneas que el modelo no declare;
- cada campo `unique` tiene su restricción única (así una relación 1:1 del MER es 1:1 de verdad);
- cada restricción declarada en el modelo (`UniqueConstraint`, incluidas las condicionales, y `CheckConstraint`) existe con su nombre;
- cada columna acepta nulos solo si el modelo lo dice (una relación identificadora de una entidad débil nunca es nula);
- las cardinalidades del MER salen de esas mismas claves: una relación con «1» en el lado que guarda la clave exige su `unique`.

Funciona en SQLite y en PostgreSQL; en la integración continua corre en el job de PostgreSQL contra el esquema que crean las
migraciones.
"""
from django.db import connection, models

from apps.core.management.commands.generar_erd import project_models


def _constraints(cursor, table):
    return connection.introspection.get_constraints(cursor, table)


def _has(constraints, **expected):
    columns = expected.pop("columns")
    return any(
        info["columns"] == columns and all(info.get(key) == value for key, value in expected.items())
        for info in constraints.values()
    )


def compare(models_=None):
    """Devuelve la lista de diferencias entre los modelos y la base; vacía si coinciden."""
    from apps.core.management.commands import generar_mer as mer

    models_ = [m for m in (models_ or project_models()) if m._meta.managed and not m._meta.proxy]
    problems = []
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        for model in models_:
            meta, table = model._meta, model._meta.db_table
            if table not in tables:
                problems.append(f"{table}: la tabla no existe en la base.")
                continue
            constraints = _constraints(cursor, table)
            description = {column.name: column for column in connection.introspection.get_table_description(cursor, table)}
            if not _has(constraints, columns=[meta.pk.column], primary_key=True):
                problems.append(f"{table}: la clave primaria no es {meta.pk.column}.")
            declared_fks = set()
            for field in meta.concrete_fields:
                column = description.get(field.column)
                if column is None:
                    problems.append(f"{table}.{field.column}: la columna no existe en la base.")
                    continue
                if not field.primary_key and bool(column.null_ok) != field.null:
                    problems.append(f"{table}.{field.column}: en la base {'acepta' if column.null_ok else 'no acepta'} nulos y el modelo dice lo contrario.")
                if isinstance(field, models.ForeignKey) and field.db_constraint:
                    target = (field.related_model._meta.db_table, field.target_field.column)
                    declared_fks.add((field.column, target))
                    if not _has(constraints, columns=[field.column], foreign_key=target):
                        problems.append(f"{table}.{field.column}: falta la clave foránea hacia {target[0]}.{target[1]}.")
                if field.unique and not field.primary_key and not _has(constraints, columns=[field.column], unique=True):
                    problems.append(f"{table}.{field.column}: falta la restricción única.")
            for name, info in constraints.items():
                if info.get("foreign_key") and (info["columns"][0], tuple(info["foreign_key"])) not in declared_fks:
                    problems.append(f"{table}: la base tiene la clave foránea {name} ({info['columns']}) que el modelo no declara.")
            for constraint in meta.constraints:
                info = constraints.get(constraint.name)
                kind = "unique" if isinstance(constraint, models.UniqueConstraint) else "check"
                if info is None or not info.get(kind):
                    problems.append(f"{table}: falta la restricción {constraint.name} ({kind}).")
        by_name = {m.__name__: m for m in models_}
        for relation in mer.relations(models_):
            if relation["kind"] != "1n":
                continue
            owner = by_name[relation["owner"]]
            field_name = relation["id"].removeprefix(f"r_{relation['owner']}_")
            field = owner._meta.get_field(field_name)
            one_to_one = relation["ends"][1][1] == "1"
            if one_to_one != bool(field.unique):
                problems.append(f"MER {relation['name']} ({owner.__name__}.{field_name}): la cardinalidad no coincide con la unicidad.")
            if relation["identifying"] and field.null:
                problems.append(f"MER {relation['name']}: la relación identificadora de {owner.__name__} no puede ser nula.")
    return problems
