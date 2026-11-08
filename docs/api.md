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
| 409 | Conflicto con el estado actual; por ejemplo, el lote ya fue inspeccionado, la inspección ya fue ingresada al inventario final o la relación de despacho ya se creó con ese `token` |
| 429 | Demasiados intentos (límite de frecuencia) o, en el rastreo de una guía, consulta demasiado seguida (enfriamiento de 10 min por guía; el cuerpo trae `segundos`) |
| 503 | El servicio de rastreo (Track123) está apagado, sin clave o no respondió. La guía conserva su último estado y nada más se bloquea |

## Módulos

La API tiene **114 rutas** y **157 operaciones**, todas descritas en Swagger con su etiqueta. Aquí solo el mapa; los detalles
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
| `calidad` | `/api/calidad/defectos/` y `/api/calidad/defectos/<id>/` (catálogo de defectos corregibles e incorregibles: listar con filtros `activo` y `q`, crear, editar y desactivar), `/api/calidad/pendientes/` (lotes devueltos de lavandería por inspeccionar) | TE-59 |
| `calidad` | `/api/calidad/inspecciones/` (listar con filtros `lote`, `orden`, `desde`, `hasta` y `q`, y registrar la inspección de un lote) y `/api/calidad/inspecciones/<id>/` (consultar con su desglose de marras). No hay `PUT` ni `DELETE`: una inspección no se edita | TE-59 |
| `producto-terminado` | `/api/terminado/pendientes/` (inspecciones con aptas por ingresar, con las variantes de su referencia y lo planificado), `/api/terminado/ingresos/` (listar con filtros `referencia`, `lote`, `desde`, `hasta` y `q`, y registrar el ingreso de una inspección) y `/api/terminado/ingresos/<id>/` (consultar con su reparto por talla). No hay `PUT` ni `DELETE`: un ingreso no se edita | TE-60 |
| `producto-terminado` | `/api/terminado/existencias/` (matriz referencia × color × talla, con las celdas en cero, filtro `referencia`) y `/api/terminado/movimientos/` (libro de solo lectura con saldo antes y después; filtros `referencia`, `variante`, `tipo`, `desde` y `hasta`) | TE-60 |
| `producto-terminado` | `/api/terminado/ajustes/` (listar con filtros `referencia`, `motivo`, `desde`, `hasta`, `q` y `limit`, y ajustar el stock contra el conteo físico), `/api/terminado/ajustes/<id>/` (consultar el comprobante con sus líneas) y `/api/terminado/metadatos/` (motivos con su signo, umbral de unidades y mínimos de la observación). Ajustar exige `producto_terminado.ajustar`. No hay `PUT` ni `DELETE`: un ajuste no se edita | TE-61 |
| `ventas` | `/api/ventas/clientes/` (listar con filtros `tipo`, `activo`, `q` y `limit`, y registrar) y `/api/ventas/clientes/<id>/` (consultar y modificar o desactivar: un cliente no se borra) | TE-62 |
| `ventas` | `/api/ventas/precios/` (referencias activas con su costo de fábrica y precios; filtro `q`) y `/api/ventas/precios/<referencia>/` (`PUT`: registrar o actualizar). Modificar exige `ventas.precios` | TE-62 |
| `ventas` | `/api/ventas/facturas/` (listar con filtros `cliente`, `estado`, `desde`, `hasta`, `q` y `limit`, y emitir la factura POS interna descontando el inventario) y `/api/ventas/facturas/<id>/` (consultar con sus líneas). No hay `PUT` ni `DELETE`: una factura no se edita | TE-62 |
| `ventas` | `/api/ventas/facturas/<id>/pdf/` (descarga el PDF), `/api/ventas/facturas/<id>/anular/` (anula con motivo y reingresa las unidades; exige `ventas.anular`) y `/api/ventas/metadatos/` (tipos de cliente con su lista de precios y descuento máximo, transportadoras, IVA y la leyenda «Factura POS interna. No es factura electrónica.») | TE-62 |
| `ventas` | Las facturas (`/api/ventas/facturas/` y `…/<id>/`) traen el campo `guia`: la guía vigente de la factura (`id`, `estado`, `estado_nombre`, `color` del semáforo, `rastreo_estado`, `consultada_en` y `novedad`) o `null` si todavía no tiene. `transportadora` y `numero_guia` de la factura son el espejo de esa guía y solo los escribe el servicio de guías | TE-63 |
| `envios` | `/api/envios/metadatos/` (estados con su color de semáforo, transiciones permitidas, transportadoras y cuál se rastrea, plazos para anotar la guía y si el rastreo está habilitado), `/api/envios/resumen/` (conteos por estado, facturas sin guía, novedades abiertas y devoluciones por vendedor con su flete) y `/api/envios/pendientes/` (facturas emitidas sin guía, con `horas_sin_guia` y `urgencia`: `normal`, `atencion` desde 4 h o `vencida` desde 24 h) | TE-63 |
| `envios` | `/api/envios/guias/` (listar con filtros `estado`, `transportadora`, `factura`, `desde`, `hasta`, `q`, `todas` y `limit`) y `/api/envios/guias/<id>/` (detalle con el historial propio y la línea de tiempo guardada de la transportadora, sin llamar a la API). Una guía no se borra ni se crea suelta: nace al anotarla en una factura | TE-63 |
| `envios` | `/api/envios/facturas/<id>/guia/` (`POST`: anotar o reemplazar la guía de una factura emitida), `/api/envios/guias/<id>/estado/` (`POST`: cambiar el estado a mano), `/api/envios/guias/<id>/flete/` (`PATCH`: registrar el flete) y `/api/envios/guias/<id>/devolucion/` (`POST`: registrar en cartera la devolución física; reingresa las prendas una sola vez) | TE-63 |
| `envios` | `/api/envios/guias/<id>/rastrear/` (`POST`: consultar el estado real en Track123 y aplicarlo) y `/api/envios/rastreo/estado/` (`GET`: si el rastreo está habilitado y cuánta cuota de registros queda; leerla no gasta) | TE-63 |
| `envios` | `/api/envios/relaciones/` (`GET` con filtro `transportadora`; `POST` crea la relación de despacho `RD-0001` y pasa sus guías a en tránsito), `/api/envios/relaciones/<id>/` y `/api/envios/relaciones/<id>/pdf/` (descarga `RD-0001.pdf`) | TE-63 |
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

