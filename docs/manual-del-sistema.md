# Manual del sistema

Cómo instalar, configurar y operar TexCore. Para publicar en internet ve a
[Despliegue en Render](despliegue-render.md).

## Requisitos

- Python 3.12 o superior
- Node.js (versión LTS reciente, por Vite) para el frontend
- Una base PostgreSQL (Supabase) o, sin conexión, SQLite local
- Git

## Instalar el backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env              # Windows: copy .env.example .env
```

Edita `.env` (nunca se versiona). Lo mínimo: `DJANGO_SECRET_KEY` y, si usas Supabase, `DATABASE_URL`.
Sin `DATABASE_URL` el sistema arranca con SQLite local.

```bash
python manage.py migrate
python manage.py seed_admin          # crea el administrador inicial
python manage.py runserver           # http://localhost:8000
```

## Instalar el frontend

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

La variable `VITE_API_URL` apunta al backend (por defecto `http://localhost:8000`).

## Variables de entorno principales

| Variable | Descripción |
|---|---|
| `DJANGO_SECRET_KEY` | Clave criptográfica. Obligatoria en producción. |
| `DJANGO_DEBUG` | `true` solo en desarrollo. |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos, separados por coma. |
| `DATABASE_URL` | Cadena de Supabase (*Session pooler*). Vacía = SQLite. |
| `CORS_ALLOWED_ORIGINS` | Orígenes del frontend autorizados. |
| `NUM_PROXIES` | Proxies delante del backend (1 en Render). |
| `API_DOCS_ENABLED` | `false` oculta `/api/docs/`. Por defecto `true`. |
| `EMAIL_*`, `FRONTEND_URL` | Envío de correo para recuperar la contraseña. |

La lista completa y los valores por defecto están en `.env.example` y en el [README](https://github.com/BayronVV/TexCoreERP-Backend#readme).

## Comandos de gestión

| Comando | Para qué |
|---|---|
| `python manage.py seed_admin` | Crea (o actualiza) la cuenta administradora. Idempotente. |
| `python manage.py seed_inventario` | Carga los proveedores y productos base del inventario. |
| `python manage.py seed_demo_inventario` | Datos de demostración (solo con `DJANGO_DEBUG=true`). |
| `python manage.py generar_erd --salida docs/modelo-de-datos.md` | Regenera el [modelo de datos](modelo-de-datos.md). |
| `python manage.py test` | Ejecuta la suite de pruebas (142). |
| `python manage.py spectacular --validate --file schema.yml` | Valida y exporta el esquema OpenAPI. |

## Pruebas

```bash
python manage.py test                      # todo
python manage.py test apps.users           # solo un módulo
python manage.py test apps.inventory -v 2  # con detalle
```

Las pruebas usan siempre SQLite, nunca la base en la nube.

## Documentación

```bash
mkdocs serve        # http://127.0.0.1:8000 (usa -a 127.0.0.1:8001 si el backend ya ocupa el 8000)
mkdocs build        # genera la carpeta site/
```

## Operación y problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| Error 500 al arrancar con código nuevo | La base no tiene las migraciones: ejecuta `python manage.py migrate`. |
| 401 en todas las rutas | El `access` venció (15 min): renueva con `/api/token/refresh/` o vuelve a iniciar sesión. |
| 403 en una ruta | El rol no tiene el permiso. Se asigna en **Seguridad → Roles y permisos**. |
| No llega el correo de recuperación | Revisa `EMAIL_*`. En Render gratuito el SMTP de los puertos 25, 465 y 587 está bloqueado: se usa Brevo por el 2525 (ver [despliegue](despliegue-render.md)). |
| Las evidencias desaparecen tras desplegar | El disco de Render es efímero. Pendiente: almacenamiento persistente. |
