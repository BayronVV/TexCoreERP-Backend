import { Graphviz } from "@hpcc-js/wasm-graphviz";
import { Resvg } from "@resvg/resvg-js";
import fs from "fs"; import path from "path";
const [,, dotDir, outDir, only, maxpx] = process.argv;
fs.mkdirSync(outDir,{recursive:true});
const gv = await Graphviz.load();
for (const f of fs.readdirSync(dotDir).filter(f=>f.endsWith(".dot")).sort()) {
  if (f === "mer-general-atributos.dot") continue; // esa figura se coloca con radial.mjs
  const name=f.slice(0,-4); if (only && only!=="all" && !only.split(",").includes(name)) continue;
  const dot=fs.readFileSync(path.join(dotDir,f),"utf8");
  const engine=(dot.match(/^\/\/ layout: (\w+)/)||[])[1]||"dot";
  const t=Date.now();
  let svg;
  try { svg=gv.layout(dot,"svg",engine); } catch(e){ console.log(name,"ERROR",e.message||e); continue; }
  fs.writeFileSync(path.join(outDir,name+".svg"),svg);
  const m=svg.match(/<svg width="([\d.]+)pt" height="([\d.]+)pt"/);
  const w=parseFloat(m[1]), h=parseFloat(m[2]);
  const scale=Math.min(2, (parseFloat(maxpx)||8000)/Math.max(w,h)*0.75/0.75);
  const resvg=new Resvg(svg,{fitTo:{mode:"zoom",value:Math.min(parseFloat(process.env.ZOOMCAP||2),(parseFloat(maxpx)||8000)/(Math.max(w,h)*4/3))},font:{loadSystemFonts:false,fontFiles:["C:/Windows/Fonts/arial.ttf","C:/Windows/Fonts/arialbd.ttf"],defaultFontFamily:"Arial"},background:"white"});
  const img=resvg.render();
  fs.writeFileSync(path.join(outDir,name+".png"),img.asPng());
  console.log(name,engine,`${w}x${h}pt`,`png ${img.width}x${img.height}`,Date.now()-t,"ms");
}
