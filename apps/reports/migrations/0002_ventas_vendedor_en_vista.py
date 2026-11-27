"""
Migración que agrega `vendedor_id` y `vendedor_nombre` a `reportes_mv_ventas_referencias`
(HU 7.7 / TE-177) para filtrar el tablero gerencial por vendedor y transportadora sin joins adicionales.
"""
from django.db import migrations, models

SALES_QUERY_V1 = """
SELECT
    dl.id AS linea_id,
    fv.id AS factura_id,
    fv.numero AS numero_factura,
    fv.fecha AS fecha,
    fv.estado AS estado_factura,
    fv.estado_cobro AS estado_cobro,
    fv.cliente_tipo AS cliente_tipo,
    fv.cliente_nombre AS cliente_nombre,
    fv.transportadora AS transportadora,
    r.id AS referencia_id,
    r.codigo AS referencia_codigo,
    r.nombre AS referencia_nombre,
    r.ajuste AS tipo_jean,
    dl.talla AS talla,
    dl.color AS color,
    dl.cantidad AS unidades,
    dl.subtotal AS subtotal,
    dl.descuento AS descuento,
    dl.base AS base_gravable,
    dl.iva AS iva,
    dl.total AS total,
    (dl.costo_fabrica * dl.cantidad) AS costo_estimado
FROM ventas_factura_linea dl
INNER JOIN ventas_factura fv ON fv.id = dl.factura_id AND fv.deleted_at IS NULL
INNER JOIN referencias_variante v ON v.id = dl.variante_id
INNER JOIN referencias_referencia r ON r.id = v.referencia_id
WHERE dl.deleted_at IS NULL
"""

SALES_QUERY_V2 = """
SELECT
    dl.id AS linea_id,
    fv.id AS factura_id,
    fv.numero AS numero_factura,
    fv.fecha AS fecha,
    fv.estado AS estado_factura,
    fv.estado_cobro AS estado_cobro,
    fv.cliente_tipo AS cliente_tipo,
    fv.cliente_nombre AS cliente_nombre,
    fv.transportadora AS transportadora,
    fv.vendedor_id AS vendedor_id,
    COALESCE(NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), ''), u.email, '') AS vendedor_nombre,
    r.id AS referencia_id,
    r.codigo AS referencia_codigo,
    r.nombre AS referencia_nombre,
    r.ajuste AS tipo_jean,
    dl.talla AS talla,
    dl.color AS color,
    dl.cantidad AS unidades,
    dl.subtotal AS subtotal,
    dl.descuento AS descuento,
    dl.base AS base_gravable,
    dl.iva AS iva,
    dl.total AS total,
    (dl.costo_fabrica * dl.cantidad) AS costo_estimado
FROM ventas_factura_linea dl
INNER JOIN ventas_factura fv ON fv.id = dl.factura_id AND fv.deleted_at IS NULL
LEFT JOIN users_customuser u ON u.id = fv.vendedor_id
INNER JOIN referencias_variante v ON v.id = dl.variante_id
INNER JOIN referencias_referencia r ON r.id = v.referencia_id
WHERE dl.deleted_at IS NULL
"""


def update_sales_view(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute("DROP MATERIALIZED VIEW IF EXISTS reportes_mv_ventas_referencias CASCADE;")
            cursor.execute(f"CREATE MATERIALIZED VIEW reportes_mv_ventas_referencias AS {SALES_QUERY_V2};")
            cursor.execute(
                "CREATE UNIQUE INDEX idx_mv_ventas_linea_id ON reportes_mv_ventas_referencias (linea_id);"
            )
            cursor.execute(
                "CREATE INDEX idx_mv_ventas_filtros ON reportes_mv_ventas_referencias "
                "(fecha, tipo_jean, estado_factura, estado_cobro, vendedor_id, transportadora);"
            )
        else:
            cursor.execute("DROP VIEW IF EXISTS reportes_mv_ventas_referencias;")
            cursor.execute(f"CREATE VIEW reportes_mv_ventas_referencias AS {SALES_QUERY_V2};")


def revert_sales_view(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute("DROP MATERIALIZED VIEW IF EXISTS reportes_mv_ventas_referencias CASCADE;")
            cursor.execute(f"CREATE MATERIALIZED VIEW reportes_mv_ventas_referencias AS {SALES_QUERY_V1};")
            cursor.execute(
                "CREATE UNIQUE INDEX idx_mv_ventas_linea_id ON reportes_mv_ventas_referencias (linea_id);"
            )
            cursor.execute(
                "CREATE INDEX idx_mv_ventas_filtros ON reportes_mv_ventas_referencias "
                "(fecha, tipo_jean, estado_factura, estado_cobro);"
            )
        else:
            cursor.execute("DROP VIEW IF EXISTS reportes_mv_ventas_referencias;")
            cursor.execute(f"CREATE VIEW reportes_mv_ventas_referencias AS {SALES_QUERY_V1};")


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0001_vistas_materializadas"),
        ("users", "0017_permiso_auditoria"),
    ]

    operations = [
        migrations.AddField(
            model_name="vistaventasreferencia",
            name="vendedor_id",
            field=models.BigIntegerField(null=True),
        ),
        migrations.AddField(
            model_name="vistaventasreferencia",
            name="vendedor_nombre",
            field=models.CharField(default="", max_length=254),
            preserve_default=False,
        ),
        migrations.RunPython(update_sales_view, revert_sales_view),
    ]
