# Módulos y reglas de negocio

Resumen técnico de lo construido hasta ahora: por cada historia de usuario, qué hace, dónde vive en el
código, qué ruta la expone, qué permiso exige y qué reglas aplica. Los detalles de cada endpoint (parámetros,
cuerpos y respuestas) están en Swagger (`/api/docs/`); cómo se usa cada pantalla está en el
[manual de usuario](manual-de-usuario.md); los permisos por rol, en [roles y permisos](roles-y-permisos.md).

| Historia | Tema | App | Pantalla |
|---|---|---|---|
| HU 1.x | Seguridad, usuarios, roles y permisos | `users` | Seguridad y Usuarios |
| HU 2.1 a 2.4 | Inventario: proveedores, catálogo, movimientos, alertas | `inventory` | Inventario de Materias Primas |
| Compras | Órdenes de compra y recepción de mercancía | `purchasing` | Compras |
| HU 3.1 (TE-49) | Referencias de jean | `references` | Referencias de Jean |
| HU 3.2 (TE-50) | Ficha técnica de consumo por unidad | `references` | Botón *Ficha técnica* del catálogo de jeans |
| HU 4.1 (TE-51) | Validación de material y planificación | `production` | Órdenes de producción |
| HU 4.2 (TE-52) | Órdenes de producción y lotes | `production` | Órdenes de producción |
| HU 4.3 (TE-53) | Control de tiempos por etapa | `production` | Órdenes de producción → Seguimiento |
| HU 4.4 (TE-54) | Asignación de recursos | `production` | Recursos y Seguimiento |
| HU 4.5 (TE-55) | Monitor de estado | `production` | Monitor de estado |
| HU 4.6 (TE-56) | Costeo y liquidación de órdenes | `production`, `inventory` | Liquidación de Órdenes |
| HU 6.1 (TE-59) | Registro de marras y calidad | `quality` | Control de Calidad → Inspecciones y Defectos |
| HU 6.2 (TE-60) | Ingreso a inventario final (producto terminado) | `finished` | Producto Terminado → Ingreso, Existencias y Movimientos |

Cómo se conectan entre sí:

```mermaid
flowchart LR
    COMP["Compras<br/>orden → aprobación → recepción"] -- "ingreso con costo" --> INV[("Inventario<br/>stock · kardex · costo promedio")]
    REF["Referencias<br/>+ ficha técnica"] -- "consumo por prenda" --> PLAN["Simulación de material"]
    INV -- "stock disponible" --> PLAN
    PLAN --> ORD["Orden de producción<br/>y lotes"]
    ORD -- "descuenta el material<br/>(foto del costo)" --> INV
    ORD --> TIEMPOS["Etapas: corte → confección → terminación<br/>tiempos y asignación de recursos"]
    TIEMPOS --> MON["Monitor de estado"]
    TIEMPOS -- "minutos netos × tarifa" --> COSTEO["Liquidación y costo por prenda"]
    INV -- "costo unitario del material" --> COSTEO
    TIEMPOS -. "el lote sale a lavandería<br/>y vuelve recibido" .-> CAL["Control de calidad<br/>inspección del lote"]
    CAL -- "aptas · marras por defecto" --> RES["Resultado de la inspección<br/>(solo se agrega)"]
    RES -- "solo las aptas, repartidas<br/>por talla y color" --> TER[("Producto terminado<br/>stock por variante · libro de movimientos")]
```

## Seguridad y usuarios (HU 1.x)

- **Autenticación:** JWT (`/api/token/`); `access` de 15 min y `refresh` rotativo de 30 min.
- **Cuentas:** el registro público crea un usuario en rol `PENDING` con el área que pidió; un administrador lo aprueba
  asignándole rol. Las cuentas creadas por un administrador reciben una invitación (48 h) para definir su contraseña.
- **Recuperación de contraseña:** enlace de un solo uso que vence a los 15 minutos; solo se guarda su SHA-256.
- **Roles y permisos:** ver [roles y permisos](roles-y-permisos.md). Rutas en `apps/users/urls.py`.

## Inventario (HU 2.1 a 2.4)

App `apps/inventory`. Toda la lógica de stock está en `services.py` y todas las rutas cuelgan de `/api/inventario/`.

- **Catálogo:** nueve categorías que fijan tipo, unidades y datos obligatorios (ancho útil y composición para telas e hilos).
  Código automático por categoría (`TEL-0001`).
