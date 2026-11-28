#!/usr/bin/env python3
"""Genera el diagrama BPMN 2.0 del proceso de negocio de TexCore ERP.

Lee una definición declarativa (carriles, nodos con carril y columna, flujos, notas) y escribe
archivos .bpmn con el diagrama (DI) completo, editables en bpmn.io, Camunda Modeler o Bizagi.

Uso:
    python generar_bpmn.py <carpeta_de_salida>

Genera tres modelos a partir de la MISMA definición:
    texcore-proceso.bpmn            visión de conjunto (pasos 1 a 7)
    texcore-proceso-produccion.bpmn detalle: compras, producción, lavandería y producto terminado
    texcore-proceso-venta.bpmn      detalle: venta, envío, recaudo, devolución y reportes

Solo usa la biblioteca estándar. Las imágenes (SVG/PNG) las produce render.mjs.
"""
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

# --------------------------------------------------------------------------------------
# Geometría (píxeles)
# --------------------------------------------------------------------------------------
COLW = 170            # ancho de columna
TASK_W, TASK_H = 140, 84
EVENT = 36
GATE = 50
POOL_X, POOL_Y = 40, 40
POOL_HDR, LANE_HDR = 30, 30
PAD_X = 20            # margen interno antes de la primera columna
LABEL_W = 90          # bpmn-js dibuja las etiquetas externas con 90 px de ancho fijo
CHAR_W = 6.0          # ancho medio de un carácter de 12 px (para estimar etiquetas)

# --------------------------------------------------------------------------------------
# Colores: ya no se usan (apariencia estándar de bpmn.io); se conservan por si se quiere colorear
# --------------------------------------------------------------------------------------
COLORS = {
    "start":   ("#c8e6c9", "#2e7d32"),
    "user":    ("#e8f5e9", "#388e3c"),
    "service": ("#fff59d", "#f9a825"),
    "manual":  ("#eceff1", "#607d8b"),
    "gateway": ("#bbdefb", "#1565c0"),
    "end":     ("#ffcdd2", "#c62828"),
    "boundary": ("#ffe0b2", "#e65100"),
}

# --------------------------------------------------------------------------------------
# Definición declarativa del proceso
# --------------------------------------------------------------------------------------
POOL_NAME = "TexCore ERP: de la materia prima a la venta"

# id, nombre, alto, y del centro de la fila principal (desde el borde superior del carril)
LANES = [
    ("L_GER", "Gerente", 190, 72),
    ("L_ALM", "Almacenista", 190, 72),
    ("L_JEF", "Jefe de Producción", 240, 120),
    ("L_TER", "Personal de Terminación", 190, 72),
    ("L_SEC", "Secretaria", 190, 72),
    ("L_VEN", "Vendedor", 200, 72),
]

# Participantes externos (BPMN «piscina negra»: sin proceso propio). Lo que hacen ocurre fuera de TexCore y solo se ven sus
# intercambios con TexCore (flujos de mensaje). id, nombre, lado (arriba o abajo de la piscina de TexCore).
EXTERNAL_H, EXTERNAL_GAP = 70, 50
EXTERNALS = [
    ("P_LAV", "Lavandería (tercero externo: lava las prendas fuera de TexCore)", "top"),
    ("P_TRA", "Transportadora (tercero externo: transporta, entrega y cobra el contraentrega)", "bottom"),
]

# id: (tipo, nombre, carril, columna, opciones)
# tipos: start, end, user, service, manual, gateway, boundary (evento de error adjunto a una tarea: opción `attached`)
# opciones: dy (desplazamiento vertical), lab (posición de la etiqueta), doc (pantalla del menú)
N = {}


def node(i, tipo, nombre, lane, col, **kw):
    N[i] = dict(id=i, tipo=tipo, nombre=nombre, lane=lane, col=col, **kw)


# 1. Compras
node("S0", "start", "Se necesita materia prima", "L_JEF", 0, lab="b")
node("T1", "user", "Solicitar orden de compra (Compras)", "L_JEF", 1,
     doc="Compras → Órdenes de compra → Nueva orden. La orden nace en borrador (OC-0001).")
node("T2", "user", "Aprobar orden de compra (Compras)", "L_GER", 1,
     doc="Compras → Órdenes de compra → Aprobar (permiso compras.aprobar).")
node("G1", "gateway", "¿Aprobada?", "L_GER", 2, lab="a")
node("E1", "end", "Orden cancelada", "L_GER", 3, lab="b")
node("T3", "user", "Registrar recepción de mercancía (Compras)", "L_ALM", 2,
     doc="Compras → Recepción de mercancía. Quien creó la orden no puede recibirla.")
node("S1", "service", "Ingresar al stock, actualizar costo promedio y kardex", "L_ALM", 3,
     doc="Cada fila recibida suma al stock, recalcula el costo promedio ponderado y deja su fila en el kardex.")
# 2. Producción
node("T4", "user", "Definir referencia de jean: tallas y colores (HU 3.1)", "L_JEF", 3,
     doc="Referencias de Jean → Catálogo de jeans.")
node("T5", "user", "Definir ficha de consumo (HU 3.2)", "L_JEF", 4,
     doc="Catálogo de jeans → botón Ficha técnica.")
