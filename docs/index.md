# TexCore ERP

Sistema de información ERP para la **gestión y trazabilidad de la producción de jeans** en
pequeñas y medianas empresas de confección. Reemplaza los archivos de Excel y las fichas
físicas por una base de datos única, con permisos por rol.

## Estado actual del proyecto al Sprint 3

Tres sprints entregados: el Sprint 1 (seguridad e inventario), el Sprint 2 (05/10 – 19/10: referencias, producción y compras) y el
Sprint 3 (19/10 – 09/11/2026: 9 historias, 35 puntos, todas en «Listo»), que cerró el recorrido completo de la prenda: lavandería,
calidad, inventario final, facturación, guías de envío, cartera y reportes gerenciales.

| Módulo | Qué incluye | Sprint | Historias de Jira |
|---|---|---|---|
| Seguridad y usuarios | Registro, inicio de sesión con JWT, recuperación de contraseña, usuarios, roles y permisos | 1 | TE-78, TE-42, TE-43, TE-44 |
| Inventario de materias primas | Proveedores, catálogo de telas e insumos, movimientos de almacén (ingresos, órdenes de salida, kardex), alertas de stock mínimo y costo promedio ponderado por compra | 1 | TE-45, TE-46, TE-47, TE-48 |
| Compras | Órdenes de compra de materiales (las crea Producción, las aprueba el Gerente) y recepción de mercancía por el Almacenista, que alimenta el stock, el costo y el kardex | 2 | — (sin historia en Jira) |
| Referencias de jean | Catálogo de modelos con tallas, colores, fotos del prototipo y estados (borrador, activa, descontinuada) | 2 | TE-49 |
| Ficha técnica | Consumo de materiales por prenda con merma, PDF de la ficha extensa y consumo contra el stock | 2 | TE-50 |
| Producción y trazabilidad | Validación de material y planificación, órdenes de producción con lotes y tallas, control de tiempos por etapa, asignación de operarios y máquinas, monitor de estado tipo Kanban y liquidación con costeo por orden | 2 | TE-51, TE-52, TE-53, TE-54, TE-55, TE-56 |
| Lavandería (procesos externos) | Remisión de salida a lavandería (`REM-LAV-AAAA-0001`) que saca los lotes de la planta, y recepción (`REC-LAV-AAAA-0001`) que coteja conformes, mermas y dañadas, liquida la pérdida y devuelve el lote a la planta | 3 | TE-57, TE-58 |
| Control de calidad | Catálogo de defectos y inspección de los lotes que vuelven de lavandería: aptas y marras desglosadas por defecto | 3 | TE-59 |
| Producto terminado | Ingreso al inventario final de las prendas aptas de cada inspección, repartidas por talla y color; existencias en matriz, libro de movimientos y ajuste manual contra el conteo físico | 3 | TE-60, TE-61 |
| Ventas | Factura POS interna (comprobante propio, **no factura electrónica**) con descuento del inventario por talla y color, descuento del vendedor con tope por tipo de cliente, IVA, PDF y anulación; clientes y precios. Solo contraentrega | 3 | TE-62 |
| Envíos | Guía de la transportadora anotada al facturar (o después, si falta), semáforo de estados (por despachar, en tránsito, con novedad, entregada y devuelta), relaciones de despacho con PDF, devolución física en cartera, flete de las devoluciones y consulta del estado real de las guías de Interrapidísimo con Track123 | 3 | TE-63 |
| Cartera y pagos contraentrega | Conciliación de cada factura emitida como pagada (suma el recaudo al saldo financiero de la empresa) o como devolución (reingresa las prendas), con libro de movimientos de cartera y resumen de lo por cobrar, lo recaudado y las devoluciones | 3 | TE-64 |
| Reportes gerenciales | Tablero con indicadores de producción, calidad y ventas (unidades, ingresos, utilidad bruta estimada y recaudo) y filtros por fechas, tipo de jean, referencia, estado de la orden, estado de cobro y tipo de cliente, sobre vistas SQL materializadas | 3 | TE-65 |

Los datos que hay hoy en los servidores de Render son **simulados**: sirven para la demostración y se pueden modificar sin riesgo (ver
[despliegue en Render](despliegue-render.md)).

!!! info "Qué sigue: Sprint 4"
    La deuda técnica y las mejoras detectadas en el Sprint 3 quedaron en el backlog de Jira (claves TE-169 a TE-178, TE-184 y las subtareas
    TE-179 a TE-183 y TE-185; 40 puntos propuestos, para no pasar mucho de la velocidad del Sprint 3):

    - **Historias de producto:** valoración y liquidación de marras (TE-169), unificación de las existencias de producto terminado (TE-170),
      retiro de la salida a lavandería provisional de Inventario (TE-171), lavandería confiable, sin datos simulados ni pérdida de prendas
      (TE-172), coherencia entre cartera y guías de envío (TE-173), costo de fábrica calculado desde la producción (TE-174), bloqueo por
      intentos fallidos y auditoría de accesos (TE-175), trazabilidad de punta a punta (TE-176), filtros avanzados y devoluciones en los
      reportes (TE-177) y órdenes de compra con aprobación independiente (TE-178).
    - **Calidad de vida (TE-184):** seguridad (TE-179), calidad continua con CI y PostgreSQL (TE-180), observabilidad (TE-181),
      documentación al día (TE-182), datos de demostración coherentes (TE-183) y separación de los ambientes de desarrollo y producción (TE-185).

    Hasta que esas historias se entreguen, las limitaciones conocidas de cada módulo están en [módulos y reglas de negocio](modulos.md).

## Cómo está organizada esta documentación

| Necesito… | Voy a… |
|---|---|
| Entender cómo está construido el sistema | **Manual técnico**: [arquitectura](arquitectura.md), [módulos y reglas de negocio](modulos.md), [roles y permisos](roles-y-permisos.md), [API REST](api.md), [modelo de datos](modelo-de-datos.md), [convenciones de base de datos](convenciones-base-de-datos.md) |
| Instalarlo, configurarlo o desplegarlo | **Manual del sistema**: [instalación y operación](manual-del-sistema.md), [despliegue en Render](despliegue-render.md) |
| Aprender a usarlo | **[Manual de usuario](manual-de-usuario.md)** |
| Un resumen de datos técnicos | **[Ficha técnica](ficha-tecnica.md)** |

## Enlaces

- Sistema en producción: <https://texcore-web.onrender.com>
- API en producción: <https://texcore-api.onrender.com>
- Documentación interactiva de la API (Swagger): <https://texcore-api.onrender.com/api/docs/>
- Repositorios: [backend](https://github.com/BayronVV/TexCoreERP-Backend) y [frontend](https://github.com/BayronVV/TexCoreERP-Frontend)

!!! note "Documentación como código"
    Estas páginas viven en `backend/docs/` y se escriben en Markdown. El modelo de datos se genera solo
    desde los modelos de Django y la referencia de la API se genera desde el código, así que no se
    desactualizan.
