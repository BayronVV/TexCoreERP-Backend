# Despliegue en Render — TexCore

Dos servicios, uno por repositorio:

| Servicio | Tipo | Repo | URL |
|----------|------|------|-----|
| `texcore-api` | Web Service (Python) | TexCoreERP-Backend | `https://texcore-api.onrender.com` |
| `texcore-web` | Static Site | TexCoreERP-Frontend | `https://texcore-web.onrender.com` |

La base de datos es Supabase (no se crea nada en Render). Ambos servicios
despliegan la rama `main` y se redespliegan solos con cada merge.

## Backend (`texcore-api`)

- **Build:** `pip install -r requirements.txt`
- **Start:** `python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 60`
  (las migraciones corren en cada arranque; son idempotentes).
- **Health check (opcional):** `/api/health/`.

### Variables de entorno

| Variable | Valor | Nota |
|----------|-------|------|
| `PYTHON_VERSION` | `3.13.5` | Fija la versión de Python. |
| `DJANGO_DEBUG` | `false` | Obliga a tener `DJANGO_SECRET_KEY`. |
| `DJANGO_SECRET_KEY` | cadena aleatoria larga | **Distinta** a la de tu `.env` local. |
| `DJANGO_ALLOWED_HOSTS` | `texcore-api.onrender.com` | Render también agrega su host solo. |
| `APP_ENV` | `prod` | Lo muestra `/api/health/`. |
| `DATABASE_URL` | cadena del *session pooler* de Supabase | Secreto: solo se escribe en Render. |
| `DB_SSL_REQUIRE` | `true` | |
| `DB_CONN_MAX_AGE` | `0` | Evita agotar el pool de Supabase. |
| `CORS_ALLOWED_ORIGINS` | `https://texcore-web.onrender.com` | Sin barra final y sin `localhost`. |
| `FRONTEND_URL` | `https://texcore-web.onrender.com` | Arma el enlace del correo de recuperación. |
| `NUM_PROXIES` | `1` | Ver "Proxies". |
| `EMAIL_BACKEND` y `EMAIL_*` | ver `.env.example` | Solo si se envían correos reales. |
| `DEFAULT_FROM_EMAIL` | `TexCore ERP <tu-correo>` | Debe coincidir con la cuenta SMTP. |
| `TRACK123_API_KEY` | `<tu-clave>` | Clave de la API de Track123 (rastreo de guías, HU 7.2). **Secreto: solo se escribe en Render**, nunca en el repositorio ni en el `.env.example`. Sin ella el rastreo queda apagado. |
| `TRACK123_ENABLED` | `true` o `false` | `true` enciende el rastreo. Por defecto `false`: con `false` (o sin clave) los estados de las guías se cambian a mano. Las pruebas lo apagan siempre. |
| `TRACK123_BASE_URL` | `https://api.track123.com/gateway/open-api/tk/v2.1` (por defecto) | Opcional. La ruta vigente es `v2.1`; no hace falta definirla. |
| `TRACK123_TIMEOUT` | `10` (por defecto) | Opcional. Segundos que se espera a Track123 antes de dar el rastreo por no disponible. Mantenerlo por debajo del `--timeout 60` de gunicorn. |
| `TRACK123_COOLDOWN_MINUTES` | `10` (por defecto) | Opcional. Minutos que debe esperar una guía para volver a consultarse. |
| `TRACK123_QUOTA_RESERVE` | `10` (por defecto) | Opcional. Con esta cuota de registros o menos ya no se inscriben guías nuevas. |
| `SEED_DEMO_ON_DEPLOY` | `true` / `false` (por defecto `false`) | Opcional. Con `true`, al final del `migrate --noinput` del arranque se corre `seed_demo_completo --permitir-produccion`: deja datos de demostración (simulados) en todos los módulos, sin duplicar ni borrar nada. Un fallo de la siembra se avisa por el registro y **no impide el arranque**. Basta dejarlo en `true` en un despliegue y volver a `false` (aunque quedara en `true`, correrlo otra vez no duplica). |

`SUPABASE_URL` y `SUPABASE_ANON_KEY` no se usan todavía: no se cargan.

### Migraciones y datos iniciales

