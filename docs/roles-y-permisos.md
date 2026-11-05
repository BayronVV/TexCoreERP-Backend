# Roles y permisos

TexCore controla el acceso por **rol** (RBAC, RNF01). Cada rol tiene permisos con la forma `<módulo>.<acción>` y
cada ruta de la API exige uno. El menú del sistema también se arma con ellos: un módulo aparece solo si el rol
tiene `<módulo>.ver`.

## Roles base

| Código | Nombre | Para qué sirve |
|---|---|---|
| `ADMIN` | Administrador | Gestiona usuarios, roles y la configuración. Tiene **todos** los permisos de forma implícita y no se puede restringir. |
| `GERENTE` | Gerente | Consulta toda la operación, genera reportes y **aprueba las órdenes de compra**. |
| `PRODUCCION` | Jefe de Producción | Referencias, fichas técnicas, órdenes y lotes, tiempos, recursos, costeo, órdenes de compra y criterios de calidad. |
| `ALMACENISTA` | Almacenista | Proveedores, materias primas, movimientos y **recepción de mercancía**. |
| `TERMINACION` | Personal de Terminación | Control de calidad: define los defectos e inspecciona los lotes que vuelven de lavandería. |
| `SECRETARIA` | Secretaria | Producto terminado: ingresa al inventario final las prendas aptas de cada inspección, ajusta el inventario contra el conteo físico y consulta existencias y movimientos. |
| `VENDEDOR` | Vendedor | Consulta el producto terminado disponible, registra clientes y emite las facturas POS internas de venta (descuenta el inventario). Despachos y cobro llegan con las HU 7.2 y 7.3. |
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
| Procesos Externos (Lavandería) | `lavanderia.ver`, `lavanderia.gestionar` | Previsto (la salida a lavandería se opera hoy desde Inventario) |
| Control de Calidad | `calidad.ver`, `calidad.gestionar` | Activo (Inspecciones y Defectos) |
| Producto Terminado | `producto_terminado.ver`, `producto_terminado.gestionar`, `producto_terminado.ajustar` | Activo (Ingreso, Existencias, Ajuste manual y Movimientos) |
| Ventas y Despachos | `ventas.ver`, `ventas.gestionar`, `ventas.precios`, `ventas.anular` | Activo (Panel de ventas, Nueva venta, Facturas, Clientes y Precios; despachos y cobro, previstos) |
| Reportes | `reportes.ver`, `reportes.gestionar` | Previsto |

## Matriz inicial rol → permiso

Es la que dejan las migraciones (`0003`, `0007`, `0008`, `0010`, `0011` y `0012` de `apps/users`). Después se ajusta desde la pantalla de
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
| `reportes.ver`, `reportes.gestionar` | ✔ | | | | | |

`seguridad.*` solo lo tiene `ADMIN` por defecto.

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
| Consultar clientes, precios, facturas (con su detalle y PDF) y los metadatos de ventas | `ventas.ver` |
| Registrar y modificar clientes; **emitir una factura** (descuenta el inventario) | `ventas.gestionar` |
| Registrar o actualizar el costo de fábrica y los precios de una referencia | `ventas.precios` |
| Anular una factura | `ventas.anular` |

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
- **Factura interna, no electrónica:** la factura POS es un comprobante propio de TexCore y no sustituye la factura electrónica ante la DIAN.
- **Quién decide los precios:** el Vendedor factura con los precios que fija el Gerente (`ventas.precios`); el descuento que da está limitado
  por el tipo de cliente y nunca baja del costo de fábrica, sin importar el permiso.
- **Falla cerrado:** una ruta sin permiso declarado niega el acceso (ver [arquitectura](arquitectura.md)).

El frontend solo decide qué mostrar; el backend valida el permiso en cada petición.
