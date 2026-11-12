# Diagramas BPMN del proceso de negocio

Genera `texcore-proceso.bpmn` (visión de conjunto) y dos diagramas de detalle (`-produccion`, `-venta`) con apariencia estándar de bpmn.io, y los convierte a SVG y PNG.

```bash
cd backend/tools/bpmn
python generar_bpmn.py /tmp/bpmn            # escribe los .bpmn con el diagrama (DI) completo
npm install                                  # una sola vez (bpmn-js, puppeteer-core, resvg)
node render.mjs /tmp/bpmn-img /tmp/bpmn/*.bpmn   # SVG + PNG; falla si bpmn-js avisa de algo
```

- La definición (carriles, nodos con carril y columna, flujos, notas) está al inicio de `generar_bpmn.py`; los diagramas de detalle son cortes por columna de la misma definición.
- `render.mjs` usa Microsoft Edge sin ventana (`EDGE_PATH` cambia la ruta) y Arial de Windows para el PNG (lado mayor máximo `MAX_PX`, 8000 por defecto). `BPMN_NODE_MODULES` permite usar un `node_modules` en otra carpeta.
- Después copia los `.bpmn` a `docs/bpmn/` y los SVG/PNG a `docs/img/bpmn-*` (y a `BPMN/` en la raíz del proyecto): son estáticos.