- **Kardex:** el stock solo cambia con movimientos (`Movimiento`), cada uno con saldo antes y después, usuario y fecha.
  Los saldos se bloquean por fila al escribir, así dos salidas simultáneas no dejan el stock en negativo.
- **Órdenes de salida:** `OP-0001` (producción) y `LV-0001` (lavandería), con varias líneas. Una salida con stock
  insuficiente se rechaza completa y devuelve `faltantes`. Anular una orden en proceso devuelve las cantidades.
- **Costo promedio ponderado:** cada compra puede traer `costo_unitario`; el costo del producto se recalcula como
  `(existencias × promedio + compra × costo) / (existencias + compra)`. Si lo que había no tenía costo, manda el de la
  compra; una compra sin costo no cambia el promedio. Al salir material por una orden, la línea guarda una **foto del
  costo** vigente (`OrdenLinea.costo_unitario`), que es la que usa el costeo.
- **Evidencias:** foto o PDF (5 MB, hasta 10 por movimiento u orden), validadas por su contenido.

## Compras: órdenes de compra y recepción de mercancía

App `apps/purchasing`, rutas bajo `/api/compras/`, tablas `compras_*`.

```mermaid
stateDiagram-v2
    [*] --> Borrador: Producción crea (OC-0001)
    Borrador --> Aprobada: Gerente aprueba
    Borrador --> Cancelada: cancelar (motivo)
    Aprobada --> Cancelada: cancelar, sin recepciones
    Aprobada --> RecibidaParcial: recepción incompleta
    Aprobada --> Recibida: recepción completa
    RecibidaParcial --> RecibidaParcial: otra recepción
    RecibidaParcial --> Recibida: completa lo pendiente
    RecibidaParcial --> Cerrada: cerrar (motivo)
```

| Regla | Detalle |
|---|---|
| Quién hace qué | Producción crea, edita (solo en borrador), cancela y cierra (`compras.gestionar`); el Gerente aprueba (`compras.aprobar`); el Almacenista recibe (`inventario.gestionar`). |
| Contenido de la orden | Solo materia prima e insumos, sin repetir producto, hasta 100 líneas. El precio pactado por unidad es opcional. |
| Recepción | Varias filas en una sola transacción: si una falla, no se guarda ninguna. Cada fila lleva cantidad, lote y costo real (opcional). Código `RC-0001`. |
| Tolerancia | Se puede recibir hasta un **5 %** más de lo pendiente de cada línea (`OVERAGE_TOLERANCE`, fijo en el código). |
| Estados | Se guardan: borrador, aprobada, recibida parcial, recibida, cerrada y cancelada. La cantidad recibida de cada línea **no** se guarda: se suma de las recepciones. |
| Separación de funciones | Quien creó la orden no puede registrar su recepción. |
| Entrega sin orden | La recepción sin `orden` registra varios productos de un proveedor (remisión o factura, lote y costo). |
| Efecto en el inventario | Cada fila se registra con la misma regla del ingreso: suma al stock, recalcula el costo promedio y deja su fila en el kardex con el código de la orden y de la recepción. |

## Referencias de jean (HU 3.1, TE-49)

App `apps/references`, rutas bajo `/api/referencias/`, tablas `referencias_*`.

- Una **referencia** (`REF-0001`) tiene nombre, ajuste (skinny, slim, recto, bootcut, mom, wide leg, jogger u otro),
  descripción, **variantes** (talla × color, hasta 60) y hasta cinco imágenes del prototipo (2 MB cada una, una principal).
- **Estados:** `BORRADOR → ACTIVA → DESCONTINUADA` (y de vuelta a activa). Para activarla hacen falta al menos una variante
  y una imagen. Solo se archiva una referencia que no esté activa.
- Las imágenes se guardan en la base y se sirven con sesión y `ETag`.

## Ficha técnica de consumo por unidad (HU 3.2, TE-50)

- Una ficha por referencia: lista de materiales (materia prima o insumo del inventario, sin repetir, hasta 50) con
  **cantidad por prenda** (hasta 3 decimales; entera para botones, cierres y remaches) y **merma %** (0 a 50). Opcionalmente
  el tipo de lavado (`STONE_WASH`, `ENZIMATICO`, `LEJIA`, `OZONO`, `LASER` u `OTRO`) y notas.