## Ejemplo: registrar la inspección de un lote

Primero se consultan los lotes por inspeccionar (`GET /api/calidad/pendientes/`), que traen `cantidad_recibida`: lo recibido conforme
de lavandería. Después se envía la inspección con las aptas y el desglose de las marras por defecto (los ids salen de
`GET /api/calidad/defectos/?activo=true`). Aquí el lote trae 40 prendas: 36 aptas y 4 marras.

```bash
curl -X POST http://localhost:8000/api/calidad/inspecciones/   -H "Authorization: Bearer <access>" -H "Content-Type: application/json"   -d '{"lote": 12, "aptas": 36, "defectos": [{"defecto": 1, "cantidad": 3, "nota": "Bolsillo trasero"}, {"defecto": 5, "cantidad": 1}], "observaciones": "Revisado al terminar el turno"}'
```

Respuesta `201` con la inspección (`INS-0001`), el lote y la orden, `cantidad_recibida`, `aptas`, `marras` y el `detalle` por defecto, que
conserva el nombre y el tipo (corregible o no) que el defecto tenía al inspeccionar. Errores: `400` si la suma no cuadra
(`{"aptas": ["Las aptas y las marras suman 39 y el lote trae 40: falta 1."]}`), si un defecto está desactivado o repetido, si el lote no
tiene recepción de lavandería o si su orden está anulada; `409` si el lote ya fue inspeccionado.

## Ejemplo: ingresar al inventario final las aptas de una inspección

Primero se consultan las inspecciones por ingresar (`GET /api/terminado/pendientes/`), que traen `aptas`, las `variantes` de la referencia
(talla y color, con su id) y lo `planificado` por variante en el lote. Después se envía el reparto de las aptas: la suma de las cantidades
debe ser exactamente las aptas de la inspección. Aquí la inspección trae 36 aptas.

