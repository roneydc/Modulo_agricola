from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.schemas import ArquivoOut, UploadRequest, UploadResponse
from core.config import get_settings
from db import models
from db.session import get_db
from storage import client as storage

router = APIRouter(tags=["uploads"])
_s = get_settings()

ORG_DEMO = uuid.UUID("00000000-0000-0000-0000-000000000001")  # TODO: auth real


@router.post("", response_model=UploadResponse)
def criar_upload(req: UploadRequest, db: Session = Depends(get_db)):
    """Devolve uma presigned URL. Os bytes vao direto para o storage,
    sem passar pela API."""
    if req.size > _s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Arquivo acima de {_s.max_upload_mb} MB.")
    if not req.filename.lower().endswith((".tif", ".tiff")):
        raise HTTPException(415, "Apenas GeoTIFF (.tif/.tiff).")

    arquivo_id = uuid.uuid4()
    key = f"uploads/{ORG_DEMO}/{arquivo_id}/{req.filename}"
    arq = models.Arquivo(
        id=arquivo_id, org_id=ORG_DEMO, talhao_id=req.talhao_id,
        nome_original=req.filename, storage_key=key,
        tamanho_bytes=req.size, sensor=req.sensor,
    )
    db.add(arq)
    db.commit()
    return UploadResponse(
        arquivo_id=arquivo_id, upload_url=storage.url_upload(key),
        storage_key=key, expira_em_s=_s.presign_ttl_s,
    )


@router.post("/{arquivo_id}/confirmar", response_model=ArquivoOut)
def confirmar(arquivo_id: uuid.UUID, db: Session = Depends(get_db)):
    """Chamado depois do PUT no storage. Le os metadados do raster e valida."""
    from workers.tasks import extrair_metadados
    arq = db.get(models.Arquivo, arquivo_id)
    if not arq:
        raise HTTPException(404, "Arquivo nao encontrado.")
    if not storage.existe(arq.storage_key):
        raise HTTPException(409, "Upload ainda nao concluido no storage.")
    extrair_metadados.delay(str(arquivo_id))
    return arq


@router.get("/{arquivo_id}", response_model=ArquivoOut)
def obter(arquivo_id: uuid.UUID, db: Session = Depends(get_db)):
    arq = db.get(models.Arquivo, arquivo_id)
    if not arq:
        raise HTTPException(404, "Arquivo nao encontrado.")
    return arq
