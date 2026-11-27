"""Serializadores para la respuesta estructurada de los endpoints analíticos de reportes gerenciales."""
from rest_framework import serializers


class OpcionCatalogoSerializer(serializers.Serializer):
    """Opción de catálogo `{codigo, nombre}` para selectores de filtros."""
    codigo = serializers.CharField()
    nombre = serializers.CharField()


class VendedorFiltroSerializer(serializers.Serializer):
    """Vendedor disponible para filtrar ventas y devoluciones en reportes."""
    id = serializers.IntegerField()
    nombre = serializers.CharField()
    email = serializers.CharField()


class ReferenciaFiltroSerializer(serializers.Serializer):
    """Referencia de jean disponible para filtrar el tablero gerencial."""
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    ajuste = serializers.CharField()
    ajuste_nombre = serializers.CharField()
    estado = serializers.CharField()


class MetadatosReporteSerializer(serializers.Serializer):
    """Catálogos combinados que alimentan los filtros avanzados del tablero."""
    tipos_jean = OpcionCatalogoSerializer(many=True)
    estados_orden = OpcionCatalogoSerializer(many=True)
    estados_cobro = OpcionCatalogoSerializer(many=True)
    tipos_cliente = OpcionCatalogoSerializer(many=True)
    vendedores = VendedorFiltroSerializer(many=True)
    transportadoras = OpcionCatalogoSerializer(many=True)
    referencias = ReferenciaFiltroSerializer(many=True)


class ReporteKpisSerializer(serializers.Serializer):
    """Indicadores globales consolidados del periodo filtrado en el tablero gerencial."""
    total_ordenes = serializers.IntegerField()
    prendas_planificadas = serializers.IntegerField()
    prendas_aptas = serializers.IntegerField()
    prendas_marras = serializers.IntegerField()
    tasa_calidad_pct = serializers.FloatField()
    facturas_emitidas = serializers.IntegerField()
    unidades_vendidas = serializers.IntegerField()
    ingresos_totales = serializers.IntegerField()
    utilidad_bruta = serializers.IntegerField()
    recaudado_periodo = serializers.IntegerField()
    pendiente_recaudo_periodo = serializers.IntegerField()
    saldo_financiero_empresa = serializers.IntegerField(allow_null=True)
    devoluciones_guias = serializers.IntegerField()
    flete_devoluciones_total = serializers.IntegerField()


class ConsolidadoTipoJeanSerializer(serializers.Serializer):
    """Totales de producción y ventas agrupados por silueta / ajuste de jean."""
    tipo_jean = serializers.CharField()
    tipo_jean_nombre = serializers.CharField()
    ordenes_count = serializers.IntegerField()
    prendas_planificadas = serializers.IntegerField()
    prendas_aptas = serializers.IntegerField()
    prendas_marras = serializers.IntegerField()
    unidades_vendidas = serializers.IntegerField()
    ingresos_totales = serializers.IntegerField()
    utilidad_bruta = serializers.IntegerField()


class OrdenProduccionReporteSerializer(serializers.Serializer):
    """Fila analítica de orden de producción con calidad y avance por lotes."""
    orden_id = serializers.IntegerField()
    codigo = serializers.CharField()
    fecha_salida = serializers.CharField()
    estado_orden = serializers.CharField()
    estado_orden_nombre = serializers.CharField()
    responsable = serializers.CharField()
    referencia_id = serializers.IntegerField()
    referencia_codigo = serializers.CharField()
    referencia_nombre = serializers.CharField()
    tipo_jean = serializers.CharField()
    tipo_jean_nombre = serializers.CharField()
    prendas_planificadas = serializers.IntegerField()
    total_lotes = serializers.IntegerField()
    prendas_en_lotes = serializers.IntegerField()
    prendas_aptas = serializers.IntegerField()
    prendas_marras = serializers.IntegerField()
    tasa_calidad_pct = serializers.FloatField()
    avance_lotes_pct = serializers.FloatField()


class VentaReferenciaReporteSerializer(serializers.Serializer):
    """Resumen de ingresos, costos estimados y margen por referencia vendida."""
    referencia_id = serializers.IntegerField()
    referencia_codigo = serializers.CharField()
    referencia_nombre = serializers.CharField()
    tipo_jean = serializers.CharField()
    tipo_jean_nombre = serializers.CharField()
    facturas_count = serializers.IntegerField()
    unidades_vendidas = serializers.IntegerField()
    subtotal_bruto = serializers.IntegerField()
    descuento_total = serializers.IntegerField()
    base_gravable = serializers.IntegerField()
    iva_total = serializers.IntegerField()
    ingresos_totales = serializers.IntegerField()
    costo_estimado = serializers.IntegerField()
    utilidad_bruta = serializers.IntegerField()
    margen_pct = serializers.FloatField()


class VentaDetalleReporteSerializer(serializers.Serializer):
    """Línea individual de factura para consulta y exportación en Excel/CSV."""
    linea_id = serializers.IntegerField()
    factura_id = serializers.IntegerField()
    numero_factura = serializers.CharField()
    fecha = serializers.CharField()
    cliente_nombre = serializers.CharField()
    cliente_tipo = serializers.CharField()
    cliente_tipo_nombre = serializers.CharField()
    vendedor_nombre = serializers.CharField()
    transportadora = serializers.CharField()
    estado_cobro = serializers.CharField()
    estado_cobro_nombre = serializers.CharField()
    referencia_codigo = serializers.CharField()
    referencia_nombre = serializers.CharField()
    tipo_jean = serializers.CharField()
    tipo_jean_nombre = serializers.CharField()
    talla = serializers.CharField()
    color = serializers.CharField()
    unidades = serializers.IntegerField()
    subtotal = serializers.IntegerField()
    descuento = serializers.IntegerField()
    base_gravable = serializers.IntegerField()
    iva = serializers.IntegerField()
    total = serializers.IntegerField()


class DevolucionVendedorReporteSerializer(serializers.Serializer):
    """Resumen informativo de guías devueltas y flete a cargo de cada vendedor."""
    vendedor_id = serializers.IntegerField(allow_null=True)
    vendedor_nombre = serializers.CharField()
    guias_devueltas = serializers.IntegerField()
    flete_vendedor = serializers.IntegerField()


class ReporteGerencialSerializer(serializers.Serializer):
    """Respuesta completa del tablero gerencial: filtros, KPIs y tablas analíticas."""
    filtros_aplicados = serializers.DictField()
    kpis = ReporteKpisSerializer()
    consolidado_tipo_jean = ConsolidadoTipoJeanSerializer(many=True)
    ordenes_produccion = OrdenProduccionReporteSerializer(many=True)
    ventas_por_referencia = VentaReferenciaReporteSerializer(many=True)
    ventas_detalle = VentaDetalleReporteSerializer(many=True)
    devoluciones_por_vendedor = DevolucionVendedorReporteSerializer(many=True)


class ReporteRefrescoSerializer(serializers.Serializer):
    """Resultado de la solicitud explícita de refresco de vistas SQL materializadas."""
    refreshed = serializers.BooleanField(help_text="Verdadero si se refrescaron vistas materializadas")
    detail = serializers.CharField()
