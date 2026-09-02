"""Zoneamento.

Duas correcoes centrais em relacao ao notebook:

1. O predict do K-Means era um loop pixel a pixel em Python. Aqui e uma
   indexacao vetorizada. E a diferenca entre minutos e milissegundos.

2. Os labels do K-Means saem em ordem arbitraria. Sem reordenar pelo valor
   do centroide, a "zona 3" muda de significado entre execucoes e a
   prescricao fica inconsistente. `ZonificadorKMeans` sempre reordena.

O modelo e separado do fit para permitir o modo chunked: faz fit numa
amostra do raster inteiro, depois aplica predict janela por janela.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans, MiniBatchKMeans

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
def amostrar(arr: np.ndarray, n_max: int | None,
             random_state: int = 0) -> np.ndarray:
    """Amostra aleatoria dos pixels validos, achatada em 1D."""
    validos = arr[np.isfinite(arr)]
    if n_max is None or validos.size <= n_max:
        return validos
    rng = np.random.default_rng(random_state)
    idx = rng.choice(validos.size, size=n_max, replace=False)
    return validos[idx]


@dataclass
class ModeloZonas:
    """Modelo ajustado, aplicavel a qualquer janela do raster."""
    limites: np.ndarray          # fronteiras entre classes, ordenadas
    centroides: np.ndarray       # valor representativo de cada classe
    n_zonas: int
    metodo: str

    def aplicar(self, arr: np.ndarray) -> np.ndarray:
        """Classifica um array em zonas 1..n. Invalidos viram NaN."""
        valido = np.isfinite(arr)
        out = np.full(arr.shape, np.nan, dtype=np.float32)
        if not valido.any():
            return out
        # searchsorted devolve 0..n-1 ja na ordem crescente dos limites
        classe = np.searchsorted(self.limites, arr[valido], side="right")
        out[valido] = (classe + 1).astype(np.float32)
        return out


# ----------------------------------------------------------------------
def _limites_de_centroides(centroides: np.ndarray) -> np.ndarray:
    """Ponto medio entre centroides consecutivos = fronteira das classes."""
    c = np.sort(centroides.ravel())
    return (c[:-1] + c[1:]) / 2.0


def ajustar_kmeans(amostra: np.ndarray, n_zonas: int, random_state: int = 0,
                   n_init: int = 10, minibatch: bool = False) -> ModeloZonas:
    if amostra.size < n_zonas:
        raise ValueError(
            f"Apenas {amostra.size} pixels validos para {n_zonas} zonas."
        )
    X = amostra.reshape(-1, 1).astype(np.float64)
    cls = MiniBatchKMeans if minibatch else KMeans
    kw = dict(n_clusters=n_zonas, random_state=random_state, n_init=n_init)
    if minibatch:
        kw["batch_size"] = 4096
    km = cls(**kw).fit(X)
    centroides = np.sort(km.cluster_centers_.ravel())   # <- ordenacao
    return ModeloZonas(
        limites=_limites_de_centroides(centroides),
        centroides=centroides, n_zonas=n_zonas, metodo="kmeans",
    )


def ajustar_limiares(amostra: np.ndarray, n_zonas: int,
                     p_inf: float = 20.0, p_sup: float = 95.0) -> ModeloZonas:
    """Limiares lineares entre dois percentis. Metodo original do notebook."""
    v = amostra[np.isfinite(amostra)]
    vmin, vmax = float(np.percentile(v, p_inf)), float(np.percentile(v, p_sup))
    bordas = np.linspace(vmin, vmax, n_zonas + 1)
    limites = bordas[1:-1]
    centroides = (bordas[:-1] + bordas[1:]) / 2.0
    return ModeloZonas(limites=limites, centroides=centroides,
                       n_zonas=n_zonas, metodo="limiares")


def ajustar_quantis(amostra: np.ndarray, n_zonas: int) -> ModeloZonas:
    """Zonas de area equivalente."""
    v = amostra[np.isfinite(amostra)]
    qs = np.linspace(0, 100, n_zonas + 1)
    bordas = np.percentile(v, qs)
    limites = bordas[1:-1]
    centroides = (bordas[:-1] + bordas[1:]) / 2.0
    return ModeloZonas(limites=limites, centroides=centroides,
                       n_zonas=n_zonas, metodo="quantis")


def ajustar(metodo: str, amostra: np.ndarray, n_zonas: int,
            random_state: int = 0, n_init: int = 10,
            p_inf: float = 20.0, p_sup: float = 95.0,
            minibatch: bool = False) -> ModeloZonas:
    if metodo == "kmeans":
        return ajustar_kmeans(amostra, n_zonas, random_state, n_init, minibatch)
    if metodo == "limiares":
        return ajustar_limiares(amostra, n_zonas, p_inf, p_sup)
    if metodo == "quantis":
        return ajustar_quantis(amostra, n_zonas)
    raise KeyError(f"Metodo de zoneamento '{metodo}' desconhecido.")


# ----------------------------------------------------------------------
def padronizar_intervalo(zonas: np.ndarray, n_zonas: int) -> np.ndarray:
    """Reclassifica 1..n para degraus regulares de 0 a 100.

    A versao do notebook reclassificava em loop sobre o proprio array, de
    modo que um valor ja convertido podia ser convertido de novo na
    iteracao seguinte. Aqui a conversao e feita de uma vez, por LUT.
    """
    if n_zonas < 2:
        return zonas
    novos = np.linspace(0, 100, n_zonas)
    lut = np.concatenate([[np.nan], novos]).astype(np.float32)  # index 0 = NaN
    idx = np.where(np.isfinite(zonas), zonas, 0).astype(np.int32)
    idx = np.clip(idx, 0, n_zonas)
    return lut[idx]


def estatisticas_por_zona(zonas: np.ndarray, valores: np.ndarray,
                          area_pixel_ha: float) -> list[dict]:
    """Area e estatisticas do indice em cada zona."""
    out = []
    for z in np.unique(zonas[np.isfinite(zonas)]):
        m = zonas == z
        v = valores[m & np.isfinite(valores)]
        out.append({
            "zona": float(z),
            "pixels": int(m.sum()),
            "area_ha": round(float(m.sum() * area_pixel_ha), 4),
            "indice_medio": float(np.mean(v)) if v.size else None,
            "indice_min": float(np.min(v)) if v.size else None,
            "indice_max": float(np.max(v)) if v.size else None,
        })
    return out


def sugerir_n_zonas(amostra: np.ndarray, candidatos=(3, 4, 5, 6, 7, 8),
                    random_state: int = 0, n_amostra: int = 20_000) -> dict:
    """Silhouette para cada n candidato. Item 5.9 do levantamento."""
    from sklearn.metrics import silhouette_score
    v = amostrar(amostra, n_amostra, random_state).reshape(-1, 1)
    scores = {}
    for n in candidatos:
        if v.shape[0] <= n:
            continue
        km = KMeans(n_clusters=n, random_state=random_state, n_init=5).fit(v)
        scores[n] = float(silhouette_score(v, km.labels_))
    return {"scores": scores,
            "melhor": max(scores, key=scores.get) if scores else None}
