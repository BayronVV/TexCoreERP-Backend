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

`SUPABASE_URL` y `SUPABASE_ANON_KEY` no se usan todavía: no se cargan.

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

### Limitaciones conocidas

- **Evidencias de inventario (fotos y PDF):** se guardan en el disco del
  servicio, que en Render es efímero: se pierden en cada redespliegue o
  reinicio. Antes de usarlas en serio hay que moverlas a Supabase Storage o
  agregar un disco persistente (plan de pago).
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

## Después de desplegar

1. `GET https://texcore-api.onrender.com/api/health/` debe responder `ok`.
2. Abrir el frontend, iniciar sesión y revisar que no haya errores de CORS en la consola.
3. Cambiar la contraseña de las cuentas de prueba: la base es compartida y los
   repositorios son públicos.
