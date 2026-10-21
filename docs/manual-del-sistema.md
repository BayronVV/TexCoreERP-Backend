# Manual del sistema

Cómo instalar, configurar y operar TexCore. Para publicar en internet ve a
[Despliegue en Render](despliegue-render.md).

## Requisitos

- Python 3.12 o superior
- Node.js 20.19 o superior (versión LTS reciente, por Vite) para el frontend
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

`migrate` crea las tablas de todos los módulos y carga los roles y permisos iniciales (incluidos los de referencias,
fichas técnicas y compras). Al terminar, activa RLS en las tablas de Supabase (ver
[convenciones](convenciones-base-de-datos.md#4-seguridad-en-supabase)).

Para trabajar **sin conexión** deja `DATABASE_URL` vacío: el sistema usa un archivo SQLite local (`db.sqlite3`, ignorado por
git). Así se prueba sin tocar Supabase. Las pruebas automáticas siempre usan SQLite, aunque `DATABASE_URL` esté definida.

## Instalar el frontend

```bash
cd frontend
npm install
copy .env.example .env.local         # Linux/macOS: cp .env.example .env.local
npm run dev                          # http://localhost:5173
```

La variable `VITE_API_URL` apunta al backend (por defecto `http://localhost:8000`). Otros comandos del frontend: `npm run build`
(genera `dist/`), `npm run lint` (oxlint) y `npm test` (pruebas de la lógica de las pantallas con `node --test`).

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
| `APP_ENV` | Nombre del entorno que muestra `/api/health/` (`local`, `dev`, `prod`). |
| `DB_SSL_REQUIRE`, `DB_CONN_MAX_AGE` | SSL de la base (`true` en Supabase) y segundos que se reutiliza una conexión (`0` para no agotar el pool). |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL`, `FRONTEND_URL` | Envío de correo para recuperar la contraseña y armar el enlace. |
| `PASSWORD_RESET_TOKEN_MINUTES`, `ACCOUNT_INVITE_TOKEN_HOURS` | Vigencia del enlace de recuperación (15 min) y de la invitación (48 h). |
| `MEDIA_ROOT` | Carpeta de las evidencias de inventario (por defecto `backend/media/`). |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Datos que usa `seed_admin` si no se pasan por argumento. |

La lista completa y los valores por defecto están en `.env.example` y en el [README](https://github.com/BayronVV/TexCoreERP-Backend#readme).

## Comandos de gestión

| Comando | Para qué |
|---|---|
| `python manage.py seed_admin` | Crea (o actualiza) la cuenta administradora. Idempotente. |
| `python manage.py seed_inventario` | Carga los proveedores y productos base del inventario (solo con `DJANGO_DEBUG=true`). |
| `python manage.py seed_demo_inventario` | Catálogo completo, compras con costo y órdenes de salida (incluye `seed_inventario` y `seed_demo_referencias`). |
| `python manage.py seed_demo_referencias` | Referencias de jean en sus tres estados, con fotos y fichas técnicas. |
| `python manage.py seed_demo_produccion` | Órdenes de producción con lotes, tallas y tiempos de ejemplo. |
| `python manage.py seed_demo_recursos` | Operarios y máquinas, asignados a las etapas en curso. |
| `python manage.py seed_demo_compras` | Órdenes de compra: borrador, aprobada y con recepción parcial. |
| `python manage.py generar_erd --salida docs/modelo-de-datos.md` | Regenera el [modelo de datos](modelo-de-datos.md). |
| `python manage.py test` | Ejecuta la suite de pruebas (683). |
| `python manage.py spectacular --validate --file schema.yml` | Valida y exporta el esquema OpenAPI (borra después `schema.yml`). |

## Datos de demostración

Para ver el sistema con información (por ejemplo, el Monitor de estado con lotes en distintos estados) existen comandos de
demostración. **Solo funcionan con `DJANGO_DEBUG=true`** y nunca deben correrse en producción. Pasan por las mismas reglas
que la aplicación, así que el kardex, los saldos y los códigos quedan coherentes, y son idempotentes: lo que ya existe no se repite.

```bash
python manage.py seed_admin               # 1. un usuario para entrar y quien firma lo sembrado
python manage.py seed_demo_inventario     # 2. proveedores, catálogo, compras con costo, referencias con ficha y salidas
python manage.py seed_demo_produccion     # 3. órdenes con lotes, tallas y tiempos (incluye un lote detenido con alerta)
python manage.py seed_demo_recursos       # 4. operarios y máquinas asignados a las etapas en curso
python manage.py seed_demo_compras        # 5. órdenes de compra en borrador, aprobada y con recepción parcial
```

- Los pasos 3 a 5 necesitan el 2. `seed_demo_inventario` ya ejecuta `seed_inventario` y `seed_demo_referencias`.
- Los usuarios que participan se toman de los que ya existen: `seed_demo_compras` busca uno de Producción para crear, un Gerente
  o Administrador para aprobar y un Almacenista distinto del creador para recibir; si falta el Almacenista, la orden queda
  aprobada sin recepción.
- No se siembran tarifas de mano de obra: en la **Liquidación de Órdenes** la mano de obra aparece *Sin tarifa* hasta que alguien
  registre una en la pestaña **Tarifas por Minuto**.
- Las cuentas que se usen para mirar la demo se crean desde **Seguridad y Usuarios**; no hay usuarios de demostración por rol.

## Pruebas

```bash
python manage.py test                      # todo
python manage.py test apps.users           # solo un módulo
python manage.py test apps.inventory -v 2  # con detalle
python manage.py test --parallel 4         # en paralelo, más rápido
```

La suite cubre `users`, `inventory`, `references`, `production`, `purchasing` y `core`. Las pruebas de los comandos de demostración
(`test_seed*.py`) verifican que sean idempotentes. En el frontend, `npm test` prueba la lógica pura de las pantallas (reparto de
lotes, tablero, costeo, recursos, compras...).

Las pruebas usan siempre SQLite, nunca la base en la nube.

## Documentación

```bash
mkdocs serve        # http://127.0.0.1:8000 (usa -a 127.0.0.1:8001 si el backend ya ocupa el 8000)
mkdocs build        # genera la carpeta site/
mkdocs build --strict   # lo que corre la publicación: falla si hay un enlace roto o una advertencia
```

El sitio se publica solo en GitHub Pages cuando cambian `docs/` o `mkdocs.yml` en `main`. El modelo de datos se regenera con
`python manage.py generar_erd --salida docs/modelo-de-datos.md` cada vez que cambia un modelo (no se edita a mano).

## Operación y problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| Error 500 al arrancar con código nuevo | La base no tiene las migraciones: ejecuta `python manage.py migrate`. |
| 401 en todas las rutas | El `access` venció (15 min): renueva con `/api/token/refresh/` o vuelve a iniciar sesión. |
| 403 en una ruta | El rol no tiene el permiso. Se asigna en **Seguridad → Roles y permisos**. |
| No llega el correo de recuperación | Revisa `EMAIL_*`. En Render gratuito el SMTP de los puertos 25, 465 y 587 está bloqueado: se usa Brevo por el 2525 (ver [despliegue](despliegue-render.md)). |
| Las evidencias desaparecen tras desplegar | El disco de Render es efímero. Pendiente: almacenamiento persistente. |
| Un comando `seed_demo_*` dice que solo funciona con `DJANGO_DEBUG=true` | Es a propósito: no se siembran datos de demostración fuera de desarrollo. |
| La recepción de mercancía responde que quien creó la orden no puede recibirla | Separación de funciones: la recibe otro usuario con permiso de inventario (Almacenista). |
| La liquidación muestra *Sin tarifa* o *Sin costo* | Falta registrar la tarifa por minuto de la etapa, o la compra del material no trajo costo unitario. El cálculo se marca como parcial. |
| Se creó una orden de producción y dice que falta material | El stock cambió entre la simulación y la creación; la orden no se guarda. Revisa la disponibilidad y vuelve a intentar. |