Cada arranque ejecuta `migrate --noinput`, así que un despliegue con migraciones nuevas las aplica solo. Eso incluye los
**permisos y roles** de los módulos nuevos (`referencias.*`, `compras.*`, y los de calidad para el Jefe de Producción), que cargan las migraciones `0007`, `0008` y `0010` de `apps/users` (los de producto terminado ya venían en la matriz inicial: la app `finished` solo agrega sus cuatro tablas `terminado_*`). Ventas (HU 7.1) suma la app `sales` con sus cuatro tablas `ventas_*`, la migración `users/0012` con los permisos `ventas.precios` y `ventas.anular` del Gerente, y la dependencia `reportlab` (se instala sola con `requirements.txt`),
Envíos (HU 7.2) suma la app `shipping` con sus tablas `envios_guia`, `envios_evento` y `envios_relacion`, la migración de datos `shipping/0002` (convierte en registros de guía las guías que las facturas ya traían como texto; es idempotente) y la migración `users/0013` con los cuatro permisos `envios.*` y su matriz inicial. Todo se aplica solo al arrancar.
Además corre el endurecimiento de la base (RLS) al final de cada `migrate`.

- No hace falta (ni conviene) correr nada más para tener la matriz de permisos inicial; después se ajusta desde **Roles y permisos**.
- La primera cuenta administradora se crea una sola vez con `python manage.py seed_admin` desde una terminal con `DATABASE_URL` de producción, pasando
  `--email` y `--password` propios (ver el [manual del sistema](manual-del-sistema.md)). Nunca se deja la contraseña de ejemplo.
- Los comandos `seed_demo_*` sueltos **no funcionan en Render**: exigen `DJANGO_DEBUG=true`, que en producción es `false`. La excepción es `seed_demo_completo --permitir-produccion` (o `SEED_DEMO_ON_DEPLOY=true`), pensada para sembrar los datos simulados de la demostración; los demás se mantienen cerrados. Es a propósito (incluidos `seed_demo_calidad`, con la que en producción los defectos se crean desde **Control de Calidad → Defectos**, y `seed_demo_terminado`, con la que el producto terminado se ingresa desde **Producto Terminado → Ingreso**).
- `seed_demo_envios` (guías de demostración de la HU 7.2) tampoco corre en Render, por la misma razón. En producción las guías se anotan al facturar o desde **Por despachar / sin guía**.
- Una migración que cambia el esquema se aplica a la base compartida: la versión anterior del código, si sigue desplegada, debe
  tolerarlo (la 0002 de inventario ya lo advertía).

### Proxies

Detrás de Render la IP real llega en `X-Forwarded-For`. Con `NUM_PROXIES=0` se
ignora y todas las peticiones parecerían venir de la misma IP, así que los
límites por IP (login, recuperación de contraseña) compartirían un solo cupo.
Se usa `1`; si el límite bloquea a usuarios distintos a la vez, revisar el valor.

### Correo en Render

**Render bloquea el SMTP saliente en los puertos 25, 465 y 587 en el plan
gratuito.** Gmail (`smtp.gmail.com:587`) se queda esperando hasta que gunicorn
mata el proceso, y la solicitud de recuperación responde 500. Opciones:

- Un SMTP que acepte el puerto **2525** (Brevo, SendGrid, Mailgun), por ejemplo
  Brevo: `EMAIL_HOST=smtp-relay.brevo.com`, `EMAIL_PORT=2525`,
  `EMAIL_USE_TLS=true`, `EMAIL_HOST_USER` = login de Brevo, `EMAIL_HOST_PASSWORD`
  = clave SMTP de Brevo, y verificar el remitente en `DEFAULT_FROM_EMAIL`.
- Un plan de pago de Render, que sí permite SMTP.

`EMAIL_TIMEOUT` (10 s por defecto) hace que un SMTP inalcanzable falle rápido en
vez de colgar la petición. Mientras no haya SMTP, usar
`EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`: el enlace queda
en los logs del servicio.

### Rastreo de guías con Track123

El rastreo de Interrapidísimo (HU 7.2) es opcional: el sistema funciona igual con `TRACK123_ENABLED=false`.

- **La clave solo vive en Render** (variable `TRACK123_API_KEY`) y en el `.env` local, que git ignora. Nunca va en el código, en el
  `.env.example` ni en un commit; en la documentación se escribe `<tu-clave>`. Si alguna vez se filtra, se revoca en Track123 y se cambia en Render.
