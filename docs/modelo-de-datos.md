# Modelo de datos

> Generado automáticamente con `python manage.py generar_erd --salida docs/modelo-de-datos.md`.
> No lo edites a mano: vuelve a generarlo cuando cambie un modelo.

Todas las tablas de negocio heredan de `BaseModel` y por eso incluyen además `created_at`, `updated_at` y `deleted_at` (borrado lógico; ver [convenciones de base de datos](convenciones-base-de-datos.md)). Esas columnas no se repiten abajo.

## Diagrama entidad-relación

```mermaid
erDiagram
    ModulePermission {
        bigint id PK
        varchar_60 code UK
        varchar_120 name
        varchar_40 module
        varchar_255 description
    }
    Role {
        bigint id PK
        varchar_20 code UK
        varchar_60 name
        varchar_255 description
        boolean is_system
    }
    RolePermission {
        bigint id PK
        bigint role FK
        bigint permission FK
        timestamp granted_at
        bigint granted_by FK
    }
    CustomUser {
        bigint id PK
        varchar_128 password
        timestamp last_login
        boolean is_superuser
        varchar_150 username UK
        varchar_150 first_name
        varchar_150 last_name
        varchar_254 email
        boolean is_staff
        boolean is_active
        timestamp date_joined
        varchar_20 role FK
        varchar_20 requested_area FK
        varchar_20 document_id
    }
    PasswordResetToken {
        bigint id PK
        bigint user FK
        varchar_64 token_hash UK
        varchar_10 purpose
        timestamp expires_at
        timestamp used_at
        inet requested_ip
    }
    Consecutivo {
        bigint id PK
        varchar_10 clave UK
        int ultimo
    }
    Proveedor {
        bigint id PK
        varchar_10 nit
        varchar_1 nit_dv
        varchar_150 razon_social
        varchar_20 categoria
        varchar_120 contacto
        varchar_20 telefono
        varchar_120 correo
        varchar_80 ciudad
        varchar_200 direccion
    }
    Producto {
        bigint id PK
        varchar_20 codigo
        varchar_150 nombre
        varchar_15 tipo
        varchar_20 categoria
        varchar_10 unidad
        decimal_12_2 stock_actual
        decimal_12_2 stock_minimo
        varchar_255 descripcion
        decimal_4_2 ancho_util
        varchar_60 color
        varchar_120 composicion
        bytea imagen
        varchar_20 imagen_tipo
        int imagen_version
    }
    OrdenSalida {
        bigint id PK
        varchar_20 codigo
        varchar_12 tipo
        varchar_12 estado
        date fecha_salida
        varchar_120 responsable
        varchar_120 destino
        varchar_60 ficha_tecnica
        bigint producto_resultado FK
        decimal_12_2 cantidad_prendas
        text observaciones
        bigint registrado_por FK
        timestamp completada_at
        timestamp anulada_at
        varchar_255 motivo_anulacion
    }
    OrdenLinea {
        bigint id PK
        bigint orden FK
        bigint producto FK
        decimal_12_2 cantidad
    }
    Movimiento {
        bigint id PK
        bigint producto FK
        varchar_8 tipo
        varchar_15 motivo
        decimal_12_2 cantidad
        decimal_12_2 stock_antes
        decimal_12_2 stock_despues
        date fecha
        bigint proveedor FK
        varchar_150 proveedor_nombre
        varchar_40 orden_compra
        varchar_60 lote
        bigint orden FK
        text observaciones
        bigint registrado_por FK
    }
    Evidencia {
        bigint id PK
        bigint movimiento FK
        bigint orden FK
        varchar archivo
        varchar_120 nombre_original
        varchar_40 content_type
        int tamano
        bigint subido_por FK
    }
    CustomUser |o--o{ Evidencia : "subido_por"
    CustomUser |o--o{ Movimiento : "registrado_por"
    CustomUser |o--o{ OrdenSalida : "registrado_por"
    CustomUser |o--o{ RolePermission : "granted_by"
    CustomUser ||--o{ PasswordResetToken : "user"
    ModulePermission ||--o{ RolePermission : "permission"
    Movimiento |o--o{ Evidencia : "movimiento"
    OrdenSalida |o--o{ Evidencia : "orden"
    OrdenSalida |o--o{ Movimiento : "orden"
    OrdenSalida ||--o{ OrdenLinea : "orden"
    Producto ||--o{ Movimiento : "producto"
    Producto ||--o{ OrdenLinea : "producto"
    Producto ||--o{ OrdenSalida : "producto_resultado"
    Proveedor |o--o{ Movimiento : "proveedor"
    Role |o--o{ CustomUser : "requested_area"
    Role ||--o{ CustomUser : "role"
    Role ||--o{ RolePermission : "role"
```

## Tablas

### ModulePermission (`seguridad_permiso`)

Acción concreta sobre un módulo, p. ej. "inventario.gestionar".

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `code` | varchar(60) | UK |  |
| `name` | varchar(120) |  |  |
| `module` | varchar(40) |  |  |
| `description` | varchar(255) |  |  |

### Role (`seguridad_rol`)

Perfil de acceso. El código es inmutable: lo usan el JWT y el frontend.

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `code` | varchar(20) | UK |  |
| `name` | varchar(60) |  |  |
| `description` | varchar(255) |  |  |
| `is_system` | boolean |  |  |

### RolePermission (`seguridad_rol_permiso`)

Asignación de un permiso a un rol (tabla intermedia), con quién y cuándo lo concedió.

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `role` | bigint | FK | → `Role` |
| `permission` | bigint | FK | → `ModulePermission` |
| `granted_at` | timestamp |  |  |
| `granted_by` | bigint | FK, nulo | → `CustomUser` |