node("T6", "user", "Validar material con la simulación (HU 4.1)", "L_JEF", 5,
     doc="Producción y Trazabilidad → Órdenes de producción (Disponibilidad de material).")
node("G2", "gateway", "¿Alcanza el material?", "L_JEF", 6, lab="ul")
node("T7", "user", "Ajustar cantidad al máximo producible (HU 4.1)", "L_JEF", 7,
     doc="Órdenes de producción → botón «Usar N».")
node("T8", "user", "Crear orden de producción en lotes (HU 4.2)", "L_JEF", 8,
     doc="Producción y Trazabilidad → Órdenes de producción → Crear orden (OP-0001, lotes OP-0001-L01…).")
node("S2", "service", "Descontar el material del almacén (HU 4.2)", "L_JEF", 9,
     doc="En la misma transacción: salida de inventario con la merma de la ficha y foto del costo.")
node("T9", "user", "Asignar operarios y máquinas (HU 4.4)", "L_JEF", 10,
     doc="Producción y Trazabilidad → Recursos y Seguimiento.")
node("T10", "user", "Controlar tiempos: corte, confección, terminación (HU 4.3)", "L_JEF", 11,
     doc="Órdenes de producción → Seguimiento (iniciar, pausar, reanudar, terminar).")
node("T11", "user", "Seguir lotes en el monitor Kanban (HU 4.5)", "L_JEF", 12,
     doc="Producción y Trazabilidad → Monitor de estado.")
# 3. Lavandería
node("T12", "user", "Emitir remisión REM-LAV a lavandería (HU 5.1)", "L_JEF", 13,
     doc="Procesos Externos (Lavandería) → Remisión a Lavado. El lote queda En tránsito.")
node("T14", "user", "Registrar recepción con cotejo (HU 5.2)", "L_JEF", 14,
     doc="Procesos Externos (Lavandería) → Recepción de Lavandería (conformes + merma + dañadas = enviadas).")
node("S4", "service", "Validar cotejo y asentar acta REC-LAV (HU 5.2)", "L_JEF", 15,
     doc="Si la suma no cuadra, el sistema rechaza y no guarda nada.")
node("B1", "boundary", "Cotejo no cuadra", "L_JEF", 15, attached="S4", lab="br",
     doc="Error: conformes + merma + dañadas no suman lo enviado. No se guarda nada y se corrige el conteo.")
node("G3", "gateway", "¿Hay merma o dañadas?", "L_JEF", 16, lab="b")
node("S5", "service", "Liquidar pérdidas del tercero (HU 5.2)", "L_JEF", 17,
     doc="costo_perdida = (merma + dañadas) × costo unitario de la prenda.")
node("S6", "service", "Devolver lote a planta con las conformes (HU 5.2)", "L_JEF", 18,
     doc="El lote vuelve a PLANTA y su cantidad pasa a ser las prendas conformes.")
# 4. Calidad y producto terminado
node("T15", "user", "Inspeccionar lote: aptas y marras (HU 6.1)", "L_TER", 18,
     doc="Control de Calidad → Inspecciones (aptas + marras = recibidas conformes).")
node("T16", "user", "Ingresar aptas por talla y color al inventario final (HU 6.2)", "L_SEC", 18,
     doc="Producto Terminado → Ingreso.")
node("S8", "service", "Actualizar stock y libro de movimientos (HU 6.2)", "L_SEC", 19,
     doc="Saldo por variante nunca negativo; movimiento ENTRADA_PRODUCCION con saldo antes y después.")
node("G4", "gateway", "¿Hay descuadre?", "L_SEC", 20, lab="ul")
node("T17", "user", "Ajustar inventario con motivo (HU 6.3)", "L_SEC", 21,
     doc="Producto Terminado → Ajuste manual (movimientos AJUSTE).")
# 5. Venta y envío
node("T18", "manual", "Obtener la guía en el portal de la transportadora", "L_VEN", 22,
     doc="Fuera de la app: la guía se genera en el portal de la transportadora antes de facturar.")
node("T19", "user", "Facturar y anotar la guía (HU 7.1, HU 7.2)", "L_VEN", 23,
     doc="Ventas y Despachos → Nueva venta (cliente, prendas, descuento, transportadora y guía).")
node("G5", "gateway", "¿Hay stock?", "L_VEN", 24, lab="a")
node("E2", "end", "Venta rechazada: el sistema lista las faltantes", "L_VEN", 24, dy=68, lab="l")
node("S10", "service", "Descontar inventario y emitir factura POS en PDF (HU 7.1)", "L_VEN", 25,
     doc="Factura FV-0001 «POS interna» (no es electrónica); movimiento SALIDA_VENTA; PDF descargable.")
node("G6", "gateway", "¿Se agrupa en una relación de despacho?", "L_SEC", 25, lab="l")
node("T21", "user", "Armar relación de despacho (HU 7.2)", "L_SEC", 26,
     doc="Envíos → Relaciones de despacho (RD-0001). Opcional.")
node("S11", "service", "Pasar las guías a En tránsito (HU 7.2)", "L_SEC", 27,
     doc="Todas las guías de la relación pasan a EN_TRANSITO en una sola transacción.")