- Guardar la ficha **reemplaza** la lista anterior. No se puede quitar mientras la referencia tenga órdenes en proceso.
- **Consumo contra el stock** (`/api/inventario/fichas-tecnicas/<id>/consumo/?cantidad=N`): la merma se aplica una sola vez
  y el resultado se redondea hacia arriba. Es una simulación; no reserva stock.
- **PDF de la ficha extensa** (geometral, secuencia de confección, tabla de medidas): hasta 5 MB, detectado por su contenido
  y guardado en la base. Se descarga con `ETag`.
- Permisos propios: `fichas_tecnicas.ver` y `fichas_tecnicas.gestionar`.

## Validación de material y planificación (HU 4.1, TE-51 / TE-110)

`POST /api/produccion/simulacion/` recibe referencia, cantidad y, opcionalmente, la lista de lotes. Devuelve:

- `viable`, y por material lo **requerido**, lo **disponible** y lo que **falta**;
- el **máximo producible** con el stock actual y su **cuello de botella** (el material que limita);
- si hay lotes, la **cobertura acumulada**: los lotes comparten el mismo stock, así que un lote se cubre si alcanza para
  él y los anteriores juntos.

Es de solo lectura (basta `produccion.ver`): la orden vuelve a verificar el stock bajo bloqueo al crearse. La pantalla
la llama sola, con una pequeña espera mientras se escribe.

## Órdenes de producción y lotes (HU 4.2, TE-52)

`POST /api/produccion/ordenes/` crea, en **una sola transacción**: la salida de inventario (que descuenta el material de
la ficha, con su merma), la orden de producción (`OP-0001`, el mismo código de la salida), sus lotes (`OP-0001-L01`…, hasta 50,
que deben sumar exactamente el total) y, opcionalmente, las tallas de cada lote. Si falta material no queda nada ni se gasta
el consecutivo. Anular la orden (`/anular/`, con motivo) devuelve el material y deja los lotes como historial.

## Control de tiempos por etapa (HU 4.3, TE-53)

- Cada lote recorre **Corte → Confección → Terminación**, en ese orden; una etapa empieza cuando la anterior terminó y un
  lote tiene una sola etapa en curso. La lavandería, la calidad y el empaque no son etapas de este seguimiento.
- Acciones: `iniciar`, `pausar`, `reanudar`, `completar` (`POST /api/produccion/lotes/<id>/<accion>/`). Cada una queda en el
  historial de la etapa (`EventoEtapa`), que solo recibe filas nuevas.
- **Tiempo neto** = suma de los intervalos en que la etapa estuvo corriendo; el tiempo en pausa no cuenta.
- El **estado** del lote y de la orden (*Planeada, En proceso, En pausa, Terminada, Cancelada*) **no se guarda**: se calcula
  desde sus etapas y desde la anulación. El bloqueo del lote evita que dos personas se pisen.

## Asignación de recursos (HU 4.4, TE-54)

- **Catálogo:** `Operario` (`OPE-0001`; etapas en que puede trabajar y forma de pago, solo informativa) y `Maquina`
  (`MAQ-0001`; tipo, serial, ubicación, etapas y estado físico: disponible, en mantenimiento o fuera de servicio).
  Un operario no necesita usuario del sistema. Nada se borra: se desactiva.
- **Asignación por etapa** (`AsignacionEtapa`): `asignar/` asigna, reasigna o quita; `desvincular/` quita el operario, la
  máquina o ambos; `asignaciones/` muestra el historial. Cada cambio cierra la asignación abierta y abre otra.
- **Se rechaza:** recurso inactivo o no habilitado para la etapa, máquina en mantenimiento o fuera de servicio, etapa terminada,
  orden anulada. **Solo se avisa** (campo `advertencias`): que el operario o la máquina ya estén en otra etapa en curso.
- Terminar la etapa o anular la orden libera los recursos. «Ocupado» se calcula con las asignaciones abiertas; no se guarda.

## Monitor de estado (HU 4.5, TE-55)

`GET /api/produccion/monitor/` devuelve los lotes en cuatro columnas (Planeada, En proceso, En pausa, Terminada) con su total.

| Parámetro | Efecto |
|---|---|
| `limite` | Tarjetas por columna (50 por defecto, máximo 200). Los totales siempre cuentan todo. |
| `orden`, `referencia` | Filtran por id; los totales respetan el filtro. |
| `terminadas_dias` | Ventana de la columna Terminada (7 por defecto, máximo 90). |
| `canceladas=1` | Agrega una columna Cancelada, de solo consulta. |

