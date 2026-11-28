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
pip install -r requirements-dev.txt -c constraints.txt
cp .env.example .env              # Windows: copy .env.example .env
```

Edita `.env` (nunca se versiona). Lo mínimo: `DJANGO_SECRET_KEY` y, si usas Supabase, `DATABASE_URL`.
Sin `DATABASE_URL` el sistema arranca con SQLite local.

```bash
python manage.py migrate
python manage.py seed_admin          # crea el administrador inicial
python manage.py runserver           # http://localhost:8000
```

`migrate` crea las tablas de todos los módulos (56 en 9 apps), las dos vistas SQL de los reportes gerenciales y carga los roles y permisos iniciales (31 permisos: incluidos los de referencias,
fichas técnicas, compras, lavandería, calidad, producto terminado, ventas, envíos y reportes). Al terminar, activa RLS en las tablas de Supabase (ver
[convenciones](convenciones-base-de-datos.md#4-seguridad-en-supabase)). En Render corre solo en cada arranque (ver [despliegue](despliegue-render.md)).

Para trabajar **sin conexión** deja `DATABASE_URL` vacío: el sistema usa un archivo SQLite local (`db.sqlite3`, ignorado por
git). Así se prueba sin tocar Supabase. Por defecto, las pruebas automáticas (`manage.py test`) usan SQLite y cifrado rápido (`MD5PasswordHasher` solo en pruebas), salvo que definas `TEST_DATABASE_URL` para probar contra un PostgreSQL dedicado.

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
| `TEST_DATABASE_URL`, `TEST_DB_SSL_REQUIRE` | Opcional: cadena PostgreSQL dedicada para correr `manage.py test` sin tocar `DATABASE_URL` (p. ej. en CI o en un Postgres local). |
| `CORS_ALLOWED_ORIGINS` | Orígenes del frontend autorizados. |
| `NUM_PROXIES`, `THROTTLE_*` | Proxies delante del backend (1 en Render) y límites de tasa (`login`, `register`, `password_reset`, `password_reset_check`). |
| `API_DOCS_ENABLED`, `SECURE_HSTS_SECONDS` | Visibilidad de `/api/docs/` (por defecto solo con `DJANGO_DEBUG=true`; en producción se enciende con `API_DOCS_ENABLED=true`) y cabecera HSTS cuando `DJANGO_DEBUG=false`. |
| `DJANGO_LOG_LEVEL`, `DJANGO_DB_LOG_LEVEL` | Niveles del registro en consola (`INFO` para la aplicación y `WARNING` para consultas SQL por defecto). |
| `APP_ENV` | Nombre del entorno que muestra `/api/health/` (`local`, `dev`, `prod`). |
| `DB_SSL_REQUIRE`, `DB_CONN_MAX_AGE` | SSL de la base (`true` en Supabase) y segundos que se reutiliza una conexión (`0` para no agotar el pool). |
| `DB_PROD_REF` | Referencia pública del proyecto de Supabase de producción (`texcore-prod`). Con `DJANGO_DEBUG=true` o en las pruebas, la aplicación no arranca si la base apunta a ese proyecto (TE-185). Ver [ambientes](despliegue-render.md#ambientes-desarrollo-y-produccion-te-185). |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL`, `FRONTEND_URL` | Envío de correo para recuperar la contraseña y armar el enlace. |
| `PASSWORD_RESET_TOKEN_MINUTES`, `ACCOUNT_INVITE_TOKEN_HOURS` | Vigencia del enlace de recuperación (15 min) y de la invitación (48 h). |
| `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCK_MINUTES` | Intentos fallidos seguidos que bloquean la cuenta (3) y minutos de bloqueo (15). |
| `MEDIA_ROOT` | Carpeta de las evidencias de inventario (por defecto `backend/media/`). |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Datos que usa `seed_admin` si no se pasan por argumento. |
| `SEED_DEMO_ON_DEPLOY` | `true` siembra los datos de demostración (simulados) al final del `migrate` del arranque, con `seed_demo_completo --permitir-produccion`. Por defecto `false`. Idempotente, no borra nada y un fallo de la siembra no impide el arranque. Se apaga solo al correr `manage.py test`. |
| `TRACK123_API_KEY` | Clave de la API de Track123 para consultar el estado de las guías (HU 7.2). Secreto: va en el `.env` local (git lo ignora) y en las variables de Render, nunca en el repositorio. Vacía = rastreo apagado. |
| `TRACK123_ENABLED` | `true` enciende el rastreo; por defecto `false`. Se apaga solo al correr `manage.py test`. |
| `TRACK123_BASE_URL`, `TRACK123_TIMEOUT`, `TRACK123_COOLDOWN_MINUTES`, `TRACK123_QUOTA_RESERVE` | Opcionales. Por defecto: ruta `https://api.track123.com/gateway/open-api/tk/v2.1`, 10 segundos de espera, 10 minutos de enfriamiento entre consultas de una misma guía y 10 registros de cuota de reserva. |

