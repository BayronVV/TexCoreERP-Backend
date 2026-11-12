# Roles y permisos

TexCore controla el acceso por **rol** (RBAC, RNF01). Cada rol tiene permisos con la forma `<módulo>.<acción>` y
cada ruta de la API exige uno. El menú del sistema también se arma con ellos: un módulo aparece solo si el rol
tiene `<módulo>.ver`.

## Roles base

| Código | Nombre | Para qué sirve |
|---|---|---|
| `ADMIN` | Administrador | Gestiona usuarios, roles y la configuración. Tiene **todos** los permisos de forma implícita y no se puede restringir. |
| `GERENTE` | Gerente | Consulta toda la operación (incluidos la lavandería y los envíos), consulta el **tablero de reportes gerenciales**, **aprueba las órdenes de compra**, fija los precios, anula facturas y registra la devolución física de los paquetes. |
| `PRODUCCION` | Jefe de Producción | Referencias, fichas técnicas, órdenes y lotes, tiempos, recursos, costeo, órdenes de compra, criterios de calidad y **lavandería** (remisión de salida y recepción). |
| `ALMACENISTA` | Almacenista | Proveedores, materias primas, movimientos y **recepción de mercancía**. En envíos arma las relaciones de despacho, cambia los estados de las guías y registra la devolución física. |
| `TERMINACION` | Personal de Terminación | Control de calidad: define los defectos e inspecciona los lotes que vuelven de lavandería. |
| `SECRETARIA` | Secretaria | Producto terminado: ingresa al inventario final las prendas aptas de cada inspección, ajusta el inventario contra el conteo físico y consulta existencias y movimientos. En envíos anota guías, arma relaciones de despacho y cambia los estados. |
| `VENDEDOR` | Vendedor | Consulta el producto terminado disponible, registra clientes y emite las facturas POS internas de venta (descuenta el inventario) y **concilia el cobro contraentrega** de cada una (pagada o devolución). Anota la guía de la transportadora al facturar y consulta los envíos. |
| `PENDING` | Pendiente de aprobación | Cuenta recién registrada: **sin permisos** hasta que un administrador le asigne un rol. |

Los roles base no se eliminan. Un administrador puede crear roles propios desde **Seguridad y Usuarios → Roles y
permisos**; el código de un rol no cambia después de creado.

## Permisos por módulo

Cada módulo tiene `ver` (consultar) y `gestionar` (registrar y modificar). Marcar `gestionar` marca también `ver`.

| Módulo | Permisos | Estado |
|---|---|---|
| Seguridad y Usuarios | `seguridad.ver`, `seguridad.gestionar`, `seguridad.roles` | Activo |
| Inventario de Materias Primas | `inventario.ver`, `inventario.gestionar` | Activo |
| Compras | `compras.ver`, `compras.gestionar`, `compras.aprobar` | Activo |
| Referencias de Jean | `referencias.ver`, `referencias.gestionar` | Activo |
| Fichas Técnicas | `fichas_tecnicas.ver`, `fichas_tecnicas.gestionar` | Activo. Se edita **dentro del Catálogo de jeans**, por eso no tiene entrada propia en el menú; sus permisos sí aparecen en *Roles y permisos* |
| Producción y Trazabilidad | `produccion.ver`, `produccion.gestionar` | Activo |
| Procesos Externos (Lavandería) | `lavanderia.ver`, `lavanderia.gestionar` | Activo (Remisión de salida y Recepción de lavandería) |
| Control de Calidad | `calidad.ver`, `calidad.gestionar` | Activo (Inspecciones y Defectos) |
| Producto Terminado | `producto_terminado.ver`, `producto_terminado.gestionar`, `producto_terminado.ajustar` | Activo (Ingreso, Existencias, Ajuste manual y Movimientos) |
| Ventas y Despachos | `ventas.ver`, `ventas.gestionar`, `ventas.precios`, `ventas.anular` | Activo (Panel de ventas, Nueva venta, Facturas, Clientes, Precios y Cartera) |
| Envíos | `envios.ver`, `envios.anotar`, `envios.gestionar`, `envios.devolucion` | Activo (Guías, Por despachar / sin guía, Relaciones de despacho y Resumen) |
| Reportes | `reportes.ver`, `reportes.gestionar` | Activo (Tablero gerencial). Las rutas hoy solo exigen `reportes.ver`; `reportes.gestionar` existe en el catálogo pero ninguna ruta lo pide |

## Matriz inicial rol → permiso

Es la que dejan las migraciones (`0003`, `0007`, `0008`, `0010`, `0011`, `0012` y `0013` de `apps/users`; las demás no tocan permisos). En total son 31 permisos en 12 módulos. El Sprint 3 no agregó permisos: la lavandería, la cartera y los reportes usan los que ya existían. Después se ajusta desde la pantalla de
roles, así que la matriz real de un despliegue puede diferir. `ADMIN` no aparece porque lo tiene todo.