Cada tarjeta trae su `alerta` por tiempo detenido: `ATENCION` desde 2 horas y `CRITICA` desde 8 horas, para lotes en pausa o
entre una etapa y la siguiente. La respuesta resume las alertas de todos los lotes activos. Dentro de cada columna va primero lo
que más tiempo lleva esperando (en Terminada, lo más reciente). La pantalla se actualiza sola cada 20 s y permite mover un lote
arrastrando su tarjeta, lo que aplica la acción de la etapa en curso si es válida.

## Costeo y liquidación (HU 4.6, TE-56 / TE-129 / TE-130)

`GET /api/produccion/ordenes/<id>/costos/` calcula la liquidación de una orden (motor puro en `apps/production/costing.py`):

- **Materiales** = cantidad × costo unitario de la foto guardada en cada línea de la salida. Como el material se descuenta por
  orden completa, a cada lote se le asigna `total_materiales × prendas_del_lote / prendas_de_la_orden`.
- **Mano de obra** por lote y etapa = `(segundos netos / 60) × tarifa por minuto`, con la tarifa vigente a la fecha en que terminó
  la etapa (o a hoy si sigue en curso; entonces el costo es *provisional*).
- **Tarifas** (`/api/produccion/tarifas/`): historial por etapa; nunca se editan ni se borran. Para cambiar un precio se
  registra una nueva vigencia (`vigente_desde`).
- Se redondea a centavos solo al final (mitad hacia arriba). La respuesta incluye totales, **costo por prenda**, distribución
  porcentual y `completo: false` con `advertencias` si falta una tarifa o el costo de un material (*Sin tarifa*, *Sin costo*).
- Una orden anulada devuelve todos los costos en cero, porque el material regresó al almacén.

## Control de calidad: marras y defectos (HU 6.1, TE-59)

App `apps/quality`, rutas bajo `/api/calidad/`, tablas `calidad_defecto`, `calidad_inspeccion` y `calidad_marra_detalle`.
Cubre RF19 (criterios de calidad) y RF20 (registro de marras). La lógica está en `services.py`; las constantes (permisos,
prefijos `DEF` e `INS`, máximo de defectos por inspección) en `catalog.py`.

```mermaid
flowchart LR
    LAV["Recepción de lavandería<br/>(cantidad recibida conforme)"] --> PEND["Lote por inspeccionar"]
    PEND --> FORM["Inspección:<br/>aptas + marras por defecto"]
    DEF["Catálogo de defectos<br/>corregible / incorregible"] --> FORM
    FORM -- "aptas + marras = recibidas conformes" --> OK["Inspección registrada<br/>(INS-0001, no se edita)"]
    FORM -- "no cuadra · lote ya inspeccionado" --> ERR["400 / 409: no se guarda nada"]
```

| Regla | Detalle |
|---|---|
| Catálogo de defectos (RF19) | Cada `TipoDefecto` (`DEF-0001`) tiene nombre (3 a 80 caracteres), descripción y tipo: **corregible** (se podría reprocesar) o **incorregible** (marra definitiva). El nombre no se repite, sin importar mayúsculas ni espacios de más, ni siquiera frente a uno desactivado. Nunca se borra: se **desactiva** (`PATCH` con `activo`), y un defecto inactivo no se puede elegir en una inspección nueva. |
| Qué se inspecciona | La base es lo **recibido conforme** (`RecepcionLote.cantidad_recibida_conforme`) en la recepción de lavandería más reciente del lote (HU 5.2, TE-58). Los faltantes y daños de lavandería ya los liquida esa recepción; aquí solo se clasifican las prendas que sí llegaron. No se modifica el modelo `Lote`. |
| Lote «por inspeccionar» | Está en planta, tiene una recepción con prendas conformes, su orden **no está anulada** y todavía **no tiene inspección**. Lo lista `GET /api/calidad/pendientes/`. |
| La suma debe cuadrar | `aptas + marras = cantidad recibida conforme`. Las marras son la suma de su desglose por defecto (hasta 30 defectos distintos, sin repetir, con cantidades enteras mayores que cero). Si no cuadra responde `400` indicando cuántas prendas faltan o sobran. Una restricción de la base (`ck_calidad_inspeccion_suma`) lo respalda. |
| Una inspección por lote | Si el lote ya fue inspeccionado responde `409` (también si otra persona la registró un instante antes: el lote se bloquea durante la transacción). Una restricción única lo respalda. |
| Solo se agrega | La inspección no tiene `PUT`, `PATCH` ni `DELETE`. Cada línea del desglose (`MarraDetalle`) guarda el **nombre y el tipo del defecto tal como estaban**, así que renombrar o desactivar un defecto después no cambia el historial. |
| Todo o nada | Se registra en una sola transacción: si algo falla no queda nada ni se gasta el consecutivo `INS-0001`. Se guardan el inspector (el usuario de la sesión), la fecha (hoy si no se envía) y observaciones de hasta 500 caracteres. |
| Se rechaza con `400` | Lote inexistente o sin recepción de lavandería lista, orden anulada, suma que no cuadra, defecto inactivo, inexistente o repetido, cantidades que no son enteras. |

