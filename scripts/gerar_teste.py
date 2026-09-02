#!/usr/bin/env python3
"""Gera GeoTIFF sinteticos para desenvolvimento, sem precisar de dados reais.

    python scripts/gerar_teste.py --saida /tmp/t1.tif --lado 800
    python scripts/gerar_teste.py --saida /tmp/grande.tif --lado 7000
"""
from __future__ import annotations

import argparse

import numpy as np
import rasterio
from rasterio.transform import from_origin


def gerar(path: str, lado: int = 800, sensor: str = "planet_8b",
          seed: int = 0, res: float = 3.0) -> str:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:lado, 0:lado].astype(np.float32) / lado

    # padrao espacial com gradiente, manchas e ruido
    base = (0.55 + 0.30 * np.sin(3 * np.pi * x) * np.cos(2 * np.pi * y)
            + 0.12 * y + rng.normal(0, 0.03, (lado, lado)))
    base = np.clip(base, 0.05, 0.95).astype(np.float32)

    nir = base
    red = np.clip(nir * (1 - base) * 0.9 + 0.05, 0.01, 0.99).astype(np.float32)
    green = np.clip(red * 1.25, 0.01, 0.99).astype(np.float32)
    blue = np.clip(red * 0.85, 0.01, 0.99).astype(np.float32)
    rededge = np.clip((nir + red) / 2, 0.01, 0.99).astype(np.float32)

    # buraco de nodata simulando area fora do talhao
    cx, cy = lado // 4, lado // 3
    r = lado // 12
    yy, xx = np.ogrid[:lado, :lado]
    buraco = (yy - cy) ** 2 + (xx - cx) ** 2 < r * r

    mapa = {
        "planet_8b": [red * 0.7, blue, green * 0.9, green, green * 1.1,
                      red, rededge, nir],
        "planet_4b": [blue, green, red, nir],
        "drone_multi_5b": [blue, green, red, rededge, nir],
        "drone_rgb": [red, green, blue],
        "indice_pronto": [(nir - red) / (nir + red)],
    }
    bandas = mapa[sensor]
    bandas = [np.where(buraco, np.nan, b).astype(np.float32) for b in bandas]

    perfil = dict(
        driver="GTiff", height=lado, width=lado, count=len(bandas),
        dtype="float32", crs="EPSG:31982",           # SIRGAS 2000 / UTM 22S
        transform=from_origin(700000, 8900000, res, res),
        nodata=np.nan, tiled=True, blockxsize=256, blockysize=256,
        compress="deflate",
    )
    with rasterio.open(path, "w", **perfil) as dst:
        for i, b in enumerate(bandas, start=1):
            dst.write(b, i)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", required=True)
    ap.add_argument("--lado", type=int, default=800)
    ap.add_argument("--sensor", default="planet_8b")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    p = gerar(a.saida, a.lado, a.sensor, a.seed)
    print(f"{p}  ({a.lado}x{a.lado}, {a.lado**2:,} px, sensor {a.sensor})")
