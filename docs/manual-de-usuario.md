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
: Consulta cuánto hay de cada producto y su **Costo promedio** (lo que cuesta cada unidad, calculado con el promedio ponderado de las compras). Un guion
  significa que todavía no se conoce el costo. Filtra por tipo o busca por nombre o código. Es solo lectura: los productos se crean en el Catálogo.

**Ingreso**
: Registra lo que entra al almacén.

    - *Telas, hilos e insumos (compra)*: elige el **Producto**, el **Proveedor** de la lista (los de la misma categoría aparecen primero), la **Cantidad**, la **Fecha**, el **Lote** y, si quieres, la referencia de la compra.
    - *Pantalones genéricos o terminados*: solo entran al terminar una orden. Elige la **Orden de origen**; al recibirlo la orden se cierra.
    - **Costo unitario (COP, opcional)**: lo que costó cada unidad en esa compra, mayor que cero y con hasta 4 decimales (punto para los decimales). El formulario
      muestra el costo promedio actual y el valor de la compra (cantidad × costo). Con él el sistema recalcula el **costo promedio ponderado** del producto:
      `(existencias × promedio + compra × costo) / (existencias + compra)`. Si lo que había no tenía costo, el de la compra manda. Una compra sin costo no cambia
      el promedio. Sirve para costear las órdenes de producción.
    - Puedes adjuntar **Evidencias (foto o PDF)**. Pulsa **Guardar ingreso**.
    - Una cantidad de cero o negativa se rechaza con *«La cantidad debe ser mayor que cero.»*

**Salida a lavandería**
: Envía pantalones genéricos a lavar. Las órdenes de producción no se crean aquí: se crean en **Producción → Órdenes de producción**.

    1. Indica el responsable de la lavandería y, si quieres, el taller. Elige la **Referencia de jean** de la lista (solo salen las
       referencias activas). El código de la referencia (REF-0001) queda como lote con el que volverá al inventario.
    2. Elige el **Modelo a crear**, que es el jean que se obtendrá al volver de lavandería.
    3. En **Pantalones que se envían** agrega el pantalón genérico y la cantidad. Solo viajan las prendas cosidas: los botones y remaches
       se colocan después, en terminación, y los químicos los pone la lavandería. Una orden envía un solo tipo de pantalón genérico.
    4. Adjunta evidencias si lo necesitas y guarda. Se descuenta el stock y se genera el código de la orden (LV-0001...).

**Historial**
: El **Kardex de movimientos** (ingresos y salidas con el costo unitario de cada compra, saldo, quién registró y evidencias) y la lista de **Órdenes**
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

### Compras: órdenes de compra y recepción de mercancía

Menú **Compras**. Cubre el camino completo de un pedido de materia prima o insumos: **la orden la crea Producción, la aprueba el Gerente y la recibe
el almacenista**. Así quien pide no es quien recibe.

1. **Crear la orden** (Jefe de Producción, en **Compras → Órdenes de compra → Nueva orden**): elige el proveedor, la fecha esperada y las condiciones de
   pago, y agrega los materiales con su cantidad y, si ya lo acordaron, el **precio pactado** por unidad (es opcional). Un producto no se repite en la
   misma orden. La orden nace en **borrador** con un código `OC-0001`; mientras es borrador se puede **editar**.
2. **Aprobar** (Gerente): revisa la orden y pulsa **Aprobar**. Desde ese momento ya no se edita y el almacén puede recibir contra ella. Si no procede,
   Producción puede **cancelarla** indicando el motivo (solo mientras no tenga recepciones).
3. **Recibir la mercancía** (Almacenista, en **Compras → Recepción de mercancía**): elige la orden aprobada y la pantalla lista sus productos con lo
   **pedido, lo ya recibido y lo pendiente**. Escribe cuánto llegó de cada uno, el **lote** y el **costo real** (se sugiere el precio pactado) y el número
   de la remisión o la factura del proveedor. Todo se guarda **de una sola vez**: si una fila tiene un error, no se registra ninguna.
   - Se puede recibir **hasta un 5 % más** de lo pendiente de cada línea, porque a veces el proveedor envía de más.
   - Si llega solo una parte, la orden queda **Recibida parcial** y se puede hacer otra recepción después. Al completarse todo, pasa a **Recibida**.
   - Si lo pendiente ya no va a llegar, Producción **cierra la orden** indicando el motivo.
   - **Quien creó la orden no puede recibirla**, aunque tenga permiso de inventario.
4. **Entrega sin orden de compra:** en la misma pantalla de recepción, la opción **Sin orden de compra** permite registrar de una vez varios productos
   de un proveedor (con su remisión o factura, lote y costo).
