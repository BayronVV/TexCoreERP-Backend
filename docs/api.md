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
`inventario.gestionar` para registrar. Qué permiso exige cada operación y qué rol lo tiene por defecto está en [roles y permisos](roles-y-permisos.md).

| Código | Significa |
|---|---|
| 200 / 201 | Correcto / creado |
| 400 | Dato inválido o regla de negocio incumplida. Cuerpo `{campo: [mensaje]}`; si falta stock trae además `faltantes` |
| 401 | Sin sesión, token vencido o credenciales inválidas |
| 403 | El rol no tiene el permiso que la ruta exige |
| 404 | No existe |
| 429 | Demasiados intentos (límite de frecuencia) |

## Módulos

La API tiene **66 rutas** y **98 operaciones**, todas descritas en Swagger con su etiqueta. Aquí solo el mapa; los detalles
de cada endpoint (parámetros, cuerpos y respuestas) están en Swagger. El permiso que exige cada operación está en
[roles y permisos](roles-y-permisos.md), y las reglas de negocio de cada módulo en [módulos y reglas](modulos.md).

| Módulo (etiqueta) | Rutas base | Historia |
|---|---|---|
| `auth` | `/api/register/`, `/api/token/`, `/api/token/refresh/`, `/api/auth/me/`, `/api/auth/password-reset/…` (`validate/` y `confirm/`) | TE-78, TE-42, TE-43 |
| `users` | `/api/users/`, `/api/users/<id>/`, `/api/users/<id>/invite/`, `/api/roles/`, `/api/roles/<id>/`, `/api/permissions/` | TE-44 |
| `proveedores` | `/api/inventario/proveedores/…` (listar, crear, editar, archivar) y `/api/inventario/proveedores/<id>/restaurar/` | TE-45 |
| `catalogo` | `/api/inventario/catalogo/…`, `/api/inventario/catalogo/<id>/imagen/`, `/api/inventario/metadatos/` | TE-46 |
| `inventario` | `/api/inventario/productos/` (con existencias y costo promedio), `/api/inventario/alertas/` | TE-47, TE-48 |
| `movimientos` | `/api/inventario/movimientos/` (kardex), `/api/inventario/ingresos/` (las compras aceptan `costo_unitario`: actualiza el costo promedio ponderado del producto) | TE-47, TE-56 |
| `ordenes` | `/api/inventario/ordenes/…` (crear, consultar, anular). La pantalla solo crea salidas a lavandería; las de producción nacen desde `/api/produccion/ordenes/` | TE-47 |
| `evidencias` | `/api/inventario/movimientos/<id>/evidencias/`, `/api/inventario/ordenes/<id>/evidencias/`, `/api/inventario/evidencias/<id>/archivo/` | TE-47 |
| `referencias` | `/api/referencias/` y `/api/referencias/<id>/` (catálogo de jeans con variantes), `…/<id>/estado/` (borrador, activa, descontinuada), `…/<id>/imagenes/`, `/api/referencias/imagenes/<id>/archivo/` y `…/principal/`, `/api/referencias/metadatos/` | TE-49 |
| `fichas` | `/api/referencias/<id>/ficha/` (consumo por unidad: consultar, guardar, quitar), `/api/referencias/<id>/ficha/documento/` (PDF extenso), `/api/inventario/fichas-tecnicas/` (referencias activas para elegir en una orden) y `…/<id>/consumo/?cantidad=N` (consumo contra el stock) | TE-50 |
| `produccion` | `/api/produccion/simulacion/` (simula la producción contra el stock: viable, faltantes, máximo producible y cobertura por lote) | TE-51, TE-110 |
| `produccion` | `/api/produccion/ordenes/` (crear y listar órdenes con lotes y tallas), `/api/produccion/ordenes/<id>/`, `/api/produccion/ordenes/<id>/anular/` | TE-52 |
| `produccion` | `/api/produccion/lotes/<id>/<accion>/` (`iniciar`, `pausar`, `reanudar`, `completar`: el tiempo por etapa de cada lote) y `/api/produccion/lotes/<id>/historial/` | TE-53 |
| `produccion` | `/api/produccion/monitor/` (los lotes agrupados por columna: Planeada, En proceso, En pausa y Terminada, con totales, límite por columna, filtros por orden y referencia, alertas de lotes detenidos, ventana de días de la columna Terminada y columna opcional de canceladas) | TE-55, TE-126 |
| `produccion` | `/api/produccion/tarifas/` (historial de tarifas de mano de obra por minuto por etapa y registro de nuevas vigencias) | TE-56, TE-129 |
| `produccion` | `/api/produccion/ordenes/<id>/costos/` (liquidación financiera: costo real de materiales vs mano de obra por lote y etapa, distribución y costo por prenda) | TE-56, TE-130 |
| `recursos` | `/api/produccion/operarios/` y `/api/produccion/operarios/<id>/` (catálogo de operarios: crear, editar, activar o desactivar), `/api/produccion/maquinas/` y `/api/produccion/maquinas/<id>/` (catálogo de máquinas con su estado físico). Las listas traen `ocupado_en` / `ocupada_en`, que se calcula con las etapas en curso | TE-54, TE-121 |
| `recursos` | `/api/produccion/lotes/<id>/asignar/` (asigna, reasigna o quita el operario y la máquina de una etapa), `/api/produccion/lotes/<id>/desvincular/` y `/api/produccion/lotes/<id>/asignaciones/` (historial). Las etapas del lote y las tarjetas del monitor traen la asignación vigente | TE-54, TE-122 |
| `compras` | `/api/compras/ordenes/` y `/api/compras/ordenes/<id>/` (órdenes de compra de materiales: crear, listar con filtros `estado`, `proveedor` y `q`, y editar mientras son borrador), `/api/compras/ordenes/<id>/aprobar/`, `cancelar/` y `cerrar/` (aprobación del Gerente, cancelación y cierre con motivo) | — |
| `compras` | `/api/compras/recepciones/` (recibir mercancía con varios productos a la vez, contra una orden aprobada o suelta; cada fila entra al almacén con la misma regla del ingreso: stock, costo promedio y kardex) y `/api/compras/metadatos/` (estados y tolerancia de exceso) | — |
| `salud` | `/api/health/`, `/api/health/db/` | — |

