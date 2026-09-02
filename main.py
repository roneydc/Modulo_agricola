"""Ponto de entrada da API.

    uvicorn main:app --reload

Este arquivo so monta o app. Toda a logica esta em api/routes/, e o
processamento de imagem em processing/, que nao importa nada de FastAPI.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import dev, files, jobs, uploads
from core.config import get_settings
from storage import client as storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
_s = get_settings()

app = FastAPI(title="Zoneamento Agricola", version="0.1.0", debug=_s.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _s.debug else [],
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(uploads.router, prefix="/uploads")
app.include_router(jobs.router, prefix="/jobs")

# so no modo local: em s3 o cliente fala direto com o bucket
if _s.storage_backend == "local":
    app.include_router(files.router, prefix="/files")
    logging.getLogger(__name__).warning(
        "MODO DESENVOLVIMENTO: storage=local, celery_eager=%s. "
        "Nao usar em producao.", _s.celery_eager)


if _s.debug:
    app.include_router(dev.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "ambiente": _s.ambiente,
        "storage": _s.storage_backend,
        "fila": "eager" if _s.celery_eager else "celery",
    }