| Permiso | GERENTE | PRODUCCION | ALMACENISTA | TERMINACION | SECRETARIA | VENDEDOR |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| `inventario.ver` | ✔ | ✔ | ✔ | | | |
| `inventario.gestionar` | | | ✔ | | | |
| `compras.ver` | ✔ | ✔ | ✔ | | | |
| `compras.gestionar` | | ✔ | | | | |
| `compras.aprobar` | ✔ | | | | | |
| `referencias.ver` | ✔ | ✔ | ✔ | | | ✔ |
| `referencias.gestionar` | | ✔ | | | | |
| `fichas_tecnicas.ver` | ✔ | ✔ | | | | |
| `fichas_tecnicas.gestionar` | | ✔ | | | | |
| `produccion.ver` | ✔ | ✔ | | | | |
| `produccion.gestionar` | | ✔ | | | | |
| `lavanderia.ver` | ✔ | ✔ | | | | |
| `lavanderia.gestionar` | | ✔ | | | | |
| `calidad.ver` | ✔ | ✔ | | ✔ | | |
| `calidad.gestionar` | | ✔ | | ✔ | | |
| `producto_terminado.ver` | ✔ | | | | ✔ | ✔ |
| `producto_terminado.gestionar` | | | | | ✔ | |
| `producto_terminado.ajustar` | | | | | ✔ | |
| `ventas.ver` | ✔ | | | | | ✔ |
| `ventas.gestionar` | | | | | | ✔ |
| `ventas.precios` | ✔ | | | | | |
| `ventas.anular` | ✔ | | | | | |
| `envios.ver` | ✔ | | ✔ | | ✔ | ✔ |
| `envios.anotar` | | | ✔ | | ✔ | ✔ |
| `envios.gestionar` | | | ✔ | | ✔ | |
| `envios.devolucion` | ✔ | | ✔ | | | |
| `reportes.ver` | ✔ | | | | | |
| `reportes.gestionar` | ✔ | | | | | |

`seguridad.*` solo lo tiene `ADMIN` por defecto. `PENDING` no tiene ninguno.

## Qué exige cada operación

La referencia exacta de cada ruta está en Swagger. Este resumen sirve para decidir qué permiso darle a un rol.

| Operación | Permiso |
|---|---|
| Ver y gestionar usuarios | `seguridad.ver` / `seguridad.gestionar` |
| Crear, editar y eliminar roles | `seguridad.roles` |
| Consultar existencias, catálogo, proveedores, kardex, órdenes de salida y alertas | `inventario.ver` |
| Registrar ingresos, crear o anular salidas, editar catálogo y proveedores, adjuntar evidencias | `inventario.gestionar` |
| **Recibir mercancía** (`/api/compras/recepciones/`) | `inventario.gestionar` (es un ingreso al almacén) |
| Consultar órdenes de compra, recepciones y metadatos | `compras.ver` |
| Crear, editar, cancelar y cerrar órdenes de compra | `compras.gestionar` |
| Aprobar una orden de compra | `compras.aprobar` |
| Consultar referencias e imágenes | `referencias.ver` |
| Crear, editar, activar, archivar referencias y manejar sus imágenes | `referencias.gestionar` |
| Consultar la ficha técnica y descargar su PDF | `fichas_tecnicas.ver` |
| Guardar, quitar la ficha y adjuntar o quitar el PDF | `fichas_tecnicas.gestionar` |
| Listar referencias para elegir en una orden y consultar el consumo contra el stock | `inventario.ver` |
| Simular la producción, ver órdenes, lotes, historial, monitor, costos, operarios, máquinas y asignaciones | `produccion.ver` |
| Crear y anular órdenes de producción, controlar los tiempos de un lote, asignar o desvincular recursos, crear o editar operarios y máquinas, registrar tarifas | `produccion.gestionar` |
| Consultar el catálogo de defectos, los lotes por inspeccionar y las inspecciones | `calidad.ver` |
| Crear, editar, activar y desactivar defectos; registrar la inspección de un lote | `calidad.gestionar` |
| Consultar las inspecciones por ingresar, los ingresos, las existencias en matriz y el libro de movimientos de producto terminado | `producto_terminado.ver` |
| Ingresar al inventario final las aptas de una inspección | `producto_terminado.gestionar` |
| Consultar los ajustes manuales y sus motivos | `producto_terminado.ver` |
| Ajustar el inventario de producto terminado contra el conteo físico | `producto_terminado.ajustar` |
| Consultar clientes, precios, facturas (con su detalle y PDF), los metadatos de ventas y el resumen de cartera (`/api/ventas/cartera/resumen/`) | `ventas.ver` |
| Registrar y modificar clientes; **emitir una factura** (descuenta el inventario); **conciliar el cobro contraentrega** de una factura (pagada o devolución) | `ventas.gestionar` |
| Registrar o actualizar el costo de fábrica y los precios de una referencia | `ventas.precios` |
| Anular una factura | `ventas.anular` |
| Consultar los lotes disponibles, las lavanderías, las recetas, el historial de remisiones, las remisiones pendientes y las actas de recepción de lavandería | `lavanderia.ver` |
| Despachar una remisión de salida a lavandería y asentar la recepción de lavandería | `lavanderia.gestionar` |
| Consultar el tablero gerencial y sus filtros, y forzar el refresco de sus vistas (`/api/reportes/…`) | `reportes.ver` |
| Consultar guías, su detalle e historial, las facturas sin guía, las relaciones de despacho (y su PDF), el resumen y los metadatos de envíos | `envios.ver` |
| Anotar o reemplazar el número de guía de una factura ya emitida (`/api/envios/facturas/<id>/guia/`) | `envios.anotar` |
| Armar una relación de despacho, cambiar el estado de una guía, registrar el flete, **consultar el estado en Track123** (gasta cuota de registros) y leer la cuota | `envios.gestionar` |
| Registrar en cartera la devolución física de un paquete (reingresa las prendas al inventario) | `envios.devolucion` |