5. **Qué pasa en el inventario:** cada producto recibido entra como una compra normal: suma al stock, actualiza el **costo promedio ponderado** si se
   anotó el costo y deja su fila en el **Kardex**, con el código de la orden y de la recepción. El ingreso suelto de **Movimientos → Ingreso** sigue
   funcionando igual para un producto a la vez.

**Quién puede qué:** el Jefe de Producción crea, edita, cancela y cierra órdenes; el Gerente las aprueba; el Almacenista las consulta y las recibe; el
Administrador puede todo. Estos permisos se pueden ajustar en **Roles y permisos**.

## 6. Jefe de producción: referencias y fichas técnicas

Menú **Referencias de Jean → Catálogo de jeans**.

### Referencias

Cada referencia es un modelo de jean: nombre, tipo de ajuste, descripción, **tallas y colores** (se crea una combinación por cada
talla y color que escribas) y hasta cinco **fotos del prototipo**, una principal. Nace como *Borrador* y se **Activa** cuando tiene
al menos una combinación y una foto. Una referencia activa se **Descontinúa** en lugar de borrarse; solo las que no están activas
se pueden **Archivar**.

### Ficha técnica de consumo por unidad

Desde la tarjeta de la referencia, **Ficha técnica**. Define cuánto lleva **una prenda**:

1. Elige el **Tipo de lavado** (opcional) y las notas de la ficha.
2. Con **+ Agregar material** añade cada materia prima o insumo del catálogo de inventario, con la **Cantidad por prenda** y la
   **Merma %** (por ejemplo el desperdicio de corte de la tela). La columna *Con merma* muestra el consumo real por prenda.
   Un material no se puede repetir; las piezas enteras (botones, cierres, remaches) llevan cantidades enteras y no llevan merma.
3. **Guardar ficha**. La lista completa reemplaza a la anterior.

Debajo hay un espacio para adjuntar el **PDF de la ficha técnica extensa** (geometral, secuencia de confección, tabla de medidas),
de hasta 5 MB. Se puede **Ver**, **Reemplazar** o **Quitar**. Solo se adjunta cuando la ficha ya está guardada.

Con la ficha lista, el Almacenista solo elige la referencia y las prendas al crear una orden de producción. Una ficha no se puede quitar
ni una referencia archivar mientras tenga órdenes en proceso.

### Planificar producción

Menú **Producción y Trazabilidad → Planificar producción**. Antes de crear una orden, comprueba si hay material para las prendas que quieres fabricar:

1. Elige la **Referencia de jean** (solo las activas con ficha técnica) y escribe las **Prendas a producir**.
2. Si quieres dividir el total en lotes, usa **Repartir en partes iguales** o **+ Agregar lote** y escribe el tamaño de cada uno. Deben sumar
   exactamente el total; la pantalla indica cuántas prendas faltan o sobran. Los lotes se registran al crear la orden.
3. **Disponibilidad de material** muestra, por material, lo que pide la ficha (con la merma), lo que hay y lo que falta, y dice cuántas prendas
   se pueden fabricar con el stock actual y qué material lo limita. **Usar N** lleva el total a ese máximo.
4. Con lotes, **Cobertura por lote** indica hasta qué lote alcanza el material. Los lotes comparten el mismo stock, así que un lote se cubre si
   alcanza para él y los anteriores juntos.
5. **Crear orden** solo se habilita cuando hay material y los lotes están bien repartidos; al lado se lee el motivo cuando está bloqueado. Si tu
   rol puede gestionar la producción, abre **Órdenes y lotes** con la referencia, las prendas y los lotes ya cargados.

La simulación no reserva ni descuenta stock: al crear la orden el sistema vuelve a verificar que haya material.

### Órdenes y lotes

Menú **Producción y Trazabilidad → Órdenes y lotes**. Aquí se crea la orden de producción (RF11) y se divide en lotes con identificador único (RF12):

1. Elige la **Referencia de jean**, las **Prendas a producir** y el **pantalón genérico** que se producirá. Responsable y observaciones son opcionales
   (por defecto, el responsable eres tú).
2. En **Lotes** divide el total por **cantidad de lotes** o por **prendas por lote** (el último lleva lo que sobre) y ajusta cada lote a mano si quieres.
   Sin dividir se crea un único lote. Los lotes deben sumar exactamente el total (máximo 50).
3. En **Tallas por lote** (opcional) agrega las tallas y colores de la referencia y cuántas prendas lleva cada uno; deben sumar las prendas del lote.
   El **Resumen por talla** suma todos los lotes. Si cambias el reparto de lotes, las tallas se reinician para evitar datos que ya no cuadran.
4. **Crear orden** genera el código (`OP-0001`) y el de cada lote (`OP-0001-L01`, `-L02`…) y **descuenta del almacén** el material de la ficha técnica,
   con su merma. Si falta material no se crea nada y la pantalla dice cuál.
