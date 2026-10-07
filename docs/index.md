# TexCore ERP

Sistema de información ERP para la **gestión y trazabilidad de la producción de jeans** en
pequeñas y medianas empresas de confección. Reemplaza los archivos de Excel y las fichas
físicas por una base de datos única, con permisos por rol.

## Estado actual (Sprint 1)

| Módulo | Qué incluye | Historias de Jira |
|---|---|---|
| Seguridad y usuarios | Registro, inicio de sesión con JWT, recuperación de contraseña, usuarios, roles y permisos | TE-78, TE-42, TE-43, TE-44 |
| Inventario de materias primas | Proveedores, catálogo de telas e insumos, movimientos de almacén (ingresos, órdenes de salida, kardex) y alertas de stock mínimo | TE-45, TE-46, TE-47, TE-48 |

Los módulos de fichas técnicas, producción, lavandería, calidad, producto terminado, ventas y
reportes se construyen en los siguientes sprints.

## Cómo está organizada esta documentación

| Necesito… | Voy a… |
|---|---|
| Entender cómo está construido el sistema | **Manual técnico**: [arquitectura](arquitectura.md), [API REST](api.md), [modelo de datos](modelo-de-datos.md) |
| Instalarlo, configurarlo o desplegarlo | **Manual del sistema**: [instalación y operación](manual-del-sistema.md), [despliegue en Render](despliegue-render.md) |
| Aprender a usarlo | **[Manual de usuario](manual-de-usuario.md)** |
| Un resumen de datos técnicos | **[Ficha técnica](ficha-tecnica.md)** |

## Enlaces

- Sistema en producción: <https://texcore-web.onrender.com>
- API en producción: <https://texcore-api.onrender.com>
- Documentación interactiva de la API (Swagger): `/api/docs/` del backend
- Repositorios: [backend](https://github.com/BayronVV/TexCoreERP-Backend) y [frontend](https://github.com/BayronVV/TexCoreERP-Frontend)

!!! note "Documentación como código"
    Estas páginas viven en `backend/docs/` y se escriben en Markdown. El modelo de datos se genera solo
    desde los modelos de Django y la referencia de la API se genera desde el código, así que no se
    desactualizan.
