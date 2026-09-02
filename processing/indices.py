"""Indices vegetativos.

Portados do notebook, com duas correcoes:
- divisao por zero tratada sem gerar warning (np.errstate + where)
- a normalizacao do TGI usa estatisticas passadas de fora, para que o
  modo chunked produza o mesmo resultado do modo em memoria (o script
  antigo usava nanmin/nanmax do bloco atual, o que quebra em janelas)
"""
from __future__ import annotations

import numpy as np

from .sensors import PerfilSensor

# indice -> bandas necessarias
REQUISITOS: dict[str, tuple[str, ...]] = {
    "NDVI": ("red", "nir"),
    "NDRE": ("rededge", "nir"),
    "GNDVI": ("green", "nir"),
    "NDWI": ("green", "nir"),
    "TGI": ("blue", "green", "red"),
}


def bandas_necessarias(indice: str) -> tuple[str, ...]:
    if indice not in REQUISITOS:
        raise KeyError(f"Indice '{indice}' desconhecido. "
                       f"Disponiveis: {sorted(REQUISITOS)}")
    return REQUISITOS[indice]


def suportado(perfil: PerfilSensor, indice: str) -> bool:
    return perfil.tem(*bandas_necessarias(indice))


def _normalizada(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b), com NaN onde o denominador e zero."""
    soma = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(soma != 0, (a - b) / soma, np.nan)
    return out.astype(np.float32)


def ndvi(red, nir):
    return _normalizada(nir, red)


def ndre(rededge, nir):
    return _normalizada(nir, rededge)


def gndvi(green, nir):
    return _normalizada(nir, green)


def ndwi(green, nir):
    return _normalizada(green, nir)


def tgi(blue, green, red, stats: tuple[float, float] | None = None):
    """Triangular Greenness Index, normalizado min-max.

    `stats` = (min, max) globais. Obrigatorio no modo chunked; se None,
    usa as estatisticas do proprio array.
    """
    bruto = (green - 0.39 * red - 0.61 * blue).astype(np.float32)
    valido = np.isfinite(blue) & np.isfinite(green) & np.isfinite(red)
    bruto = np.where(valido, bruto, np.nan)
    if stats is None:
        vmin, vmax = float(np.nanmin(bruto)), float(np.nanmax(bruto))
    else:
        vmin, vmax = stats
    if vmax == vmin:
        return np.full_like(bruto, np.nan)
    return ((bruto - vmin) / (vmax - vmin)).astype(np.float32)


_FUNCS = {"NDVI": ndvi, "NDRE": ndre, "GNDVI": gndvi, "NDWI": ndwi, "TGI": tgi}


def calcular(indice: str, bandas: dict[str, np.ndarray],
             stats_tgi: tuple[float, float] | None = None) -> np.ndarray:
    """Despacha para a funcao do indice usando os nomes logicos das bandas."""
    nomes = bandas_necessarias(indice)
    faltando = [n for n in nomes if n not in bandas]
    if faltando:
        raise KeyError(f"{indice} precisa das bandas {faltando}, nao fornecidas.")
    args = [bandas[n] for n in nomes]
    if indice == "TGI":
        return tgi(*args, stats=stats_tgi)
    return _FUNCS[indice](*args)


def aplicar_faixa(arr: np.ndarray, v_min: float, v_max: float) -> np.ndarray:
    """Descarta valores fora da faixa fisicamente plausivel.

    O notebook fazia `img[img > 1] = nan` solto no meio do fluxo; aqui isso
    e explicito e parametrizado.
    """
    return np.where((arr >= v_min) & (arr <= v_max), arr, np.nan).astype(np.float32)


def normalizar_minmax(arr: np.ndarray,
                      stats: tuple[float, float] | None = None) -> np.ndarray:
    if stats is None:
        vmin, vmax = float(np.nanmin(arr)), float(np.nanmax(arr))
    else:
        vmin, vmax = stats
    if vmax == vmin:
        return np.full_like(arr, np.nan)
    return ((arr - vmin) / (vmax - vmin)).astype(np.float32)


def normalizar_zscore(arr: np.ndarray,
                      stats: tuple[float, float] | None = None) -> np.ndarray:
    if stats is None:
        media, desvio = float(np.nanmean(arr)), float(np.nanstd(arr))
    else:
        media, desvio = stats
    if desvio == 0:
        return np.full_like(arr, np.nan)
    return ((arr - media) / desvio).astype(np.float32)
