from __future__ import annotations

import numpy as np
import pytest
import rasterio

from processing import filters, indices as ix, vectorize, zoning
from processing.params import (
    ParamsFiltro, ParamsIndice, ParamsPipeline, ParamsZoneamento,
)
from processing.pipeline import executar
from scripts.gerar_teste import gerar


@pytest.fixture(scope="module")
def raster(tmp_path_factory):
    d = tmp_path_factory.mktemp("dados")
    return gerar(str(d / "t.tif"), lado=300, sensor="planet_8b", seed=1)


@pytest.fixture(scope="module")
def rasters_temporais(tmp_path_factory):
    d = tmp_path_factory.mktemp("temporais")
    return [gerar(str(d / f"t{i}.tif"), lado=250, seed=i) for i in range(1, 4)]


# ---------------- indices ----------------
def test_ndvi_faixa_valida():
    red = np.array([[0.2, 0.4]], dtype=np.float32)
    nir = np.array([[0.6, 0.5]], dtype=np.float32)
    r = ix.ndvi(red, nir)
    assert np.all((r >= -1) & (r <= 1))


def test_ndvi_divisao_por_zero_vira_nan():
    z = np.zeros((2, 2), dtype=np.float32)
    assert np.isnan(ix.ndvi(z, z)).all()


def test_aplicar_faixa_descarta_fora():
    a = np.array([[-2.0, 0.5, 3.0]], dtype=np.float32)
    r = ix.aplicar_faixa(a, -1, 1)
    assert np.isnan(r[0, 0]) and r[0, 1] == 0.5 and np.isnan(r[0, 2])


# ---------------- zoneamento ----------------
def test_classes_ordenadas_por_centroide():
    """Regressao: os labels do KMeans sao arbitrarios. Se a ordenacao
    quebrar, a zona N deixa de significar a mesma coisa entre execucoes."""
    rng = np.random.default_rng(0)
    a = rng.normal(0.5, 0.15, (200, 200)).astype(np.float32)
    m = zoning.ajustar_kmeans(zoning.amostrar(a, None), 5)
    assert np.all(np.diff(m.centroides) > 0)
    z = m.aplicar(a)
    medias = [a[z == k].mean() for k in range(1, 6)]
    assert medias == sorted(medias)


def test_modelo_reprodutivel():
    rng = np.random.default_rng(1)
    a = rng.normal(0.5, 0.2, (150, 150)).astype(np.float32)
    s = zoning.amostrar(a, None)
    m1 = zoning.ajustar_kmeans(s, 4, random_state=42)
    m2 = zoning.ajustar_kmeans(s, 4, random_state=42)
    np.testing.assert_allclose(m1.centroides, m2.centroides)


def test_padronizar_intervalo_nao_reconverte():
    """Regressao do bug do notebook: reclassificar em loop sobre o proprio
    array fazia valores ja convertidos serem convertidos de novo."""
    z = np.array([[1, 2, 3], [4, 5, np.nan]], dtype=np.float32)
    r = zoning.padronizar_intervalo(z, 5)
    validos = r[np.isfinite(r)]
    assert len(np.unique(validos)) == 5
    assert validos.min() == 0 and validos.max() == 100
    assert np.isnan(r[1, 2])


def test_zoneamento_falha_com_poucos_pixels():
    with pytest.raises(ValueError):
        zoning.ajustar_kmeans(np.array([0.1, 0.2], dtype=np.float32), 5)


# ---------------- filtros ----------------
def test_mediana_preserva_nan():
    a = np.ones((20, 20), dtype=np.float32)
    a[5, 5] = np.nan
    r = filters.mediana(a, 3)
    assert np.isnan(r[5, 5])
    assert np.isfinite(r[0, 0])


def test_majoritario_remove_ruido_isolado():
    a = np.ones((30, 30), dtype=np.float32)
    a[15, 15] = 5.0
    r = filters.majoritario(a, 5)
    assert r[15, 15] == 1.0


def test_raio_overlap():
    assert filters.raio_necessario(1) == 0
    assert filters.raio_necessario(5) == 3


# ---------------- pipeline ----------------
def _params(entrada, saida, **kw) -> ParamsPipeline:
    z = ParamsZoneamento(n_zonas=kw.pop("n_zonas", 4))
    return ParamsPipeline(
        entradas=entrada if isinstance(entrada, list) else [entrada],
        saida=str(saida),
        indice=ParamsIndice(sensor=kw.pop("sensor", "planet_8b")),
        filtro=ParamsFiltro(mediana_kernel=kw.pop("mediana", 5)),
        zoneamento=z, **kw,
    )


