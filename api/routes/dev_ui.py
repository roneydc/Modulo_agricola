"""Pagina de teste servida pela propria API.

Nao e o front-end definitivo: e o minimo para conferir no navegador se o
zoneamento saiu certo, sem abrir QGIS. Faz a mesma sequencia do client.py,
so que em JavaScript.

Registrada apenas quando debug=True.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

PAGINA = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zoneamento — teste</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  body{margin:0;font:14px system-ui,sans-serif;display:flex;height:100vh}
  #painel{width:340px;padding:16px;overflow:auto;border-right:1px solid #ddd;box-sizing:border-box}
  #mapa{flex:1}
  h1{font-size:16px;font-weight:600;margin:0 0 16px}
  label{display:block;margin:10px 0 4px;font-size:12px;color:#555}
  input,select{width:100%;padding:6px;box-sizing:border-box;border:1px solid #ccc;border-radius:4px}
  button{margin-top:16px;width:100%;padding:10px;border:0;border-radius:4px;
         background:#2d6a4f;color:#fff;font-size:14px;cursor:pointer}
  button:disabled{background:#999;cursor:not-allowed}
  #status{margin-top:12px;padding:10px;background:#f4f4f4;border-radius:4px;
          font-size:12px;white-space:pre-wrap;min-height:20px}
  table{width:100%;border-collapse:collapse;margin-top:12px;font-size:12px}
  th,td{text-align:left;padding:4px;border-bottom:1px solid #eee}
  .sw{display:inline-block;width:12px;height:12px;border-radius:2px;vertical-align:middle}
  a{color:#2d6a4f;font-size:12px;display:block;margin-top:4px}
</style>
</head>
<body>
<div id="painel">
  <h1>Zoneamento — teste</h1>
  <label>Arquivo GeoTIFF</label>
  <input type="file" id="arquivo" accept=".tif,.tiff">
  <label>Sensor</label>
  <select id="sensor">
    <option value="planet_8b">PlanetScope 8 bandas</option>
    <option value="planet_4b">PlanetScope 4 bandas</option>
    <option value="drone_multi_5b">Drone multiespectral 5b</option>
    <option value="drone_rgb">Drone RGB</option>
    <option value="indice_pronto">Índice pronto (1 banda)</option>
  </select>
  <label>Índice</label>
  <select id="indice">
    <option>NDVI</option><option>NDRE</option><option>GNDVI</option>
    <option>NDWI</option><option>TGI</option>
  </select>
  <label>Zonas</label>
  <input type="number" id="zonas" value="5" min="2" max="20">
  <label>Filtro de mediana (0 = desligado)</label>
  <input type="number" id="mediana" value="5" min="0" max="31">
  <button id="rodar">Processar</button>
  <div id="status"></div>
  <div id="resultado"></div>
</div>
<div id="mapa"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const API = window.location.origin;
const mapa = L.map('mapa').setView([-10.2, -48.33], 12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {attribution:'OpenStreetMap', maxZoom:19}).addTo(mapa);
let camada = null;

const log = t => document.getElementById('status').textContent = t;
const CORES = ['#a50026','#f46d43','#fee08b','#a6d96a','#1a9850',
               '#006837','#66bd63','#d9ef8b','#fdae61','#d73027'];
const cor = (z,n) => CORES[Math.floor((z-1)/Math.max(n-1,1)*(CORES.length-1))];

document.getElementById('rodar').onclick = async () => {
  const f = document.getElementById('arquivo').files[0];
  if (!f) { log('Selecione um arquivo.'); return; }
  const btn = document.getElementById('rodar');
  btn.disabled = true;
  document.getElementById('resultado').innerHTML = '';
  try {
    log('Enviando ' + (f.size/1e6).toFixed(1) + ' MB...');
    const sensor = document.getElementById('sensor').value;
    let r = await fetch(API + '/uploads', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({filename:f.name, size:f.size, sensor})
    });
    if (!r.ok) throw new Error(await r.text());
    const up = await r.json();

    await fetch(up.upload_url, {method:'PUT', body:f});
    await fetch(API + '/uploads/' + up.arquivo_id + '/confirmar', {method:'POST'});

    log('Criando job...');
    const zonas = +document.getElementById('zonas').value;
    r = await fetch(API + '/jobs', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        arquivo_ids:[up.arquivo_id],
        indice:{indice:document.getElementById('indice').value, sensor},
        filtro:{mediana_kernel:+document.getElementById('mediana').value,
                majoritario_kernel:5},
        zoneamento:{n_zonas:zonas, metodo:'kmeans'}
      })
    });
    if (!r.ok) throw new Error(await r.text());
    const job = await r.json();

    let s;
    while (true) {                       // mesmo polling do client.py
      s = await (await fetch(API + '/jobs/' + job.job_id)).json();
      log((s.etapa || s.status) + '  ' + Math.round(s.progresso*100) + '%');
      if (s.status === 'done' || s.status === 'failed') break;
      await new Promise(r => setTimeout(r, 1500));
    }
    if (s.status === 'failed') throw new Error(s.erro);

    log('Concluído em ' + s.metadados.duracao_s + 's (' + s.metadados.estrategia + ')');

    const gj = await (await fetch(API + '/jobs/' + job.job_id + '/zonas')).json();
    if (camada) mapa.removeLayer(camada);
    camada = L.geoJSON(gj, {
      style: x => ({fillColor: cor(x.properties.zona, zonas), color:'#333',
                    weight:1, fillOpacity:0.75}),
      onEachFeature: (x,l) => l.bindPopup(
        'Zona ' + x.properties.zona + '<br>' +
        x.properties.area_ha.toFixed(2) + ' ha' +
        (x.properties.Rx ? '<br>Rx: ' + x.properties.Rx : ''))
    }).addTo(mapa);
    mapa.fitBounds(camada.getBounds());

    let html = '<table><tr><th></th><th>Zona</th><th>Área (ha)</th><th>Índice</th></tr>';
    for (const e of s.estatisticas)
      html += '<tr><td><span class="sw" style="background:' + cor(e.zona,zonas) +
              '"></span></td><td>' + e.zona + '</td><td>' + e.area_ha.toFixed(2) +
              '</td><td>' + e.indice_medio.toFixed(4) + '</td></tr>';
    html += '</table>';
    for (const [k,v] of Object.entries(s.saidas))
      html += '<a href="' + v + '" download>' + k + '</a>';
    document.getElementById('resultado').innerHTML = html;
  } catch (e) {
    log('ERRO: ' + e.message);
  } finally {
    btn.disabled = false;
  }
};
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGINA
