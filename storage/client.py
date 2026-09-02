"""Abstracao do object storage.

Dois backends com a mesma interface:

  local - grava em disco. As "presigned URLs" apontam para a rota /files
          da propria API. Serve para desenvolver sem MinIO nem R2.
  s3    - R2, S3, MinIO, B2. O upload vai direto do cliente para o
          storage, sem passar pela API.

A escolha e por STORAGE_BACKEND no .env. O resto do codigo nao muda.
"""
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import quote

from core.config import get_settings

_s = get_settings()


class Storage(ABC):
    @abstractmethod
    def url_upload(self, key: str, ttl: int | None = None) -> str: ...

    @abstractmethod
    def url_download(self, key: str, ttl: int | None = None) -> str: ...

    @abstractmethod
    def baixar(self, key: str, destino: str | Path) -> str: ...

    @abstractmethod
    def subir(self, origem: str | Path, key: str) -> str: ...

    @abstractmethod
    def existe(self, key: str) -> bool: ...


class StorageLocal(Storage):
    """Disco local. Nao usar em producao: nao escala horizontalmente,
    porque cada worker so enxerga o proprio disco."""

    def __init__(self, raiz: str | Path, base_url: str):
        self.raiz = Path(raiz).resolve()
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/")

    def _caminho(self, key: str) -> Path:
        # impede que uma key com ../ escape da raiz
        destino = (self.raiz / key).resolve()
        if not str(destino).startswith(str(self.raiz)):
            raise ValueError(f"Key invalida: {key}")
        return destino

    def url_upload(self, key: str, ttl: int | None = None) -> str:
        return f"{self.base_url}/files/{quote(key)}"

    def url_download(self, key: str, ttl: int | None = None) -> str:
        return f"{self.base_url}/files/{quote(key)}"

    def baixar(self, key: str, destino: str | Path) -> str:
        origem = self._caminho(key)
        if not origem.exists():
            raise FileNotFoundError(f"Nao encontrado no storage: {key}")
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, destino)
        return str(destino)

    def subir(self, origem: str | Path, key: str) -> str:
        destino = self._caminho(key)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, destino)
        return key

    def gravar_bytes(self, key: str, dados: bytes) -> str:
        destino = self._caminho(key)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados)
        return key

    def caminho_local(self, key: str) -> Path:
        return self._caminho(key)

    def existe(self, key: str) -> bool:
        return self._caminho(key).exists()


class StorageS3(Storage):
    def __init__(self):
        import boto3
        from botocore.config import Config

        self.bucket = _s.s3_bucket
        self.cli = boto3.client(
            "s3",
            endpoint_url=_s.s3_endpoint or None,
            aws_access_key_id=_s.s3_access_key,
            aws_secret_access_key=_s.s3_secret_key,
            region_name=_s.s3_region,
            config=Config(signature_version="s3v4"),
        )

    def url_upload(self, key: str, ttl: int | None = None) -> str:
        return self.cli.generate_presigned_url(
            "put_object", Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl or _s.presign_ttl_s)

    def url_download(self, key: str, ttl: int | None = None) -> str:
        return self.cli.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl or _s.presign_ttl_s)

    def baixar(self, key: str, destino: str | Path) -> str:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        self.cli.download_file(self.bucket, key, str(destino))
        return str(destino)

    def subir(self, origem: str | Path, key: str) -> str:
        self.cli.upload_file(str(origem), self.bucket, key)
        return key

    def existe(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.cli.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False


_instancia: Storage | None = None


def get_storage() -> Storage:
    global _instancia
    if _instancia is None:
        if _s.storage_backend == "local":
            _instancia = StorageLocal(_s.storage_dir, _s.base_url)
        else:
            _instancia = StorageS3()
    return _instancia


# atalhos, para o codigo chamador nao precisar do get_storage()
def url_upload(key: str, ttl: int | None = None) -> str:
    return get_storage().url_upload(key, ttl)


def url_download(key: str, ttl: int | None = None) -> str:
    return get_storage().url_download(key, ttl)


def baixar(key: str, destino: str | Path) -> str:
    return get_storage().baixar(key, destino)


def subir(origem: str | Path, key: str) -> str:
    return get_storage().subir(origem, key)


def existe(key: str) -> bool:
    return get_storage().existe(key)