Rutas y permisos (la referencia exacta está en Swagger, etiqueta `calidad`):

| Ruta | Operaciones | Permiso |
|---|---|---|
| `/api/calidad/defectos/` | `GET` (filtros `activo`, `q`, `limit`), `POST` | `calidad.ver` / `calidad.gestionar` |
| `/api/calidad/defectos/<id>/` | `GET`, `PATCH` | `calidad.ver` / `calidad.gestionar` |
| `/api/calidad/pendientes/` | `GET` | `calidad.ver` |
| `/api/calidad/inspecciones/` | `GET` (filtros `lote`, `orden`, `desde`, `hasta`, `q`, `limit`), `POST` | `calidad.ver` / `calidad.gestionar` |
| `/api/calidad/inspecciones/<id>/` | `GET` | `calidad.ver` |

Quién puede qué: el Personal de Terminación y el Jefe de Producción **gestionan** (definen defectos e inspeccionan; este último
por la migración `users/0010_permisos_calidad_produccion`), el Gerente solo **consulta** y el Administrador tiene todo. Ver
[roles y permisos](roles-y-permisos.md).

!!! warning "Limitaciones conocidas de la HU 6.1"
    - **Sin reproceso:** el tipo corregible/incorregible solo se registra; no hay flujo para reparar y volver a inspeccionar.
    - **Sin valoración de las marras:** no se calcula su costo ni su pérdida, y las aptas pasan al inventario de producto terminado
      (HU 6.2), pero las marras no tienen inventario.
    - **Sin muestreo AQL:** se clasifica el lote completo, no una muestra.
    - **Una inspección por lote y sin corrección:** si se digita mal una inspección no hay forma de corregirla desde el sistema
      (queda como pregunta pendiente para el responsable del producto).

## Producto terminado: ingreso al inventario final (HU 6.2, TE-60)

App `apps/finished`, rutas bajo `/api/terminado/`, tablas `terminado_stock`, `terminado_ingreso`, `terminado_ingreso_linea` y
`terminado_movimiento`. Cubre RF21 (ingreso de producto terminado). La lógica está en `services.py`; las constantes (permisos,
prefijo `IPT`, tipos de movimiento, máximo de líneas por ingreso) en `catalog.py`.

```mermaid
flowchart LR
    INS["Inspección de calidad<br/>(HU 6.1) con aptas"] --> PEND["Inspección por ingresar"]
    PEND --> FORM["Ingreso: aptas repartidas<br/>por talla y color"]
    REFV["Variantes de la referencia<br/>del lote"] --> FORM
    FORM -- "tallas suman exactamente las aptas" --> OK["Ingreso registrado (IPT-0001, no se edita)"]
    OK --> STOCK[("Stock por variante<br/>nunca negativo")]
    OK --> LIBRO[("Libro de movimientos<br/>saldo antes y después")]
    FORM -- "no cuadra · variante ajena · ya ingresada" --> ERR["400 / 409: no se guarda nada"]
```

