# TexCore — Backend

API REST del ERP TexCore (gestión y trazabilidad de producción de jeans).

**Stack:** Python 3.12+ · Django 5.2 LTS · Django REST Framework · PostgreSQL en Supabase

## Estructura

```
backend/
├── config/            # Configuración del proyecto (settings, urls, wsgi/asgi)
├── apps/              # Un módulo de Django por área de negocio
│   ├── core/          # Transversal: endpoints de salud, modelo base (borrado lógico), permisos
│   └── users/         # Usuarios, roles y permisos, recuperación de contraseña
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
| `DB_CONN_MAX_AGE`      | No (`0`) | Segundos que se reutiliza la conexión (0 con runserver). |
| `NUM_PROXIES`          | No (`0`) | Proxies delante del backend; 0 ignora `X-Forwarded-For`. |
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

Salvo los marcados como públicos, todos exigen `Authorization: Bearer <access>`.

| Método | Ruta | Permiso | Descripción |
|--------|------|---------|-------------|
| GET | `/api/health/`, `/api/health/db/` | público | Estado del servidor y de la base. |
| POST | `/api/register/` | público | Solicitud de cuenta; queda en rol `PENDING` con el área pedida. |
| POST | `/api/token/`, `/api/token/refresh/` | público | Login JWT. El correo no distingue mayúsculas; cada refresh entrega un refresh nuevo. |
| GET | `/api/auth/me/` | sesión | Usuario activo con su rol y permisos efectivos. |
| POST | `/api/auth/password-reset/` | público | Pide el correo de recuperación. Responde igual exista o no la cuenta. |
| POST | `/api/auth/password-reset/validate/` | público | `{token}`: ¿el enlace sigue vigente? Devuelve `purpose` y el correo. |
| POST | `/api/auth/password-reset/confirm/` | público | `{token, password, password_confirm}`: guarda la nueva contraseña. |
| GET, POST | `/api/users/` | `seguridad.ver` / `seguridad.gestionar` | Lista usuarios / crea uno y le envía la invitación. |
| GET, PATCH, DELETE | `/api/users/<id>/` | `seguridad.ver` / `seguridad.gestionar` | Ver, cambiar rol, activar/desactivar, borrado lógico. |
| POST | `/api/users/<id>/invite/` | `seguridad.gestionar` | Reenvía el enlace para definir contraseña. |
| GET, POST | `/api/roles/` | `seguridad.ver` / `seguridad.roles` | Roles con sus permisos y cantidad de usuarios / crear rol. |
| GET, PATCH, DELETE | `/api/roles/<id>/` | `seguridad.ver` / `seguridad.roles` | Ver, editar permisos, eliminar (solo roles no base y sin usuarios). |
| GET | `/api/permissions/` | `seguridad.ver` | Catálogo de permisos por módulo. |

## Roles y permisos (HU 1.4)

Tablas `seguridad_rol`, `seguridad_permiso` y `seguridad_rol_permiso`
(modelos `Role`, `ModulePermission`, `RolePermission` en `apps/users`).
`CustomUser.role` es una llave foránea a `seguridad_rol.code`: la columna
sigue guardando el código (`ADMIN`, `VENDEDOR`...), así el JWT y el
frontend no cambian.

- Cada módulo tiene los permisos `<modulo>.ver` y `<modulo>.gestionar`;
  Seguridad además tiene `seguridad.roles`.
- `ADMIN` tiene todos los permisos de forma implícita y no se puede
  restringir. `PENDING` no puede tener permisos.
- Reglas de RF03: nadie cambia su propio rol ni se desactiva o elimina a
  sí mismo, y siempre debe quedar al menos un administrador activo que
  pueda entrar (una cuenta invitada sin contraseña no cuenta).
- Delegación: alguien con `seguridad.gestionar` o `seguridad.roles` que no
  es ADMIN puede administrar roles y usuarios operativos, pero no puede
  crear ni tocar administradores, asignar roles con permisos de Seguridad,
  dar o quitar permisos de Seguridad, ni editar los permisos de su propio
  rol. Así nadie puede fabricarse un administrador.
- "Registrar y modificar" en un módulo exige también "Ver" ese módulo.
- Los datos iniciales salen del diagrama de casos de uso
  (migración `0003_roles_y_permisos`); después se administran desde la
  pantalla "Roles y permisos".

**Validación en cada ruta (TE-77):** las vistas declaran
`permission_classes = [HasPermission]` y `required_permissions`
(`apps/core/permissions.py`). DRF lo ejecuta antes del handler en cada
petición, con el usuario del JWT ya resuelto (un middleware clásico de
Django no lo tendría todavía). Si una vista no declara el permiso, se
niega el acceso.

```python
class MiVista(generics.ListCreateAPIView):
    permission_classes = [HasPermission]
    required_permissions = {"GET": "inventario.ver", "POST": "inventario.gestionar"}
