"""Composicao de 2 ou mais rasters de indice numa camada unica.

O ponto critico e a normalizacao por imagem antes de agregar. NDVI de
estadios fenologicos diferentes tem faixas de valor diferentes; a media
direta faz a imagem de maior amplitude dominar o resultado, e o zoneamento
passa a refletir a data em vez do potencial produtivo do talhao.
Por isso `normalizar_por_imagem` vem ligado por padrao.
"""
from __future__ import annotations

import logging

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from . import indices as ix
from .params import ParamsComposicao

log = logging.getLogger(__name__)

_AGREGADORES = {
    "media": np.nanmean,
    "mediana": np.nanmedian,
    "min": np.nanmin,
    "max": np.nanmax,
    "std": np.nanstd,
}


def alinhar(arrays: list[np.ndarray], profiles: list[dict],
            ref: int = 0) -> list[np.ndarray]:
    """Reamostra todos os arrays para o grid do array de referencia.

    Se todos ja compartilham CRS, transform e shape, nao faz nada.
    """
    p_ref = profiles[ref]
    alvo_shape = (p_ref["height"], p_ref["width"])
    saida = []
    for arr, p in zip(arrays, profiles):
        mesmo = (
            arr.shape == alvo_shape
            and p["transform"] == p_ref["transform"]
            and p["crs"] == p_ref["crs"]
        )
        if mesmo:
            saida.append(arr.astype(np.float32))
            continue
        log.info("Reamostrando raster para o grid de referencia.")
        destino = np.full(alvo_shape, np.nan, dtype=np.float32)
        reproject(
            source=arr, destination=destino,
            src_transform=p["transform"], src_crs=p["crs"],
            dst_transform=p_ref["transform"], dst_crs=p_ref["crs"],
            src_nodata=np.nan, dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        saida.append(destino)
    return saida


def _normalizar(arrays: list[np.ndarray], metodo: str) -> list[np.ndarray]:
    out = []
    for a in arrays:
        v = a[np.isfinite(a)]
        if v.size == 0:
            out.append(a)
            continue
        if metodo == "zscore":
            out.append(ix.normalizar_zscore(a, (float(v.mean()), float(v.std()))))
        else:
            out.append(ix.normalizar_minmax(a, (float(v.min()), float(v.max()))))
    return out


def compor(arrays: list[np.ndarray], profiles: list[dict],
           params: ParamsComposicao) -> np.ndarray:
    """Alinha, normaliza e agrega. Devolve uma camada unica."""
    if len(arrays) == 1:
        return arrays[0].astype(np.float32)

    arrays = alinhar(arrays, profiles)

    if params.normalizar_por_imagem:
        arrays = _normalizar(arrays, params.metodo_normalizacao)
    else:
        log.warning(
            "Compondo sem normalizar por imagem. Se as datas tiverem "
            "amplitudes diferentes, o resultado tende a refletir a imagem "
            "de maior amplitude."
        )

    pilha = np.stack(arrays)   # (n, H, W)

    if params.pesos:
        if len(params.pesos) != len(arrays):
            raise ValueError(
                f"{len(params.pesos)} pesos para {len(arrays)} imagens."
            )
        if params.agregador != "media":
            raise ValueError("Pesos so se aplicam ao agregador 'media'.")
        w = np.asarray(params.pesos, dtype=np.float32)[:, None, None]
        valido = np.isfinite(pilha)
        soma_w = np.where(valido, w, 0).sum(axis=0)
        soma_v = np.where(valido, np.nan_to_num(pilha) * w, 0).sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            resultado = np.where(soma_w > 0, soma_v / soma_w, np.nan)
    else:
        fn = _AGREGADORES[params.agregador]
        with np.errstate(invalid="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                resultado = fn(pilha, axis=0)

    n_validos = np.isfinite(pilha).sum(axis=0)
    if params.mascara == "intersecao":
        exigido = pilha.shape[0]
    else:
        exigido = max(1, params.min_observacoes)
    resultado = np.where(n_validos >= exigido, resultado, np.nan)

    return resultado.astype(np.float32)


def estabilidade_temporal(arrays: list[np.ndarray],
                          profiles: list[dict]) -> np.ndarray:
    """Coeficiente de variacao entre datas. Zonas com CV alto sao instaveis
    e merecem tratamento diferente das estaveis. Item 3.9 do levantamento."""
    arrays = alinhar(arrays, profiles)
    pilha = np.stack(arrays)
    with np.errstate(invalid="ignore", divide="ignore"):
        media = np.nanmean(pilha, axis=0)
        desvio = np.nanstd(pilha, axis=0)
        cv = np.where(media != 0, desvio / np.abs(media), np.nan)
    return cv.astype(np.float32)
