// Renderiza archivos .bpmn a SVG y PNG con bpmn-js (en Microsoft Edge sin ventana) y resvg.
//
// Uso:  node render.mjs <salida> <archivo.bpmn> [<archivo.bpmn> ...]
// Variables opcionales:
//   BPMN_NODE_MODULES  carpeta con node_modules (bpmn-js, puppeteer-core, @resvg/resvg-js);
//                      por defecto, la carpeta de este script.
//   EDGE_PATH          ejecutable de Edge/Chrome (por defecto, el de Windows).
//   MAX_PX             lado mayor máximo del PNG (8000 por defecto).
//
// Falla si bpmn-js informa errores o advertencias al importar el diagrama.
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const base = process.env.BPMN_NODE_MODULES || here;
const req = createRequire(path.join(base, "x.js"));
const puppeteer = req("puppeteer-core");
const { Resvg } = req("@resvg/resvg-js");
const viewerJs = req.resolve("bpmn-js/dist/bpmn-viewer.production.min.js");

const [outDir, ...files] = process.argv.slice(2);
if (!outDir || files.length === 0) {
  console.error("Uso: node render.mjs <salida> <archivo.bpmn> [...]");
  process.exit(2);
}
mkdirSync(outDir, { recursive: true });
const maxPx = Number(process.env.MAX_PX || 8000);
const edge = process.env.EDGE_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";

const browser = await puppeteer.launch({ executablePath: edge, headless: true, args: ["--no-sandbox"] });
let fallo = false;
try {
  const page = await browser.newPage();
  await page.setContent('<html><body><div id="c" style="width:1000px;height:800px"></div></body></html>');
  await page.addScriptTag({ path: viewerJs });
  for (const file of files) {
    const xml = readFileSync(file, "utf-8");
    const name = path.basename(file, ".bpmn");
    const r = await page.evaluate(async (xml) => {
      const viewer = new BpmnJS({ container: "#c" });
      try {
        const res = await viewer.importXML(xml);
        const { svg } = await viewer.saveSVG();
        return { warnings: (res.warnings || []).map((w) => w.message), svg };
      } catch (e) {
        return { error: String(e && e.message ? e.message : e), warnings: (e && e.warnings || []).map((w) => w.message) };
      }
    }, xml);
    if (r.error || r.warnings.length) {
      fallo = true;
      console.error(`${name}: ERROR`, r.error || "", r.warnings);
      continue;
    }
    // El SVG de bpmn-js trae el texto con Arial; se pasa a fondo blanco y se rasteriza.
    // resvg ignora marker-start/end dentro de style: se pasan a atributos para que se dibujen las flechas.
    let svg = r.svg.replace("<svg ", '<svg style="background:#ffffff" ');
    svg = svg.replace(/<(path|polyline|line)[^>]*>/g, (tag) => {
      let extra = "";
      tag = tag.replace(/\s*(marker-(?:start|end)):\s*url\('(#[^']+)'\);?/g, (_m, prop, ref) => {
        extra += ` ${prop}="url(${ref})"`;
        return "";
      });
      return extra ? tag.replace(/^<(\w+)/, `<$1${extra}`) : tag;
    });
    writeFileSync(path.join(outDir, `${name}.svg`), svg, "utf-8");
    const probe = new Resvg(svg, { font: { loadSystemFonts: false, fontFiles: ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"], defaultFontFamily: "Arial" } });
    const longest = Math.max(probe.width, probe.height);
    const resvg = new Resvg(svg, {
      background: "#ffffff",
      fitTo: longest > maxPx ? { mode: probe.width >= probe.height ? "width" : "height", value: maxPx } : { mode: "original" },
      font: { loadSystemFonts: false, fontFiles: ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"], defaultFontFamily: "Arial" },
    });
    const png = resvg.render();
    writeFileSync(path.join(outDir, `${name}.png`), png.asPng());
    console.log(`${name}: sin advertencias; PNG ${png.width} x ${png.height}`);
  }
} finally {
  await browser.close();
}
process.exit(fallo ? 1 : 0);
