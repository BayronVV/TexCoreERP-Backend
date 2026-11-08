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
fichas técnicas, compras, calidad, producto terminado, ventas y envíos). Al terminar, activa RLS en las tablas de Supabase (ver
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
| `TRACK123_API_KEY` | Clave de la API de Track123 para consultar el estado de las guías (HU 7.2). Secreto: va en el `.env` local (git lo ignora) y en las variables de Render, nunca en el repositorio. Vacía = rastreo apagado. |
| `TRACK123_ENABLED` | `true` enciende el rastreo; por defecto `false`. Se apaga solo al correr `manage.py test`. |
| `TRACK123_BASE_URL`, `TRACK123_TIMEOUT`, `TRACK123_COOLDOWN_MINUTES`, `TRACK123_QUOTA_RESERVE` | Opcionales. Por defecto: ruta `https://api.track123.com/gateway/open-api/tk/v2.1`, 10 segundos de espera, 10 minutos de enfriamiento entre consultas de una misma guía y 10 registros de cuota de reserva. |

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
| `python manage.py seed_demo_calidad` | 8 defectos típicos de denim y dos lotes devueltos de lavandería: uno inspeccionado y otro por inspeccionar. Necesita antes `seed_demo_inventario` y `seed_demo_produccion`. |
| `python manage.py seed_demo_terminado` | Ingresa al inventario final (producto terminado) las aptas de la inspección de demostración, por las mismas reglas de la aplicación. Necesita antes `seed_demo_calidad`. |
| `python manage.py seed_demo_ventas` | 4 clientes (distribuidor, mayoristas y detal) y el costo de fábrica y los precios de demostración de las referencias de la demo. No crea facturas. Necesita antes las referencias de demostración (`seed_demo_referencias`) y, para vender, `seed_demo_terminado`. |
| `python manage.py seed_demo_envios` | Guías de demostración (HU 7.2): las 3 guías reales de Interrapidísimo del PO quedan entregadas con la respuesta real guardada, y guías sintéticas (marcadas) para ver todo el semáforo: por despachar, en tránsito dentro de una relación, con novedad, devuelta con su flete y una factura sin guía. Idempotente, solo con `DJANGO_DEBUG=true` y **no llama a Track123 ni gasta cuota**. Necesita antes `seed_demo_ventas` y stock de producto terminado. |
| `python manage.py seed_demo_tarifas` | Una tarifa de mano de obra por minuto para corte, confección y terminación (vigentes desde el 1 de enero de 2026), para que la liquidación de las órdenes no marque el costo como incompleto. Idempotente. |
| `python manage.py seed_demo_stock` | Entre 12 y 20 unidades en cada talla y color de las referencias activas, por ajuste manual (motivo «Sobrante o hallazgo», con su comprobante `AJT`). Solo sube lo que está por debajo de la meta. |
| `python manage.py seed_demo_completo` | **Todo en uno**: encadena los comandos anteriores en su orden, salta los módulos que ya tienen datos y al final imprime cuántos registros tiene cada módulo (falla si alguno quedó vacío). Con `--permitir-produccion` corre también con `DJANGO_DEBUG=false`: es la siembra de los datos **simulados** de la demostración sobre la base compartida; no borra nada ni toca usuarios, roles ni permisos. |
| `python manage.py generar_erd --salida docs/modelo-de-datos.md` | Regenera el [modelo de datos](modelo-de-datos.md). |
| `python manage.py test` | Ejecuta la suite de pruebas (922). |
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
python manage.py seed_demo_calidad        # 6. defectos típicos y dos lotes devueltos de lavandería (uno ya inspeccionado)
python manage.py seed_demo_terminado      # 7. ingresa al inventario final las aptas de la inspección de demostración
python manage.py seed_demo_ventas         # 8. clientes y precios de demostración para vender (no crea facturas)
python manage.py seed_demo_envios         # 9. guías de demostración: las 3 reales entregadas y otras sintéticas para el semáforo
# o, todo de una vez (incluye tarifas y stock por talla y color):
python manage.py seed_demo_completo       # --permitir-produccion para correrlo contra la base de producción (datos simulados)
```

- El paso 8 necesita las referencias del 2 y, para tener prendas que facturar, el 7; las facturas se hacen en vivo desde **Ventas y Despachos → Nueva venta**.
- El paso 9 emite sus propias facturas de demostración (observaciones «Demo envíos: …») por las mismas reglas que *Nueva venta*, así que necesita el 8 y stock de producto terminado (el 7). Puede correrse varias veces: no duplica nada. Si las facturas demo de la HU 7.3 traen guías ficticias, las reemplaza por las tres reales.
- Los pasos 3 a 7 necesitan el 2; el 6 necesita además el 3 (los lotes salen de las órdenes de producción) y el 7 necesita el 6 (ingresa las aptas de la inspección de demostración). `seed_demo_inventario` ya ejecuta `seed_inventario` y `seed_demo_referencias`.
- Los usuarios que participan se toman de los que ya existen: `seed_demo_compras` busca uno de Producción para crear, un Gerente
  o Administrador para aprobar y un Almacenista distinto del creador para recibir; si falta el Almacenista, la orden queda
  aprobada sin recepción.
- No se siembran tarifas de mano de obra: en la **Liquidación de Órdenes** la mano de obra aparece *Sin tarifa* hasta que alguien
  registre una en la pestaña **Tarifas por Minuto**.
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

## Pruebas

```bash
python manage.py test                      # todo
python manage.py test apps.users           # solo un módulo
python manage.py test apps.inventory -v 2  # con detalle
python manage.py test --parallel 4         # en paralelo, más rápido
```

La suite cubre `users`, `inventory`, `references`, `production`, `purchasing`, `quality`, `finished`, `sales`, `shipping` y `core`. Las pruebas de los comandos de demostración
(`test_seed*.py`) verifican que sean idempotentes. En el frontend, `npm test` prueba la lógica pura de las pantallas (reparto de
lotes, tablero, costeo, recursos, compras, calidad, producto terminado...).

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
| Al facturar dice «Falta el precio de venta de: …» | La referencia no tiene fila en *Ventas y Despachos → Precios*. El Gerente registra el costo de fábrica y los precios (o corre `seed_demo_ventas` en desarrollo). |
| «Consultar estado» responde que el servicio de rastreo no está disponible (503) | El rastreo está apagado (`TRACK123_ENABLED=false`), falta `TRACK123_API_KEY`, la clave no es válida o Track123 no respondió. La guía conserva su estado: cámbialo a mano si hace falta. |
| «Consultar estado» dice que la guía se consultó hace poco (429) | Enfriamiento de 10 minutos por guía, para no gastar consultas. Espera el tiempo indicado. |
| «Consultar estado» dice que la cuota de registros está en la reserva | Quedan 10 registros o menos en el plan de Track123: no se inscriben guías nuevas. Las ya registradas se siguen consultando. |
| «Consultar estado» dice que solo está disponible para Interrapidísimo | El rastreo no existe para Envía ni Otra: sus estados se cambian a mano. |
| Una factura aparece en *Por despachar / sin guía* con urgencia | Le falta anotar la guía: atención desde 4 h y vencida desde 24 h. Se anota desde esa pantalla (permiso `envios.anotar`). |
| El servidor no arranca con `ModuleNotFoundError: reportlab` | Falta la dependencia del PDF de la factura (HU 7.1): `pip install -r requirements.txt`. |
| Se creó una orden de producción y dice que falta material | El stock cambió entre la simulación y la creación; la orden no se guarda. Revisa la disponibilidad y vuelve a intentar. |
