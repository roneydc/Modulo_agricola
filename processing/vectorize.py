"""Raster classificado -> poligonos.

Correcoes em relacao ao notebook:
- `unary_union` esta deprecado no Shapely 2, trocado por `union_all`
- geometrias invalidas sao reparadas antes do dissolve
- area em hectares calculada em CRS metrico
- remocao de poligonos abaixo da area minima
"""
from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import shapely
from rasterio.features import shapes
from shapely.geometry import shape

log = logging.getLogger(__name__)


def para_poligonos(zonas: np.ndarray, transform, crs,
                   dissolve: bool = True,
                   snap_tolerancia: float = 1.0,
                   simplify_tolerancia: float = 0.5,
                   area_minima_ha: float = 0.0,
                   explodir_multipart: bool = False) -> gpd.GeoDataFrame:
    valido = np.isfinite(zonas)
    if not valido.any():
        raise ValueError("Raster de zonas sem pixels validos para vetorizar.")

    # shapes() nao aceita float32 com NaN; converte para inteiro
    inteiro = np.where(valido, zonas, -1).astype(np.int32)

    geoms, valores = [], []
    for geom, valor in shapes(inteiro, mask=valido, transform=transform):
        if valor is None or int(valor) < 0:
            continue
        geoms.append(shape(geom))
        valores.append(int(valor))

    gdf = gpd.GeoDataFrame({"zona": valores, "geometry": geoms}, crs=crs)
    gdf["geometry"] = gdf.geometry.make_valid()
    gdf = gdf[~gdf.geometry.is_empty]

    if dissolve:
        gdf = gdf.dissolve(by="zona").reset_index()

    #if snap_tolerancia > 0 and len(gdf) > 1:
        # O notebook fazia snap(geom, unary_union(tudo), tol) para cada
        # geometria. Isso e O(n*m) e domina o tempo total: 38s contra 0.2s
        # num raster de 600x600. set_precision arredonda os vertices para
        # uma grade comum, resolvendo os slivers com o mesmo efeito.
    #    gdf["geometry"] = shapely.set_precision(
    #        gdf.geometry.values, snap_tolerancia)
    #    gdf = gdf[~gdf.geometry.is_empty]

    #if simplify_tolerancia > 0:
    #    gdf["geometry"] = gdf.geometry.simplify(
    #        simplify_tolerancia, preserve_topology=True)

    #gdf["geometry"] = gdf.geometry.make_valid()

    #if explodir_multipart:
    #    gdf = gdf.explode(index_parts=False).reset_index(drop=True)

    gdf["area_ha"] = _area_ha(gdf)

    if area_minima_ha > 0:
        antes = len(gdf)
        gdf = gdf[gdf["area_ha"] >= area_minima_ha].reset_index(drop=True)
        if len(gdf) < antes:
            log.info("Removidos %d poligonos abaixo de %.2f ha.",
                     antes - len(gdf), area_minima_ha)

    return gdf.reset_index(drop=True)


def _area_ha(gdf: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Area em hectares. Reprojeta para UTM se o CRS for geografico."""
    if gdf.crs is None:
        raise ValueError("GeoDataFrame sem CRS; nao da para calcular area.")
    if gdf.crs.is_geographic:
        utm = gdf.estimate_utm_crs()
        return gdf.to_crs(utm).geometry.area / 10_000.0
    return gdf.geometry.area / 10_000.0


# ----------------------------------------------------------------------
def exportar_shapefile(gdf: gpd.GeoDataFrame, path: str | Path) -> str:
    """Escreve o .shp e zipa os arquivos irmaos."""
    import shutil
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    nome = path.stem
    with tempfile.TemporaryDirectory() as tmp:
        gdf.to_file(Path(tmp) / f"{nome}.shp", driver="ESRI Shapefile")
        zip_base = str(path.with_suffix(""))
        shutil.make_archive(zip_base, "zip", tmp)
    return f"{zip_base}.zip"


def exportar_geojson(gdf: gpd.GeoDataFrame, path: str | Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # GeoJSON exige EPSG:4326
    gdf.to_crs(4326).to_file(path, driver="GeoJSON")
    return str(path)


def recortar_por_talhao(gdf: gpd.GeoDataFrame,
                        talhao_path: str) -> gpd.GeoDataFrame:
    talhao = gpd.read_file(talhao_path).to_crs(gdf.crs)
    return gpd.clip(gdf, talhao).reset_index(drop=True)


def mascara_talhao(talhao_path: str, profile: dict) -> np.ndarray:
    """Mascara booleana do talhao no grid do raster."""
    from rasterio.features import geometry_mask
    talhao = gpd.read_file(talhao_path).to_crs(profile["crs"])
    return ~geometry_mask(
        talhao.geometry, out_shape=(profile["height"], profile["width"]),
        transform=profile["transform"], invert=False,
    )
