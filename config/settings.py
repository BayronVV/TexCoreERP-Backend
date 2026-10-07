"""
Configuración de Django para TexCore.

Todo lo que cambia entre entornos (local, testing, producción) se lee de
variables de entorno o del archivo `.env`. Ver `.env.example`.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Carga backend/.env si existe. Las variables ya definidas en el sistema
# (por ejemplo en el servidor de despliegue) tienen prioridad.
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# --- Núcleo -----------------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Define DJANGO_SECRET_KEY en el entorno o en backend/.env")
    SECRET_KEY = "solo-desarrollo-no-usar-en-produccion"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
# Render define el host público del servicio; se acepta aunque no esté en la lista.
if os.getenv("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])

# --- Aplicaciones -------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    # Terceros
    "rest_framework",
    "drf_spectacular",  # documentación OpenAPI de la API (/api/docs/)
    "corsheaders",
    # Módulos de TexCore (uno por carpeta dentro de apps/)
    "apps.core",
    "apps.users",
    "apps.inventory",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

# --- Base de datos ------------------------------------------------------------
# DATABASE_URL apunta a Supabase (Postgres). Sin ella se usa SQLite local para
# poder arrancar el proyecto sin conexión. Los tests usan siempre SQLite para
# no crear bases de prueba en la nube.

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == "test"

if DATABASE_URL and not RUNNING_TESTS:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            # 0 = una conexión por petición. Con runserver (un hilo por petición) un
            # valor mayor deja conexiones abiertas y agota el pool de Supabase.
            conn_max_age=int(os.getenv("DB_CONN_MAX_AGE", "0")),
            conn_health_checks=True,
            ssl_require=env_bool("DB_SSL_REQUIRE", True),
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- API y CORS ---------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # Autenticación JWT (HU01), implementada en apps.users.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # Una vista que no declare required_permissions queda cerrada. Las públicas
    # (login, registro, recuperación, health) declaran AllowAny.
    "DEFAULT_PERMISSION_CLASSES": ["apps.core.permissions.HasPermission"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Proxies delante del backend. 0 = usar la IP de la conexión e ignorar
    # X-Forwarded-For (si no, cualquiera evade los límites cambiando ese header).
    "NUM_PROXIES": int(os.getenv("NUM_PROXIES", "0")),
    "DEFAULT_THROTTLE_RATES": {
        "login": os.getenv("THROTTLE_LOGIN", "10/minute"),
        "register": os.getenv("THROTTLE_REGISTER", "20/hour"),
        "password_reset": os.getenv("THROTTLE_PASSWORD_RESET", "5/hour"),
        "password_reset_check": os.getenv("THROTTLE_PASSWORD_RESET_CHECK", "30/hour"),
    },
}

# RF01: la sesión vence a los 30 minutos sin uso. Cada refresh entrega un
# refresh nuevo, así que mientras la persona trabaja la sesión se extiende.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(minutes=30),
    "ROTATE_REFRESH_TOKENS": True,
    # Los tokens llevan un resumen del hash de la contraseña: al cambiarla
    # (p. ej. con "olvidé mi contraseña") se invalidan las sesiones abiertas.
    "CHECK_REVOKE_TOKEN": True,
    "TOKEN_REFRESH_SERIALIZER": "apps.users.serializers.SafeTokenRefreshSerializer",
    # Registra el último acceso al iniciar sesión (se muestra en "Usuarios").
    "UPDATE_LAST_LOGIN": True,
}

# --- Documentación de la API (drf-spectacular) ----------------------------------
# /api/docs/ (Swagger UI), /api/redoc/ y /api/schema/ (OpenAPI). Para ocultarla en
# un despliegue: API_DOCS_ENABLED=false.
API_DOCS_ENABLED = env_bool("API_DOCS_ENABLED", True)

SPECTACULAR_SETTINGS = {
    "TITLE": "TexCore ERP · API",
    "DESCRIPTION": (
        "API REST del sistema ERP para la gestión y trazabilidad de la producción de jeans.\n\n"
        "Autenticación: JWT. Inicia sesión en `POST /api/token/`, copia el `access` y pulsa "
        "**Authorize** (esquema Bearer). Cada ruta exige un permiso por rol (RNF01): sin él la "
        "API responde 403; sin sesión, 401."
    ),
    "VERSION": "Sprint 1",
    "SERVE_INCLUDE_SCHEMA": False,
    # Agrupa las rutas por módulo: /api/inventario/... -> «inventario», /api/users/... -> «users»
    "SCHEMA_PATH_PREFIX": r"/api",
    # Peticiones y respuestas con esquemas separados (los campos de solo lectura no se envían)
    "COMPONENT_SPLIT_REQUEST": True,
    # Nombres claros para los enums que comparten el nombre de campo («tipo», «categoria»).
    "ENUM_NAME_OVERRIDES": {
        "TipoProductoEnum": "apps.inventory.catalog.PRODUCT_TYPES",
        "TipoOrdenEnum": "apps.inventory.catalog.ORDER_TYPES",
        "TipoMovimientoEnum": "apps.inventory.catalog.MOVEMENT_TYPES",
        "CategoriaProductoEnum": "apps.inventory.catalog.CATEGORY_CHOICES",
        "CategoriaProveedorEnum": "apps.inventory.catalog.SUPPLIER_CATEGORY_CHOICES",
    },
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True, "displayRequestDuration": True},
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

# --- Seguridad en producción (DJANGO_DEBUG=false) -----------------------------
# Detrás del proxy de Render la conexión llega por HTTP; el proxy avisa el
# esquema original en X-Forwarded-Proto. No se activa SECURE_SSL_REDIRECT porque
# Render ya redirige http -> https y el chequeo de salud del servicio entra por http.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --- Correo y recuperación de contraseña (HU 1.3) -------------------------------
# En desarrollo los correos se imprimen en la consola del runserver. Para
# guardarlos como archivos .eml usa EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend
# y EMAIL_FILE_PATH; para enviarlos de verdad, el backend SMTP con EMAIL_HOST/*.

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_FILE_PATH = os.getenv("EMAIL_FILE_PATH", str(BASE_DIR / "tmp" / "emails"))
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
# Sin tope, un servidor SMTP inalcanzable deja la petición colgada hasta que gunicorn
# mata el proceso (500). Con tope, el envío falla rápido y la API responde igual.
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "TexCore ERP <no-reply@texcore.local>")

# URL pública del frontend: se usa para armar el enlace del correo.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
PASSWORD_RESET_TOKEN_MINUTES = int(os.getenv("PASSWORD_RESET_TOKEN_MINUTES", "15"))  # RF02
ACCOUNT_INVITE_TOKEN_HOURS = int(os.getenv("ACCOUNT_INVITE_TOKEN_HOURS", "48"))

# --- Internacionalización -----------------------------------------------------

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos -------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Evidencias de inventario (fotos y PDF). No se sirven como archivos publicos: se
# descargan por un endpoint que exige permiso. En produccion moverlas a Supabase
# Storage, porque el disco de un servidor web suele ser efimero.
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(BASE_DIR / "media")))

# --- Metadatos ----------------------------------------------------------------

APP_NAME = "TexCore API"
APP_VERSION = "0.1.0"
APP_ENV = os.getenv("APP_ENV", "local")

AUTH_USER_MODEL = "users.CustomUser"

# Además de la política propia (apps/users/validators.py) se rechazan
# contraseñas comunes o parecidas a los datos de la persona.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
