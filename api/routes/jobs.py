from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.schemas import JobOut, JobRequest
from db import models
from db.session import get_db
from storage import client as storage

router = APIRouter(tags=["jobs"])
ORG_DEMO = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post("", response_model=JobOut, status_code=202)
def criar_job(req: JobRequest, db: Session = Depends(get_db)):
    """Retorna em milissegundos. O processamento acontece no worker."""
    from workers.tasks import processar

    arquivos = [db.get(models.Arquivo, aid) for aid in req.arquivo_ids]
    if any(a is None for a in arquivos):
        raise HTTPException(404, "Um ou mais arquivos nao encontrados.")

    job = models.Job(
        org_id=ORG_DEMO, talhao_id=req.talhao_id,
        tipo=models.TipoJob.completo,
        status=models.StatusJob.queued,
        params=req.model_dump(mode="json"),
        entradas=[str(a) for a in req.arquivo_ids],
    )
    db.add(job)
    db.commit()

    processar.delay(str(job.id))
    return JobOut(job_id=job.id, status=job.status.value, criado_em=job.criado_em)


@router.get("/{job_id}", response_model=JobOut)
def obter_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job nao encontrado.")

    saidas = job.saidas
    if saidas:  # troca as chaves de storage por URLs assinadas
        saidas = {k: storage.url_download(v) for k, v in saidas.items()}

    return JobOut(
        job_id=job.id, status=job.status.value, etapa=job.etapa,
        progresso=job.progresso, erro=job.erro, saidas=saidas,
        estatisticas=job.estatisticas, metadados=job.metadados,
        criado_em=job.criado_em,
    )


@router.get("/{job_id}/zonas")
def geojson_zonas(job_id: uuid.UUID, db: Session = Depends(get_db)):
    """GeoJSON direto do PostGIS, para o mapa do front."""
    from geoalchemy2.shape import to_shape
    from shapely.geometry import mapping

    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job nao encontrado.")
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(to_shape(z.geometria)),
                "properties": {
                    "zona": z.zona, "area_ha": z.area_ha,
                    "indice_medio": z.indice_medio,
                    "Rx": z.rx, "total_insumo": z.total_insumo,
                },
            }
            for z in job.zonas
        ],
    }


@router.post("/{job_id}/reprocessar", response_model=JobOut, status_code=202)
def reprocessar(job_id: uuid.UUID, req: JobRequest, db: Session = Depends(get_db)):
    """Roda de novo com outros parametros, reaproveitando o job anterior
    como pai. Trocar o numero de zonas nao precisa recalcular o indice."""
    from workers.tasks import processar

    pai = db.get(models.Job, job_id)
    if not pai:
        raise HTTPException(404, "Job nao encontrado.")

    novo = models.Job(
        org_id=pai.org_id, talhao_id=pai.talhao_id,
        tipo=models.TipoJob.zoneamento, status=models.StatusJob.queued,
        params=req.model_dump(mode="json"), entradas=pai.entradas,
        job_pai_id=pai.id,
    )
    db.add(novo)
    db.commit()
    processar.delay(str(novo.id))
    return JobOut(job_id=novo.id, status=novo.status.value)
