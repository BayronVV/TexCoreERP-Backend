# API REST

La API es JSON sobre HTTPS y se documenta sola con **OpenAPI** (drf-spectacular). La fuente de verdad
es siempre la documentación interactiva, que se genera desde el código:

| Qué | Ruta |
|---|---|
| Swagger UI (probar endpoints) | `/api/docs/` |
| ReDoc (lectura) | `/api/redoc/` |
| Esquema OpenAPI (YAML) | `/api/schema/` |

En local: <http://localhost:8000/api/docs/>. Para ocultarla en un despliegue define `API_DOCS_ENABLED=false`.

## Autenticación

1. Inicia sesión con `POST /api/token/` y copia el valor `access`.
2. Envíalo en cada petición: `Authorization: Bearer <access>`.
3. Cuando venza (15 min) pide uno nuevo con `POST /api/token/refresh/`; la respuesta trae también un `refresh` nuevo.

```bash
curl -X POST http://localhost:8000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "usuario@empresa.com", "password": "TuContraseña#1"}'
```

En Swagger UI pulsa **Authorize** y pega el `access`: queda guardado entre recargas.

## Permisos y códigos de respuesta

Cada ruta exige un permiso por rol (RNF01), por ejemplo `inventario.ver` para consultar y
`inventario.gestionar` para registrar.

| Código | Significa |
|---|---|
| 200 / 201 | Correcto / creado |
| 400 | Dato inválido o regla de negocio incumplida. Cuerpo `{campo: [mensaje]}`; si falta stock trae además `faltantes` |
| 401 | Sin sesión, token vencido o credenciales inválidas |
| 403 | El rol no tiene el permiso que la ruta exige |
| 404 | No existe |
| 429 | Demasiados intentos (límite de frecuencia) |

## Módulos

Los detalles de cada endpoint (parámetros, cuerpos y respuestas) están en Swagger; aquí solo el mapa.

| Módulo (etiqueta) | Rutas base | Historia |
|---|---|---|
| `auth` | `/api/register/`, `/api/token/`, `/api/token/refresh/`, `/api/auth/me/`, `/api/auth/password-reset/…` | TE-78, TE-42, TE-43 |
| `users` | `/api/users/`, `/api/users/<id>/`, `/api/users/<id>/invite/`, `/api/roles/`, `/api/permissions/` | TE-44 |
| `proveedores` | `/api/inventario/proveedores/…` | TE-45 |
| `catalogo` | `/api/inventario/catalogo/…`, `/api/inventario/metadatos/` | TE-46 |
| `inventario` | `/api/inventario/productos/`, `/api/inventario/alertas/` | TE-47, TE-48 |
| `movimientos` | `/api/inventario/movimientos/`, `/api/inventario/ingresos/` (las compras aceptan `costo_unitario`: actualiza el costo promedio ponderado del producto) | TE-47, TE-56 |
| `ordenes` | `/api/inventario/ordenes/…` (crear, consultar, anular) | TE-47 |
| `evidencias` | `/api/inventario/movimientos/<id>/evidencias/`, `/api/inventario/ordenes/<id>/evidencias/`, `/api/inventario/evidencias/<id>/archivo/` | TE-47 |
| `referencias` | `/api/referencias/…` (catálogo de jeans: variantes, estado e imágenes), `/api/referencias/metadatos/` | TE-49 |
| `fichas` | `/api/referencias/<id>/ficha/` (consumo por unidad), `/api/referencias/<id>/ficha/documento/` (PDF), `/api/inventario/fichas-tecnicas/` y `…/<id>/consumo/?cantidad=N` (consumo contra el stock) | TE-50 |
| `produccion` | `/api/produccion/simulacion/` (simula la producción contra el stock: viable, faltantes, máximo producible y lotes) | TE-51 |
| `produccion` | `/api/produccion/ordenes/` (crear y listar órdenes con lotes y tallas), `/api/produccion/ordenes/<id>/`, `/api/produccion/ordenes/<id>/anular/` | TE-52 |
| `produccion` | `/api/produccion/lotes/<id>/<accion>/` (`iniciar`, `pausar`, `reanudar`, `completar`: el tiempo por etapa de cada lote) y `/api/produccion/lotes/<id>/historial/` | TE-53 |
| `produccion` | `/api/produccion/monitor/` (los lotes agrupados por columna: Planeada, En proceso, En pausa y Terminada, con totales, límite por columna, filtros por orden y referencia, alertas de lotes detenidos, ventana de días de la columna Terminada y columna opcional de canceladas) | TE-55 |
| `produccion` | `/api/produccion/tarifas/` (historial de tarifas de mano de obra por minuto por etapa y registro de nuevas vigencias) | TE-56, TE-129 |
| `produccion` | `/api/produccion/ordenes/<id>/costos/` (liquidación financiera: costo real de materiales vs mano de obra por lote y etapa, distribución y costo por prenda) | TE-56, TE-130 |
| `salud` | `/api/health/`, `/api/health/db/` | — |

## Ejemplo: registrar un ingreso

```bash
curl -X POST http://localhost:8000/api/inventario/ingresos/ \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"producto": 6, "cantidad": "100", "fecha": "2026-10-01", "proveedor": 2, "lote": "L-2026-01"}'
```

Respuesta `201` con el movimiento del kardex (saldo antes y después). Si la cantidad es cero o negativa
responde `400` con `{"cantidad": ["La cantidad debe ser mayor que cero."]}`.

## Mantener la documentación al día

La referencia se actualiza sola al cambiar el código. Para que un endpoint nuevo quede bien documentado:

1. Dale un `serializer_class`, o usa `@extend_schema` con `request` y `responses` si la vista es un `APIView`.
2. Añade `summary`, `description` y `tags` (ver `apps/inventory/views.py` como modelo).
3. Valida el esquema: `python manage.py spectacular --validate --file schema.yml` debe terminar sin errores (borra después `schema.yml`).