La lista completa y los valores por defecto están en `.env.example` y en el [README](https://github.com/BayronVV/TexCoreERP-Backend#readme).

## Comandos de gestión

| Comando | Para qué |
|---|---|
| `python manage.py seed_admin` | Crea (o actualiza) la cuenta administradora. Idempotente. |
| `python manage.py seed_inventario` | Carga los proveedores y productos base del inventario (solo con `DJANGO_DEBUG=true`). |
| `python manage.py seed_demo_inventario` | Catálogo completo, compras con costo y órdenes de producción de ejemplo (incluye `seed_inventario` y `seed_demo_referencias`; ya no siembra órdenes provisionales `LV` desde TE-171). |
| `python manage.py seed_demo_referencias` | Referencias de jean en sus tres estados, con fotos y fichas técnicas. |
| `python manage.py seed_demo_produccion` | Órdenes de producción con lotes, tallas y tiempos de ejemplo. |
| `python manage.py seed_demo_recursos` | Operarios y máquinas, asignados a las etapas en curso. |
| `python manage.py seed_demo_compras` | Órdenes de compra: borrador, aprobada y con recepción parcial. |
| `python manage.py seed_demo_calidad` | 8 defectos típicos de denim y dos lotes devueltos de lavandería: uno inspeccionado y otro por inspeccionar. Necesita antes `seed_demo_inventario` y `seed_demo_produccion`. |
| `python manage.py seed_demo_terminado` | Ingresa al inventario final (producto terminado) las aptas de la inspección de demostración, por las mismas reglas de la aplicación. Necesita antes `seed_demo_calidad`. |
| `python manage.py seed_demo_ventas` | 4 clientes (distribuidor, mayoristas y detal), el costo de fábrica y los precios de demostración de las referencias activas, la caja general (saldo financiero en cero) y, si todavía no hay facturas, hasta 3 facturas de demostración: la primera sale de una talla y color que entró desde un lote real (para seguir la trazabilidad de la factura al lote) y las otras de `REF-0001`. Necesita antes las referencias de demostración (`seed_demo_referencias`) y, para facturar, el stock de producto terminado (`seed_demo_terminado`). |
| `python manage.py seed_demo_envios` | Guías de demostración (HU 7.2): las 3 guías reales de Interrapidísimo del PO quedan entregadas con la respuesta real guardada, y guías sintéticas (marcadas) para ver todo el semáforo: por despachar, en tránsito dentro de una relación, con novedad, devuelta con su flete y una factura sin guía. Idempotente, solo con `DJANGO_DEBUG=true` y **no llama a Track123 ni gasta cuota**. Necesita antes `seed_demo_ventas` y stock de producto terminado. |
| `python manage.py seed_demo_lavanderia` | Lavanderías (proveedores de la categoría lavandería) y cuatro recetas de lavado con su tarifa. Idempotente y, como los demás `seed_demo_*`, solo con `DJANGO_DEBUG=true`. Forma parte de `seed_demo_completo` (antes de calidad, que envía y recibe los lotes de ejemplo). |
| `python manage.py seed_demo_tarifas` | Una tarifa de mano de obra por minuto para corte, confección y terminación (vigentes desde el 1 de enero de 2026), para que la liquidación de las órdenes no marque el costo como incompleto. Idempotente. |
| `python manage.py seed_demo_stock` | Entre 12 y 20 unidades en cada talla y color de las referencias activas, por ajuste manual (motivo «Sobrante o hallazgo», con su comprobante `AJT`). Solo sube lo que está por debajo de la meta y ajusta cada talla y color una sola vez: correrlo de nuevo no duplica ajustes aunque las ventas de la demo hayan bajado el stock. |
| `python manage.py seed_demo_completo` | **Todo en uno**: encadena inventario, producción, recursos, tarifas, compras, lavandería, calidad, producto terminado, stock por talla y color, ventas y envíos, en su orden; salta los módulos que ya tienen datos y al final imprime cuántos registros tiene cada módulo (falla si alguno quedó vacío). Con `--permitir-produccion` corre también con `DJANGO_DEBUG=false`: es la siembra de los datos **simulados** de la demostración sobre la base compartida; no borra nada ni toca usuarios, roles ni permisos. Es el comando que dispara `SEED_DEMO_ON_DEPLOY`. |
| `python manage.py reiniciar_datos_demo --confirmar` | **Reinicio de la demostración (TE-183):** vacía todas las tablas de los módulos de negocio (tomadas de los modelos; reinicia sus consecutivos), vuelve a correr `seed_demo_completo` y la comprobación de coherencia, todo en una sola transacción: si algo falla, la base queda como estaba. **Conserva** usuarios, roles, permisos, accesos, tokens y la auditoría, y deja una fila `demo.reiniciar` en ella. Pide escribir el nombre de la base (`--no-input` lo omite); con `DJANGO_DEBUG=false` exige además `--permitir-produccion`. Nunca lo dispara el arranque de Render. |
| `python manage.py verificar_coherencia_demo` | Solo lee y falla si algo no cuadra: en inventario, producto terminado y cartera cada saldo es el de su último movimiento y cada movimiento parte del saldo del anterior (incluidos los de borrado lógico); no hay registros huérfanos ni movimientos de producto terminado sin documento; al menos un lote se recorre completo y una factura llega a su lote de origen (HU 7.6). Además, cada referencia activa tiene su producto terminado enlazado en Inventario y lo que Inventario muestra es la suma de sus tallas y colores (HU 6.5). |
| `python manage.py purgar_registros` | Borra los accesos y la auditoría de más de 12 meses (`--meses N`, `--simular` para solo contar) y deja la purga registrada. Conviene programarlo (cron de Render). |
| `python manage.py generar_erd --salida docs/modelo-de-datos.md` | Regenera el [modelo de datos](modelo-de-datos.md), con la última migración de cada módulo, la fecha y el commit con que se generó. |
| `python manage.py verificar_mer` | Solo lee: compara el modelo de datos (claves primarias y foráneas, restricciones únicas y de chequeo, nulos y cardinalidades del MER) con la base conectada y falla si no coinciden (TE-188). |
| `python manage.py test` | Ejecuta la suite de pruebas (1133 en backend). |
| `python manage.py makemigrations --check --dry-run` | Verifica que no existan migraciones pendientes. |
| `ruff check apps config` | Ejecuta el linter estático del backend. |
| `coverage run manage.py test && coverage report` | Mide la cobertura real sobre `apps/`. |
| `python manage.py spectacular --validate --fail-on-warn --file schema.yml` | Valida y exporta el esquema OpenAPI (borra después `schema.yml`). |

## Datos de demostración

Para ver el sistema con información (por ejemplo, el Monitor de estado con lotes en distintos estados) existen comandos de
demostración. Los `seed_demo_*` sueltos **solo funcionan con `DJANGO_DEBUG=true`**; la única forma de sembrar con `DJANGO_DEBUG=false` es
`seed_demo_completo --permitir-produccion` (o la variable `SEED_DEMO_ON_DEPLOY=true` en Render). Pasan por las mismas reglas
que la aplicación, así que el kardex, los saldos y los códigos quedan coherentes, y son idempotentes: lo que ya existe no se repite.

!!! note "Los datos de los servidores de Render son simulados"
    La base compartida de desarrollo y de la demostración desplegada en Render (<https://texcore-web.onrender.com>) contiene solo datos de
    demostración: clientes, facturas, guías, lotes y existencias inventados para mostrar el sistema. Se pueden modificar o completar sin
    riesgo, pero no son información real de una empresa. La siembra nunca toca los usuarios, los roles ni los permisos.

```bash
python manage.py seed_admin               # 1. un usuario para entrar y quien firma lo sembrado
python manage.py seed_demo_inventario     # 2. proveedores, catálogo, compras con costo, referencias con ficha y órdenes OP
python manage.py seed_demo_produccion     # 3. órdenes con lotes, tallas y tiempos (incluye un lote detenido con alerta)
python manage.py seed_demo_recursos       # 4. operarios y máquinas asignados a las etapas en curso
python manage.py seed_demo_compras        # 5. órdenes de compra en borrador, aprobada y con recepción parcial
python manage.py seed_demo_calidad        # 6. defectos típicos y dos lotes devueltos de lavandería (uno ya inspeccionado)
python manage.py seed_demo_terminado      # 7. ingresa al inventario final las aptas de la inspección de demostración
python manage.py seed_demo_ventas         # 8. clientes, precios y, si hay stock, hasta 3 facturas de demostración
python manage.py seed_demo_envios         # 9. guías de demostración: las 3 reales entregadas y otras sintéticas para el semáforo
python manage.py seed_demo_lavanderia     # lavanderías y recetas de lavado (también va dentro de seed_demo_completo)
# o, todo de una vez (incluye lavandería, tarifas y stock por talla y color):
python manage.py seed_demo_completo       # --permitir-produccion para correrlo contra la base de producción (datos simulados)
# para empezar de cero (borra los datos de negocio, conserva usuarios y permisos) y comprobar:
python manage.py reiniciar_datos_demo --confirmar
python manage.py verificar_coherencia_demo
```

- El paso 8 necesita las referencias del 2 y, para tener prendas que facturar, el 7; las demás facturas se hacen en vivo desde **Ventas y Despachos → Nueva venta**.
- El paso 9 emite sus propias facturas de demostración (observaciones «Demo envíos: …») por las mismas reglas que *Nueva venta*, así que necesita el 8 y stock de producto terminado (el 7). Puede correrse varias veces: no duplica nada. Si las facturas demo de la HU 7.3 traen guías ficticias, las reemplaza por las tres reales.
- Los pasos 3 a 7 necesitan el 2; el 6 necesita además el 3 (los lotes salen de las órdenes de producción) y el 7 necesita el 6 (ingresa las aptas de la inspección de demostración). `seed_demo_inventario` ya ejecuta `seed_inventario` y `seed_demo_referencias`.
- Los usuarios que participan se toman de los que ya existen: `seed_demo_compras` busca uno de Producción para crear, un Gerente
  o Administrador para aprobar y un Almacenista distinto del creador para recibir; si falta el Almacenista, la orden queda
  aprobada sin recepción.
- `seed_demo_tarifas` (parte de `seed_demo_completo`) siembra una tarifa por etapa; si no se corre, en la **Liquidación de Órdenes** la mano de
  obra aparece *Sin tarifa* hasta que alguien registre una en la pestaña **Tarifas por Minuto**.
- Las cuentas que se usen para mirar la demo se crean desde **Seguridad y Usuarios**; no hay usuarios de demostración por rol.

## Rastreo de guías con Track123 (HU 7.2)

El módulo de envíos puede consultar el estado real de las guías de **Interrapidísimo** en la API de Track123. Es opcional: sin `TRACK123_API_KEY`
o con `TRACK123_ENABLED=false` todo funciona y los estados se cambian a mano.

Para encenderlo en local: pide la clave en Track123 (Developers > API), escríbela en tu `.env` (`TRACK123_API_KEY=<tu-clave>` y `TRACK123_ENABLED=true`) y reinicia.
**Nunca la subas al repositorio ni la pegues en un chat o un documento**; en Render va solo como variable de entorno (ver [despliegue](despliegue-render.md#rastreo-de-guias-con-track123)).

**Cuida la cuota.** El plan actual permite **50 registros de guías nuevas**: registrar una guía gasta 1, consultar una ya registrada no gasta. Por eso:

- El rastreo es **siempre manual** (botón **Consultar estado**); ninguna pantalla ni tarea lo dispara sola.
- Cada guía se registra una vez, no se vuelve a consultar antes de 10 minutos y la última respuesta queda guardada y se muestra sin llamar de nuevo.
- Con 10 registros o menos de cuota ya no se inscriben guías nuevas. `GET /api/envios/rastreo/estado/` (o el contador de la pantalla) muestra lo que queda sin gastar nada.
- No uses guías de prueba inventadas: cada intento de registrar una gasta cuota. Para la demostración existe `seed_demo_envios`, que no consulta.

**Verificaciones hechas** con la clave real del PO (8 de noviembre de 2026), que corrigen la documentación del proveedor:

- Las rutas vigentes son `/tk/v2.1/...` (no las anteriores).
- El `courierCode` de Interrapidísimo es `inter-rapidisimo-inter-rapidsimo` y hay que enviarlo siempre: con la autodetección, 2 de las 3 guías reales quedaron con otra transportadora y respondieron `NO_RECORD`.
- Registrar gasta 1 de cuota por guía y consultar no gasta.
- Una clave inválida **no** da un error HTTP: Track123 responde `200` con el código `B0001`. El sistema lo trata como «clave no válida» (503 para el usuario, sin mostrar la clave).
- Una guía no registrada llega en `rejected` con «trackNo not registered».
- No existe un estado «devuelto»: la devolución viene dentro de `ABNORMAL` (sub-estados `ABNORMAL_05`, `06` y `07`).
- Las tres guías de referencia (`700187211301`, `700180879081`, `700200165317`) salen `DELIVERED` con seis eventos cada una; sus respuestas, sin la clave, son los datos de prueba (`apps/shipping/fixtures/track123_entregadas.json`).

**Las pruebas automáticas jamás llaman a la API real:** al correr `manage.py test` el rastreo queda apagado y el transporte HTTP se reemplaza por respuestas guardadas.

## Observabilidad y manejo global de errores (TE-181)

- **Registro hacia la consola de Render (`LOGGING`):** todas las trazas de la aplicación (`apps`, `django`, `django.request`) se envían a consola (`StreamHandler`) con marca temporal, nivel y módulo, incluso cuando `DJANGO_DEBUG=false`. Cualquier error `500` deja la traza completa en el logger `django.request`.
- **Manejador global de excepciones (`apps.core.exceptions.api_exception_handler`):** traduce errores no controlados de validación o base de datos en respuestas JSON legibles:
  - `ValidationError` de Django y `DataError` de base de datos (campos más largos que `max_length`, fechas mal formadas) → **400 Bad Request**.
  - `IntegrityError` por unicidad o clave foránea → **409 Conflict** (o **400** en restricciones `CHECK`/`NOT NULL`).
  - Excepciones no previstas → **500** JSON uniforme con registro en `django.request`.
- **Casos borde cubiertos:** fechas o filtros inválidos en `GET /api/reportes/gerencial/?desde=abc` responden **400**; descarga de evidencias cuyo archivo fue borrado en un redespliegue responde **404** con mensaje; las consultas simultáneas de rastreo Track123 se serializan para no inscribir ni gastar cuota dos veces; las vistas materializadas de reportes solo se refrescan al cambiar los datos origen (via `on_commit` tras señales) o al invocar `POST /api/reportes/refrescar/` (con **503** si la base falla).

## Pruebas y calidad continua

```bash
python manage.py test                           # suite completa en SQLite (~3,5 min)
python manage.py test apps.users                # solo un módulo
python manage.py test apps.core.test_postgres   # verificaciones de PostgreSQL
ruff check apps config                          # análisis estático del backend
python manage.py makemigrations --check --dry-run
coverage run manage.py test && coverage report  # medición de cobertura (96 %)
pip-audit -r requirements.txt                   # auditoría de dependencias
```

Para correr las pruebas críticas contra una base **PostgreSQL** real (por ejemplo local con Docker o en CI) sin tocar Supabase:

```bash
TEST_DATABASE_URL="postgresql://texcore:texcore@localhost:5432/texcore_test" \
  TEST_DB_SSL_REQUIRE=false \
  python manage.py test apps.core.test_postgres apps.production apps.quality apps.finished apps.sales apps.shipping apps.reports
```

La suite cubre `users`, `inventory`, `references`, `production` (con lavandería y concurrencia), `purchasing`, `quality`, `finished`, `sales`, `shipping`, `reports` y `core`. En el frontend, `npm test` valida las funciones puras, la exportación Excel/CSV, el cliente HTTP (`fetch`), las rutas protegidas y la sincronía menú–enrutamiento (`234` pruebas), junto con `npm run lint` (`oxlint`) y `npm run build`.

El detalle de tiempos antes/después, el reporte de cobertura por historia de usuario (H06) y los flujos de GitHub Actions están en [calidad y cobertura de pruebas](calidad-y-cobertura.md).

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
| Las evidencias desaparecen tras desplegar | El disco de Render es efímero: la descarga responde **404** con aviso claro mientras no se conecte almacenamiento persistente. |
| Un comando `seed_demo_*` dice que solo funciona con `DJANGO_DEBUG=true` | Es a propósito: no se siembran datos de demostración fuera de desarrollo. Para sembrar la demostración en Render usa `seed_demo_completo --permitir-produccion` o `SEED_DEMO_ON_DEPLOY=true`. |
| `seed_demo_completo` falla con «Quedaron módulos sin datos» | Algún paso no pudo sembrar su módulo. Corre antes los pasos que faltan o revisa el mensaje del paso. |
| `reiniciar_datos_demo` termina con «se deshizo el reinicio» | La siembra o la comprobación de coherencia encontró un problema y no se borró nada; el mensaje dice qué libro o registro no cuadra. En PostgreSQL también puede ser que la aplicación tenga la tabla en uso (espera de bloqueos de 15 s): córrelo sin tráfico y por el puerto de sesión (5432). |
| La lista de recetas de lavado o de lavanderías sale vacía | No existe pantalla ni ruta para crear recetas: se cargan con `seed_demo_lavanderia` o con `seed_demo_completo`. Las lavanderías son proveedores de la categoría lavandería. |
| El tablero de reportes no cambia tras refrescar | En SQLite las vistas son normales y siempre están al día; en PostgreSQL se refrescan automáticamente cuando cambian los datos origen o manualmente con `POST /api/reportes/refrescar/` (*Actualizar datos*), sin refrescar repetidamente en cada consulta. |
| La recepción de mercancía responde que quien creó la orden no puede recibirla | Separación de funciones: la recibe otro usuario con permiso de inventario (Almacenista). |
| La liquidación muestra *Sin tarifa* o *Sin costo* | Falta registrar la tarifa por minuto de la etapa, o la compra del material no trajo costo unitario. El cálculo se marca como parcial. |
| Al facturar dice «Falta el precio de venta de: …» | La referencia no tiene fila en *Ventas y Despachos → Precios*. El Gerente registra el costo de fábrica y los precios (o corre `seed_demo_ventas` en desarrollo). |
| «Consultar estado» responde que el servicio de rastreo no está disponible (503) | El rastreo está apagado (`TRACK123_ENABLED=false`), falta `TRACK123_API_KEY`, la clave no es válida o Track123 no respondió. La guía conserva su estado: cámbialo a mano si hace falta. |
| «Consultar estado» dice que la guía se consultó hace poco (429) | Enfriamiento de 10 minutos por guía, para no gastar consultas. Espera el tiempo indicado. |
| «Consultar estado» dice que la cuota de registros está en la reserva | Quedan 10 registros o menos en el plan de Track123: no se inscriben guías nuevas. Las ya registradas se siguen consultando. |
| «Consultar estado» dice que solo está disponible para Interrapidísimo | El rastreo no existe para Envía ni Otra: sus estados se cambian a mano. |
| Una factura aparece en *Por despachar / sin guía* con urgencia | Le falta anotar la guía: atención desde 4 h y vencida desde 24 h. Se anota desde esa pantalla (permiso `envios.anotar`). |
| El servidor no arranca con `ModuleNotFoundError: reportlab` | Falta la dependencia del PDF de la factura (HU 7.1): `pip install -r requirements.txt`. |
| Se creó una orden de producción y dice que falta material | El stock cambió entre la simulación y la creación; la orden no se guarda. Revisa la disponibilidad y vuelve a intentar. |
