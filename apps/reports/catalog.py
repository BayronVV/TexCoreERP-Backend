"""Constantes y permisos del módulo de reportes gerenciales."""

REPORTS_VIEW = "reportes.ver"
REPORTS_MANAGE = "reportes.gestionar"

# Nombres de las vistas SQL analíticas (materializadas en PostgreSQL, vistas estándar en SQLite para tests)
MV_PRODUCTION_SUMMARY = "reportes_mv_produccion_ordenes"
MV_SALES_BY_REFERENCE = "reportes_mv_ventas_referencias"


# --- Trazabilidad de punta a punta (HU 7.6, TE-176) ----------------------------------------------------------------
# Permiso de consulta que exige cada bloque. No hay permiso propio: la pantalla se abre con cualquiera de ellos y cada
# bloque sin su permiso llega como {"acceso": false}, sin datos.
TRACE_BLOCKS = {
    "referencia": "referencias.ver",
    "ficha": "fichas_tecnicas.ver",
    "orden": "produccion.ver",
    "materiales": "inventario.ver",
    "compras": "compras.ver",
    "lavanderia": "lavanderia.ver",
    "calidad": "calidad.ver",
    "ingreso": "producto_terminado.ver",
    "venta": "ventas.ver",
    "existencias": "producto_terminado.ver",
    "envio": "envios.ver",
}
TRACE_VIEW_ANY = tuple(sorted(set(TRACE_BLOCKS.values())))
