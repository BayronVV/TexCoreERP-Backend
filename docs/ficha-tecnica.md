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
| Documentación de la API | OpenAPI con drf-spectacular (`/api/docs/`) |
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

### Sprint 1

- **Seguridad y usuarios:** registro, inicio de sesión, recuperación de contraseña, gestión de usuarios, roles y permisos por módulo.
- **Inventario de materias primas:** proveedores, catálogo de telas e insumos, ingresos, órdenes de salida (producción y lavandería), kardex, evidencias y alertas de stock mínimo.

### Sprint 2

- **Referencias de jean (HU 3.1):** catálogo de modelos con tallas, colores, fotos del prototipo y estados (borrador, activa, descontinuada).
- **Ficha técnica de consumo (HU 3.2):** materiales por prenda con merma, PDF de la ficha extensa y consumo contra el stock.
- **Validación de material (HU 4.1):** simulación de producción contra el stock, máximo producible y cobertura por lote.
- **Órdenes y lotes (HU 4.2):** orden de producción con lotes y tallas; descuenta el material de la ficha y devuelve el stock al anular.
- **Control de tiempos (HU 4.3):** corte, confección y terminación con inicio, pausa, reanudación y fin; tiempo neto e historial.
- **Asignación de recursos (HU 4.4):** catálogo de operarios y máquinas, asignación por etapa con historial.
- **Monitor de estado (HU 4.5):** tablero Kanban de lotes con alertas por tiempo detenido y movimiento arrastrando la tarjeta.
- **Costeo y liquidación (HU 4.6):** costo promedio ponderado en las compras, tarifas de mano de obra por minuto y liquidación por orden.
- **Compras:** orden de compra (Producción) → aprobación (Gerente) → recepción de mercancía (Almacenista), con costo y kardex.
- **Datos de demostración:** comandos `seed_demo_*` para poblar un entorno de desarrollo.

## Calidad

| Aspecto | Valor |
|---|---|
| Pruebas automatizadas del backend | 683 (usuarios, inventario, referencias, producción, compras y salud), todas aprobadas |
| Pruebas automatizadas del frontend | 154 (lógica de las pantallas), todas aprobadas |
| Rutas de la API | 66 (sin contar la documentación): 8 públicas, 58 internas con sesión y 57 de ellas con permiso por rol |
| Documentación de la API | 98 operaciones descritas; el esquema se valida sin errores (4 advertencias de nombres de enumeraciones repetidas) |
| Modelo de datos | 30 tablas en 5 apps (usuarios, inventario, referencias, producción y compras), con diagrama entidad-relación generado desde los modelos |
| Tiempo de respuesta medido | Consulta a la base en producción (`/api/health/db/`): mediana 0,41 s, n = 15 (7 oct 2026) |

## Requerimientos

27 requerimientos funcionales y 10 no funcionales, trazados a 10 historias de usuario y 12 casos de uso en
el documento de requerimientos del proyecto.