```bash
curl -X POST http://localhost:8000/api/terminado/ingresos/   -H "Authorization: Bearer <access>" -H "Content-Type: application/json"   -d '{"inspeccion": 3, "lineas": [{"variante": 11, "cantidad": 20}, {"variante": 12, "cantidad": 16}], "ubicacion": "Estante A2", "observaciones": "Entregado por Terminación"}'
```

Respuesta `201` con el ingreso (`IPT-0001`), la inspección, el lote y la orden, y sus `lineas` (talla, color, `cantidad`, `planificada` y `diferencia`).
Cada línea suma al saldo de su variante y deja un movimiento `ENTRADA_PRODUCCION` en `GET /api/terminado/movimientos/`. Errores: `400` si la
suma no cuadra (`{"lineas": ["Las tallas suman 35 y la inspección trae 36 aptas: falta 1."]}`), si una variante no es de la referencia del lote
o se repite, o si la orden está anulada; `409` si la inspección ya fue ingresada
(`{"inspeccion": ["La inspección INS-0001 ya fue ingresada al inventario."]}`).

## Ejemplo: ajustar el stock contra el conteo físico

Primero se leen los saldos con `GET /api/terminado/existencias/` (cada celda trae `variante` y `cantidad`) y las reglas con
`GET /api/terminado/metadatos/`. Después se envía **solo lo que cambia**: por cada variante, el saldo que vio la persona (`esperado`) y lo
que contó (`contado`). `token` es un UUID que genera el formulario y evita ajustar dos veces con un doble clic. Aquí faltan 2 prendas en la
variante 11 y 1 en la 12.

```bash
curl -X POST http://localhost:8000/api/terminado/ajustes/   -H "Authorization: Bearer <access>" -H "Content-Type: application/json"   -d '{"motivo": "PERDIDA", "observacion": "Dos prendas no aparecieron en el conteo del viernes", "token": "7b0e6c2a-5d1f-4c8e-9a43-2f6b8d1e0c55", "lineas": [{"variante": 11, "esperado": 12, "contado": 10}, {"variante": 12, "esperado": 8, "contado": 7}]}'
```

Respuesta `201` con el comprobante (`AJT-0001`): `motivo_nombre`, `observacion`, `unidades_faltantes` y `unidades_sobrantes` (se suman por
separado, sin netear), quién lo hizo y sus `lineas` (talla, color, `stock_antes`, `stock_contado` y `diferencia`). Cada línea con diferencia
deja un movimiento `AJUSTE` en `GET /api/terminado/movimientos/`. Errores:

- `400` si el motivo no es del catálogo, la observación tiene menos de 10 caracteres
  (`{"observacion": ["Explica el ajuste en la observación (mínimo 10 caracteres)."]}`), no hay diferencias que ajustar, un motivo que solo
  resta recibe un sobrante (o al revés), hay variantes repetidas o inexistentes, o falta el `token`. Si una línea cambia más de 20 unidades,
  «Otro» no se acepta y la observación pide al menos 30 caracteres.
- `409` si el saldo de alguna variante cambió desde que se leyó
  (`{"detail": ["El stock cambió en: 30 Azul. Recarga la matriz y vuelve a contar."], "variantes": ["30 Azul"]}`): no se guarda nada.
- `409` si ese `token` ya generó un comprobante (`{"detail": ["Este ajuste ya se registró como AJT-0001."], "ajuste": 1, "codigo": "AJT-0001"}`).
- `403` si el rol no tiene `producto_terminado.ajustar`.

## Ejemplo: emitir una factura POS interna

Es una factura **interna** de TexCore (comprobante propio): **no es factura electrónica ante la DIAN**, y la respuesta lo recuerda en `aviso`.
Antes se leen el cliente (`GET /api/ventas/clientes/`), las variantes y su disponibilidad (`GET /api/terminado/existencias/`) y las reglas
(`GET /api/ventas/metadatos/`). Cada línea es una variante (talla y color) con su `cantidad` y el `descuento_pct` que decide el vendedor.
`token` es un UUID que genera el formulario y evita facturar dos veces con un doble clic. `transportadora` (`INTERRAPIDISIMO`, `ENVIA` u
`OTRA`), `numero_guia` y `observaciones` son opcionales. Aquí se venden 4 prendas a un cliente mayorista (tope de descuento: 15 %).