Los listados aceptan `?limit=` (por defecto 100) y los filtros que indica Swagger para cada uno (por ejemplo `?q=`, `?estado=`,
`?categoria=`). Las rutas de producción que reciben una acción sobre un lote usan el id del **lote**, no el de la orden.

## Ejemplo: registrar un ingreso

```bash
curl -X POST http://localhost:8000/api/inventario/ingresos/ \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"producto": 6, "cantidad": "100", "fecha": "2026-10-01", "proveedor": 2, "lote": "L-2026-01"}'
```

Respuesta `201` con el movimiento del kardex (saldo antes y después). Si la cantidad es cero o negativa
responde `400` con `{"cantidad": ["La cantidad debe ser mayor que cero."]}`.

## Ejemplo: simular y crear una orden de producción

Primero se simula (solo lectura) para saber si alcanza el material, y después se crea la orden, que descuenta el stock.

```bash
curl -X POST http://localhost:8000/api/produccion/simulacion/   -H "Authorization: Bearer <access>" -H "Content-Type: application/json"   -d '{"referencia": 1, "cantidad": 80, "lotes": [30, 30, 20]}'
```

La respuesta trae `viable`, `lineas` (por material: requerido, disponible y faltante), `faltantes`, `maximo_producible`,
`cuello_de_botella` y, por cada lote, si el stock lo cubre (`lotes` y `lotes_cubiertos`). Si hay material, la orden se crea con
`POST /api/produccion/ordenes/` enviando `referencia`, `cantidad`, `producto_resultado` (el pantalón genérico que resulta) y,
opcionalmente, `lotes` con la forma `[{"cantidad": 30, "tallas": [{"variante": 5, "cantidad": 30}]}]`. Si falta material responde
`400` con `faltantes` y no crea nada.

## Mantener la documentación al día

La referencia se actualiza sola al cambiar el código. Para que un endpoint nuevo quede bien documentado:

1. Dale un `serializer_class`, o usa `@extend_schema` con `request` y `responses` si la vista es un `APIView`.
2. Añade `summary`, `description` y `tags` (ver `apps/inventory/views.py` como modelo).
3. Valida el esquema: `python manage.py spectacular --validate --file schema.yml` debe terminar sin errores (borra después `schema.yml`).
