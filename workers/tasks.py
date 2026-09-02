"""Tasks do worker.

Responsabilidade: baixar do storage, chamar processing/, subir os
resultados e atualizar o banco. Nenhuma logica de imagem mora aqui.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from celery import Celery

from core.config import get_settings
from db import models
from db.session import SessionLocal
from storage import client as storage

log = logging.getLogger(__name__)
_s = get_settings()

celery = Celery("zoneamento", broker=_s.redis_url, backend=_s.redis_url)
celery.conf.update(
    # eager = roda no processo da API, sem Redis nem worker separado.
    # Em producao vem False e o worker consome a fila normalmente.
    task_always_eager=_s.celery_eager,
    task_eager_propagates=False,
    task_track_started=True,
    task_time_limit=_s.job_timeout_s,
    task_soft_time_limit=_s.job_timeout_s - 60,
    worker_prefetch_multiplier=1,   # tasks longas: nao acumular na fila
    task_acks_late=True,
)


@celery.task(name="extrair_metadados")
def extrair_metadados(arquivo_id: str) -> dict:
    """Le o cabecalho do raster e grava os metadados. Nao processa pixels."""
    from processing.io import FonteRaster

    db = SessionLocal()
    try:
        arq = db.get(models.Arquivo, uuid.UUID(arquivo_id))
        with tempfile.TemporaryDirectory() as tmp:
            local = storage.baixar(arq.storage_key, Path(tmp) / "in.tif")
            fonte = FonteRaster(local, arq.sensor)
            info = fonte.info
        arq.largura, arq.altura = info.largura, info.altura
        arq.n_bandas = info.n_bandas
        arq.crs = info.crs
        arq.resolucao_m = info.resolucao[0]
        db.commit()
        return {"arquivo_id": arquivo_id, "n_pixels": info.n_pixels}
    finally:
        db.close()


@celery.task(name="processar", bind=True)
def processar(self, job_id: str) -> dict:
    """Pipeline completo de um job."""
    from api.schemas import JobRequest
    from processing.pipeline import executar

    db = SessionLocal()
    job = db.get(models.Job, uuid.UUID(job_id))
    if job is None:
        raise ValueError(f"Job {job_id} nao existe.")

    job.status = models.StatusJob.running
    job.iniciado_em = datetime.utcnow()
    db.commit()

    tmp = Path(tempfile.mkdtemp(prefix="zon_", dir=_s.dir_trabalho))
    try:
        # 1. baixa as entradas
        locais = []
        for aid in job.entradas:
            arq = db.get(models.Arquivo, uuid.UUID(aid))
            locais.append(storage.baixar(arq.storage_key, tmp / f"in_{aid}.tif"))

        # 2. monta os parametros e roda o pipeline
        req = JobRequest.model_validate(job.params)
        params = req.para_params(entradas=locais, saida=str(tmp / "out"))
        params.limiar_chunk_px = _s.limiar_chunk_px
        params.chunk_px = _s.chunk_px

        def progresso(etapa: str, frac: float) -> None:
            job.etapa, job.progresso = etapa, float(frac)
            db.commit()

        resultado = executar(params, progresso=progresso)

        # 3. sobe as saidas
        saidas = {}
        for nome, caminho in resultado.saidas.items():
            key = f"jobs/{job.org_id}/{job.id}/{Path(caminho).name}"
            storage.subir(caminho, key)
            saidas[nome] = key

        # 4. grava as zonas no PostGIS
        _salvar_zonas(db, job, resultado.saidas["geojson"], resultado.estatisticas)

        job.saidas = saidas
        job.estatisticas = resultado.estatisticas
        job.metadados = resultado.metadados
        job.status = models.StatusJob.done
        job.progresso = 1.0
        job.concluido_em = datetime.utcnow()
        db.commit()
        return {"job_id": job_id, "status": "done"}

    except Exception as e:
        # nunca `except: pass`. O erro precisa chegar ao usuario.
        log.exception("Job %s falhou", job_id)
        job.status = models.StatusJob.failed
        job.erro = _mensagem_limpa(e, tmp, db, job)
        job.concluido_em = datetime.utcnow()
        db.commit()
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        db.close()


def _salvar_zonas(db, job, geojson_path: str, estatisticas: list[dict]) -> None:
    import geopandas as gpd
    from geoalchemy2.shape import from_shape
    from shapely.geometry import MultiPolygon

    stats = {int(e["zona"]): e for e in estatisticas}
    gdf = gpd.read_file(geojson_path).to_crs(4326)
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom])
        z = int(row["zona"])
        db.add(models.Zona(
            job_id=job.id, zona=z,
            area_ha=float(row.get("area_ha", 0)),
            indice_medio=stats.get(z, {}).get("indice_medio"),
            rx=float(row["Rx"]) if "Rx" in row and row["Rx"] is not None else None,
            total_insumo=float(row["total_insumo"]) if "total_insumo" in row else None,
            geometria=from_shape(geom, srid=4326),
        ))
    db.commit()


def _mensagem_limpa(exc: Exception, tmp: Path, db, job) -> str:
    """Troca os caminhos temporarios internos pelo nome original do arquivo.

    Sem isso o usuario recebe "/tmp/zoneamento/zon_ab12/in_<uuid>.tif nao
    tem 8 bandas", que nao diz nada e ainda expoe a estrutura do servidor.
    """
    msg = f"{type(exc).__name__}: {exc}"
    for aid in job.entradas:
        arq = db.get(models.Arquivo, uuid.UUID(aid))
        if arq:
            msg = msg.replace(str(tmp / f"in_{aid}.tif"), arq.nome_original)
    return msg.replace(str(tmp), "").replace(str(_s.dir_trabalho), "")
