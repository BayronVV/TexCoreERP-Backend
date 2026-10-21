# Arquitectura

TexCore usa una **arquitectura por capas** (cliente-servidor en N capas). El backend sigue el patrón
de Django, MVT, que se parece a MVC; por eso conviene describir el sistema completo como capas.

## Vista general

```mermaid
flowchart LR
    U([Usuario]) --> F["Presentación<br/>React + Vite (SPA)"]
    F -- "HTTPS · JSON · JWT" --> V["API / control<br/>Vistas DRF"]
    V --> S["Negocio<br/>services.py y serializers"]
    S --> M["Dominio<br/>Modelos Django"]
    M --> D[("PostgreSQL<br/>Supabase")]
    V -. "permiso por ruta" .- P["HasPermission<br/>(transversal)"]
```

| Capa | Dónde está | Responsabilidad |
|---|---|---|
| Presentación | Repositorio `TexCoreERP-Frontend` (`src/components`, `src/auth`, `src/api`) | Pantallas y formularios. No decide reglas de negocio. |
| API / control | `apps/*/views.py`, `apps/*/urls.py` | Recibe la petición, comprueba el permiso y delega. |
| Negocio | `apps/*/services.py` (más `costing.py`, `tracking.py`, `monitor.py`, `resources.py` y `fichas.py` en sus apps), `apps/users/password_reset.py`, serializers | Reglas: stock suficiente, cantidades, NIT, composición textil, delegación de roles, consumo por ficha, estado derivado de lotes, costeo, recepción de mercancía. |
| Dominio | `apps/*/models.py` | Entidades y restricciones de datos. |
| Persistencia | ORM de Django → PostgreSQL (Supabase) | Almacenamiento. |

### Por qué capas y no MVC "a secas"

- Django es **MVT** (Model, View, Template): su *View* hace de controlador. Aquí la plantilla la sustituye
  una SPA de React que es un proyecto aparte, así que MVC solo describe una parte del sistema.
- Cada capa se cambia y se prueba sin tocar las demás: las pruebas del backend (683) y las funciones puras del frontend no dependen de la interfaz.
- Permite repartir el trabajo (frontend y backend) y cumple el requisito de arquitectura modular (RNF09):
  `users`, `inventory`, `references`, `production`, `purchasing` y `core` son módulos independientes y los siguientes se añaden igual.

Correspondencia con el modelo de análisis (interfaz / control / entidad):

| Modelo de análisis | En el código |
|---|---|
| Clase interfaz | Componentes React, por ejemplo `Login.jsx` |
| Clase control | Vista DRF + serializer o servicio |
| Clase entidad | Modelo Django, por ejemplo `CustomUser`, `Producto` |

## Estructura del backend

```
backend/
├── config/        # settings, urls, wsgi/asgi
├── apps/
│   ├── core/       # salud, BaseModel (borrado lógico), permiso HasPermission, comando generar_erd
│   ├── users/      # usuarios, roles y permisos, recuperación de contraseña
│   ├── inventory/  # proveedores, catálogo, órdenes de salida, kardex, evidencias, alertas, costo promedio
│   ├── purchasing/ # órdenes de compra y recepción de mercancía
│   ├── references/ # referencias de jean (variantes, imágenes) y ficha técnica de consumo
│   └── production/ # simulación, órdenes y lotes, tiempos, recursos, monitor y costeo
└── docs/          # esta documentación
```

| App | Depende de | Qué aporta |
|---|---|---|
| `core` | — | `BaseModel` (borrado lógico), `HasPermission`, endpoints de salud, RLS de Supabase |
| `users` | `core` | Usuarios, roles y permisos (catálogo y migraciones con la matriz inicial) |
| `inventory` | `core`, `references` | Existencias, kardex, consecutivos (`OP`, `LV`, `TEL`...), costo promedio y foto de costo |
| `references` | `core`, `inventory` | Referencias, variantes, ficha técnica (lee el catálogo de inventario) |
| `production` | `core`, `inventory`, `references` | Órdenes y lotes (descuentan stock vía `inventory.services`), etapas, recursos, monitor, costeo |
| `purchasing` | `core`, `inventory` | Órdenes de compra; recibir mercancía reutiliza `inventory.services.register_entry` |

`inventory` y `references` se conocen entre sí: la orden de salida apunta a una referencia y la ficha técnica lee el catálogo de productos. `production` y `purchasing` solo consumen a `inventory` a través de sus servicios, nunca escriben saldos por su cuenta.

Cada app separa sus responsabilidades en `models.py`, `serializers.py`, `views.py`, `urls.py` y,
cuando hay reglas de negocio, `services.py`. En `production` el motor de costeo (`costing.py`), el control de tiempos
(`tracking.py`), el tablero (`monitor.py`) y los recursos (`resources.py`) son módulos de funciones sin dependencia de la vista,
para probarlos por separado. Cada app guarda sus constantes en `catalog.py`.