def test_pipeline_memoria(raster, tmp_path):
    res = executar(_params(raster, tmp_path / "m"))
    assert res.metadados["estrategia"] == "memoria"
    assert len(res.estatisticas) == 4
    for chave in ("indice_tif", "zonas_tif", "shapefile", "geojson"):
        assert chave in res.saidas


def test_zonas_ordenadas_no_resultado(raster, tmp_path):
    res = executar(_params(raster, tmp_path / "o"))
    medias = [e["indice_medio"] for e in res.estatisticas]
    assert medias == sorted(medias), "zona N deve ter indice medio crescente"


def test_chunked_equivalente_a_memoria(raster, tmp_path):
    """As duas estrategias devem convergir. A diferenca residual vem da
    amostragem do KMeans, nao de costura entre janelas."""
    m = executar(_params(raster, tmp_path / "m", estrategia="memoria"))
    c = executar(_params(raster, tmp_path / "c", estrategia="chunked",
                         chunk_px=100))
    with rasterio.open(m.saidas["zonas_tif"]) as s:
        zm = s.read(1)
    with rasterio.open(c.saidas["zonas_tif"]) as s:
        zc = s.read(1)
    v = np.isfinite(zm) & np.isfinite(zc)
    assert (zm[v] == zc[v]).mean() > 0.90


def test_chunked_sem_costura(raster, tmp_path):
    """Tamanhos de bloco diferentes devem dar praticamente o mesmo
    resultado. Se divergirem, o overlap esta errado."""
    a = executar(_params(raster, tmp_path / "a", estrategia="chunked", chunk_px=64))
    b = executar(_params(raster, tmp_path / "b", estrategia="chunked", chunk_px=256))
    with rasterio.open(a.saidas["zonas_tif"]) as s:
        za = s.read(1)
    with rasterio.open(b.saidas["zonas_tif"]) as s:
        zb = s.read(1)
    v = np.isfinite(za) & np.isfinite(zb)
    assert (za[v] == zb[v]).mean() > 0.95


def test_composicao_multitemporal(rasters_temporais, tmp_path):
    res = executar(_params(rasters_temporais, tmp_path / "comp", n_zonas=3))
    assert len(res.estatisticas) == 3
    assert res.metadados["area_total_ha"] > 0


def test_composicao_normalizada_nao_e_dominada(rasters_temporais):
    """Sem normalizar, a imagem de maior amplitude domina a media."""
    import rasterio as rio
    from processing import composite, io
    from processing.params import ParamsComposicao
    from processing.pipeline import _indice_de_fonte

    p = ParamsPipeline(indice=ParamsIndice())
    arrs, profs = [], []
    for path in rasters_temporais:
        arrs.append(_indice_de_fonte(io.FonteRaster(path, "planet_8b"), p))
        with rio.open(path) as s:
            profs.append(s.profile.copy())
    arrs[1] = arrs[1] * 0.2   # datas com amplitudes muito diferentes
    arrs[2] = arrs[2] * 0.2

    com = composite.compor(arrs, profs, ParamsComposicao(normalizar_por_imagem=True))
    sem = composite.compor(arrs, profs, ParamsComposicao(normalizar_por_imagem=False))
    v = np.isfinite(com) & np.isfinite(sem) & np.isfinite(arrs[0])
    corr_com = abs(np.corrcoef(com[v], arrs[0][v])[0, 1])
    corr_sem = abs(np.corrcoef(sem[v], arrs[0][v])[0, 1])
    assert corr_sem > corr_com


def test_area_total_bate_com_pixels(raster, tmp_path):
    res = executar(_params(raster, tmp_path / "area"))
    soma_zonas = sum(e["area_ha"] for e in res.estatisticas)
    assert abs(soma_zonas - res.metadados["area_total_ha"]) / soma_zonas < 0.05


def test_prescricao(raster, tmp_path):
    from processing.params import ParamsPrescricao
    from processing.prescription import escala_linear

    p = _params(raster, tmp_path / "rx")
    p.prescricao = ParamsPrescricao(
        doses=escala_linear([1, 2, 3, 4], 40, 80), unidade="kg/ha")
    res = executar(p)
    assert res.resumo_rx
    doses = [l["Rx"] for l in res.resumo_rx]
    assert min(doses) >= 40 and max(doses) <= 80


def test_sensor_errado_da_erro_claro(raster):
    from processing.io import FonteRaster
    with pytest.raises(ValueError, match="bandas"):
        FonteRaster(raster, "indice_pronto")  # 8 bandas lidas como 1