### CustomUser (`users_customuser`)

Usuario del sistema. El correo es también el `username`; el rol decide los permisos (RBAC).

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `password` | varchar(128) |  |  |
| `last_login` | timestamp | nulo |  |
| `is_superuser` | boolean |  |  |
| `username` | varchar(150) | UK |  |
| `first_name` | varchar(150) |  |  |
| `last_name` | varchar(150) |  |  |
| `email` | varchar(254) |  |  |
| `is_staff` | boolean |  |  |
| `is_active` | boolean |  |  |
| `date_joined` | timestamp |  |  |
| `role` | varchar(20) | FK | → `Role` |
| `requested_area` | varchar(20) | FK, nulo | → `Role` |
| `document_id` | varchar(20) | nulo |  |

### PasswordResetToken (`seguridad_token_recuperacion`)

Token de un solo uso para restablecer o definir la contraseña (HU 1.3).

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `user` | bigint | FK | → `CustomUser` |
| `token_hash` | varchar(64) | UK |  |
| `purpose` | varchar(10) |  |  |
| `expires_at` | timestamp |  |  |
| `used_at` | timestamp | nulo |  |
| `requested_ip` | inet | nulo |  |

### Consecutivo (`inventario_consecutivo`)

Último número usado por cada prefijo (OP, LV, MP...). Se bloquea al asignar.

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `clave` | varchar(10) | UK |  |
| `ultimo` | int |  |  |

### Proveedor (`inventario_proveedor`)

Proveedor de telas e insumos (HU 2.1). El NIT es único entre los proveedores activos.

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `nit` | varchar(10) |  |  |
| `nit_dv` | varchar(1) |  |  |
| `razon_social` | varchar(150) |  |  |
| `categoria` | varchar(20) |  |  |
| `contacto` | varchar(120) |  |  |
| `telefono` | varchar(20) |  |  |
| `correo` | varchar(120) |  |  |
| `ciudad` | varchar(80) |  |  |
| `direccion` | varchar(200) |  |  |

### Producto (`inventario_producto`)

Producto del catálogo (HU 2.2): materia prima, insumo, pantalón genérico o terminado.

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `codigo` | varchar(20) |  |  |
| `nombre` | varchar(150) |  |  |
| `tipo` | varchar(15) |  |  |
| `categoria` | varchar(20) |  |  |
| `unidad` | varchar(10) |  |  |
| `stock_actual` | decimal(12,2) |  |  |
| `stock_minimo` | decimal(12,2) |  |  |
| `descripcion` | varchar(255) |  |  |
| `ancho_util` | decimal(4,2) | nulo |  |
| `color` | varchar(60) |  |  |
| `composicion` | varchar(120) |  |  |
| `imagen` | bytea | nulo |  |
| `imagen_tipo` | varchar(20) |  |  |
| `imagen_version` | int |  |  |

### OrdenSalida (`inventario_orden`)

Orden de producción (OP) o de lavandería (LV) que saca materiales del almacén (HU 2.3).

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `codigo` | varchar(20) |  |  |
| `tipo` | varchar(12) |  |  |
| `estado` | varchar(12) |  |  |
| `fecha_salida` | date |  |  |
| `responsable` | varchar(120) |  |  |
| `destino` | varchar(120) |  |  |
| `ficha_tecnica` | varchar(60) |  |  |
| `producto_resultado` | bigint | FK | → `Producto` |
| `cantidad_prendas` | decimal(12,2) | nulo |  |
| `observaciones` | text |  |  |
| `registrado_por` | bigint | FK, nulo | → `CustomUser` |
| `completada_at` | timestamp | nulo |  |
| `anulada_at` | timestamp | nulo |  |
| `motivo_anulacion` | varchar(255) |  |  |

### OrdenLinea (`inventario_orden_linea`)

Línea de la cesta de una orden: un producto y la cantidad que sale.

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `orden` | bigint | FK | → `OrdenSalida` |
| `producto` | bigint | FK | → `Producto` |
| `cantidad` | decimal(12,2) |  |  |

### Movimiento (`inventario_movimiento`)

Fila del kardex: cada ingreso o salida con el saldo antes y después, el usuario y la fecha.

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `producto` | bigint | FK | → `Producto` |
| `tipo` | varchar(8) |  |  |
| `motivo` | varchar(15) |  |  |
| `cantidad` | decimal(12,2) |  |  |
| `stock_antes` | decimal(12,2) |  |  |
| `stock_despues` | decimal(12,2) |  |  |
| `fecha` | date |  |  |
| `proveedor` | bigint | FK, nulo | → `Proveedor` |
| `proveedor_nombre` | varchar(150) |  |  |
| `orden_compra` | varchar(40) |  |  |
| `lote` | varchar(60) |  |  |
| `orden` | bigint | FK, nulo | → `OrdenSalida` |
| `observaciones` | text |  |  |
| `registrado_por` | bigint | FK, nulo | → `CustomUser` |

### Evidencia (`inventario_evidencia`)

Foto o PDF adjunto a un movimiento o a una orden.

| Campo | Tipo | Restricciones | Relación |
|---|---|---|---|
| `id` | bigint | PK |  |
| `movimiento` | bigint | FK, nulo | → `Movimiento` |
| `orden` | bigint | FK, nulo | → `OrdenSalida` |
| `archivo` | varchar |  |  |
| `nombre_original` | varchar(120) |  |  |
| `content_type` | varchar(40) |  |  |
| `tamano` | int |  |  |
| `subido_por` | bigint | FK, nulo | → `CustomUser` |