Las tablas llevan el prefijo de su módulo: `seguridad_`, `inventario_`, `referencias_`, `produccion_` y `compras_`
(ver [convenciones](convenciones-base-de-datos.md)).

## Flujo de una petición

```mermaid
sequenceDiagram
    participant C as Cliente (React)
    participant V as Vista DRF
    participant P as HasPermission
    participant S as services.py
    participant DB as PostgreSQL
    C->>V: POST /api/inventario/ingresos/ (Bearer JWT)
    V->>P: ¿el rol tiene inventario.gestionar?
    P-->>V: sí (si no, 403)
    V->>S: register_entry(...)
    S->>DB: bloquea el producto y guarda el movimiento
    DB-->>S: movimiento
    S-->>V: movimiento
    V-->>C: 201 + movimiento
```

Las reglas de negocio fallan con un error 400 `{campo: [mensaje]}` que la interfaz muestra junto al campo.

## Seguridad

- **Autenticación JWT** (simplejwt): `access` de 15 minutos y `refresh` rotativo de 30 minutos, así la sesión vence
  tras 30 minutos sin uso. Cambiar la contraseña invalida las sesiones abiertas.
- **Permiso por ruta** (RNF01): `HasPermission` es el permiso por defecto de toda la API. Cada vista declara
  `required_permissions`; una vista sin declararlo queda **cerrada** (falla cerrado). Las rutas públicas
  (login, registro, recuperación, salud) lo declaran explícitamente.
- **RBAC**: los roles tienen permisos `<modulo>.ver` y `<modulo>.gestionar`; `ADMIN` los tiene todos.
- **Delegación segura**: quien gestiona usuarios sin ser administrador no puede crear administradores
  ni asignar roles con permisos de Seguridad (corrección del BUG-01 de QA).
- **Límites de frecuencia**: login 10/min por IP; registro 20/hora; recuperación 5/hora por IP y 3 correos/hora por usuario.
- **Base de datos**: después de cada migración se activa RLS sin privilegios para los roles de la API de Supabase.

## Decisiones de diseño

| Decisión | Motivo |
|---|---|
| Borrado lógico (`deleted_at`) en todas las tablas de negocio | Conservar el historial y la trazabilidad (ver [convenciones](convenciones-base-de-datos.md)). |
| El stock solo cambia con movimientos (kardex) | Cada cambio queda con saldo antes y después, usuario y fecha. |
| Código consecutivo por categoría (`TEL-0001`, `OP-0002`...) | Identificadores legibles y únicos, generados dentro de una transacción. |
| Imagen de referencia del producto guardada en la base | El disco de Render es efímero; en la base no se pierde. Se sirve con sesión y `ETag`. |
| Tipo de archivo decidido por su contenido (firma binaria) | No confiar en el nombre ni en el tipo que declare el navegador. |
| Metadatos del catálogo servidos por la API (`/api/inventario/metadatos/`, `/api/referencias/metadatos/`, `/api/compras/metadatos/`) | El frontend no duplica categorías, unidades, estados ni reglas. |
| Estado de lotes y órdenes de producción calculado, no guardado | Sale de las etapas y de la anulación; así nunca queda desincronizado (ver [módulos](modulos.md)). |
| Tiempo neto con intervalos (`acumulado_s` + `reanudada_at`) | Las pausas no cuentan y no hace falta recorrer el historial para calcularlo. |
| Historial que solo crece: eventos de etapa, asignaciones y tarifas de mano de obra | Trazabilidad: lo pasado no se edita; un cambio abre un registro nuevo. |
| Foto del costo unitario en cada línea de la orden de salida | La liquidación usa el costo con que salió el material, aunque el promedio cambie después. |
| Costo promedio ponderado móvil por producto | Costear con un solo valor por material sin guardar capas de compras. |
| Orden de producción, lotes y descuento de stock en una sola transacción | Si falta material no queda nada ni se gasta el consecutivo. |
| Recepción de mercancía en una sola transacción, con tolerancia de 5 % | Una fila con error no deja recepciones a medias; el proveedor a veces envía de más. |
| Operarios y máquinas como catálogo simple, sin cuenta de usuario | Los operarios no usan el sistema; «ocupado» se calcula con las etapas en curso. |
| Permisos propios para fichas técnicas y compras (`fichas_tecnicas.*`, `compras.aprobar`) | Separar quién diseña, quién aprueba y quién recibe. |

!!! warning "Limitaciones conocidas"
    - Las evidencias (foto o PDF) se guardan en el disco del servicio y se pierden al redesplegar en Render (plan gratuito).
    - El bloqueo de cuenta al tercer intento fallido (RF01) y un registro de auditoría general (RNF02) están pendientes.
    - Desarrollo y producción comparten hoy la misma base de datos.
