"""Pagina de teste no navegador.

Registrada apenas em modo debug. E um andaime para validar o fluxo
visualmente antes de existir front-end; nao e o front-end definitivo.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

PAGINA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Zoneamento - teste</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
 body{font-family:system-ui,sans-serif;margin:0;display:flex;height:100vh}
 aside{width:340px;padding:20px;border-right:1px solid #ddd;overflow:auto}
 #mapa{flex:1}
 label{display:block;margin:12px 0 4px;font-size:13px;color:#555}
 input,select,button{width:100%;padding:8px;font-size:14px;box-sizing:border-box}
 button{margin-top:16px;background:#2c6e49;color:#fff;border:0;cursor:pointer}
 button:disabled{background:#999;cursor:wait}
 #log{margin-top:16px;font-size:12px;font-family:ui-monospace,monospace;
      white-space:pre-wrap;background:#f6f6f6;padding:10px;border-radius:4px}
 table{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px}
 td,th{border-bottom:1px solid #eee;padding:5px;text-align:left}
 a{font-size:12px;display:block;margin-top:4px}
</style></head><body>
<aside>
 <h3>Zoneamento</h3>
 <label>Arquivo GeoTIFF</label>
 <input type="file" id="arq" accept=".tif,.tiff">
 <label>Sensor</label>
 <select id="sensor">
  <option value="planet_8b">PlanetScope 8 bandas</option>
  <option value="planet_4b">PlanetScope 4 bandas</option>
  <option value="drone_multi_5b">Drone multiespectral</option>
  <option value="drone_rgb">Drone RGB</option>
  <option value="indice_pronto">Indice ja calculado</option>
 </select>
 <label>Indice</label>
 <select id="indice"><option>NDVI</option><option>NDRE</option>
  <option>GNDVI</option><option>NDWI</option><option>TGI</option></select>
 <label>Zonas</label><input type="number" id="zonas" value="5" min="2" max="20">
 <label>Mediana (0 = desligado)</label><input type="number" id="mediana" value="5">
 <button id="btn">Processar</button>
 <div id="log"></div>
 <div id="tabela"></div>
</aside>
<div id="mapa"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const mapa = L.map('mapa').setView([-10.2, -48.3], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {attribution:'OpenStreetMap'}).addTo(mapa);
let camada = null;
const log = m => document.getElementById('log').textContent += m + "\\n";
const cores = ['#d73027','#fc8d59','#fee08b','#d9ef8b','#91cf60','#1a9850',
               '#66bd63','#a6d96a','#4d9221','#276419'];

document.getElementById('btn').onclick = async () => {
  const f = document.getElementById('arq').files[0];
  if (!f) return alert('Selecione um arquivo .tif');
  const btn = document.getElementById('btn');
  btn.disabled = true;
  document.getElementById('log').textContent = '';
  document.getElementById('tabela').innerHTML = '';
  try {
    log('Solicitando URL de upload...');
    const up = await (await fetch('/uploads', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({filename:f.name, size:f.size,
                            sensor:document.getElementById('sensor').value})
    })).json();

    log('Enviando ' + (f.size/1e6).toFixed(1) + ' MB...');
    await fetch(up.upload_url, {method:'PUT', body:f});
    await fetch('/uploads/' + up.arquivo_id + '/confirmar', {method:'POST'});

    log('Criando job...');
    const job = await (await fetch('/jobs', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        arquivo_ids:[up.arquivo_id],
        indice:{indice:document.getElementById('indice').value,
                sensor:document.getElementById('sensor').value},
        filtro:{mediana_kernel:+document.getElementById('mediana').value,
                majoritario_kernel:5},
        zoneamento:{n_zonas:+document.getElementById('zonas').value}})
    })).json();

    let s;
    while (true) {
      s = await (await fetch('/jobs/' + job.job_id)).json();
      log('  ' + (s.etapa || s.status) + ' ' + Math.round(s.progresso*100) + '%');
      if (s.status === 'done' || s.status === 'failed') break;
      await new Promise(r => setTimeout(r, 1500));
    }
    if (s.status === 'failed') { log('ERRO: ' + s.erro); btn.disabled=false; return; }

    log('Concluido em ' + s.metadados.duracao_s + 's (' + s.metadados.estrategia + ')');

    const gj = await (await fetch('/jobs/' + job.job_id + '/zonas')).json();
    if (camada) mapa.removeLayer(camada);
    camada = L.geoJSON(gj, {
      style: f => ({fillColor: cores[(f.properties.zona-1) % cores.length],
                    fillOpacity:.75, color:'#333', weight:1}),
      onEachFeature: (f,l) => l.bindPopup(
        'Zona ' + f.properties.zona + '<br>' +
        f.properties.area_ha.toFixed(2) + ' ha')
    }).addTo(mapa);
    mapa.fitBounds(camada.getBounds());

    let html = '<table><tr><th>Zona</th><th>Area (ha)</th><th>Indice</th></tr>';
    s.estatisticas.forEach(e => html += '<tr><td>' + e.zona + '</td><td>' +
      e.area_ha.toFixed(2) + '</td><td>' + e.indice_medio.toFixed(4) +
      '</td></tr>');
    html += '</table>';
    for (const [k,v] of Object.entries(s.saidas))
      html += '<a href="' + v + '" download>' + k + '</a>';
    document.getElementById('tabela').innerHTML = html;
  } catch (e) { log('ERRO: ' + e); }
  btn.disabled = false;
};
</script></body></html>"""


@router.get("/", response_class=HTMLResponse)
def pagina():
    return PAGINA