node("T23", "user", "Consultar estado de la guía (HU 7.2)", "L_SEC", 29,
     doc="Envíos → Guías → botón Consultar estado (permiso envios.gestionar).")
node("S12", "service", "Consultar Track123 y actualizar el semáforo (HU 7.2)", "L_SEC", 30,
     doc="Solo Interrapidísimo, solo a petición. Estados: por despachar, en tránsito, con novedad, entregada, devuelta.")
node("G7", "gateway", "¿Cómo quedó la entrega?", "L_SEC", 31, lab="al")
# 6. Recaudo o devolución
node("G8", "gateway", "¿Llegó el recaudo?", "L_SEC", 32, lab="a")
node("E6", "end", "Recaudo pendiente: la factura sigue por cobrar", "L_SEC", 32, dy=68, lab="l")
node("T24", "user", "Confirmar recaudo de la guía entregada (HU 7.3, HU 7.5)", "L_SEC", 33,
     doc="Ventas y Despachos → Gestión de cartera → Confirmar recaudo (permiso ventas.conciliar: Secretaria y Gerente). "
         "Solo se confirma el recaudo de una guía entregada.")
node("S13", "service", "Sumar recaudo al saldo financiero (HU 7.3)", "L_SEC", 34,
     doc="Movimiento de cartera RECAUDO con saldo antes y después.")
node("T27", "user", "Registrar devolución física del paquete (HU 7.2)", "L_ALM", 32,
     doc="Envíos → Guías → detalle de la guía devuelta → Registrar devolución (permiso envios.devolucion).")
node("S14", "service", "Reingresar stock y anotar flete al vendedor (HU 7.2)", "L_ALM", 33,
     doc="Movimiento DEVOLUCION_VENTA; el flete queda como flete_vendedor (solo se registra y se reporta).")
node("E4", "end", "Devolución registrada", "L_ALM", 34, lab="b")
# 7. Reportes
node("T25", "user", "Consultar tablero gerencial y exportar a Excel o CSV (HU 7.4)", "L_GER", 35,
     doc="Reportes → Tablero gerencial → Exportar Excel (.xlsx) o CSV (.csv).")
node("E3", "end", "Proceso completado", "L_GER", 36, lab="b")

# Flujos: (origen, destino, etiqueta, ruta, opciones)
# ruta: h (recto), v (recto vertical), rv (derecha y luego vertical), vr (vertical y luego derecha),
#       corr (por un pasillo: exit, entry)
F = []


def flow(s, t, label="", route="auto", **kw):
    F.append(dict(src=s, tgt=t, label=label, route=route, **kw))


flow("S0", "T1")
flow("T1", "T2", route="v")
flow("T2", "G1")
flow("G1", "E1", "No", default=True)
flow("G1", "T3", "Sí", route="v", cond="orden aprobada por el Gerente")
flow("T3", "S1")
flow("S1", "T4", route="v")
flow("T4", "T5")
flow("T5", "T6")
flow("T6", "G2")
flow("G2", "T7", "No", cond="alcanza para menos prendas de las pedidas")
flow("G2", "T8", "Sí", route="corr", exit="t", entry="t", cond="el material alcanza para todo el pedido")
flow("G2", "T1", "No: falta material, solicitar compra", route="corr", exit="b", entry="b", lseg=1, default=True)
flow("T7", "T8")
flow("T8", "S2")
flow("S2", "T9")
flow("T9", "T10")
flow("T10", "T11")
flow("T11", "T12")
flow("T12", "T14")
flow("T14", "S4")
flow("S4", "G3")
flow("B1", "T14", route="corr", exit="b", entry="b")
flow("G3", "S5", "Sí", cond="merma + dañadas > 0")
flow("G3", "S6", "No", route="corr", exit="t", entry="t", lseg=0, default=True)
flow("S5", "S6")
flow("S6", "T15", route="v")
flow("T15", "T16", route="v")
flow("T16", "S8")
flow("S8", "G4")
flow("G4", "T17", "Sí", cond="el conteo físico no coincide con el sistema")
flow("G4", "T18", "No", route="vr", default=True)
flow("T17", "T18", route="rv")
flow("T18", "T19")
flow("T19", "G5")
flow("G5", "S10", "Sí", cond="hay stock de todas las tallas y colores pedidos")
flow("G5", "E2", "No", route="v", default=True)
flow("S10", "G6", route="v")
flow("G6", "T21", "Sí", cond="se despachan varias guías juntas")
flow("G6", "T23", "No", route="corr", exit="t", entry="t", lseg=0, default=True)
flow("T21", "S11")
flow("S11", "T23")
flow("T23", "S12")
flow("S12", "G7")
flow("G7", "G8", "Entregada", cond="estado de la guía = entregada")
flow("G7", "T27", "Devuelta", route="vr", cond="estado de la guía = devuelta")
flow("G7", "T23", "Con novedad o en tránsito: volver a consultar", route="corr", exit="b", entry="b", lseg=1, default=True)
flow("G8", "T24", "Sí", cond="la transportadora entregó el dinero del contraentrega")
flow("G8", "E6", "No", route="v", default=True)
flow("T24", "S13")
flow("S13", "T25", route="rv")
flow("T27", "S14")
flow("S14", "E4")
flow("T25", "E3")

