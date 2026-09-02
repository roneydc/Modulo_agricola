"""Orquestracao do pipeline.

Ponto de entrada unico, chamado tanto pelo cli.py quanto pelo worker.
Nao importa nada de FastAPI, Celery, banco ou storage.

Duas estrategias:

  memoria  - le o raster inteiro. Simples e rapido para arquivos pequenos.
  chunked  - duas passadas. A primeira amostra pixels validos varrendo o
             raster para ajustar o modelo e calcular os percentis globais;
             a segunda aplica o modelo janela por janela, escrevendo direto
             no arquivo de saida. As janelas de leitura tem overlap quando
             ha filtro de vizinhanca, senao aparecem costuras nas bordas.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import composite, filters, indices as ix, io, prescription, vectorize, zoning
from .params import ParamsPipeline

log = logging.getLogger(__name__)

Progresso = Callable[[str, float], None]


def _sem_progresso(etapa: str, frac: float) -> None:
    pass


@dataclass
class Resultado:
    saidas: dict[str, str] = field(default_factory=dict)
    estatisticas: list[dict] = field(default_factory=list)
    resumo_rx: list[dict] = field(default_factory=list)
    metadados: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "saidas": self.saidas,
            "estatisticas": self.estatisticas,
            "resumo_rx": self.resumo_rx,
            "metadados": self.metadados,
        }


# ----------------------------------------------------------------------
def escolher_estrategia(p: ParamsPipeline, fontes: list[io.FonteRaster]) -> str:
    if p.estrategia != "auto":
        return p.estrategia
    total = max(f.info.n_pixels for f in fontes)
    if len(fontes) > 1:
        # composicao exige as camadas alinhadas em memoria simultaneamente
        return "memoria"
    return "chunked" if total > p.limiar_chunk_px else "memoria"


def _indice_de_fonte(fonte: io.FonteRaster, p: ParamsPipeline,
                     janela=None, stats_tgi=None) -> np.ndarray:
    """Calcula o indice a partir das bandas, ou le a banda unica direto."""
    if fonte.perfil.nome == "indice_pronto":
        arr = fonte.ler(["value"], janela)["value"]
    else:
        nomes = ix.bandas_necessarias(p.indice.indice)
        bandas = fonte.ler(list(nomes), janela)
        arr = ix.calcular(p.indice.indice, bandas, stats_tgi=stats_tgi)
    return ix.aplicar_faixa(arr, p.indice.v_min, p.indice.v_max)


# ----------------------------------------------------------------------
def _executar_memoria(p: ParamsPipeline, fontes: list[io.FonteRaster],
                      progresso: Progresso) -> tuple[np.ndarray, np.ndarray, dict, object]:
    progresso("indice", 0.0)
    camadas, profiles = [], []
    for i, f in enumerate(fontes):
        camadas.append(_indice_de_fonte(f, p))
        with __import__("rasterio").open(f.path) as src:
            profiles.append(src.profile.copy())
        progresso("indice", (i + 1) / len(fontes))

    if len(camadas) > 1:
        progresso("composicao", 0.0)
        indice = composite.compor(camadas, profiles, p.composicao)
        progresso("composicao", 1.0)
    else:
        indice = camadas[0]

    if p.talhao:
        mascara = vectorize.mascara_talhao(p.talhao, profiles[0])
        indice = np.where(mascara, indice, np.nan).astype(np.float32)

    # ORDEM: mediana -> outliers. Precisa ser identica no modo chunked,
    # senao os dois modos ajustam o K-Means sobre distribuicoes diferentes
    # e produzem centroides diferentes para o mesmo raster.
    progresso("filtros", 0.0)
    if p.filtro.mediana_kernel > 1:
        indice = filters.mediana(indice, p.filtro.mediana_kernel)
    indice = filters.remover_outliers(
        indice, p.filtro.outlier_p_inf, p.filtro.outlier_p_sup)
    progresso("filtros", 1.0)

    progresso("zoneamento", 0.0)
    amostra = zoning.amostrar(indice, p.zoneamento.amostra_max,
                              p.zoneamento.random_state)
    modelo = zoning.ajustar(
        p.zoneamento.metodo, amostra, p.zoneamento.n_zonas,
        random_state=p.zoneamento.random_state, n_init=p.zoneamento.n_init,
        p_inf=p.zoneamento.p_inf, p_sup=p.zoneamento.p_sup,
    )
    zonas = modelo.aplicar(indice)
    if p.filtro.majoritario_kernel > 1:
        zonas = filters.majoritario(zonas, p.filtro.majoritario_kernel)
    progresso("zoneamento", 1.0)

    return indice, zonas, profiles[0], modelo


def _executar_chunked(p: ParamsPipeline, fonte: io.FonteRaster,
                      progresso: Progresso, saida_dir: Path):
    """Duas passadas sobre o raster."""
    perfil_saida = fonte.profile_saida()
    # O overlap precisa cobrir TODOS os filtros de vizinhanca aplicados
    # dentro da janela, nao so a mediana. Sem isso o majoritario produz
    # costuras nas bordas dos blocos.
    overlap = max(filters.raio_necessario(p.filtro.mediana_kernel),
                  filters.raio_necessario(p.filtro.majoritario_kernel))

    # ---- passada 1: amostragem para modelo e percentis globais ----
    progresso("amostragem", 0.0)
    # a amostragem tambem le com overlap e aplica a mediana, para que o
    # modelo seja ajustado sobre a mesma distribuicao do modo memoria
    janelas = list(fonte.janelas(p.chunk_px, overlap=overlap))
    alvo = p.zoneamento.amostra_max or 500_000
    por_janela = max(1000, alvo // max(1, len(janelas)))
    rng = np.random.default_rng(p.zoneamento.random_state)

    amostras, tgi_min, tgi_max = [], np.inf, -np.inf
    for i, (leitura, _) in enumerate(janelas):
        if fonte.perfil.nome != "indice_pronto" and p.indice.indice == "TGI":
            bandas = fonte.ler(list(ix.bandas_necessarias("TGI")), leitura)
            bruto = bandas["green"] - 0.39 * bandas["red"] - 0.61 * bandas["blue"]
            v = bruto[np.isfinite(bruto)]
            if v.size:
                tgi_min, tgi_max = min(tgi_min, v.min()), max(tgi_max, v.max())
            continue
        arr = _indice_de_fonte(fonte, p, leitura)
        if p.filtro.mediana_kernel > 1:
            arr = filters.mediana(arr, p.filtro.mediana_kernel)
        arr = fonte.recortar_overlap(arr, leitura, janelas[i][1])
        v = arr[np.isfinite(arr)]
        if v.size:
            n = min(por_janela, v.size)
            amostras.append(v[rng.choice(v.size, n, replace=False)])
        progresso("amostragem", (i + 1) / len(janelas))

    stats_tgi = None
    if p.indice.indice == "TGI" and np.isfinite(tgi_min):
        stats_tgi = (float(tgi_min), float(tgi_max))
        for i, (leitura, _) in enumerate(janelas):
            arr = _indice_de_fonte(fonte, p, leitura, stats_tgi=stats_tgi)
            v = arr[np.isfinite(arr)]
            if v.size:
                n = min(por_janela, v.size)
                amostras.append(v[rng.choice(v.size, n, replace=False)])

    if not amostras:
        raise ValueError("Nenhum pixel valido encontrado no raster.")
    amostra = np.concatenate(amostras)
    log.info("Amostra de %d pixels de %d totais.", amostra.size, fonte.info.n_pixels)

    limites_outlier = filters.limites_percentil(
        amostra, p.filtro.outlier_p_inf, p.filtro.outlier_p_sup)
    amostra = amostra[(amostra >= limites_outlier[0]) & (amostra <= limites_outlier[1])]

    modelo = zoning.ajustar(
        p.zoneamento.metodo, amostra, p.zoneamento.n_zonas,
        random_state=p.zoneamento.random_state, n_init=p.zoneamento.n_init,
        p_inf=p.zoneamento.p_inf, p_sup=p.zoneamento.p_sup,
        minibatch=amostra.size > 1_000_000,
    )

    # ---- passada 2: aplica janela por janela ----
    progresso("zoneamento", 0.0)
    path_idx = saida_dir / "indice.tif"
    path_zonas = saida_dir / "zonas.tif"
    janelas_ov = list(fonte.janelas(p.chunk_px, overlap=overlap))

    with io.EscritorJanelas(path_idx, perfil_saida) as w_idx, \
         io.EscritorJanelas(path_zonas, perfil_saida) as w_zonas:
        for i, (leitura, escrita) in enumerate(janelas_ov):
            arr = _indice_de_fonte(fonte, p, leitura, stats_tgi=stats_tgi)
            if p.filtro.mediana_kernel > 1:
                arr = filters.mediana(arr, p.filtro.mediana_kernel)
            arr = filters.remover_outliers(arr, None, None, stats=limites_outlier)
            z = modelo.aplicar(arr)
            if p.filtro.majoritario_kernel > 1:
                z = filters.majoritario(z, p.filtro.majoritario_kernel)
            w_idx.escrever(fonte.recortar_overlap(arr, leitura, escrita), escrita)
            w_zonas.escrever(fonte.recortar_overlap(z, leitura, escrita), escrita)
            progresso("zoneamento", (i + 1) / len(janelas_ov))

    return str(path_idx), str(path_zonas), modelo, perfil_saida


# ----------------------------------------------------------------------
def executar(p: ParamsPipeline, progresso: Progresso = _sem_progresso) -> Resultado:
    t0 = time.time()
    saida_dir = Path(p.saida)
    saida_dir.mkdir(parents=True, exist_ok=True)

    fontes = [io.FonteRaster(e, p.indice.sensor) for e in p.entradas]
    estrategia = escolher_estrategia(p, fontes)
    log.info("Estrategia: %s (%d pixels, %d entrada(s))",
             estrategia, fontes[0].info.n_pixels, len(fontes))

    res = Resultado()

    if estrategia == "chunked":
        path_idx, path_zonas, modelo, perfil = _executar_chunked(
            p, fontes[0], progresso, saida_dir)
        res.saidas["indice_tif"] = path_idx
        res.saidas["zonas_tif"] = path_zonas
        import rasterio
        with rasterio.open(path_zonas) as src:
            zonas = src.read(1)
            transform, crs = src.transform, src.crs
        with rasterio.open(path_idx) as src:
            indice = src.read(1)
    else:
        indice, zonas, perfil, modelo = _executar_memoria(p, fontes, progresso)
        transform, crs = perfil["transform"], perfil["crs"]
        perfil_saida = fontes[0].profile_saida()
        res.saidas["indice_tif"] = io.escrever_raster(
            saida_dir / "indice.tif", indice, perfil_saida)
        res.saidas["zonas_tif"] = io.escrever_raster(
            saida_dir / "zonas.tif", zonas, perfil_saida)

    # estatisticas antes de padronizar, para manter a referencia ao indice
    res_x, res_y = fontes[0].info.resolucao
    area_pixel_ha = (res_x * res_y) / 10_000.0
    res.estatisticas = zoning.estatisticas_por_zona(zonas, indice, area_pixel_ha)

    progresso("preview", 0.0)
    res.saidas["indice_png"] = io.salvar_preview(saida_dir / "indice.png", indice)
    res.saidas["zonas_png"] = io.salvar_preview(saida_dir / "zonas.png", zonas)
    progresso("preview", 1.0)

    progresso("vetorizacao", 0.0)
    gdf = vectorize.para_poligonos(
        zonas, transform, crs,
        dissolve=p.vetorizacao.dissolve,
        snap_tolerancia=p.vetorizacao.snap_tolerancia,
        simplify_tolerancia=p.vetorizacao.simplify_tolerancia,
        area_minima_ha=p.vetorizacao.area_minima_ha,
        explodir_multipart=p.vetorizacao.explodir_multipart,
    )
    if p.talhao:
        gdf = vectorize.recortar_por_talhao(gdf, p.talhao)
    gdf = prescription.aplicar(gdf, p.prescricao)
    progresso("vetorizacao", 1.0)

    res.saidas["shapefile"] = vectorize.exportar_shapefile(gdf, saida_dir / "zonas.shp")
    res.saidas["geojson"] = vectorize.exportar_geojson(gdf, saida_dir / "zonas.geojson")
    res.resumo_rx = prescription.resumo(gdf, p.prescricao.unidade)

    res.metadados = {
        "estrategia": estrategia,
        "n_zonas": p.zoneamento.n_zonas,
        "metodo": modelo.metodo,
        "centroides": [round(float(c), 6) for c in modelo.centroides],
        "limites": [round(float(l), 6) for l in modelo.limites],
        "random_state": p.zoneamento.random_state,
        "n_poligonos": int(len(gdf)),
        "area_total_ha": round(float(gdf["area_ha"].sum()), 3),
        "duracao_s": round(time.time() - t0, 2),
        "params": p.to_dict(),
    }

    path_meta = saida_dir / "resultado.json"
    path_meta.write_text(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
    res.saidas["metadados"] = str(path_meta)

    log.info("Concluido em %.1fs", res.metadados["duracao_s"])
    return res
