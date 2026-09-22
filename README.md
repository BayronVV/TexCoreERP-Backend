# TexCore — Backend

API REST del ERP TexCore (gestión y trazabilidad de producción de jeans).

**Stack:** Python 3.12+ · Django 5.2 LTS · Django REST Framework · PostgreSQL en Supabase

## Estructura

```
backend/
├── config/            # Configuración del proyecto (settings, urls, wsgi/asgi)
├── apps/              # Un módulo de Django por área de negocio
│   └── core/          # Transversal: endpoints de salud y modelo base (borrado lógico)
├── docs/              # Convenciones técnicas (base de datos, borrado lógico)
├── manage.py
├── requirements.txt
└── .env.example       # Plantilla de variables de entorno (sin secretos)
```

Los módulos de negocio de los próximos sprints (usuarios, inventario,
producción, ...) se agregan como `apps/<modulo>/` y se registran en
`INSTALLED_APPS`.

## Levantar en local

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                 # Linux/macOS: cp .env.example .env
# Edita .env: DJANGO_SECRET_KEY y DATABASE_URL (ver abajo)
python manage.py runserver
```

La API queda en http://localhost:8000.

## Variables de entorno

| Variable               | Obligatoria | Descripción |
|------------------------|-------------|-------------|
| `DJANGO_SECRET_KEY`    | Sí en producción | Clave criptográfica de Django. |
| `DJANGO_DEBUG`         | No (`false`) | `true` solo en desarrollo. |
| `DJANGO_ALLOWED_HOSTS` | No | Hosts permitidos, separados por coma. |
| `APP_ENV`              | No (`local`) | Nombre del entorno que muestra `/api/health/`. |
| `DATABASE_URL`         | Recomendada | Cadena de Supabase (*Session pooler*). Vacía = SQLite local. |
| `DB_SSL_REQUIRE`       | No (`true`) | Supabase exige SSL. |
| `DB_CONN_MAX_AGE`      | No (`60`) | Segundos que se reutiliza la conexión. |
| `CORS_ALLOWED_ORIGINS` | No | Orígenes del frontend autorizados. |

Base de datos por entorno: **texcore-dev** (desarrollo diario, rama
`pruebas`) y **texcore-prod** (rama `main`). Solo cambia `DATABASE_URL`.

## Endpoints

| Método | Ruta              | Descripción |
|--------|-------------------|-------------|
| GET    | `/api/health/`    | El servidor está vivo (no toca la base de datos). |
| GET    | `/api/health/db/` | `SELECT 1` y lista de tablas: comprueba la conexión a Supabase. |

## Pruebas

```powershell
python manage.py check
python manage.py test        # usa SQLite temporal, nunca la base en la nube
```

## Convenciones

- Borrado lógico, nombres y migraciones: [docs/convenciones-base-de-datos.md](docs/convenciones-base-de-datos.md)
- Ramas: trabajo diario en `pruebas` (ramas `feature/*` salen de ella); `main`
  solo recibe merges aprobados por Pull Request.
