"""Leitura e escrita de rasters.

Diferencas em relacao ao script antigo:
- nao carrega todas as bandas na memoria no __init__
- le apenas as bandas necessarias, ja em float32
- guarda o profile enquanto o arquivo esta aberto (o script usava
  src.transform depois do bloco `with`, o que funciona por acidente)
- escreve COG com overviews, nao GeoTIFF simples
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window

from .sensors import PerfilSensor, get_perfil, inferir_perfil

log = logging.getLogger(__name__)

NODATA = np.float32(np.nan)


@dataclass
class InfoRaster:
    path: str
    largura: int
    altura: int
    n_bandas: int
    crs: str | None
    transform: object
    dtype: str
    nodata: float | None
    resolucao: tuple[float, float]

    @property
    def n_pixels(self) -> int:
        return self.largura * self.altura

    @property
    def crs_metrico(self) -> bool:
        if self.crs is None:
            return False
        return not rasterio.crs.CRS.from_string(self.crs).is_geographic


class FonteRaster:
    """Acesso a um GeoTIFF sem carregar tudo em memoria."""

    def __init__(self, path: str | Path, perfil: PerfilSensor | str | None = None):
        self.path = str(path)
        with rasterio.open(self.path) as src:
            self._profile = src.profile.copy()
            self.info = InfoRaster(
                path=self.path,
                largura=src.width,
                altura=src.height,
                n_bandas=src.count,
                crs=str(src.crs) if src.crs else None,
                transform=src.transform,
                dtype=str(src.dtypes[0]),
                nodata=src.nodata,
                resolucao=(abs(src.transform.a), abs(src.transform.e)),
            )
        if perfil is None:
            self.perfil = inferir_perfil(self.info.n_bandas)
        elif isinstance(perfil, str):
            self.perfil = get_perfil(perfil)
        else:
            self.perfil = perfil
        self._validar()

    def _validar(self) -> None:
        if self.info.crs is None:
            raise ValueError(f"{self.path}: raster sem CRS definido.")
        # Contagem exata, nao apenas "cabe". Um arquivo de 8 bandas lido com
        # o perfil 'indice_pronto' passaria silenciosamente e produziria a
        # banda 1 do Planet tratada como NDVI, sem nenhum aviso.
        if self.perfil.n_bandas != self.info.n_bandas:
            raise ValueError(
                f"{self.path}: perfil '{self.perfil.nome}' espera "
                f"{self.perfil.n_bandas} bandas, arquivo tem "
                f"{self.info.n_bandas}. Verifique o sensor selecionado."
            )

    # ------------------------------------------------------------------
    def ler(self, nomes: list[str], janela: Window | None = None) -> dict[str, np.ndarray]:
        """Le apenas as bandas pedidas, em float32, com nodata como NaN."""
        idx = [self.perfil.indice_banda(n) for n in nomes]
        with rasterio.open(self.path) as src:
            arrays = src.read(idx, window=janela, masked=True)
        out = {}
        for nome, arr in zip(nomes, arrays):
            a = arr.filled(np.nan).astype(np.float32)
            out[nome] = a
        return out

    def janelas(self, lado: int = 2048, overlap: int = 0) -> Iterator[tuple[Window, Window]]:
        """Gera (janela_leitura, janela_escrita).

        A janela de leitura e expandida pelo overlap para que filtros de
        vizinhanca nao produzam costuras nas bordas dos blocos. A janela de
        escrita e a regiao util, sem a borda.
        """
        W, H = self.info.largura, self.info.altura
        for top in range(0, H, lado):
            for left in range(0, W, lado):
                w = min(lado, W - left)
                h = min(lado, H - top)
                escrita = Window(left, top, w, h)
                if overlap <= 0:
                    yield escrita, escrita
                    continue
                l0 = max(0, left - overlap)
                t0 = max(0, top - overlap)
                l1 = min(W, left + w + overlap)
                t1 = min(H, top + h + overlap)
                leitura = Window(l0, t0, l1 - l0, t1 - t0)
                yield leitura, escrita

    @staticmethod
    def recortar_overlap(arr: np.ndarray, leitura: Window, escrita: Window) -> np.ndarray:
        """Corta o resultado da janela de leitura para a regiao util."""
        dy = int(escrita.row_off - leitura.row_off)
        dx = int(escrita.col_off - leitura.col_off)
        return arr[dy:dy + int(escrita.height), dx:dx + int(escrita.width)]

    def profile_saida(self, count: int = 1, dtype: str = "float32") -> dict:
        p = self._profile.copy()
        p.update(
            driver="GTiff", count=count, dtype=dtype, nodata=np.nan,
            tiled=True, blockxsize=512, blockysize=512,
            compress="deflate", predictor=2, BIGTIFF="IF_SAFER",
        )
        return p


# ----------------------------------------------------------------------
def escrever_raster(path: str | Path, array: np.ndarray, profile: dict,
                    overviews: bool = True) -> str:
    """Escreve um GeoTIFF tiled com overviews (COG na pratica)."""
    path = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    p = profile.copy()
    p.update(height=array.shape[0], width=array.shape[1], count=1,
             dtype=array.dtype.name)
    with rasterio.open(path, "w", **p) as dst:
        dst.write(array, 1)
        if overviews:
            dst.build_overviews([2, 4, 8, 16], Resampling.average)
            dst.update_tags(ns="rio_overview", resampling="average")
    return path


class EscritorJanelas:
    """Escrita incremental por janela, para o modo chunked."""

    def __init__(self, path: str | Path, profile: dict):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._profile = profile
        self._dst = None

    def __enter__(self):
        self._dst = rasterio.open(self.path, "w", **self._profile)
        return self

    def escrever(self, array: np.ndarray, janela: Window) -> None:
        self._dst.write(array.astype(self._profile["dtype"]), 1, window=janela)

    def __exit__(self, *exc):
        if self._dst is not None:
            if exc[0] is None:
                self._dst.build_overviews([2, 4, 8, 16], Resampling.average)
                self._dst.update_tags(ns="rio_overview", resampling="average")
            self._dst.close()
        return False


def salvar_preview(path: str | Path, array: np.ndarray,
                   cmap: str = "RdYlGn", max_lado: int = 1200) -> str:
    """PNG de previsualizacao. Substitui a classe Visualizar do notebook,
    que dependia de matplotlib interativo."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    a = array
    passo = max(1, max(a.shape) // max_lado)
    a = a[::passo, ::passo]
    finitos = a[np.isfinite(a)]
    if finitos.size == 0:
        raise ValueError("Array sem pixels validos para preview.")
    plt.imsave(path, a, cmap=cmap,
               vmin=float(np.nanmin(finitos)), vmax=float(np.nanmax(finitos)))
    return path
