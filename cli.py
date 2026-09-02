#!/usr/bin/env python3
"""Simulador de entrada/saida do usuario, etapas 1 a 3.

Chama processing/ direto, sem HTTP, sem fila, sem banco. E a forma mais
rapida de desenvolver e depurar a logica de imagem.

Nao confundir com client.py, que fala HTTP com a API e substitui o
navegador a partir da etapa 4.

Exemplos:
    python cli.py talhao.tif --indice NDVI --zonas 5
    python cli.py t1.tif t2.tif t3.tif --agregador media --zonas 6
    python cli.py grande.tif --estrategia chunked --chunk-px 1024
    python cli.py talhao.tif --sugerir-zonas
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from processing import zoning
from processing.params import (
    ParamsComposicao, ParamsFiltro, ParamsIndice, ParamsPipeline,
    ParamsPrescricao, ParamsVetorizacao,
)
from processing.pipeline import executar
from processing.sensors import PERFIS


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Zoneamento agricola a partir de imagens multiespectrais.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("entradas", nargs="+", help="um ou mais GeoTIFF")
    p.add_argument("--saida", default="./out")

    g = p.add_argument_group("indice")
    g.add_argument("--indice", default="NDVI",
                   choices=["NDVI", "NDRE", "GNDVI", "NDWI", "TGI"])
    g.add_argument("--sensor", default="planet_8b", choices=sorted(PERFIS))
    g.add_argument("--v-min", type=float, default=-1.0)
    g.add_argument("--v-max", type=float, default=1.0)

    g = p.add_argument_group("composicao (2+ entradas)")
    g.add_argument("--agregador", default="media",
                   choices=["media", "mediana", "min", "max", "std"])
    g.add_argument("--sem-normalizar", action="store_true",
                   help="nao normaliza cada imagem antes de compor (nao recomendado)")
    g.add_argument("--mascara", default="intersecao",
                   choices=["intersecao", "uniao"])
    g.add_argument("--pesos", type=float, nargs="+")

    g = p.add_argument_group("filtros")
    g.add_argument("--mediana", type=int, default=0, help="kernel, 0 = desligado")
    g.add_argument("--majoritario", type=int, default=5)
    g.add_argument("--p-inf", type=float, default=None)
    g.add_argument("--p-sup", type=float, default=None)

    g = p.add_argument_group("zoneamento")
    g.add_argument("--zonas", type=int, default=5)
    g.add_argument("--metodo", default="kmeans",
                   choices=["kmeans", "limiares", "quantis"])
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--amostra-max", type=int, default=500_000)
    g.add_argument("--sugerir-zonas", action="store_true",
                   help="calcula silhouette para varios n e sai")

    g = p.add_argument_group("vetorizacao")
    g.add_argument("--simplify", type=float, default=0.5)
    g.add_argument("--snap", type=float, default=1.0)
    g.add_argument("--area-minima", type=float, default=0.0, help="hectares")
    g.add_argument("--talhao", help="shapefile/geojson de recorte")

    g = p.add_argument_group("prescricao")
    g.add_argument("--dose-min", type=float)
    g.add_argument("--dose-max", type=float)
    g.add_argument("--dose-inversa", action="store_true",
                   help="maior dose na zona mais fraca")
    g.add_argument("--unidade", default="kg/ha")

    g = p.add_argument_group("execucao")
    g.add_argument("--estrategia", default="auto",
                   choices=["auto", "memoria", "chunked"])
    g.add_argument("--limiar-chunk", type=int, default=40_000_000)
    g.add_argument("--chunk-px", type=int, default=2048)
    g.add_argument("-v", "--verbose", action="store_true")
    return p


def params_de_args(a) -> ParamsPipeline:
    doses = {}
    if a.dose_min is not None and a.dose_max is not None:
        from processing.prescription import escala_linear
        doses = escala_linear(list(range(1, a.zonas + 1)),
                              a.dose_min, a.dose_max, a.dose_inversa)
    return ParamsPipeline(
        entradas=a.entradas, saida=a.saida, estrategia=a.estrategia,
        limiar_chunk_px=a.limiar_chunk, chunk_px=a.chunk_px, talhao=a.talhao,
        indice=ParamsIndice(indice=a.indice, sensor=a.sensor,
                            v_min=a.v_min, v_max=a.v_max),
        composicao=ParamsComposicao(
            agregador=a.agregador,
            normalizar_por_imagem=not a.sem_normalizar,
            mascara=a.mascara, pesos=a.pesos),
        filtro=ParamsFiltro(mediana_kernel=a.mediana,
                            majoritario_kernel=a.majoritario,
                            outlier_p_inf=a.p_inf, outlier_p_sup=a.p_sup),
        zoneamento=__import__("processing.params", fromlist=["ParamsZoneamento"])
            .ParamsZoneamento(metodo=a.metodo, n_zonas=a.zonas,
                              random_state=a.seed, amostra_max=a.amostra_max),
        vetorizacao=ParamsVetorizacao(simplify_tolerancia=a.simplify,
                                      snap_tolerancia=a.snap,
                                      area_minima_ha=a.area_minima),
        prescricao=ParamsPrescricao(doses=doses, unidade=a.unidade),
    )


def barra(etapa: str, frac: float) -> None:
    n = int(frac * 24)
    print(f"\r  {etapa:<14} [{'#' * n}{'.' * (24 - n)}] {frac:5.0%}",
          end="", flush=True)
    if frac >= 1.0:
        print()


def main(argv=None) -> int:
    a = montar_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if a.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if a.sugerir_zonas:
        from processing.io import FonteRaster
        from processing.pipeline import _indice_de_fonte
        p = params_de_args(a)
        arr = _indice_de_fonte(FonteRaster(a.entradas[0], a.sensor), p)
        print(json.dumps(zoning.sugerir_n_zonas(arr), indent=2))
        return 0

    try:
        res = executar(params_de_args(a), progresso=barra)
    except Exception as e:
        print(f"\nERRO: {e}", file=sys.stderr)
        return 1

    m = res.metadados
    print(f"\nConcluido em {m['duracao_s']}s  (estrategia: {m['estrategia']})")
    print(f"{m['n_poligonos']} poligonos, {m['area_total_ha']} ha")
    print("\nZonas:")
    for e in res.estatisticas:
        print(f"  zona {e['zona']:>4.0f}  {e['area_ha']:>10.2f} ha  "
              f"indice medio {e['indice_medio']:.4f}")
    print("\nSaidas:")
    for k, v in res.saidas.items():
        print(f"  {k:<14} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
