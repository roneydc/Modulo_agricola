"""Parametros do pipeline.

Fonte unica de verdade: o CLI (argparse) e a API (Pydantic) constroem
estes mesmos objetos. Se um campo mudar de nome aqui, muda nos dois.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

Indice = Literal["NDVI", "NDRE", "GNDVI", "NDWI", "TGI"]
Metodo = Literal["kmeans", "limiares", "quantis"]
Agregador = Literal["media", "mediana", "min", "max", "std"]
Estrategia = Literal["auto", "memoria", "chunked"]


@dataclass
class ParamsIndice:
    indice: Indice = "NDVI"
    sensor: str = "planet_8b"
    # faixa valida do indice; valores fora viram nodata
    v_min: float = -1.0
    v_max: float = 1.0
    normalizar: bool = False


@dataclass
class ParamsComposicao:
    """Combina 2+ rasters de indice numa camada unica."""
    agregador: Agregador = "media"
    # normalizar cada imagem antes de compor. Ver secao 3.3 do levantamento:
    # sem isso a imagem de maior amplitude domina o resultado.
    normalizar_por_imagem: bool = True
    metodo_normalizacao: Literal["minmax", "zscore"] = "minmax"
    # "intersecao": pixel so vale se valido em todas as imagens
    # "uniao": ignora NaN, exige min_observacoes
    mascara: Literal["intersecao", "uniao"] = "intersecao"
    min_observacoes: int = 1
    pesos: list[float] | None = None


@dataclass
class ParamsFiltro:
    mediana_kernel: int = 0          # 0 = desligado
    majoritario_kernel: int = 5      # aplicado depois do zoneamento
    outlier_p_inf: float | None = None
    outlier_p_sup: float | None = None


@dataclass
class ParamsZoneamento:
    metodo: Metodo = "kmeans"
    n_zonas: int = 5
    random_state: int = 0
    n_init: int = 10
    # amostra usada para o fit no modo chunked (e no modo memoria se
    # o raster for grande). None = usa todos os pixels validos.
    amostra_max: int | None = 500_000
    # percentis usados pelo metodo "limiares"
    p_inf: float = 20.0
    p_sup: float = 95.0
    # saida reclassificada em degraus regulares de 0 a 100
    padronizar_intervalo: bool = True


@dataclass
class ParamsVetorizacao:
    dissolve: bool = True
    simplify_tolerancia: float = 0.5   # unidades do CRS (metros em UTM)
    snap_tolerancia: float = 1.0
    area_minima_ha: float = 0.0        # 0 = nao remove nada
    explodir_multipart: bool = False


@dataclass
class ParamsPrescricao:
    """Regra zona -> dose. Vazio = nao gera coluna Rx."""
    doses: dict[int, float] = field(default_factory=dict)
    inversa: bool = False              # True = mais dose na zona mais fraca
    dose_min: float | None = None
    dose_max: float | None = None
    unidade: str = "kg/ha"


@dataclass
class ParamsPipeline:
    entradas: list[str] = field(default_factory=list)
    saida: str = "./out"
    estrategia: Estrategia = "auto"
    # acima deste numero de pixels, o modo auto escolhe chunked
    limiar_chunk_px: int = 40_000_000
    chunk_px: int = 2048               # lado da janela no modo chunked
    talhao: str | None = None          # shapefile/geojson de recorte

    indice: ParamsIndice = field(default_factory=ParamsIndice)
    composicao: ParamsComposicao = field(default_factory=ParamsComposicao)
    filtro: ParamsFiltro = field(default_factory=ParamsFiltro)
    zoneamento: ParamsZoneamento = field(default_factory=ParamsZoneamento)
    vetorizacao: ParamsVetorizacao = field(default_factory=ParamsVetorizacao)
    prescricao: ParamsPrescricao = field(default_factory=ParamsPrescricao)

    def to_dict(self) -> dict:
        return asdict(self)