```

## Sesión (RF01)

El access token dura 15 minutos y el refresh 30, y cada refresh entrega uno
nuevo: la sesión vence tras 30 minutos sin uso. El login tiene un límite de
10 intentos por minuto por IP.

## Recuperación de contraseña (HU 1.3)

1. `POST /api/auth/password-reset/` con el correo. Si la cuenta existe y
   está activa se envía un enlace `FRONTEND_URL/restablecer-contrasena?token=...`.
2. El token es aleatorio (`secrets.token_urlsafe`), se guarda solo su
   SHA-256 en `seguridad_token_recuperacion`, vence en 15 minutos (RF02),
   sirve una sola vez y pedir uno nuevo invalida los anteriores.
3. Límites: 5 solicitudes por hora por IP (la IP de la conexión; ver
   `NUM_PROXIES` si hay un proxy delante) y 3 correos por hora por usuario.
   Si el correo no se puede enviar la respuesta es la misma, para no
   revelar qué cuentas existen.
5. Al cambiar la contraseña se cierran las sesiones abiertas: los tokens
   emitidos antes dejan de servir.
4. Las cuentas creadas por un administrador reciben el mismo tipo de
   enlace (`purpose=invite`, vigencia 48 h) para definir su contraseña.

En desarrollo el correo se imprime en la consola del `runserver`; ver
`.env.example` para guardarlo como archivo o enviarlo por SMTP.

## Despliegue

Render (Web Service Python) con gunicorn. Pasos, variables de entorno, CORS y
limitaciones en [`docs/despliegue-render.md`](docs/despliegue-render.md).

## Pruebas

```powershell
python manage.py check
python manage.py test        # usa SQLite temporal, nunca la base en la nube
```

## Convenciones

- Borrado lógico, nombres y migraciones: [docs/convenciones-base-de-datos.md](docs/convenciones-base-de-datos.md)
- Ramas: trabajo diario en `pruebas` (ramas `feature/*` salen de ella); `main`
  solo recibe merges aprobados por Pull Request.

## Inventario (HU 2.1 a 2.4)

App `apps/inventory`. Todo bajo `/api/inventario/`; ver requiere `inventario.ver` y registrar `inventario.gestionar`.

| Endpoint | Qué hace |
|----------|----------|
| `GET metadatos/` | Categorías, unidades compatibles y reglas del catálogo (las pantallas las leen de aquí). |
| `GET productos/` | Productos **con existencias**, para Inventario. Solo lectura. |
| `GET/POST catalogo/`, `GET/PATCH/DELETE catalogo/<id>/` | Catálogo de telas e insumos (HU 2.2). **No expone existencias**: el saldo solo cambia con movimientos. Filtros `?categoria=` y `?q=`. |
| `GET/POST/DELETE catalogo/<id>/imagen/` | Imagen de referencia (JPG/PNG/WEBP, máx. 2 MB). Se guarda en la base y se sirve con sesión. |
| `GET/POST proveedores/`, `GET/PATCH/DELETE proveedores/<id>/` | Proveedores (HU 2.1, RF04). NIT único entre activos; `?q=`, `?categoria=`, `?archivados=1`. |
| `POST proveedores/<id>/restaurar/` | Reactiva un proveedor archivado (si su NIT sigue libre). |
| `POST ingresos/` | Ingreso. Compras: proveedor (id de la lista) y lote obligatorios. Pantalones: solo cerrando la orden OP/LV que los fabricó. |
| `GET/POST ordenes/` | Salidas con varias líneas ("cesta"). Numeran `OP-0001` (producción) y `LV-0001` (lavandería). |
| `POST ordenes/<id>/anular/` | Anula una orden en proceso y devuelve el stock. |
| `GET movimientos/` | Kardex: cada cambio de saldo con saldo antes y después. |
| `POST movimientos/<id>/evidencias/`, `POST ordenes/<id>/evidencias/` | Fotos JPG/PNG/WEBP o PDF (5 MB, hasta 10). Se validan por contenido. |
| `GET evidencias/<id>/archivo/` | Descarga con sesión; los archivos no son públicos. |
| `GET alertas/` | Productos cuyo saldo llegó al mínimo. |

**Catálogo (RF05).** Cada producto tiene una categoría (telas, hilos, cierres, botones y remaches,
etiquetas y empaque, químicos, otros insumos, pantalón genérico, producto terminado) que fija su tipo,
las unidades compatibles y los datos obligatorios: las **telas** exigen ancho útil (0 a 5 m, lo usa el
corte computarizado) y las telas y los hilos exigen composición con porcentajes que sumen 100
(`80% algodón / 20% nylon`). El código se asigna solo por categoría (`TEL-0001`, `HIL-0001`...). La
categoría y la unidad no cambian cuando el producto ya tiene movimientos.

**Proveedores (RF04).** NIT con 6 a 10 dígitos y dígito de verificación opcional (se guarda normalizado;
`890.900.001-4` y `890900001-4` son el mismo). Se clasifican por el tipo de insumo que suministran. Los
ingresos de compra eligen un proveedor activo y el kardex guarda también su nombre de ese momento. Los
"insumos vinculados" son los distintos productos que se han recibido de él.

Flujo: `OP` saca tela e insumos y al terminar entra el pantalón genérico; `LV` saca genéricos
más botones e insumos y al volver entra el producto terminado del modelo. Una salida con stock
insuficiente se rechaza completa y devuelve `faltantes`. Los saldos se bloquean por fila, así
que dos salidas simultáneas no pueden dejar el stock en negativo.

Las imágenes del catálogo viven en la base (columna `imagen`), por eso sobreviven a los redespliegues. Las evidencias se guardan en `MEDIA_ROOT` (por defecto `backend/media/`, ignorado por git).
En producción hay que moverlas a Supabase Storage.

`python manage.py seed_inventario` crea proveedores y un catálogo de ejemplo (solo con `DJANGO_DEBUG=true`).

**Migraciones 0002 y 0003.** La 0002 convierte el texto libre `proveedor` de los movimientos en
`proveedor_nombre` (no se pierde el historial) y agrega la llave `proveedor`; la 0003 clasifica los
productos anteriores por su nombre. Si la base la comparte un backend desplegado con la versión anterior,
esa versión falla en el historial de movimientos hasta que se despliegue la nueva.