```bash
curl -X POST http://localhost:8000/api/ventas/facturas/   -H "Authorization: Bearer <access>" -H "Content-Type: application/json"   -d '{"cliente": 2, "lineas": [{"variante": 11, "cantidad": 3, "descuento_pct": 10}, {"variante": 12, "cantidad": 1}], "transportadora": "ENVIA", "numero_guia": "", "observaciones": "Entrega en la sede principal", "token": "3c9f6a52-8d1e-4b7a-a0c4-5e2d7b91f6a8"}'
```

Respuesta `201` con la factura (`FV-0001`): los datos del cliente, el `vendedor_nombre`, `modalidad_pago` (`CONTRAENTREGA`), `estado_cobro`
(`POR_COBRAR`), los montos en pesos enteros (`subtotal`, `descuento_total`, `base_gravable`, `iva_tarifa`, `iva_total`, `total` y
`valor_a_recaudar`), `aviso` y sus `lineas` (precio unitario, descuento, base, IVA y total de cada una). Cada línea baja el saldo de su
variante y deja un movimiento `SALIDA_VENTA` en `GET /api/terminado/movimientos/`. Con `GET /api/ventas/facturas/<id>/pdf/` se descarga el PDF.
Errores:

- `400` si falta stock: no se guarda nada y se listan **todas** las faltantes
  (`{"lineas": ["Stock insuficiente. REF-0001 30 Azul: hay 2 y pides 3."], "faltantes": [{"variante": 11, "nombre": "REF-0001 30 Azul", "disponible": 2, "pedido": 3}]}`).
- `400` si el descuento pasa del tope del tipo de cliente (`«…: el descuento máximo para un cliente mayorista es 15 %.»`) o deja el precio por
  debajo del costo de fábrica (`«…: con 15 % el precio queda por debajo del costo de fábrica ($50.000).»`).
- `400` si no hay líneas, una variante se repite o no existe, una cantidad no es un entero mayor que cero, el cliente no existe o está inactivo,
  una referencia no tiene precio registrado, la transportadora no es de la lista o falta el `token`.
- `409` si ese `token` ya generó una factura (`{"detail": ["Esta venta ya se facturó como FV-0001."], "factura": 1, "numero": "FV-0001"}`).
- `403` si el rol no tiene `ventas.gestionar`.

Para anular se envía `POST /api/ventas/facturas/<id>/anular/` con `{"motivo": "El cliente canceló el pedido antes del despacho"}` (de 10 a 255
caracteres). Responde `200` con la factura en estado `ANULADA` y deja un movimiento `DEVOLUCION_VENTA` por línea. Errores: `400` si el motivo
es muy corto, `409` si la factura ya estaba anulada (`{"detail": ["La factura FV-0001 ya está anulada."]}`) y `403` si el rol no tiene
`ventas.anular`.

## Ejemplo: anotar la guía, despachar y consultar el estado

La guía **se genera en el portal de la transportadora antes de facturar** y se anota en la venta: `POST /api/ventas/facturas/` acepta
`transportadora` y `numero_guia` (opcionales; con número, la transportadora es obligatoria) y la guía nace en la misma transacción que la factura,
en estado `POR_DESPACHAR`. Si no se anotó, la factura aparece en `GET /api/envios/pendientes/` y se anota después:

```bash
curl -X POST http://localhost:8000/api/envios/facturas/1/guia/   -H "Authorization: Bearer <access>" -H "Content-Type: application/json"   -d '{"transportadora": "INTERRAPIDISIMO", "numero_guia": "700187211301"}'
```

Responde `201` con la guía. Los espacios del número se quitan; un número de Interrapidísimo que no tenga 12 dígitos se acepta, pero la guía trae
`aviso_formato`. Si la factura ya tenía una guía **por despachar**, esa se anula y la nueva la reemplaza; si ya salió, no se puede reemplazar.
Errores: `400` si el número ya está asignado a otra factura de esa transportadora, la factura está anulada o ya se gestionó como devolución;
`403` si el rol no tiene `envios.anotar`.

