"""Prescricao (Rx): zona -> dose.

No notebook isso era uma funcao `regra()` com degraus fixos de 10 em 10,
recompilada a cada mudanca. Aqui e uma tabela parametrizavel, que na
plataforma vira um perfil salvo por cultura/insumo/cliente.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np

from .params import ParamsPrescricao


def aplicar(gdf: gpd.GeoDataFrame, params: ParamsPrescricao) -> gpd.GeoDataFrame:
    """Adiciona a coluna Rx com a dose de cada zona."""
    if not params.doses:
        return gdf

    zonas = sorted(gdf["zona"].unique())
    doses = dict(params.doses)

    if params.inversa:
        # inverte o mapeamento: a zona mais fraca recebe a maior dose
        valores = [doses[z] for z in zonas if z in doses]
        doses = dict(zip(zonas, reversed(valores)))

    faltando = [z for z in zonas if z not in doses]
    if faltando:
        raise ValueError(
            f"Sem dose definida para as zonas {faltando}. "
            f"Zonas presentes: {zonas}"
        )

    gdf = gdf.copy()
    gdf["Rx"] = gdf["zona"].map(doses).astype(float)

    if params.dose_min is not None:
        gdf["Rx"] = gdf["Rx"].clip(lower=params.dose_min)
    if params.dose_max is not None:
        gdf["Rx"] = gdf["Rx"].clip(upper=params.dose_max)

    gdf["total_insumo"] = (gdf["Rx"] * gdf["area_ha"]).round(2)
    return gdf


def escala_linear(zonas: list[int], dose_min: float, dose_max: float,
                  inversa: bool = False) -> dict[int, float]:
    """Gera uma tabela de doses linear entre dois extremos.

    Atalho para o caso mais comum, evitando digitar zona a zona.
    """
    z = sorted(zonas)
    valores = np.linspace(dose_min, dose_max, len(z))
    if inversa:
        valores = valores[::-1]
    return {int(k): float(round(v, 2)) for k, v in zip(z, valores)}


def ajustar_para_total(gdf: gpd.GeoDataFrame, total_alvo: float) -> gpd.GeoDataFrame:
    """Reescala as doses para que o consumo total bata com um valor definido.

    Util quando o produtor ja comprou uma quantidade fixa de insumo.
    Item 9.6 do levantamento.
    """
    if "Rx" not in gdf.columns:
        raise ValueError("Aplique a prescricao antes de ajustar o total.")
    atual = float((gdf["Rx"] * gdf["area_ha"]).sum())
    if atual == 0:
        raise ValueError("Consumo total atual e zero; nao da para reescalar.")
    fator = total_alvo / atual
    gdf = gdf.copy()
    gdf["Rx"] = (gdf["Rx"] * fator).round(2)
    gdf["total_insumo"] = (gdf["Rx"] * gdf["area_ha"]).round(2)
    return gdf


def resumo(gdf: gpd.GeoDataFrame, unidade: str = "kg/ha") -> list[dict]:
    """Tabela por zona para relatorio e CSV."""
    cols = ["zona", "area_ha"]
    if "Rx" in gdf.columns:
        cols += ["Rx", "total_insumo"]
    agg = gdf.groupby("zona").agg(
        area_ha=("area_ha", "sum"),
        **({"Rx": ("Rx", "first"),
            "total_insumo": ("total_insumo", "sum")} if "Rx" in gdf.columns else {})
    ).reset_index()
    agg["area_ha"] = agg["area_ha"].round(3)
    linhas = agg.to_dict("records")
    for l in linhas:
        l["unidade"] = unidade
    return linhas
