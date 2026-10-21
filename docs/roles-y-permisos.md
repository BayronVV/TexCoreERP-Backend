# Roles y permisos

TexCore controla el acceso por **rol** (RBAC, RNF01). Cada rol tiene permisos con la forma `<módulo>.<acción>` y
cada ruta de la API exige uno. El menú del sistema también se arma con ellos: un módulo aparece solo si el rol
tiene `<módulo>.ver`.

## Roles base

| Código | Nombre | Para qué sirve |
|---|---|---|
| `ADMIN` | Administrador | Gestiona usuarios, roles y la configuración. Tiene **todos** los permisos de forma implícita y no se puede restringir. |
| `GERENTE` | Gerente | Consulta toda la operación, genera reportes y **aprueba las órdenes de compra**. |
| `PRODUCCION` | Jefe de Producción | Referencias, fichas técnicas, órdenes y lotes, tiempos, recursos, costeo y órdenes de compra. |
| `ALMACENISTA` | Almacenista | Proveedores, materias primas, movimientos y **recepción de mercancía**. |
| `TERMINACION` | Personal de Terminación | Control de calidad (módulo futuro). |
| `SECRETARIA` | Secretaria | Producto terminado (módulo futuro). |
| `VENDEDOR` | Vendedor | Ventas y despachos (módulo futuro). |
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
| Control de Calidad | `calidad.ver`, `calidad.gestionar` | Previsto |
| Producto Terminado | `producto_terminado.ver`, `producto_terminado.gestionar` | Previsto |
| Ventas y Despachos | `ventas.ver`, `ventas.gestionar` | Previsto |
| Reportes | `reportes.ver`, `reportes.gestionar` | Previsto |

## Matriz inicial rol → permiso

Es la que dejan las migraciones (`0003`, `0007` y `0008` de `apps/users`). Después se ajusta desde la pantalla de
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
| `calidad.ver` | ✔ | | | ✔ | | |
| `calidad.gestionar` | | | | ✔ | | |
| `producto_terminado.ver` | ✔ | | | | ✔ | ✔ |
| `producto_terminado.gestionar` | | | | | ✔ | |
| `ventas.ver` | ✔ | | | | | ✔ |
| `ventas.gestionar` | | | | | | ✔ |
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

### Reglas que no dependen del permiso

- **Separación de funciones en compras:** quien creó una orden de compra **no puede recibirla**, aunque tenga
  `inventario.gestionar`. Aprobar tampoco exige ser distinto de quien la creó, pero lo normal es que sea el Gerente.
- **Delegación segura:** alguien con `seguridad.gestionar` o `seguridad.roles` que no es administrador no puede crear
  administradores, asignar roles con permisos de Seguridad, dar o quitar esos permisos ni editar los de su propio rol.
- **Nadie sobre sí mismo:** no se cambia el propio rol ni se desactiva o elimina la propia cuenta, y siempre queda al
  menos un administrador activo.
- **Falla cerrado:** una ruta sin permiso declarado niega el acceso (ver [arquitectura](arquitectura.md)).

El frontend solo decide qué mostrar; el backend valida el permiso en cada petición.
