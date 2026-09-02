from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ambiente: str = "dev"
    debug: bool = True

    database_url: str = "postgresql+psycopg://zon:zon@localhost:5432/zoneamento"
    redis_url: str = "redis://localhost:6379/0"

    base_url: str = "http://127.0.0.1:8000"

    # "local" grava em disco e serve pela rota /files, sem MinIO nem R2.
    # "s3" usa R2/S3/MinIO/B2.
    storage_backend: str = "local"
    storage_dir: str = "./.storage"

    # executa as tasks no proprio processo, sem Redis nem worker separado.
    # So para desenvolvimento: bloqueia a request ate terminar.
    celery_eager: bool = True

    # storage S3-compatible (R2, MinIO, B2, S3)
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "zoneamento"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "auto"
    presign_ttl_s: int = 3600

    # limites de processamento
    limiar_chunk_px: int = 40_000_000
    chunk_px: int = 2048
    max_upload_mb: int = 4096
    job_timeout_s: int = 3600

    dir_trabalho: str = "/tmp/zoneamento"

    jwt_secret: str = "trocar-em-producao"
    jwt_ttl_min: int = 60 * 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
