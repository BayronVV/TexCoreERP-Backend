"""
Migración que crea las vistas SQL materializadas para el tablero de reportes gerenciales:
- `reportes_mv_produccion_ordenes`: consolida órdenes de producción, estado de orden, tipo de jean (ajuste), lotes y calidad.
- `reportes_mv_ventas_referencias`: consolida ventas por línea, factura, estado de cobro, referencia y tipo de jean.

En PostgreSQL se crean como `MATERIALIZED VIEW` con índices para lecturas rápidas y refresco eficiente.
En SQLite (entorno local sin servidor o pruebas unitarias) se crean como `VIEW` estándar con el mismo esquema.
"""
from django.db import migrations, models


PRODUCTION_QUERY = """
SELECT
    po.id AS orden_id,
    po.codigo AS codigo,
    io.fecha_salida AS fecha_salida,
    io.estado AS estado_orden,
    io.responsable AS responsable,
    r.id AS referencia_id,
    r.codigo AS referencia_codigo,
    r.nombre AS referencia_nombre,
    r.ajuste AS tipo_jean,
    po.cantidad AS prendas_planificadas,
    COALESCE(lotes_agg.total_lotes, 0) AS total_lotes,
    COALESCE(lotes_agg.prendas_en_lotes, 0) AS prendas_en_lotes,
    COALESCE(lotes_agg.prendas_aptas, 0) AS prendas_aptas,
    COALESCE(lotes_agg.prendas_marras, 0) AS prendas_marras
FROM produccion_orden po
INNER JOIN inventario_orden io ON io.id = po.orden_salida_id AND io.deleted_at IS NULL
INNER JOIN referencias_referencia r ON r.id = po.referencia_id AND r.deleted_at IS NULL
LEFT JOIN (
    SELECT
        l.orden_id AS orden_id,
        COUNT(l.id) AS total_lotes,
        COALESCE(SUM(l.cantidad), 0) AS prendas_en_lotes,
        COALESCE(SUM(ci.aptas), 0) AS prendas_aptas,
        COALESCE(SUM(ci.marras), 0) AS prendas_marras
    FROM produccion_lote l
    LEFT JOIN calidad_inspeccion ci ON ci.lote_id = l.id AND ci.deleted_at IS NULL
    WHERE l.deleted_at IS NULL
    GROUP BY l.orden_id
) lotes_agg ON lotes_agg.orden_id = po.id
WHERE po.deleted_at IS NULL
"""

SALES_QUERY = """
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


def create_materialized_views(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute("DROP MATERIALIZED VIEW IF EXISTS reportes_mv_produccion_ordenes CASCADE;")
            cursor.execute(f"CREATE MATERIALIZED VIEW reportes_mv_produccion_ordenes AS {PRODUCTION_QUERY};")
            cursor.execute(
                "CREATE UNIQUE INDEX idx_mv_prod_orden_id ON reportes_mv_produccion_ordenes (orden_id);"
            )
            cursor.execute(
                "CREATE INDEX idx_mv_prod_filtros ON reportes_mv_produccion_ordenes (fecha_salida, tipo_jean, estado_orden);"
            )

            cursor.execute("DROP MATERIALIZED VIEW IF EXISTS reportes_mv_ventas_referencias CASCADE;")
            cursor.execute(f"CREATE MATERIALIZED VIEW reportes_mv_ventas_referencias AS {SALES_QUERY};")
            cursor.execute(
                "CREATE UNIQUE INDEX idx_mv_ventas_linea_id ON reportes_mv_ventas_referencias (linea_id);"
            )
            cursor.execute(
                "CREATE INDEX idx_mv_ventas_filtros ON reportes_mv_ventas_referencias (fecha, tipo_jean, estado_factura, estado_cobro);"
            )
        else:
            cursor.execute("DROP VIEW IF EXISTS reportes_mv_produccion_ordenes;")
            cursor.execute(f"CREATE VIEW reportes_mv_produccion_ordenes AS {PRODUCTION_QUERY};")

            cursor.execute("DROP VIEW IF EXISTS reportes_mv_ventas_referencias;")
            cursor.execute(f"CREATE VIEW reportes_mv_ventas_referencias AS {SALES_QUERY};")


def drop_materialized_views(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute("DROP MATERIALIZED VIEW IF EXISTS reportes_mv_produccion_ordenes CASCADE;")
            cursor.execute("DROP MATERIALIZED VIEW IF EXISTS reportes_mv_ventas_referencias CASCADE;")
        else:
            cursor.execute("DROP VIEW IF EXISTS reportes_mv_produccion_ordenes;")
            cursor.execute("DROP VIEW IF EXISTS reportes_mv_ventas_referencias;")


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("inventory", "0006_alter_producto_categoria_alter_proveedor_categoria"),
        ("references", "0003_ficha_documento"),
        ("production", "0007_recepcionlavanderia_recepcionlote_and_more"),
        ("quality", "0001_initial"),
        ("sales", "0002_cartera_conciliacion"),
    ]

    operations = [
        migrations.CreateModel(
            name="VistaProduccionOrden",
            fields=[
                ("orden_id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("codigo", models.CharField(max_length=20)),
                ("fecha_salida", models.DateField()),
                ("estado_orden", models.CharField(max_length=12)),
                ("responsable", models.CharField(max_length=120)),
                ("referencia_id", models.BigIntegerField()),
                ("referencia_codigo", models.CharField(max_length=20)),
                ("referencia_nombre", models.CharField(max_length=150)),
                ("tipo_jean", models.CharField(max_length=15)),
                ("prendas_planificadas", models.IntegerField()),
                ("total_lotes", models.IntegerField()),
                ("prendas_en_lotes", models.IntegerField()),
                ("prendas_aptas", models.IntegerField()),
                ("prendas_marras", models.IntegerField()),
            ],
            options={
                "db_table": "reportes_mv_produccion_ordenes",
                "ordering": ["-fecha_salida", "-orden_id"],
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="VistaVentasReferencia",
            fields=[
                ("linea_id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("factura_id", models.BigIntegerField()),
                ("numero_factura", models.CharField(max_length=20)),
                ("fecha", models.DateField()),
                ("estado_factura", models.CharField(max_length=10)),
                ("estado_cobro", models.CharField(max_length=12)),
                ("cliente_tipo", models.CharField(max_length=12)),
                ("cliente_nombre", models.CharField(max_length=150)),
                ("transportadora", models.CharField(max_length=16)),
                ("referencia_id", models.BigIntegerField()),
                ("referencia_codigo", models.CharField(max_length=20)),
                ("referencia_nombre", models.CharField(max_length=150)),
                ("tipo_jean", models.CharField(max_length=15)),
                ("talla", models.CharField(max_length=10)),
                ("color", models.CharField(max_length=60)),
                ("unidades", models.IntegerField()),
                ("subtotal", models.BigIntegerField()),
                ("descuento", models.BigIntegerField()),
                ("base_gravable", models.BigIntegerField()),
                ("iva", models.BigIntegerField()),
                ("total", models.BigIntegerField()),
                ("costo_estimado", models.BigIntegerField()),
            ],
            options={
                "db_table": "reportes_mv_ventas_referencias",
                "ordering": ["-fecha", "-linea_id"],
                "managed": False,
            },
        ),
        migrations.RunPython(create_materialized_views, drop_materialized_views),
    ]