5. **Órdenes recientes** lista las órdenes con sus lotes y su estado. **Anular** (exige el motivo) devuelve el material al almacén; los lotes quedan como historial.
   La orden también aparece en el historial de salidas de Inventario con el mismo código.

### Control de tiempos por etapa

En **Órdenes de producción → Órdenes recientes**, el botón **Seguimiento** de una orden abre sus lotes. Cada lote recorre tres etapas, siempre en
este orden: **Corte, Confección y Terminación**. Una etapa solo empieza cuando la anterior terminó, y cuando termina la última el lote queda
*Terminado*. La lavandería no es una etapa de este seguimiento: es un proceso externo (subcontratado) y se controla aparte, con sus propias órdenes
de salida y entrada. El control de calidad y el empaque también tienen sus propios módulos.

- **▶ Iniciar** arranca la siguiente etapa y empieza a contar el tiempo. Queda registrado quién lo hizo y a qué hora.
- **⏸ Pausar** detiene el reloj; **▶ Reanudar** lo vuelve a poner en marcha. El tiempo en pausa **no cuenta**: el tiempo neto es solo el que la etapa estuvo corriendo.
- **⏹ Terminar** cierra la etapa en curso (también si estaba en pausa) y deja listo el botón para iniciar la siguiente.
- Solo se habilitan los botones que tienen sentido en ese momento, y el estado del lote se actualiza al instante.
- El **estado del lote y de la orden** se calcula solo: *Planeada* (nada ha empezado), *En proceso*, *En pausa*, *Terminada* o *Cancelada* (si la orden se anuló).
- **Historial** muestra cada inicio, pausa, reanudación y fin, con quién lo hizo y cuándo. Solo se agregan registros; nunca se editan.

Quien tiene el rol de Gerente puede ver los tiempos pero no controlarlos. Una orden anulada no admite acciones.

### Monitor de estado

Menú **Producción y Trazabilidad → Monitor de estado**. Muestra **todos los lotes en producción** en cuatro columnas, sin tener que abrir orden por orden:

- **Planeada**: lotes que todavía no empiezan. **En proceso**: con una etapa corriendo o entre una etapa y la siguiente. **En pausa**: con la etapa
  en curso detenida. **Terminada**: con las tres etapas terminadas.
- Cada tarjeta muestra el código del lote, la referencia, las prendas, la **etapa en curso** (Corte, Confección o Terminación), el **tiempo neto** (sin
  pausas), cuánto hace que se movió y quién lo hizo. Dentro de cada columna, primero va lo que más tiempo lleva esperando; en Terminada, lo más reciente.
- Cada columna cuenta todos sus lotes aunque solo se vean los primeros 50; para ver el resto, filtra por **Orden** o por **Referencia**.
  La columna **Terminada** solo muestra lo de los **últimos 7 días**, para que no crezca sin fin.
- **Alertas por tiempo:** un lote *detenido* (en pausa, o entre una etapa y la siguiente sin iniciar la siguiente) se marca con **Atención** (amarillo) a
  partir de **2 horas** sin movimiento y con **Crítica** (rojo) a partir de **8 horas**, más o menos una jornada de trabajo. Arriba del tablero se resume
  cuántos lotes hay en cada nivel. Estos tiempos son orientativos y se pueden ajustar. Un lote con una etapa corriendo o que aún no empieza no genera alerta.
- **Ver canceladas:** por defecto los lotes de órdenes anuladas no aparecen; marca esta casilla para ver una columna **Cancelada** al final, solo de
  consulta (sin botones ni arrastre).
- **Mover un lote**: arrastra su tarjeta o pulsa sus botones (**Iniciar**, **Pausar**, **Reanudar**, **Terminar etapa**). El sistema aplica la acción
  de la etapa en curso y comprueba que sea posible: a *En proceso* se inicia o reanuda, a *En pausa* se pausa, y a *Terminada* solo se puede llevar un
  lote que esté en su última etapa (Terminación). Si el movimiento no es válido, la tarjeta no cambia y aparece el motivo.
- El tablero se **actualiza solo cada 20 segundos** mientras la pestaña esté a la vista, y también con el botón **Actualizar**.
- El **Gerente** ve el tablero pero no puede mover lotes. Los lotes de órdenes anuladas no aparecen.

### Operarios y máquinas (asignación de recursos)

Menú **Producción y Trazabilidad → Recursos**. Es el catálogo de las personas y las máquinas del taller, con dos pestañas: **Operarios** y **Máquinas**.
Los operarios **no necesitan una cuenta del sistema**: basta con registrarlos aquí.

- **Operarios:** se registran con nombre, documento (opcional), las **etapas en las que pueden trabajar** (Corte, Confección, Terminación) y cómo se les
  paga (por pieza, por tiempo o salario; solo informativo, la nómina no se maneja aquí). El código `OPE-0001` se genera solo. Por privacidad no se
  guardan teléfono, dirección, salud ni salario.