# Notas de texto (anotaciones): id, texto, carril, columna (puede ser decimal), dy, ancho, alto,
#   nodo asociado, lado de la nota (l/r/t/b), lado del nodo (l/r/t/b)
A = []


def note(i, texto, lane, col, node_id, a_side, n_side, dy=0, w=150, h=56):
    A.append(dict(id=i, texto=texto, lane=lane, col=col, dy=dy, w=w, h=h, node=node_id,
                  a_side=a_side, n_side=n_side))


note("A1", "No existe «rechazar»: si el Gerente no aprueba, Producción cancela la orden indicando el motivo.",
     "L_GER", 4.5, "E1", "l", "r", w=320, h=44)
note("A4", "Defectos: las marras se registran con su defecto, restan de las aptas y no entran al inventario.",
     "L_TER", 16.5, "T15", "r", "l", w=320, h=44)
note("A5", "Opcional: solo cuando hay descuadre; exige un motivo.",
     "L_TER", 20, "G4", "b", "t", w=150, h=44)
note("A8", "Solo Interrapidísimo y solo cuando alguien pulsa «Consultar estado».",
     "L_SEC", 30, "S12", "b", "t", dy=-84, w=230, h=40)
note("A10", "El flete solo se registra a nombre del vendedor y se reporta; no se descuenta de ningún pago.",
     "L_ALM", 33.5, "S14", "t", "b", dy=84, w=320, h=40)

# Flujos de mensaje con los participantes externos: id, origen, destino, etiqueta (origen o destino es un id de EXTERNALS)
MESSAGES = [
    ("M1", "T12", "P_LAV", "Remisión REM-LAV y prendas"),
    ("M2", "P_LAV", "T14", "Prendas lavadas y acta de entrega"),
    ("M3", "P_TRA", "T18", "Número de guía (portal)"),
    ("M4", "S11", "P_TRA", "Paquetes despachados"),
    ("M5", "P_TRA", "S12", "Estado del envío (Track123)"),
    ("M6", "P_TRA", "T24", "Dinero del contraentrega"),
]

# Cortes para los diagramas de detalle: columnas incluidas, eventos extra y flujos extra
SLICES = {
    "texcore-proceso": dict(titulo=POOL_NAME, cols=None),
    "texcore-proceso-produccion": dict(
        titulo="Compras, producción, lavandería y producto terminado", cols=(0, 21),
        extra_nodes=[("E5", "end", "Producto terminado listo para vender", "L_SEC", 22, dict(lab="a"))],
        extra_flows=[("G4", "E5", "No", "corr", dict(exit="b", entry="b", default=True)), ("T17", "E5", "", "h", {})]),
    "texcore-proceso-venta": dict(
        titulo="Venta, envío y recaudo", cols=(22, 36),
        extra_nodes=[("S9", "start", "Hay producto terminado y un pedido", "L_VEN", 21, dict(lab="b"))],
        extra_flows=[("S9", "T18", "", "h", {})]),
}

# --------------------------------------------------------------------------------------
# Construcción del modelo
# --------------------------------------------------------------------------------------
TIPO_BPMN = {"start": "startEvent", "end": "endEvent", "user": "userTask", "service": "serviceTask",
             "manual": "manualTask", "gateway": "exclusiveGateway", "boundary": "boundaryEvent"}


def size(tipo):
    if tipo in ("start", "end", "boundary"):
        return EVENT, EVENT
    if tipo == "gateway":
        return GATE, GATE
    return TASK_W, TASK_H


