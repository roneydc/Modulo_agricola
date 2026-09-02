"""Schemas da API.

Os nomes dos campos espelham processing/params.py de proposito. Se
divergirem, aparece traducao manual entre as camadas e o bug vem depois.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from processing.params import (
    ParamsComposicao, ParamsFiltro, ParamsIndice, ParamsPipeline,
    ParamsPrescricao, ParamsVetorizacao, ParamsZoneamento,
)


# ---------------- upload ----------------
class UploadRequest(BaseModel):
    filename: str
    size: int
    talhao_id: uuid.UUID | None = None
    sensor: str = "planet_8b"


class UploadResponse(BaseModel):
    arquivo_id: uuid.UUID
    upload_url: str
    storage_key: str
    expira_em_s: int


class ArquivoOut(BaseModel):
    id: uuid.UUID
    nome_original: str
    largura: int | None = None
    altura: int | None = None
    n_bandas: int | None = None
    crs: str | None = None
    sensor: str | None = None
    n_pixels: int | None = None

    model_config = {"from_attributes": True}


# ---------------- jobs ----------------
class IndiceIn(BaseModel):
    indice: Literal["NDVI", "NDRE", "GNDVI", "NDWI", "TGI"] = "NDVI"
    sensor: str = "planet_8b"
    v_min: float = -1.0
    v_max: float = 1.0
    normalizar: bool = False


class ComposicaoIn(BaseModel):
    agregador: Literal["media", "mediana", "min", "max", "std"] = "media"
    normalizar_por_imagem: bool = True
    metodo_normalizacao: Literal["minmax", "zscore"] = "minmax"
    mascara: Literal["intersecao", "uniao"] = "intersecao"
    min_observacoes: int = 1
    pesos: list[float] | None = None


class FiltroIn(BaseModel):
    mediana_kernel: int = 0
    majoritario_kernel: int = 5
    outlier_p_inf: float | None = 2.0
    outlier_p_sup: float | None = 98.0


class ZoneamentoIn(BaseModel):
    metodo: Literal["kmeans", "limiares", "quantis"] = "kmeans"
    n_zonas: int = Field(5, ge=2, le=20)
    random_state: int = 0
    amostra_max: int | None = 500_000
    padronizar_intervalo: bool = True


class VetorizacaoIn(BaseModel):
    dissolve: bool = True
    simplify_tolerancia: float = 0.5
    snap_tolerancia: float = 1.0
    area_minima_ha: float = 0.0
    explodir_multipart: bool = False


class PrescricaoIn(BaseModel):
    doses: dict[int, float] = Field(default_factory=dict)
    inversa: bool = False
    dose_min: float | None = None
    dose_max: float | None = None
    unidade: str = "kg/ha"


class JobRequest(BaseModel):
    arquivo_ids: list[uuid.UUID] = Field(min_length=1)
    talhao_id: uuid.UUID | None = None
    indice: IndiceIn = Field(default_factory=IndiceIn)
    composicao: ComposicaoIn = Field(default_factory=ComposicaoIn)
    filtro: FiltroIn = Field(default_factory=FiltroIn)
    zoneamento: ZoneamentoIn = Field(default_factory=ZoneamentoIn)
    vetorizacao: VetorizacaoIn = Field(default_factory=VetorizacaoIn)
    prescricao: PrescricaoIn = Field(default_factory=PrescricaoIn)

    def para_params(self, entradas: list[str], saida: str) -> ParamsPipeline:
        """Converte o request na dataclass consumida por processing/."""
        return ParamsPipeline(
            entradas=entradas, saida=saida,
            indice=ParamsIndice(**self.indice.model_dump()),
            composicao=ParamsComposicao(**self.composicao.model_dump()),
            filtro=ParamsFiltro(**self.filtro.model_dump()),
            zoneamento=ParamsZoneamento(**self.zoneamento.model_dump()),
            vetorizacao=ParamsVetorizacao(**self.vetorizacao.model_dump()),
            prescricao=ParamsPrescricao(**self.prescricao.model_dump()),
        )


class JobOut(BaseModel):
    job_id: uuid.UUID
    status: str
    etapa: str | None = None
    progresso: float = 0.0
    erro: str | None = None
    saidas: dict | None = None
    estatisticas: list | None = None
    metadados: dict | None = None
    criado_em: datetime | None = None

    model_config = {"from_attributes": True}