| Regla | Detalle |
|---|---|
| Qué se ingresa | Solo las **aptas** de una inspección de calidad (HU 6.1). Las **marras no entran** a este saldo: siguen sin inventario hasta la HU 6.4 (TE-169). |
| Inspección «por ingresar» | Tiene al menos una prenda apta, su orden **no está anulada** y todavía **no tiene ingreso**. La lista `GET /api/terminado/pendientes/` trae además las variantes (talla y color) de la referencia del lote y lo planificado por talla. |
| La suma debe cuadrar | Las líneas por talla y color deben sumar **exactamente** las aptas de la inspección. Si no cuadra responde `400` indicando cuántas prendas faltan o sobran. Hasta 100 variantes por ingreso, sin repetir, con cantidades enteras mayores que cero. |
| Variantes de la referencia | Cada talla y color debe ser una variante de la **referencia del lote**; una ajena se rechaza con `400`. |
| Lo planificado es un dato | Lo que el lote tenía planificado por talla (`LoteTalla`) se copia a cada línea (`planificada`, con su `diferencia`) para comparar; **no es una regla**: se puede ingresar distinto de lo planificado mientras la suma cuadre. |
| Un ingreso por inspección | Si la inspección ya fue ingresada responde `409` (también si otra persona la ingresó un instante antes). Una restricción única de la base lo respalda. |
| Todo o nada | Una sola transacción con la inspección bloqueada: el ingreso (`IPT-0001`), el saldo de cada variante y su movimiento en el libro. Los saldos se bloquean por fila en orden de id para que dos ingresos simultáneos no se bloqueen entre sí. Si algo falla no queda nada ni se gasta el consecutivo. |
| Saldo y libro | El saldo (`StockTerminado`) nunca es negativo y solo cambia con un movimiento. Cada movimiento (`MovimientoTerminado`) guarda cantidad con signo, saldo antes y saldo después, y una restricción de la base exige `saldo_después = saldo_antes + cantidad`. Tipos: `ENTRADA_PRODUCCION` (hoy), `AJUSTE` (HU 6.3) y `SALIDA_VENTA` (HU 7.1). |
| Solo se agrega | No hay `PUT`, `PATCH` ni `DELETE`. Cada línea guarda la talla y el color tal como estaban al ingresar. |
| Ubicación en bodega | Solo un texto libre opcional por ingreso (hasta 80 caracteres), sin controles. |
| Código `IPT-0001` | No se usa `PT`, porque ese prefijo ya es el de los productos de la categoría Producto terminado del inventario de materias primas. |

Rutas y permisos (la referencia exacta está en Swagger, etiqueta `producto-terminado`):

| Ruta | Operaciones | Permiso |
|---|---|---|
| `/api/terminado/pendientes/` | `GET` | `producto_terminado.ver` |
| `/api/terminado/ingresos/` | `GET` (filtros `referencia`, `lote`, `desde`, `hasta`, `q`, `limit`), `POST` | `producto_terminado.ver` / `producto_terminado.gestionar` |
| `/api/terminado/ingresos/<id>/` | `GET` | `producto_terminado.ver` |
| `/api/terminado/existencias/` | `GET` (filtro `referencia`): matriz referencia × color × talla, con las celdas en cero | `producto_terminado.ver` |
| `/api/terminado/movimientos/` | `GET` (filtros `referencia`, `variante`, `tipo`, `desde`, `hasta`, `limit`) | `producto_terminado.ver` |

Quién puede qué: la Secretaria y el Administrador **gestionan** (ingresan); el Vendedor y el Gerente solo **consultan**. Los permisos
`producto_terminado.ver` y `producto_terminado.gestionar` ya existían desde la matriz inicial, así que **no hay migración de permisos
nueva**. Ver [roles y permisos](roles-y-permisos.md).

!!! warning "Limitaciones conocidas de la HU 6.2"
    - **Sin reversa de ingresos:** un ingreso equivocado se corrige con un ajuste de la HU 6.3, que todavía no está hecha.
    - **Sin ubicaciones controladas:** la ubicación es solo texto libre; el aviso MSG-WRN-05 queda pendiente.
    - **Sin reservas ni valorización de costos:** el saldo es de cantidades; no se reserva para pedidos ni se calcula su valor.
    - **Sin recepción parcial:** se ingresan todas las aptas de la inspección de una vez.
    - **Sin notificación por correo** del nuevo stock (el aviso es una tarjeta en el inicio).
    - **Las marras siguen sin inventario** (HU 6.4, TE-169).

## Datos de demostración

Comandos solo para desarrollo (exigen `DJANGO_DEBUG=true`), idempotentes y que pasan por las mismas reglas que la aplicación.
`seed_demo_calidad` crea 8 defectos típicos de denim y dos lotes devueltos de lavandería (uno inspeccionado y otro por inspeccionar); necesita antes `seed_demo_inventario` y `seed_demo_produccion`. `seed_demo_terminado` ingresa al inventario final las aptas de la inspección de demostración; necesita antes `seed_demo_calidad`. Orden recomendado: ver [manual del sistema](manual-del-sistema.md#datos-de-demostracion).
