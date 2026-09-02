"""Filtros de pre e pos-processamento.

O filtro de mediana do notebook zerava os NaN antes de filtrar, o que puxa
as bordas do talhao para baixo. Aqui os NaN sao preservados e o filtro
ignora os invalidos.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter, generic_filter


def raio_necessario(kernel: int) -> int:
    """Overlap minimo entre janelas para este kernel nao gerar costura."""
    return 0 if kernel <= 1 else kernel // 2 + 1


def mediana(arr: np.ndarray, kernel: int) -> np.ndarray:
    """Filtro de mediana preservando a mascara de invalidos."""
    if kernel <= 1:
        return arr
    invalido = ~np.isfinite(arr)
    if invalido.all():
        return arr
    # preenche temporariamente com a mediana global para nao arrastar
    # as bordas, filtra, e devolve os NaN ao lugar
    preenchido = np.where(invalido, np.nanmedian(arr), arr)
    suave = median_filter(preenchido, size=kernel, mode="nearest")
    return np.where(invalido, np.nan, suave).astype(np.float32)


def _moda(valores: np.ndarray) -> float:
    v = valores[np.isfinite(valores)]
    if v.size == 0:
        return np.nan
    unicos, contagem = np.unique(v, return_counts=True)
    return float(unicos[np.argmax(contagem)])


def majoritario(arr: np.ndarray, kernel: int) -> np.ndarray:
    """Filtro de moda. Remove o ruido sal-e-pimenta do raster classificado.

    Existia comentado no notebook. E lento com generic_filter; para kernels
    pequenos e classes poucas, a versao por contagem de mascaras e melhor.
    """
    if kernel <= 1:
        return arr
    classes = np.unique(arr[np.isfinite(arr)])
    if classes.size == 0 or classes.size > 64:
        return generic_filter(arr, _moda, size=kernel, mode="nearest")

    from scipy.ndimage import uniform_filter
    contagens = np.stack([
        uniform_filter((arr == c).astype(np.float32), size=kernel, mode="nearest")
        for c in classes
    ])
    vencedor = classes[np.argmax(contagens, axis=0)]
    return np.where(np.isfinite(arr), vencedor, np.nan).astype(np.float32)


def remover_outliers(arr: np.ndarray, p_inf: float | None, p_sup: float | None,
                     stats: tuple[float, float] | None = None) -> np.ndarray:
    """Corta as caudas por percentil.

    `stats` = (limite_inf, limite_sup) ja calculados. Obrigatorio no modo
    chunked, onde nao da para calcular percentil do array inteiro.
    """
    if p_inf is None and p_sup is None:
        return arr
    if stats is not None:
        lo, hi = stats
    else:
        validos = arr[np.isfinite(arr)]
        if validos.size == 0:
            return arr
        lo = np.percentile(validos, p_inf) if p_inf is not None else -np.inf
        hi = np.percentile(validos, p_sup) if p_sup is not None else np.inf
    return np.where((arr >= lo) & (arr <= hi), arr, np.nan).astype(np.float32)


def limites_percentil(amostra: np.ndarray, p_inf: float | None,
                      p_sup: float | None) -> tuple[float, float]:
    v = amostra[np.isfinite(amostra)]
    lo = float(np.percentile(v, p_inf)) if p_inf is not None else float("-inf")
    hi = float(np.percentile(v, p_sup)) if p_sup is not None else float("inf")
    return lo, hi
