"""
Modelos de solo lectura respaldados por vistas SQL materializadas en PostgreSQL.
Evitan sobrecargar la base de datos transaccional con cruces pesados de múltiples tablas
durante la consulta de reportes gerenciales.
"""
from django.db import models

from . import catalog


class VistaProduccionOrden(models.Model):
    """
    Fila consolidada de una orden de producción en la vista materializada `reportes_mv_produccion_ordenes`.
    Cruza orden de producción, orden de salida de inventario, referencia (tipo de jean), lotes e inspecciones de calidad.
    """
    orden_id = models.BigIntegerField(primary_key=True)
    codigo = models.CharField(max_length=20)
    fecha_salida = models.DateField()
    estado_orden = models.CharField(max_length=12)
    responsable = models.CharField(max_length=120)
    referencia_id = models.BigIntegerField()
    referencia_codigo = models.CharField(max_length=20)
    referencia_nombre = models.CharField(max_length=150)
    tipo_jean = models.CharField(max_length=15)
    prendas_planificadas = models.IntegerField()
    total_lotes = models.IntegerField()
    prendas_en_lotes = models.IntegerField()
    prendas_aptas = models.IntegerField()
    prendas_marras = models.IntegerField()

    class Meta:
        managed = False
        db_table = catalog.MV_PRODUCTION_SUMMARY
        ordering = ["-fecha_salida", "-orden_id"]


class VistaVentasReferencia(models.Model):
    """
    Fila pre-agregada de ventas por factura y referencia de jean en la vista materializada `reportes_mv_ventas_referencias`.
    Cruza facturas de venta, líneas de detalle, variantes y referencias (tipo de jean).
    """
    linea_id = models.BigIntegerField(primary_key=True)
    factura_id = models.BigIntegerField()
    numero_factura = models.CharField(max_length=20)
    fecha = models.DateField()
    estado_factura = models.CharField(max_length=10)
    estado_cobro = models.CharField(max_length=12)
    cliente_tipo = models.CharField(max_length=12)
    cliente_nombre = models.CharField(max_length=150)
    transportadora = models.CharField(max_length=16)
    referencia_id = models.BigIntegerField()
    referencia_codigo = models.CharField(max_length=20)
    referencia_nombre = models.CharField(max_length=150)
    tipo_jean = models.CharField(max_length=15)
    talla = models.CharField(max_length=10)
    color = models.CharField(max_length=60)
    unidades = models.IntegerField()
    subtotal = models.BigIntegerField()
    descuento = models.BigIntegerField()
    base_gravable = models.BigIntegerField()
    iva = models.BigIntegerField()
    total = models.BigIntegerField()
    costo_estimado = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = catalog.MV_SALES_BY_REFERENCE
        ordering = ["-fecha", "-linea_id"]