class Model:
    def __init__(self, key, spec):
        self.key = key
        self.spec = spec
        lo, hi = spec["cols"] if spec["cols"] else (0, 10 ** 6)
        self.base = 0
        nodes = {i: dict(n) for i, n in N.items() if lo <= n["col"] <= hi}
        for (i, tipo, nombre, lane, col, kw) in spec.get("extra_nodes", []):
            nodes[i] = dict(id=i, tipo=tipo, nombre=nombre, lane=lane, col=col, **kw)
        self.nodes = nodes
        self.base = min(n["col"] for n in nodes.values())
        flows = [dict(f) for f in F if f["src"] in nodes and f["tgt"] in nodes]
        for (s, t, lab, route, kw) in spec.get("extra_flows", []):
            flows.append(dict(src=s, tgt=t, label=lab, route=route, **kw))
        self.flows = flows
        self.notes = [dict(a) for a in A if a["node"] in nodes and lo <= a["col"] <= hi]
        external_ids = {e[0] for e in EXTERNALS}
        self.messages = [
            dict(id=i, src=s, tgt=t, label=lab) for (i, s, t, lab) in MESSAGES
            if all(end in nodes or end in external_ids for end in (s, t))
        ]
        used_ext = {end for msg in self.messages for end in (msg["src"], msg["tgt"]) if end in external_ids}
        self.externals = [e for e in EXTERNALS if e[0] in used_ext]
        used = {n["lane"] for n in nodes.values()}
        self.lanes = [l for l in LANES if l[0] in used]
        maxcol = max(n["col"] for n in nodes.values()) - self.base
        self.ncols = maxcol + 1
        # geometría: piscinas externas arriba y abajo de la de TexCore, y carriles
        has_top = any(e[2] == "top" for e in self.externals)
        self.pool_y = POOL_Y + (EXTERNAL_H + EXTERNAL_GAP if has_top else 0)
        self.lane_geo = {}
        y = self.pool_y
        for (lid, name, h, cy) in self.lanes:
            self.lane_geo[lid] = dict(y=y, h=h, cy=cy)
            y += h
        self.pool_h = y - self.pool_y
        self.external_geo = {}
        for (eid, name, side) in self.externals:
            ey = POOL_Y if side == "top" else self.pool_y + self.pool_h + EXTERNAL_GAP
            self.external_geo[eid] = dict(y=ey, h=EXTERNAL_H, side=side)
        self.total_h = (max(g["y"] + g["h"] for g in self.external_geo.values()) if self.external_geo else 0)
        self.total_h = max(self.total_h, self.pool_y + self.pool_h) - POOL_Y
        self.content_x = POOL_X + POOL_HDR + LANE_HDR + PAD_X
        self.pool_w = POOL_HDR + LANE_HDR + PAD_X * 2 + self.ncols * COLW
        self.lane_x = POOL_X + POOL_HDR
        self.lane_w = self.pool_w - POOL_HDR
        for n in nodes.values():
            if n["tipo"] != "boundary":
                self.place(n)
        for n in nodes.values():
            if n["tipo"] == "boundary":  # sobre el borde inferior de la tarea a la que va adjunto
                host = nodes[n["attached"]]
                n.update(w=EVENT, h=EVENT, cx=host["cx"], cy=host["y"] + host["h"])
                n.update(x=n["cx"] - EVENT / 2, y=n["cy"] - EVENT / 2)

    def message_points(self, msg):
        """Flujo de mensaje vertical entre una tarea y el borde de la piscina externa (arriba o abajo)."""
        ext_id = msg["src"] if msg["src"] in self.external_geo else msg["tgt"]
        node_id = msg["tgt"] if ext_id == msg["src"] else msg["src"]
        g, n = self.external_geo[ext_id], self.nodes[node_id]
        if g["side"] == "top":
            p_node, p_ext = (n["cx"], n["y"]), (n["cx"], g["y"] + g["h"])
        else:
            p_node, p_ext = (n["cx"], n["y"] + n["h"]), (n["cx"], g["y"])
        return [p_node, p_ext] if msg["src"] == node_id else [p_ext, p_node]

    def cx(self, col):
        return self.content_x + (col - self.base) * COLW + COLW / 2

    def place(self, n):
        w, h = size(n["tipo"])
        g = self.lane_geo[n["lane"]]
        cx = self.cx(n["col"])
        cy = g["y"] + g["cy"] + n.get("dy", 0)
        n.update(w=w, h=h, cx=cx, cy=cy, x=cx - w / 2, y=cy - h / 2)

    # puntos de anclaje -------------------------------------------------------------
    def anchor(self, n, side):
        return {"l": (n["x"], n["cy"]), "r": (n["x"] + n["w"], n["cy"]),
                "t": (n["cx"], n["y"]), "b": (n["cx"], n["y"] + n["h"])}[side]

    def corridor(self, n, side):
        g = self.lane_geo[n["lane"]]
        return g["y"] + 16 if side == "t" else g["y"] + g["h"] - 16

    def route(self, f):
        s, t = self.nodes[f["src"]], self.nodes[f["tgt"]]
        r = f["route"]
        if r == "auto":
            r = "h" if abs(s["cy"] - t["cy"]) < 1 else ("v" if abs(s["cx"] - t["cx"]) < 1 else "rv")
        if r == "h":
            return [self.anchor(s, "r"), self.anchor(t, "l")]
        if r == "v":
            down = t["cy"] > s["cy"]
            return [self.anchor(s, "b" if down else "t"), self.anchor(t, "t" if down else "b")]
        if r == "rv":
            p0 = self.anchor(s, "r")
            down = t["cy"] > s["cy"]
            p2 = self.anchor(t, "t" if down else "b")
            return [p0, (p2[0], p0[1]), p2]
        if r == "vr":
            down = t["cy"] > s["cy"]
            p0 = self.anchor(s, "b" if down else "t")
            p2 = self.anchor(t, "l")
            return [p0, (p0[0], p2[1]), p2]
        if r == "corr":
            p0 = self.anchor(s, f["exit"])
            p3 = self.anchor(t, f["entry"])
            ycor = self.corridor(s, f["exit"])
            return [p0, (p0[0], ycor), (p3[0], ycor), p3]
        raise ValueError(r)

    # etiquetas ---------------------------------------------------------------------
    @staticmethod
    def wrap_lines(text, width_px):
        maxc = max(4, int(width_px / CHAR_W))
        lines, cur = 1, 0
        for word in text.split():
            L = len(word)
            if cur == 0:
                cur = L
            elif cur + 1 + L <= maxc:
                cur += 1 + L
            else:
                lines += 1
                cur = L
        return lines

    def flow_label(self, f, pts):
        text = f["label"]
        seg = f.get("lseg", 0)
        a, b = pts[seg], pts[seg + 1]
        horizontal = abs(a[1] - b[1]) < 1
        w = LABEL_W
        lines = self.wrap_lines(text, w - 6)
        h = lines * 14 + 2
        if horizontal:
            direction = 1 if b[0] > a[0] else -1
            if direction > 0:
                x = a[0] + 6
            else:
                x = a[0] - 6 - w
            y = a[1] - h - 3
        else:
            direction = 1 if b[1] > a[1] else -1
            if f.get("lside") == "l":
                x = a[0] - 6 - w
            else:
                x = a[0] + 6
            y = a[1] + 4 if direction > 0 else a[1] - 4 - h
        return (x, y, w, h)

    def node_label(self, n):
        pos = n.get("lab", "b")
        text = n["nombre"]
        if n["tipo"] == "gateway":
            w = LABEL_W
        else:
            w = LABEL_W
        lines = self.wrap_lines(text, w - 4)
        h = lines * 14 + 2
        cx, cy, x0, y0 = n["cx"], n["cy"], n["x"], n["y"]
        x1, y1 = x0 + n["w"], y0 + n["h"]
        if pos == "b":
            return (cx - w / 2, y1 + 3, w, h)
        if pos == "a":
            return (cx - w / 2, y0 - h - 3, w, h)
        if pos == "ul":
            return (cx - n["w"] / 2 - w - 2, cy - h - 4, w, h)
        if pos == "l":
            return (x0 - w - 4, cy - h / 2, w, h)
        if pos == "r":
            return (x1 + 4, cy - h / 2, w, h)
        if pos == "al":
            return (cx - w - 6, y0 - h - 3, w, h)
        if pos == "br":
            return (x1 + 4, y1 - 6, w, h)
        raise ValueError(pos)

    # notas ---------------------------------------------------------------------------
    def place_note(self, a):
        g = self.lane_geo[a["lane"]]
        cx = self.cx(a["col"])
        cy = g["y"] + g["cy"] + a["dy"]
        a.update(x=cx - a["w"] / 2, y=cy - a["h"] / 2, cx=cx, cy=cy)
        n = self.nodes[a["node"]]
        p_node = self.anchor(n, a["n_side"])
        s = a["a_side"]
        # Punto en la nota: para t/b, se alinea con el nodo si cabe; para l/r, centro vertical.
        if s in ("t", "b"):
            px = min(max(p_node[0], a["x"] + 6), a["x"] + a["w"] - 6)
            p_note = (px, a["y"] if s == "t" else a["y"] + a["h"])
        else:
            p_note = (a["x"] if s == "l" else a["x"] + a["w"], a["cy"])
        if s in ("t", "b") and abs(p_note[0] - p_node[0]) < 1:
            pts = [p_node, p_note]
        elif s in ("t", "b"):
            midy = (p_node[1] + p_note[1]) / 2
            pts = [p_node, (p_node[0], midy), (p_note[0], midy), p_note]
        elif abs(p_note[1] - p_node[1]) < 1:
            pts = [p_node, p_note]
        else:
            midx = (p_node[0] + p_note[0]) / 2
            pts = [p_node, (midx, p_node[1]), (midx, p_note[1]), p_note]
        a["pts"] = pts


