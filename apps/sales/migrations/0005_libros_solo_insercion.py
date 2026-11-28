"""Libros de solo inserción (TE-188).

1. Regla del libro de cartera en la base: saldo después = saldo antes + monto, y monto nunca negativo (como ya tenía el libro de
   producto terminado).
2. En PostgreSQL, triggers que impiden editar o borrar filas de los tres libros de movimientos: kardex de inventario
   (`inventario_movimiento`), libro de producto terminado (`terminado_movimiento`) y libro de cartera (`ventas_movimiento_cartera`).
   Frenan también `QuerySet.update()` y el SQL directo, que la protección del modelo no ve. Una corrección o reversión es siempre un
   movimiento nuevo.

   - Vaciar los libros (`TRUNCATE`) solo se permite al reinicio de los datos de demostración (`reiniciar_datos_demo`, que activa
     `texcore.permitir_reinicio` dentro de su transacción) y en las bases de prueba de Django (`test_…`), que se vacían entre pruebas.
   - El error usa el código SQLSTATE 23001 (`restrict_violation`): Django lo recibe como `IntegrityError` y la API responde 409.

En SQLite no hay triggers: allí protege el modelo (`AppendOnlyModel`).
"""
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q

LEDGERS = ("inventario_movimiento", "terminado_movimiento", "ventas_movimiento_cartera")

FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION texcore_libro_solo_insercion() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF coalesce(current_setting('texcore.permitir_reinicio', true), '') = 'on' THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    RAISE EXCEPTION 'El libro % es de solo inserción: los movimientos no se editan ni se borran; una corrección es un movimiento nuevo.',
        TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE OR REPLACE FUNCTION texcore_libro_sin_vaciar() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF coalesce(current_setting('texcore.permitir_reinicio', true), '') = 'on' OR current_database() LIKE 'test\_%' THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'El libro % no se puede vaciar: solo lo hace reiniciar_datos_demo.', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;
"""

DROP_FUNCTIONS = """
DROP FUNCTION IF EXISTS texcore_libro_solo_insercion();
DROP FUNCTION IF EXISTS texcore_libro_sin_vaciar();
"""


def triggers_sql(table):
    return (
        f"CREATE TRIGGER {table}_solo_insercion BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION texcore_libro_solo_insercion();\n"
        f"CREATE TRIGGER {table}_sin_vaciar BEFORE TRUNCATE ON {table} "
        f"FOR EACH STATEMENT EXECUTE FUNCTION texcore_libro_sin_vaciar();"
    )


def drop_triggers_sql(table):
    return f"DROP TRIGGER IF EXISTS {table}_solo_insercion ON {table};\nDROP TRIGGER IF EXISTS {table}_sin_vaciar ON {table};"


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(FUNCTIONS)
    for table in LEDGERS:
        schema_editor.execute(triggers_sql(table))


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in LEDGERS:
        schema_editor.execute(drop_triggers_sql(table))
    schema_editor.execute(DROP_FUNCTIONS)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0004_una_sola_caja"),
        ("inventory", "0008_unificar_productos_terminados"),
        ("finished", "0003_ventas_facturacion"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="movimientocartera",
            constraint=models.CheckConstraint(condition=Q(saldo_despues=F("saldo_antes") + F("monto")), name="ck_cartera_movimiento_saldo"),
        ),
        migrations.AddConstraint(
            model_name="movimientocartera",
            constraint=models.CheckConstraint(condition=Q(monto__gte=0), name="ck_cartera_movimiento_monto"),
        ),
        migrations.RunPython(install, uninstall),
    ]
