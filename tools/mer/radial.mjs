// MER general con atributos: 1) layout de entidades+rombos, 2) atributos alrededor de cada dueño con relajación
import { Graphviz } from "@hpcc-js/wasm-graphviz";
import { Resvg } from "@resvg/resvg-js";
import fs from "fs";

const [,, inDot, outDir, scaleArg, ringArg, maxpx] = process.argv;
const SCALE = parseFloat(scaleArg || "1.6");
const RING_GAP = parseFloat(ringArg || "0.22"); // pulgadas de separación entre caja y óvalo
const gv = await Graphviz.load();
const full = fs.readFileSync(inDot, "utf8").split("\n");

const isAttrNode = (l) => /^\s+a_[^ ]+ \[/.test(l);
const isAttrEdge = (l) => /--\s+a_/.test(l) || /^\s+a_\S+\s+--/.test(l);
const core = full.filter((l) => !isAttrNode(l) && !isAttrEdge(l)).join("\n");

// 1) layout del núcleo
const json = JSON.parse(gv.layout(core, "json", "neato"));
const pos = new Map(); // nombre -> {x,y} en pulgadas
const sizeOf = new Map();
for (const o of json.objects || []) {
  if (!o.pos) continue;
  const [x, y] = o.pos.split(",").map(Number);
  pos.set(o.name, { x: (x / 72) * SCALE, y: (y / 72) * SCALE });
  sizeOf.set(o.name, { w: parseFloat(o.width || 1), h: parseFloat(o.height || 0.5) });
}
// aristas del núcleo para evitar sus ángulos
const nameByGvid = new Map((json.objects || []).map((o) => [o._gvid, o.name]));
const incident = new Map();
for (const e of json.edges || []) {
  const a = nameByGvid.get(e.tail), b = nameByGvid.get(e.head);
  if (!a || !b) continue;
  (incident.get(a) || incident.set(a, []).get(a)).push(b);
  (incident.get(b) || incident.set(b, []).get(b)).push(a);
}

// 2) atributos por dueño (leídos del DOT completo)
const attrs = []; // {id, owner, label}
const ownerOf = new Map();
for (const l of full) {
  const m = l.match(/^\s+(\S+)\s+--\s+(a_\S+)\s+\[/);
  if (m) ownerOf.set(m[2], m[1]);
}
for (const l of full) {
  if (!isAttrNode(l)) continue;
  const id = l.match(/^\s+(a_\S+) \[/)[1];
  const lab = (l.match(/label=<(.*)>\]/) || [])[1] || id;
  const text = lab.replace(/<[^>]+>/g, "");
  attrs.push({ id, owner: ownerOf.get(id), text, w: 0.075 * text.length + 0.35, h: 0.32 });
}
const byOwner = new Map();
for (const a of attrs) (byOwner.get(a.owner) || byOwner.set(a.owner, []).get(a.owner)).push(a);

const edgeDist = (w, h, ang) => { const c = Math.abs(Math.cos(ang)) || 1e-6, s = Math.abs(Math.sin(ang)) || 1e-6; return Math.min(w / 2 / c, h / 2 / s); };
const target = (a, ang) => { const o = sizeOf.get(a.owner); return edgeDist(o.w, o.h, ang) + edgeDist(a.w, a.h, ang) + RING_GAP; };
const angDiff = (a, b) => { let d = Math.abs(a - b) % (2 * Math.PI); return d > Math.PI ? 2 * Math.PI - d : d; };
for (const [owner, list] of byOwner) {
  const p = pos.get(owner); if (!p) continue;
  const edgeAngles = (incident.get(owner) || []).map((n) => { const q = pos.get(n); return q ? Math.atan2(q.y - p.y, q.x - p.x) : null; }).filter((v) => v !== null);
  let best = 0, bestScore = -1;
  for (let off = 0; off < 360; off += 3) {
    const th = (off * Math.PI) / 180; let score = Infinity;
    for (let i = 0; i < list.length; i++) {
      const ang = th + (i * 2 * Math.PI) / list.length;
      for (const ea of edgeAngles) score = Math.min(score, angDiff(ang, ea));
    }
    if (edgeAngles.length === 0) score = 1;
    if (score > bestScore) { bestScore = score; best = th; }
  }
  list.forEach((a, i) => { const ang = best + (i * 2 * Math.PI) / list.length; const d = target(a, ang); a.x = p.x + d * Math.cos(ang); a.y = p.y + d * Math.sin(ang); a.owner_pos = p; });
}

// 3) relajación con cajas: los atributos se repelen entre sí y de los nodos fijos, con un resorte al anillo de su dueño
const fixed = [...pos.entries()].map(([name, p]) => ({ name, x: p.x, y: p.y, w: sizeOf.get(name).w, h: sizeOf.get(name).h }));
const push = (a, bx, by, bw, bh, gap, k) => {
  const dx = a.x - bx, dy = a.y - by, nx = (a.w + bw) / 2 + gap, ny = (a.h + bh) / 2 + gap;
  if (Math.abs(dx) < nx && Math.abs(dy) < ny) {
    const px = nx - Math.abs(dx), py = ny - Math.abs(dy);
    if (px < py) return [Math.sign(dx || 1) * px * k, 0];
    return [0, Math.sign(dy || 1) * py * k];
  }
  return [0, 0];
};
for (let it = 0; it < 600; it++) {
  for (const a of attrs) {
    if (a.x === undefined) continue;
    let fx = 0, fy = 0;
    const dx0 = a.x - a.owner_pos.x, dy0 = a.y - a.owner_pos.y, d0 = Math.hypot(dx0, dy0) || 1e-6, ang = Math.atan2(dy0, dx0);
    const k = (d0 - target(a, ang)) * 0.2; fx -= (dx0 / d0) * k; fy -= (dy0 / d0) * k;
    for (const f of fixed) {
      if (f.name === a.owner) continue;
      const [px, py] = push(a, f.x, f.y, f.w, f.h, 0.1, 0.7); fx += px; fy += py;
    }
    for (const b of attrs) {
      if (b === a || b.x === undefined) continue;
      const [px, py] = push(a, b.x, b.y, b.w, b.h, 0.04, 0.5); fx += px; fy += py;
    }
    // no invadir la caja de su propio dueño
    const own = sizeOf.get(a.owner); const [qx, qy] = push(a, a.owner_pos.x, a.owner_pos.y, own.w, own.h, 0.08, 0.8); fx += qx; fy += qy;
    a.x += fx; a.y += fy;
  }
}

// 4) DOT final con todo fijado
let minx = Infinity, miny = Infinity;
for (const p of pos.values()) { minx = Math.min(minx, p.x); miny = Math.min(miny, p.y); }
for (const a of attrs) { minx = Math.min(minx, a.x - a.w / 2); miny = Math.min(miny, a.y - a.h / 2); }
const place = (x, y) => `pos="${(x - minx + 0.4).toFixed(3)},${(y - miny + 0.4).toFixed(3)}!"`;
const attrById = new Map(attrs.map((a) => [a.id, a]));
const out = full.map((l) => {
  const mn = l.match(/^\s+(\S+) \[/);
  if (mn && pos.has(mn[1]) && !isAttrNode(l)) return l.replace(" [", ` [${place(pos.get(mn[1]).x, pos.get(mn[1]).y)}, `);
  if (isAttrNode(l)) { const id = l.match(/^\s+(a_\S+) \[/)[1]; const a = attrById.get(id); return l.replace(" [", ` [${place(a.x, a.y)}, `); }
  if (isAttrEdge(l)) return l.replace(/, len=[\d.]+/, "");
  return l;
}).join("\n").replace(/overlap=prism;?/, "overlap=true;").replace(/splines=true/, "splines=line");
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(`${outDir}/mer-general-atributos.dot`, out);
const svg = gv.layout(out, "svg", "neato");
fs.writeFileSync(`${outDir}/mer-general-atributos.svg`, svg);
const m = svg.match(/<svg width="([\d.]+)pt" height="([\d.]+)pt"/); const w = parseFloat(m[1]), h = parseFloat(m[2]);
const limit = parseFloat(maxpx || 8000);
const zoom = Math.min(2, limit / (Math.max(w, h) * 4 / 3));
const png = new Resvg(svg, { fitTo: { mode: "zoom", value: zoom }, font: { loadSystemFonts: false, fontFiles: ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"], defaultFontFamily: "Arial" }, background: "white" }).render();
fs.writeFileSync(`${outDir}/mer-general-atributos.png`, png.asPng());
console.log(`${w}x${h}pt  png ${png.width}x${png.height}  atributos:${attrs.length} dueños:${byOwner.size}`);