- **La cuota es corta** (50 registros de guías nuevas en el plan actual). Registrar una guía gasta 1; consultarla después no gasta. Por eso
  nadie consulta por accidente: el rastreo solo ocurre cuando alguien pulsa **Consultar estado**, hay enfriamiento por guía y una reserva
  (`TRACK123_QUOTA_RESERVE`). `GET /api/envios/rastreo/estado/` muestra la cuota restante sin gastarla.
- **Si falla, no bloquea:** con la clave inválida (Track123 responde HTTP 200 con el código `B0001`), sin red o apagado, la consulta responde
  `503`, la guía conserva su estado y se puede cambiar a mano. Facturar y despachar nunca dependen de Track123.
- **Solo Interrapidísimo.** Envía y Otra no se consultan: sus estados son manuales.

### Limitaciones conocidas

- **Evidencias de inventario (fotos y PDF):** se guardan en el disco del
  servicio, que en Render es efímero: se pierden en cada redespliegue o
  reinicio. Antes de usarlas en serio hay que moverlas a Supabase Storage o
  agregar un disco persistente (plan de pago).
- **Lo que sí sobrevive a un redespliegue:** las imágenes del catálogo, las fotos de las referencias y el PDF de la ficha técnica se
  guardan en la base de datos, no en el disco.
- **Plan gratuito:** el servicio se duerme tras 15 minutos sin tráfico y la
  primera petición tarda cerca de un minuto en responder.
- **Base de datos compartida:** hoy apunta a `texcore-dev`. Para producción real
  usar `texcore-prod` cambiando solo `DATABASE_URL`.

## Frontend (`texcore-web`)

- **Build:** `npm ci && npm run build`
- **Publish directory:** `dist`
- **Variables:** `VITE_API_URL=https://texcore-api.onrender.com`, `NODE_VERSION=22`.
  `VITE_API_URL` se lee al compilar: si cambia, hay que volver a desplegar.
- **Regla de reescritura (obligatoria):** en el panel del sitio →
  *Redirects/Rewrites* agregar `/*` → `/index.html`, acción **Rewrite**. Sin ella,
  recargar `/inventario` o abrir el enlace del correo de recuperación da 404.
  Render no sirve un `404.html` como respaldo: sin la regla, esas rutas
  responden "Not Found" en texto plano. Solo se puede crear desde el panel.

## Despliegues en Jira

Render despliega solo cada cambio que llega a `main`, pero no avisa a Jira. El workflow
`.github/workflows/deploy-render.yml` (en los dos repos) espera el resultado real de ese
despliegue consultando la API de Render (`.github/scripts/wait_render_deploy.py`) y lo publica
como un despliegue de GitHub en el entorno `production`. La app **GitHub for Atlassian** lo muestra
en la pestaña *Implementaciones* de las incidencias cuya clave (p. ej. `TE-45`) aparece en los commits,
y en la página *Despliegues* del proyecto.

- Requiere el secreto de repositorio `RENDER_API_KEY` (GitHub: Settings > Secrets and variables > Actions;
  la clave se crea en Render: Account Settings > API Keys).
- Y tener activada la función *Despliegues* en Jira (Configuración del proyecto > Funciones) con GitHub Actions
  como herramienta conectada.
- Si Render falla o cancela el despliegue, el workflow falla y Jira lo muestra como fallido.
- También se puede lanzar a mano: pestaña Actions > *Despliegue en Render* > *Run workflow*.

## Documentación publicada

El sitio de manuales (este mismo) se construye con `mkdocs build --strict` y se publica en GitHub Pages
(<https://bayronvv.github.io/TexCoreERP-Backend/>) con el workflow `.github/workflows/docs.yml`, que corre cuando cambian
`docs/` o `mkdocs.yml` en `main`. Requiere una vez: *Settings > Pages > Source = GitHub Actions*. Si el build falla por un enlace
roto, el sitio anterior sigue publicado.

## Después de desplegar

1. `GET https://texcore-api.onrender.com/api/health/` debe responder `ok`.
2. Abrir el frontend, iniciar sesión y revisar que no haya errores de CORS en la consola.
   Entrar a **Roles y permisos** y confirmar que aparecen los módulos Referencias, Fichas Técnicas y Compras.
3. Cambiar la contraseña de las cuentas de prueba: la base es compartida y los
   repositorios son públicos.
