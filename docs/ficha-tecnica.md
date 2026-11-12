# Ficha técnica

| | |
|---|---|
| **Sistema** | TexCore ERP: gestión y trazabilidad de la producción de jeans |
| **Materia** | Análisis y Diseño de Sistemas · VII semestre · UFPS |
| **Equipo** | Product Owner: Adrian Ortiz · Scrum Master: Nelson Beltran · Desarrolladores: Bayron Vargas, Santiago Rozo, Carlos Beltran |
| **Metodología** | Híbrida: base predictiva (casos de uso, requerimientos, modelo de análisis) y ejecución ágil con Scrum en Jira |
| **Arquitectura** | Por capas: SPA + API REST + base relacional (ver [arquitectura](arquitectura.md)) |

## Tecnología

| Componente | Tecnología |
|---|---|
| Backend | Python · Django 5.2 LTS · Django REST Framework 3.18 |
| Autenticación | JSON Web Tokens (djangorestframework-simplejwt 5.5) |
| PDF de la factura de venta y de la relación de despacho | reportlab 4 (HU 7.1 y 7.2) |
| Documentación de la API | OpenAPI con drf-spectacular (`/api/docs/`) |
| Rastreo de guías de envío | API de Track123 v2.1 (opcional, solo Interrapidísimo, apagada por defecto; ver [despliegue](despliegue-render.md#rastreo-de-guias-con-track123)) |
| Reportes gerenciales | Vistas SQL materializadas en PostgreSQL (vistas estándar en SQLite), refrescadas con `REFRESH MATERIALIZED VIEW CONCURRENTLY` |
| Base de datos | PostgreSQL en Supabase (SQLite local sin conexión) · driver psycopg 3 |
| Servidor de aplicación | Gunicorn (producción) |
| Frontend | React 19 · Vite 8 · React Router 7 · Axios (Node 20.19 o superior) |
| Pruebas del frontend | `node --test` sobre la lógica pura de las pantallas · análisis estático con oxlint |
| Documentación | MkDocs Material (este sitio, en GitHub Pages) · modelo de datos generado con `generar_erd` (Mermaid) |
| Correo | SMTP de Brevo por el puerto 2525 |
| Control de versiones | Git y GitHub (flujo rama → `pruebas` → `main` con pull requests) |
| Gestión | Jira Cloud (proyecto TE) con despliegues visibles mediante GitHub Actions |
| Despliegue | Render (plan gratuito): servicio web `texcore-api` y sitio estático `texcore-web` |

## Despliegue

| | URL |
|---|---|
| Sistema | <https://texcore-web.onrender.com> |
| API | <https://texcore-api.onrender.com> |
| Estado de la API | <https://texcore-api.onrender.com/api/health/> |

Cada cambio que llega a `main` se despliega solo. El servicio gratuito se suspende tras 15 minutos sin uso,
por eso la primera petición puede tardar.

## Roles del sistema

Administrador (`ADMIN`), Gerente (`GERENTE`), Producción (`PRODUCCION`), Almacenista (`ALMACENISTA`),
Terminación (`TERMINACION`), Secretaria (`SECRETARIA`), Vendedor (`VENDEDOR`) y Pendiente (`PENDING`, sin acceso hasta que se le asigne un rol).

## Alcance entregado

Tres sprints, todos cerrados. El Sprint 3 (19/10 – 09/11/2026) entregó las 9 historias comprometidas (35 puntos, todas en «Listo»).

### Sprint 1

- **Seguridad y usuarios:** registro, inicio de sesión, recuperación de contraseña, gestión de usuarios, roles y permisos por módulo.
- **Inventario de materias primas:** proveedores, catálogo de telas e insumos, ingresos, órdenes de salida (producción y lavandería), kardex, evidencias y alertas de stock mínimo.

### Sprint 2 (05/10 – 19/10/2026)

- **Referencias de jean (HU 3.1, TE-49):** catálogo de modelos con tallas, colores, fotos del prototipo y estados (borrador, activa, descontinuada).
- **Ficha técnica de consumo (HU 3.2, TE-50):** materiales por prenda con merma, PDF de la ficha extensa y consumo contra el stock.
- **Validación de material (HU 4.1, TE-51):** simulación de producción contra el stock, máximo producible y cobertura por lote.
- **Órdenes y lotes (HU 4.2, TE-52):** orden de producción con lotes y tallas; descuenta el material de la ficha y devuelve el stock al anular.
- **Control de tiempos (HU 4.3, TE-53):** corte, confección y terminación con inicio, pausa, reanudación y fin; tiempo neto e historial.
- **Asignación de recursos (HU 4.4, TE-54):** catálogo de operarios y máquinas, asignación por etapa con historial.
- **Monitor de estado (HU 4.5, TE-55):** tablero Kanban de lotes con alertas por tiempo detenido y movimiento arrastrando la tarjeta.
- **Costeo y liquidación (HU 4.6, TE-56):** costo promedio ponderado en las compras, tarifas de mano de obra por minuto y liquidación por orden.
- **Compras (sin historia en Jira):** orden de compra (Producción) → aprobación (Gerente) → recepción de mercancía (Almacenista), con costo y kardex.

### Sprint 3 (19/10 – 09/11/2026)

- **Remisión de salida a lavandería (HU 5.1, TE-57):** remisión `REM-LAV-AAAA-0001` que saca los lotes de la planta interna (pasan a «en tránsito») y calcula el costo estimado del servicio.
- **Recepción de lavandería (HU 5.2, TE-58):** acta `REC-LAV-AAAA-0001` que coteja conformes, mermas y dañadas contra lo enviado, liquida la pérdida y devuelve el lote a la planta.
- **Marras y calidad (HU 6.1, TE-59):** catálogo de defectos corregibles e incorregibles e inspección de los lotes que vuelven de lavandería, con las marras desglosadas por defecto.
- **Ingreso a inventario final (HU 6.2, TE-60):** ingreso al producto terminado de las aptas de cada inspección, repartidas por talla y color; existencias en matriz y libro de movimientos.
- **Ajuste manual de inventario (HU 6.3, TE-61):** corrección del inventario de producto terminado contra el conteo físico, con motivo, observación y comprobante.
- **Facturación y descuento (HU 7.1, TE-62):** factura POS interna (comprobante propio, **no factura electrónica**) con descuento del inventario por talla y color, descuento del vendedor con tope por tipo de cliente, IVA del 19 %, PDF descargable y anulación con reingreso al inventario. Solo contraentrega; clientes y precios mantenidos a mano.
- **Guías de envío con rastreo Track123 (HU 7.2, TE-63):** guía de la transportadora anotada al facturar, semáforo de estados, relaciones de despacho con PDF, devolución física y consulta opcional del estado real de las guías de Interrapidísimo.
- **Control de pagos contraentrega (HU 7.3, TE-64):** conciliación de cada factura como pagada (suma al saldo financiero) o como devolución (reingresa las prendas), con libro de movimientos de cartera y resumen de lo por cobrar.
- **Tablero de reportes gerenciales (HU 7.4, TE-65):** indicadores de producción, calidad y ventas con filtros, sobre vistas SQL materializadas.
- **Datos de demostración:** comandos `seed_demo_*` y `seed_demo_completo` para poblar un entorno (en Render, con `SEED_DEMO_ON_DEPLOY`); los datos de los servidores desplegados son simulados.

### Sprint 4 (planeado)

Backlog de deuda técnica y mejoras en Jira (TE-169 a TE-178, TE-184 y subtareas TE-179 a TE-183 y TE-185; 40 puntos propuestos). Resumen en la [página principal](index.md).

## Calidad

| Aspecto | Valor |
|---|---|
| Pruebas automatizadas del backend | 928 (usuarios, inventario, referencias, producción con lavandería, compras, calidad, producto terminado, ventas con cartera, envíos, reportes y salud), todas aprobadas |
| Pruebas automatizadas del frontend | 221 (lógica de las pantallas), todas aprobadas |
| Rutas de la API | 114 (sin contar la documentación): 8 públicas (salud, registro, inicio de sesión, renovación y recuperación de contraseña) y 106 que exigen sesión y un permiso |
| Documentación de la API | 157 operaciones descritas; el esquema se valida con `manage.py spectacular --validate` y sale con **0 errores y 0 advertencias** (las vistas de lavandería y reportes ya describen su petición y su respuesta) |
| Modelo de datos | 54 tablas en 9 apps (usuarios, inventario, referencias, producción, compras, calidad, producto terminado, ventas y envíos), con diagrama entidad-relación generado desde los modelos. La app de reportes no agrega tablas: lee dos vistas SQL materializadas |
| Tiempo de respuesta medido | Consulta a la base en producción (`/api/health/db/`): mediana 0,41 s, n = 15 (7 oct 2026) |

## Requerimientos

27 requerimientos funcionales y 10 no funcionales, trazados a 10 historias de usuario y 12 casos de uso en
el documento de requerimientos del proyecto. Con el Sprint 3 quedaron abordados los requerimientos **RF17 a RF26**:

| Requerimientos | Alcance | Historias |
|---|---|---|
| RF17 y RF18 | Remisión a lavandería y recepción con faltantes | TE-57, TE-58 |
| RF19 y RF20 | Catálogo de defectos y registro de prendas aptas y marras | TE-59 |
| RF21 y RF22 | Ingreso de producto terminado por talla y ajuste manual | TE-60, TE-61 |
| RF23 | Facturación y descuento de inventario al facturar | TE-62 |
| RF24 y RF25 | Guías de envío y recaudo contraentrega | TE-63, TE-64 |
| RF26 | Reportes gerenciales | TE-65 |

Pendiente: los filtros avanzados multicriterio (RF27) quedan para el Sprint 4 (TE-177); el tablero de reportes ya filtra por fechas, tipo de jean, referencia, estados y tipo de cliente.
