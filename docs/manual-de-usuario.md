# Manual de usuario

Guía para usar TexCore desde el navegador: <https://texcore-web.onrender.com>.
Lo que ves en el menú depende de tu rol: solo aparecen los módulos que tienes permitidos.

!!! info "Sesión"
    La sesión se cierra sola tras 30 minutos sin usar el sistema. Solo vuelve a iniciar sesión.

## 1. Entrar al sistema

1. Escribe tu **Usuario / Correo electrónico** y tu **Contraseña**.
2. Pulsa **Iniciar sesión**.

Si algún dato no coincide verás *«Credenciales inválidas. Por favor intenta de nuevo.»* No indica cuál dato falló.

## 2. Pedir una cuenta

En el inicio de sesión pulsa **Regístrate** y completa:

- **Nombre(s)** y **Apellidos**
- **Correo electrónico corporativo**
- **Cédula** (opcional)
- **Cargo o área solicitada**: Almacenista, Producción, Gerencia, Secretaria, Terminación o Vendedor
- **Contraseña** y **Repite la contraseña**

La contraseña debe tener al menos 8 caracteres, una mayúscula, una minúscula, un número y un símbolo;
una lista de requisitos te muestra cuáles cumples. Al enviar verás *«Solicitud enviada. Un administrador
te asignará un rol.»* Hasta entonces tu cuenta está **Pendiente** y no entra a ningún módulo.

## 3. Olvidé mi contraseña

1. En el inicio de sesión pulsa **¿Olvidaste tu contraseña?**
2. Escribe tu **Correo electrónico** y pulsa **Enviar enlace**.
3. Abre el correo y entra al enlace para escribir la nueva contraseña.

El enlace sirve **una sola vez** y vence a los **15 minutos**. Si no llega, revisa la carpeta de spam o pide otro
(si pides uno nuevo, el anterior deja de servir). Por seguridad el sistema responde lo mismo exista o no el correo.

## 4. Administrador: usuarios y roles

Menú **Seguridad y Usuarios**.

### Usuarios

- Filtra por rol o estado (**Activo**, **Inactivo**, **Pendiente**) o busca por nombre, correo o cédula.
- **Solicitudes pendientes**: arriba aparece la lista de quienes pidieron cuenta, con el área que solicitaron. Elige el
  rol en el selector y pulsa **Aprobar**. Si no corresponde, **Rechazar** (esa persona no podrá iniciar sesión; puedes reactivarla después).
- **+ Nuevo usuario** → **Crear y enviar invitación**: a la persona le llega un correo con un enlace para definir su contraseña.
- **Desactivar usuario** impide que entre; **Eliminar usuario** la oculta sin borrar su historial.
- Reglas: nadie cambia su propio rol ni se desactiva o elimina a sí mismo, y siempre debe quedar al menos un
  administrador activo. Solo un administrador crea administradores o asigna roles con permisos de Seguridad.

### Roles y permisos

Define qué módulos puede ver y operar cada rol. Por cada módulo marca **Ver** y/o **Registrar y modificar**
(al marcar *Registrar y modificar* se marca también *Ver*). El Administrador tiene todos los permisos y no se puede restringir.
Con **Crear rol** puedes crear un rol propio; su código no se puede cambiar después.

## 5. Almacenista: inventario

Menú **Inventario de Materias Primas**, con tres secciones: **Movimientos**, **Catálogo** y **Proveedores**.

### Inicio: alertas de stock

En el **Inicio** aparecen los productos con existencias en el mínimo o por debajo (*Bajo el mínimo*) o sin existencias
(*Agotado*). Si todo está bien verás *«Inventario en orden»*.

### Movimientos

Cuatro pestañas:

**Existencias**
: Consulta cuánto hay de cada producto. Filtra por tipo o busca por nombre o código. Es solo lectura: los productos se crean en el Catálogo.

**Ingreso**
: Registra lo que entra al almacén.

    - *Telas, hilos e insumos (compra)*: elige el **Producto**, el **Proveedor** de la lista (los de la misma categoría aparecen primero), la **Cantidad**, la **Fecha**, el **Lote** y, si quieres, la referencia de la compra.
    - *Pantalones genéricos o terminados*: solo entran al terminar una orden. Elige la **Orden de origen**; al recibirlo la orden se cierra.
    - Puedes adjuntar **Evidencias (foto o PDF)**. Pulsa **Guardar ingreso**.
    - Una cantidad de cero o negativa se rechaza con *«La cantidad debe ser mayor que cero.»*

**Salida**
: Crea una orden que saca materiales del almacén.

    1. Elige el tipo: **Producción (OP)** o **Lavandería (LV)**.
    2. Indica el responsable, la ficha técnica y el producto que se obtendrá.
    3. Arma la **Cesta de la orden** con **Agregar a la cesta**. Si no hay stock suficiente el sistema lo avisa y muestra qué falta.
    4. Adjunta evidencias si lo necesitas y guarda. Se descuenta el stock y se genera el código de la orden (OP-0001, LV-0001...).

**Historial**
: El **Kardex de movimientos** (ingresos y salidas con saldo, quién registró y evidencias) y la lista de **Órdenes**
  (En proceso, Completadas, Anuladas). Para corregir una orden en proceso usa **Anular orden**: escribe el motivo y
  **Anular y devolver stock**; las cantidades vuelven al inventario.

### Catálogo

Fichas de telas e insumos organizadas por **categoría**. Cada producto tiene su código (TEL-, HIL-, CIE-...), unidad,
**Stock mínimo** y, según la categoría, **Ancho útil** (telas) y **Composición** (telas e hilos, debe sumar 100 %).
Puedes buscar, filtrar por categoría, **Editar** y agregar una imagen de referencia. El catálogo no muestra existencias.
La categoría y la unidad no se pueden cambiar cuando el producto ya tiene movimientos.

### Proveedores

El **Directorio de proveedores** guarda NIT, razón social, contacto, ciudad y el tipo de insumo que suministran.
El NIT no puede repetirse entre proveedores activos. Un proveedor se puede **archivar** (deja de salir en los ingresos
pero conserva su historial) y **Restaurar**.

## Preguntas frecuentes

**No veo un módulo del menú.** Tu rol no tiene permiso. Pídele a un administrador que lo ajuste en *Roles y permisos*.

**Me sale «Tu rol no tiene permiso para realizar esta acción.»** Es el mismo caso: tu rol puede ver pero no registrar, o ni siquiera ver.

**Mi cuenta dice Pendiente.** Un administrador todavía no te asignó rol.