def lab_bounds(box):
    x, y, w, h = box
    return (x, y, w, h)


def fmt(v):
    return f"{v:.0f}" if abs(v - round(v)) < 1e-6 else f"{v:.1f}"


def build_xml(m: Model):
    key = m.key
    pid = "Process_TexCore"
    out = []
    w = out.append
    w('<?xml version="1.0" encoding="UTF-8"?>')
    w('<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
      'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
      'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
      'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
      f'id="Definitions_{key}" targetNamespace="https://texcore.example/bpmn" '
      'exporter="TexCore generar_bpmn.py" exporterVersion="1.0">')
    w('  <bpmn:collaboration id="Collaboration_TexCore">')
    w(f'    <bpmn:participant id="Participant_TexCore" name={quoteattr(m.spec["titulo"])} processRef="{pid}" />')
    for (eid, name, side) in m.externals:
        w(f'    <bpmn:participant id="{eid}" name={quoteattr(name)} />')
    for msg in m.messages:
        w(f'    <bpmn:messageFlow id="{msg["id"]}" name={quoteattr(msg["label"])} sourceRef="{msg["src"]}" targetRef="{msg["tgt"]}" />')
    w('  </bpmn:collaboration>')
    w(f'  <bpmn:process id="{pid}" name={quoteattr(m.spec["titulo"])} isExecutable="false">')
    w('    <bpmn:laneSet id="LaneSet_TexCore">')
    for (lid, name, h, cy) in m.lanes:
        w(f'      <bpmn:lane id="{lid}" name={quoteattr(name)}>')
        for n in m.nodes.values():
            if n["lane"] == lid:
                w(f'        <bpmn:flowNodeRef>{n["id"]}</bpmn:flowNodeRef>')
        w('      </bpmn:lane>')
    w('    </bpmn:laneSet>')
    incoming = {i: [] for i in m.nodes}
    outgoing = {i: [] for i in m.nodes}
    for k, f in enumerate(m.flows, 1):
        f["id"] = f"Flow_{k:02d}"
        outgoing[f["src"]].append(f["id"])
        incoming[f["tgt"]].append(f["id"])
    for n in sorted(m.nodes.values(), key=lambda q: (q["col"], q["id"])):
        tag = TIPO_BPMN[n["tipo"]]
        fill, stroke = COLORS[n["tipo"]]
        inner = []
        if n.get("doc"):
            inner.append(f'      <bpmn:documentation>{escape(n["doc"])}</bpmn:documentation>')
        for fid in incoming[n["id"]]:
            inner.append(f'      <bpmn:incoming>{fid}</bpmn:incoming>')
        for fid in outgoing[n["id"]]:
            inner.append(f'      <bpmn:outgoing>{fid}</bpmn:outgoing>')
        attrs = ""
        if n["tipo"] == "gateway":
            default = [f["id"] for f in m.flows if f["src"] == n["id"] and f.get("default")]
            if default:
                attrs = f' default="{default[0]}"'
        if n["tipo"] == "boundary":
            attrs = f' attachedToRef="{n["attached"]}"'
            inner.append(f'      <bpmn:errorEventDefinition id="{n["id"]}_error" />')
        w(f'    <bpmn:{tag} id="{n["id"]}" name={quoteattr(n["nombre"])}{attrs}>')
        out.extend(inner)
        w(f'    </bpmn:{tag}>')
    for f in m.flows:
        nm = f' name={quoteattr(f["label"])}' if f["label"] else ""
        if f.get("cond"):
            w(f'    <bpmn:sequenceFlow id="{f["id"]}"{nm} sourceRef="{f["src"]}" targetRef="{f["tgt"]}">')
            w(f'      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">{escape(f["cond"])}</bpmn:conditionExpression>')
            w('    </bpmn:sequenceFlow>')
        else:
            w(f'    <bpmn:sequenceFlow id="{f["id"]}"{nm} sourceRef="{f["src"]}" targetRef="{f["tgt"]}" />')
    for a in m.notes:
        w(f'    <bpmn:textAnnotation id="{a["id"]}"><bpmn:text>{escape(a["texto"])}</bpmn:text></bpmn:textAnnotation>')
        w(f'    <bpmn:association id="Assoc_{a["id"]}" associationDirection="None" '
          f'sourceRef="{a["node"]}" targetRef="{a["id"]}" />')
    w('  </bpmn:process>')
    # ---------------- DI ----------------
    w('  <bpmndi:BPMNDiagram id="BPMNDiagram_TexCore">')
    w('    <bpmndi:BPMNPlane id="BPMNPlane_TexCore" bpmnElement="Collaboration_TexCore">')
    w(f'      <bpmndi:BPMNShape id="Participant_TexCore_di" bpmnElement="Participant_TexCore" isHorizontal="true">'
      f'<dc:Bounds x="{POOL_X}" y="{fmt(m.pool_y)}" width="{fmt(m.pool_w)}" height="{fmt(m.pool_h)}" />'
      f'</bpmndi:BPMNShape>')
    for (eid, name, side) in m.externals:
        g = m.external_geo[eid]
        w(f'      <bpmndi:BPMNShape id="{eid}_di" bpmnElement="{eid}" isHorizontal="true">'
          f'<dc:Bounds x="{POOL_X}" y="{fmt(g["y"])}" width="{fmt(m.pool_w)}" height="{g["h"]}" />'
          f'</bpmndi:BPMNShape>')
    for (lid, name, h, cy) in m.lanes:
        g = m.lane_geo[lid]
        w(f'      <bpmndi:BPMNShape id="{lid}_di" bpmnElement="{lid}" isHorizontal="true">'
          f'<dc:Bounds x="{m.lane_x}" y="{fmt(g["y"])}" width="{fmt(m.lane_w)}" height="{g["h"]}" />'
          f'</bpmndi:BPMNShape>')
    for n in sorted(m.nodes.values(), key=lambda q: (q["col"], q["id"])):
        fill, stroke = COLORS[n["tipo"]]
        extra = ' isMarkerVisible="true"' if n["tipo"] == "gateway" else ""
        lx, ly, lw, lh = lab_bounds(m.node_label(n)) if n["tipo"] in ("start", "end", "gateway", "boundary") else (0, 0, 0, 0)
        label = ""
        if lw:
            label = (f'<bpmndi:BPMNLabel><dc:Bounds x="{fmt(lx)}" y="{fmt(ly)}" width="{fmt(lw)}" '
                     f'height="{fmt(lh)}" /></bpmndi:BPMNLabel>')
        w(f'      <bpmndi:BPMNShape id="{n["id"]}_di" bpmnElement="{n["id"]}"{extra} '
          f'>'
          f'<dc:Bounds x="{fmt(n["x"])}" y="{fmt(n["y"])}" width="{n["w"]}" height="{n["h"]}" />{label}'
          f'</bpmndi:BPMNShape>')
    for a in m.notes:
        m.place_note(a)
        w(f'      <bpmndi:BPMNShape id="{a["id"]}_di" bpmnElement="{a["id"]}">'
          f'<dc:Bounds x="{fmt(a["x"])}" y="{fmt(a["y"])}" width="{a["w"]}" height="{a["h"]}" />'
          f'</bpmndi:BPMNShape>')
    for f in m.flows:
        pts = m.route(f)
        f["pts"] = pts
        w(f'      <bpmndi:BPMNEdge id="{f["id"]}_di" bpmnElement="{f["id"]}">')
        for (x, y) in pts:
            w(f'        <di:waypoint x="{fmt(x)}" y="{fmt(y)}" />')
        if f["label"]:
            lx, ly, lw, lh = lab_bounds(m.flow_label(f, pts))
            w(f'        <bpmndi:BPMNLabel><dc:Bounds x="{fmt(lx)}" y="{fmt(ly)}" width="{fmt(lw)}" '
              f'height="{fmt(lh)}" /></bpmndi:BPMNLabel>')
        w('      </bpmndi:BPMNEdge>')
    for msg in m.messages:
        pts = m.message_points(msg)
        msg["pts"] = pts
        w(f'      <bpmndi:BPMNEdge id="{msg["id"]}_di" bpmnElement="{msg["id"]}">')
        for (x, y) in pts:
            w(f'        <di:waypoint x="{fmt(x)}" y="{fmt(y)}" />')
        top, bottom = sorted((pts[0][1], pts[1][1]))
        w(f'        <bpmndi:BPMNLabel><dc:Bounds x="{fmt(pts[0][0] + 6)}" y="{fmt((top + bottom) / 2 - 14)}" '
          f'width="{LABEL_W}" height="28" /></bpmndi:BPMNLabel>')
        w('      </bpmndi:BPMNEdge>')
    for a in m.notes:
        w(f'      <bpmndi:BPMNEdge id="Assoc_{a["id"]}_di" bpmnElement="Assoc_{a["id"]}">')
        for (x, y) in a["pts"]:
            w(f'        <di:waypoint x="{fmt(x)}" y="{fmt(y)}" />')
        w('      </bpmndi:BPMNEdge>')
    w('    </bpmndi:BPMNPlane>')
    w('  </bpmndi:BPMNDiagram>')
    w('</bpmn:definitions>')
    return "\n".join(out) + "\n"