- **Máquinas:** se registran con su tipo (plana, fileteadora, collarín, presilladora, ojaladora, botonadora, remachadora, cortadora de tela u otra),
  marca y modelo, serial, ubicación o línea y las etapas en las que se usan. El código `MAQ-0001` se genera solo. Su **estado** es físico:
  *Disponible*, *En mantenimiento* o *Fuera de servicio*. Que una máquina esté **ocupada** no se anota a mano: se calcula con las etapas en curso.
- **Nada se borra:** un operario o una máquina se **desactiva** para que no se pueda asignar, y se conserva su historial.
- **Asignar:** en el **Seguimiento** de una orden, cada etapa de cada lote tiene un menú de **Operario** y otro de **Máquina**, que solo ofrecen los
  habilitados para esa etapa. La asignación se guarda sin recargar la pantalla. Se puede cambiar mientras la etapa no haya terminado; **quitar** deja la
  etapa sin responsable. Cada cambio cierra la asignación anterior y abre otra, así queda **quién trabajó cada etapa y cuándo**.
- **Qué se rechaza:** un operario o una máquina inactivos o que no sirven para esa etapa, una máquina en mantenimiento o fuera de servicio, una etapa que
  ya terminó y una orden anulada.
- **Qué solo se avisa:** si el operario o la máquina ya están en otra etapa que está en curso, el sistema lo indica en amarillo pero **deja asignar**, porque
  en un taller las máquinas se comparten por turnos. Lo mismo al pasar una máquina a mantenimiento mientras está en una etapa en curso: avisa y no cierra nada.
- **Se libera solo:** al terminar la etapa o anular la orden, el operario y la máquina quedan libres y la asignación pasa al historial.
- El **Monitor de estado** muestra, en cada tarjeta, el operario y la máquina de la etapa en curso.
- El **Gerente** puede ver el catálogo y las asignaciones, pero no cambiarlos.

### Liquidación de órdenes y costeo (HU 4.6)

Menú **Producción y Trazabilidad → Liquidación de Órdenes**. Permite consultar la conciliación financiera real de cada orden de producción (RF16), calculando el costo de materiales y el costo de mano de obra invertido:

1. **Selección de orden:** elige una orden de producción para consultar su desglose de costos. La pantalla muestra la referencia, la cantidad de prendas fabricadas, el estado de producción y si está anulada.
2. **Costo de materiales:** corresponde a la suma de las cantidades reales consumidas por orden multiplicadas por la foto del costo unitario tomada al descontar el material (`OrdenLinea.costo_unitario`, basado en el costo promedio ponderado de compra).
   - *Prorrateo por lote:* como los materiales se descuentan para la orden completa, a cada lote se le asigna material en estricta proporción a sus prendas: `total_materiales × prendas_del_lote / prendas_de_la_orden`.
   - Si algún material no tiene costo registrado, se marca claramente como *Sin costo* y se genera una advertencia.
3. **Costo de mano de obra:** para cada lote y etapa (Corte, Confección y Terminación), toma el tiempo neto registrado (en segundos, sin pausas), lo convierte a minutos y lo multiplica por la **tarifa por minuto** vigente a la fecha de finalización de la etapa (o la fecha actual si la etapa sigue en curso).
   - Si una etapa está en curso, su costo se marca como *provisional* porque el tiempo neto sigue sumando minutos.
   - Si una etapa acumula tiempo pero no existe una tarifa vigente para esa etapa, se marca como *Sin tarifa* y se genera una advertencia.
4. **Tarifas de mano de obra (gestión):** en la pestaña de tarifas, quienes tienen permiso de gestión pueden consultar el histórico y registrar una nueva vigencia de costo por minuto por etapa (`Corte`, `Confección` o `Terminación`) indicando su fecha de inicio (por defecto hoy). El sistema no sobreescribe ni elimina tarifas pasadas, conservando la trazabilidad histórica de costos.
5. **Totales, costo por prenda y distribución:** la liquidación resume el costo total de materiales, el total de mano de obra, el costo por prenda fabricada y la distribución porcentual (% Materiales vs % Mano de Obra) mediante una gráfica comparativa.
   - Si faltan tarifas o costos de materiales, el sistema advierte que el cálculo es *parcial* (`completo: false`).
   - Si la orden fue anulada, los costos se reflejan en cero ya que los insumos y materiales fueron devueltos al almacén.

## Preguntas frecuentes

**No veo un módulo del menú.** Tu rol no tiene permiso. Pídele a un administrador que lo ajuste en *Roles y permisos*.

**Me sale «Tu rol no tiene permiso para realizar esta acción.»** Es el mismo caso: tu rol puede ver pero no registrar, o ni siquiera ver.

**Mi cuenta dice Pendiente.** Un administrador todavía no te asignó rol.