Para despachar se arma la **relación de despacho** con las guías `POR_DESPACHAR` de **una misma transportadora** (hasta 100). `token` es un UUID que
genera el formulario y evita crear la relación dos veces:

```bash
curl -X POST http://localhost:8000/api/envios/relaciones/   -H "Authorization: Bearer <access>" -H "Content-Type: application/json"   -d '{"transportadora": "INTERRAPIDISIMO", "guias": [1, 2, 3], "responsable": "Bodega", "token": "9d2f4b6e-1c3a-4e58-b7d0-6a8c2e41f357"}'
```

Responde `201` con la relación (`RD-0001`) y sus guías, ya `EN_TRANSITO`; el PDF para firmar está en `GET /api/envios/relaciones/<id>/pdf/`. Es
atómica: si **una** guía no sirve (no existe, no está por despachar, es de otra transportadora o su factura está anulada) responde `400` con todos
los problemas y no cambia ninguna ni gasta el consecutivo. `409` si ese `token` ya generó una relación
(`{"detail": ["Esta relación ya se creó como RD-0001."], "relacion": 1, "codigo": "RD-0001"}`). Exige `envios.gestionar`.

El estado se cambia a mano con `POST /api/envios/guias/<id>/estado/` (`{"estado": "EN_NOVEDAD", "nota": "Dirección errada"}`). Las transiciones son
`POR_DESPACHAR → EN_TRANSITO | ANULADA`, `EN_TRANSITO → ENTREGADA | EN_NOVEDAD | DEVUELTA` y `EN_NOVEDAD → EN_TRANSITO | ENTREGADA | DEVUELTA`; las
guías entregadas, devueltas y anuladas ya no se mueven. **Novedad y devolución exigen una `nota` de al menos 5 caracteres.** Un salto no permitido o
una nota corta responden `400`.

Con `POST /api/envios/guias/<id>/rastrear/` (cuerpo opcional `{"forzar": true}`) el sistema le pregunta a Track123 por el estado real y lo aplica por
las mismas transiciones. **Nunca se llama solo**, y solo para Interrapidísimo. La respuesta es el detalle de la guía más `aviso` (qué se ignoró
o por qué no hubo cambio; vacío si todo fue bien). Errores:

- `429` si la guía se consultó hace menos de 10 minutos (`{"detail": ["Esta guía se consultó hace poco: intenta de nuevo en 7 min."], "segundos": 420}`).
- `503` si el rastreo está apagado o sin clave, si Track123 no respondió o si rechazó la clave: la guía no cambia.
- `400` si la guía es de otra transportadora, está anulada o reemplazada, ya terminó (entregada o devuelta, con su respuesta guardada), la cuota de
  registros está en la reserva o Track123 rechazó la guía.
- `403` si el rol no tiene `envios.gestionar`.

Cuando la guía llega devuelta, `POST /api/envios/guias/<id>/devolucion/` (`envios.devolucion`) registra la devolución en cartera con la misma regla
de la HU 7.3: las prendas vuelven al inventario **una sola vez** y la factura queda en `DEVOLUCION`. `400` si la guía no está devuelta o la
factura ya se gestionó. El flete (`PATCH /api/envios/guias/<id>/flete/` con `{"valor_flete": 12000}`, un entero de 0 a 10.000.000) se guarda en la
guía; si la guía está devuelta, es además el `flete_vendedor`: se registra y se reporta en el resumen, pero no se descuenta de nada.

Anular una factura (`POST /api/ventas/facturas/<id>/anular/`) con la guía ya despachada se rechaza con `400`; con la guía por despachar, se anula
también la guía.

## Mantener la documentación al día

La referencia se actualiza sola al cambiar el código. Para que un endpoint nuevo quede bien documentado:

1. Dale un `serializer_class`, o usa `@extend_schema` con `request` y `responses` si la vista es un `APIView`.
2. Añade `summary`, `description` y `tags` (ver `apps/inventory/views.py` como modelo).
3. Valida el esquema: `python manage.py spectacular --validate --file schema.yml` debe terminar sin errores (borra después `schema.yml`).