def check(m: Model):
    """Comprobaciones de geometría (segmentos que atraviesan tareas ajenas) y de semántica BPMN.

    Semántica: cada salida de una compuerta exclusiva lleva condición o es su única salida por defecto; todo nodo que no es
    de inicio tiene una entrada y todo nodo que no es de fin tiene una salida; los flujos de mensaje unen TexCore con un
    participante externo (nunca dos nodos de la misma piscina).
    """
    problemas = []
    for g in (n for n in m.nodes.values() if n["tipo"] == "gateway"):
        outs = [f for f in m.flows if f["src"] == g["id"]]
        defaults = [f for f in outs if f.get("default")]
        if len(outs) > 1 and len(defaults) != 1:
            problemas.append(f"{g['id']}: debe tener exactamente una salida por defecto ({len(defaults)})")
        for f in outs:
            if len(outs) > 1 and not f.get("default") and not f.get("cond"):
                problemas.append(f"{g['id']}->{f['tgt']}: salida sin condición")
            if f.get("default") and f.get("cond"):
                problemas.append(f"{g['id']}->{f['tgt']}: la salida por defecto no lleva condición")
    for n in m.nodes.values():
        if n["tipo"] not in ("start", "boundary") and not any(f["tgt"] == n["id"] for f in m.flows):
            problemas.append(f"{n['id']}: sin flujo de entrada")
        if n["tipo"] != "end" and not any(f["src"] == n["id"] for f in m.flows):
            problemas.append(f"{n['id']}: sin flujo de salida")
    external_ids = {e[0] for e in EXTERNALS}
    for msg in m.messages:
        if (msg["src"] in external_ids) == (msg["tgt"] in external_ids):
            problemas.append(f"{msg['id']}: un flujo de mensaje debe unir TexCore con un participante externo")
    boxes = {i: (n["x"] - 2, n["y"] - 2, n["x"] + n["w"] + 2, n["y"] + n["h"] + 2)
             for i, n in m.nodes.items() if n["tipo"] != "boundary"}
    edges = [(f["id"], f["src"], f["tgt"], f["pts"]) for f in m.flows]
    edges += [(msg["id"], msg["src"], msg["tgt"], msg["pts"]) for msg in m.messages]
    for (fid, src, tgt, pts) in edges:
        attached = {m.nodes[src].get("attached")} if src in m.nodes else set()
        for (a, b) in zip(pts, pts[1:]):
            for i, (x0, y0, x1, y1) in boxes.items():
                if i in (src, tgt) or i in attached:
                    continue
                sx0, sx1 = sorted((a[0], b[0]))
                sy0, sy1 = sorted((a[1], b[1]))
                if sx1 >= x0 and sx0 <= x1 and sy1 >= y0 and sy0 <= y1:
                    problemas.append(f"{fid} {src}->{tgt} cruza {i}")
    return problemas


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    fallos = 0
    for key, spec in SLICES.items():
        m = Model(key, spec)
        xml = build_xml(m)
        (out / f"{key}.bpmn").write_text(xml, encoding="utf-8")
        probs = check(m)
        print(f"{key}.bpmn: {len(m.nodes)} nodos, {len(m.flows)} flujos, "
              f"{len(m.messages)} mensajes, {fmt(m.pool_w + POOL_X * 2)} x {fmt(m.total_h + POOL_Y * 2)} px",
              "OK" if not probs else probs)
        if probs:
            fallos += 1
    if fallos:
        sys.exit(1)


if __name__ == "__main__":
    main()
