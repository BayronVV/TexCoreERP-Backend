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
| Frontend | React 19 · Vite 8 · React Router 7 · Axios |
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

## Alcance entregado en el Sprint 1

- **Seguridad y usuarios:** registro, inicio de sesión, recuperación de contraseña, gestión de usuarios, roles y permisos por módulo.
- **Inventario de materias primas:** proveedores, catálogo de telas e insumos, ingresos, órdenes de salida (producción y lavandería), kardex, evidencias y alertas de stock mínimo.

## Calidad

| Aspecto | Valor |
|---|---|
| Pruebas automatizadas del backend | 142 (usuarios, inventario y salud), todas aprobadas |
| Rutas de la API | 32 (sin contar la documentación): 8 públicas, 24 internas con sesión y 23 de ellas con permiso por rol |
| Documentación de la API | 47 operaciones descritas, esquema validado sin advertencias |
| Tiempo de respuesta medido | Consulta a la base en producción (`/api/health/db/`): mediana 0,41 s, n = 15 (7 oct 2026) |

## Requerimientos

27 requerimientos funcionales y 10 no funcionales, trazados a 10 historias de usuario y 12 casos de uso en
el documento de requerimientos del proyecto.