### Reglas que no dependen del permiso

- **Separación de funciones en compras:** quien creó una orden de compra **no puede recibirla**, aunque tenga
  `inventario.gestionar`. Aprobar tampoco exige ser distinto de quien la creó, pero lo normal es que sea el Gerente.
- **Delegación segura:** alguien con `seguridad.gestionar` o `seguridad.roles` que no es administrador no puede crear
  administradores, asignar roles con permisos de Seguridad, dar o quitar esos permisos ni editar los de su propio rol.
- **Nadie sobre sí mismo:** no se cambia el propio rol ni se desactiva o elimina la propia cuenta, y siempre queda al
  menos un administrador activo.
- **Calidad no se corrige:** una inspección registrada no se edita ni se borra, ni siquiera con `calidad.gestionar` o siendo
  administrador; la ruta no existe.
- **Un ingreso no se edita:** un ingreso de producto terminado registrado no se modifica ni se borra, ni siquiera con
  `producto_terminado.gestionar` o siendo administrador; la ruta no existe. Un error se corrige con un ajuste manual (HU 6.3), que exige `producto_terminado.ajustar`. El libro
  de movimientos tampoco se escribe directamente desde la API: solo cambia al ingresar o al ajustar.
- **Un ajuste no se edita:** un ajuste manual registrado tampoco se modifica ni se borra, ni siquiera siendo administrador; la
  ruta no existe. Un ajuste equivocado se corrige con otro ajuste.
- **Una factura no se edita ni se borra:** una factura de venta emitida no se modifica ni se elimina, ni siquiera con `ventas.gestionar` o
  siendo administrador; la ruta no existe. Solo se **anula** (con `ventas.anular` y un motivo), y entonces las unidades vuelven al inventario
  por el libro y el número no se reutiliza. Los movimientos de venta (`SALIDA_VENTA` y `DEVOLUCION_VENTA`) solo los escribe la factura, no la API directamente.
- **La guía solo se anota con la factura emitida:** al facturar, la guía que viene en la venta se crea con el permiso de facturar (`ventas.gestionar`); anotarla o reemplazarla después es de `envios.anotar`. La guía vigente de una factura no se puede reemplazar cuando ya fue despachada.
- **El historial de una guía no se edita:** los cambios de estado quedan en un historial de solo inserción (quién, cuándo, desde dónde: a mano, Track123 o sistema); ni siquiera un administrador lo modifica. Una guía reemplazada pasa a *Anulada*, no se borra.
- **Los estados finales no se mueven:** una guía entregada, devuelta o anulada ya no cambia de estado, ni a mano ni por el rastreo.
- **El rastreo es de quien gestiona:** consultar el estado en Track123 gasta cuota de la cuenta, así que exige `envios.gestionar`; el Vendedor y el Gerente ven el último estado guardado pero no lo consultan.
- **La devolución física la registra bodega o gerencia:** `envios.devolucion` (Almacenista y Gerente). El flete de una devolución se registra a nombre del vendedor y solo se reporta.
- **La lavandería no se corrige:** una remisión o una recepción de lavandería registrada no se edita ni se borra, ni siquiera con `lavanderia.gestionar` o siendo administrador; la ruta no existe. Una remisión ya retornada o anulada no admite otra recepción, y la recepción exige cotejar todos los lotes de la remisión.
- **La cartera se concilia una vez:** una factura emitida pasa de `POR_COBRAR` a `PAGADO` o a `DEVOLUCION` una sola vez; después no se mueve, ni siquiera siendo administrador. Una factura anulada no se concilia. La devolución física que registra Envíos (`envios.devolucion`) usa esta misma conciliación.
- **Los reportes son de solo lectura:** el tablero gerencial no modifica nada; refrescar sus vistas tampoco cambia los datos de negocio, pero con `reportes.ver` basta para pedirlo.
- **Factura interna, no electrónica:** la factura POS es un comprobante propio de TexCore y no sustituye la factura electrónica ante la DIAN.
- **Quién decide los precios:** el Vendedor factura con los precios que fija el Gerente (`ventas.precios`); el descuento que da está limitado
  por el tipo de cliente y nunca baja del costo de fábrica, sin importar el permiso.
- **Falla cerrado:** una ruta sin permiso declarado niega el acceso (ver [arquitectura](arquitectura.md)).

El frontend solo decide qué mostrar; el backend valida el permiso en cada petición.
