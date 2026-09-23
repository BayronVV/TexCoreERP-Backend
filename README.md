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

## Seed de datos

Para entrar por primera vez al ERP hace falta una cuenta con rol
`ADMIN` (los registros nuevos quedan en `PENDING` hasta que un admin
les asigna rol). Créala con:

```powershell
python manage.py seed_admin
```

Es idempotente (se puede correr varias veces sin duplicar la cuenta) y
usa `admin@texcore.test` / `Admin#2026` si no defines `ADMIN_EMAIL` /
`ADMIN_PASSWORD` en `.env`. En texcore-prod pasa una contraseña propia:

```powershell
python manage.py seed_admin --email tu-correo@empresa.com --password "Otra#Clave1"
```

`--reset-password` fuerza la contraseña también si la cuenta ya existía.

## Endpoints

| Método | Ruta                      | Descripción |
|--------|---------------------------|-------------|
| GET    | `/api/health/`            | El servidor está vivo (no toca la base de datos). |
| GET    | `/api/health/db/`         | `SELECT 1` y lista de tablas: comprueba la conexión a Supabase. |
| POST   | `/api/register/`          | Crea una cuenta (queda en rol `PENDING`). |
| POST   | `/api/token/`             | Login: devuelve tokens JWT (`access` / `refresh`). |
| POST   | `/api/token/refresh/`     | Renueva el `access` token. |
| GET    | `/api/users/`             | Lista usuarios (solo `ADMIN`). |
| PATCH  | `/api/users/<id>/role/`   | Cambia el rol de un usuario (solo `ADMIN`). |

## Control de acceso por rol (HU 1.4)

Cada vista puede declarar `permission_classes = [HasRole]` y una lista
`allowed_roles` (ver `apps/core/permissions.py`). `HasRole` corre antes
que la vista, para toda petición autenticada por JWT — es el punto de
la app que "intercepta la petición y valida si el rol tiene acceso a la
ruta" (un middleware clásico de Django no puede hacerlo aquí, porque
`request.user` solo queda resuelto cuando DRF procesa el token, no
durante el pipeline de `MIDDLEWARE`).

```python
class MiVista(generics.ListAPIView):
    permission_classes = [HasRole]
    allowed_roles = ["ADMIN", "GERENTE"]
```

`apps/core/constants.py` (`ROLE_MODULES`) documenta qué módulo del
sistema puede usar cada rol, según el diagrama de casos de uso. El
frontend mantiene la misma tabla en `src/config/roleModules.js` para
bloquear visualmente el menú lateral (TE-75); si cambias una, cambia la
otra.

## Pruebas

```powershell
python manage.py check
python manage.py test        # usa SQLite temporal, nunca la base en la nube
```

## Convenciones

- Borrado lógico, nombres y migraciones: [docs/convenciones-base-de-datos.md](docs/convenciones-base-de-datos.md)
- Ramas: trabajo diario en `pruebas` (ramas `feature/*` salen de ella); `main`
  solo recibe merges aprobados por Pull Request.
