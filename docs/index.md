# TexCore ERP

Sistema de información ERP para la **gestión y trazabilidad de la producción de jeans** en
pequeñas y medianas empresas de confección. Reemplaza los archivos de Excel y las fichas
físicas por una base de datos única, con permisos por rol.

## Estado actual (Sprint 2)

| Módulo | Qué incluye | Historias de Jira |
|---|---|---|
| Seguridad y usuarios | Registro, inicio de sesión con JWT, recuperación de contraseña, usuarios, roles y permisos | TE-78, TE-42, TE-43, TE-44 |
| Inventario de materias primas | Proveedores, catálogo de telas e insumos, movimientos de almacén (ingresos, órdenes de salida, kardex), alertas de stock mínimo y costo promedio ponderado por compra | TE-45, TE-46, TE-47, TE-48 |
| Compras | Órdenes de compra de materiales (las crea Producción, las aprueba el Gerente) y recepción de mercancía por el Almacenista, que alimenta el stock, el costo y el kardex | — |
| Referencias de jean | Catálogo de modelos con tallas, colores, fotos del prototipo y estados (borrador, activa, descontinuada) | TE-49 |
| Ficha técnica | Consumo de materiales por prenda con merma, PDF de la ficha extensa y consumo contra el stock | TE-50 |
| Producción y trazabilidad | Validación de material y planificación, órdenes de producción con lotes y tallas, control de tiempos por etapa, asignación de operarios y máquinas, monitor de estado tipo Kanban y liquidación con costeo por orden | TE-51, TE-52, TE-53, TE-54, TE-55, TE-56 |

Los módulos de lavandería como proceso propio, calidad, producto terminado, ventas y reportes se construyen en los
siguientes sprints. Sus permisos ya existen en el catálogo, pero todavía no tienen pantallas.

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
