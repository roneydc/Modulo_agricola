"""Rota /files.

Equivalente local das presigned URLs. No modo storage_backend=local, o
PUT e o GET desta rota fazem o papel que o R2 ou o S3 fariam.

Em producao (storage_backend=s3) esta rota nao e registrada: o cliente
fala direto com o bucket e a API nunca ve os bytes.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from core.config import get_settings
from storage.client import StorageLocal, get_storage

router = APIRouter(tags=["files"])
_s = get_settings()

TIPOS = {
    ".tif": "image/tiff", ".tiff": "image/tiff",
    ".png": "image/png", ".json": "application/json",
    ".geojson": "application/geo+json", ".zip": "application/zip",
}


def _local() -> StorageLocal:
    st = get_storage()
    if not isinstance(st, StorageLocal):
        raise HTTPException(404, "Rota disponivel apenas no storage local.")
    return st


@router.put("/{key:path}")
async def enviar(key: str, request: Request):
    """Recebe os bytes. No modo s3 o cliente faria este PUT direto no
    bucket, sem passar por aqui."""
    st = _local()
    dados = await request.body()
    if not dados:
        raise HTTPException(400, "Corpo vazio.")
    if len(dados) > _s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Acima de {_s.max_upload_mb} MB.")
    st.gravar_bytes(key, dados)
    return {"key": key, "bytes": len(dados)}


@router.get("/{key:path}")
def baixar(key: str):
    st = _local()
    try:
        caminho = st.caminho_local(key)
    except ValueError:
        raise HTTPException(400, "Key invalida.")
    if not caminho.exists():
        raise HTTPException(404, "Arquivo nao encontrado.")
    return FileResponse(
        caminho,
        media_type=TIPOS.get(caminho.suffix.lower(), "application/octet-stream"),
        filename=caminho.name,
    )
