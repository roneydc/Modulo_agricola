from __future__ import annotations

import enum
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer,
    String, Text, func
)
# JSONB em vez de JSON: indexavel e com operadores nativos no Postgres.
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class StatusJob(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class TipoJob(str, enum.Enum):
    """Etapas separadas para permitir reprocessar so o que mudou.
    Trocar o numero de zonas nao deve recalcular o indice."""
    indice = "indice"
    composicao = "composicao"
    zoneamento = "zoneamento"
    vetorizacao = "vetorizacao"
    completo = "completo"


class Organizacao(Base):
    __tablename__ = "organizacoes"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    nome: Mapped[str] = mapped_column(String(200))
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizacoes.id"))
    # unique + index no mesmo campo gera um unico indice unico,
    # em vez de constraint + indice redundante
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class Talhao(Base):
    __tablename__ = "talhoes"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizacoes.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200))
    fazenda: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cultura: Mapped[str | None] = mapped_column(String(100), nullable=True)
    area_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometria = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    arquivos: Mapped[list["Arquivo"]] = relationship(back_populates="talhao")


class Arquivo(Base):
    """Raster enviado pelo usuario ou gerado pelo pipeline."""
    __tablename__ = "arquivos"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizacoes.id"), index=True)
    talhao_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("talhoes.id"), nullable=True, index=True)

    nome_original: Mapped[str] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(1000), unique=True)
    tamanho_bytes: Mapped[int] = mapped_column(BigInteger)

    # metadados extraidos na ingestao
    largura: Mapped[int | None] = mapped_column(Integer, nullable=True)
    altura: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_bandas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolucao_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    sensor: Mapped[str | None] = mapped_column(String(50), nullable=True)
    data_imagem: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    talhao: Mapped[Talhao | None] = relationship(back_populates="arquivos")

    @property
    def n_pixels(self) -> int | None:
        if self.largura and self.altura:
            return self.largura * self.altura
        return None


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_org_status", "org_id", "status"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizacoes.id"), index=True)
    talhao_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("talhoes.id"), nullable=True)

    tipo: Mapped[TipoJob] = mapped_column(Enum(TipoJob), default=TipoJob.completo)
    status: Mapped[StatusJob] = mapped_column(
        Enum(StatusJob), default=StatusJob.queued, index=True)

    # ParamsPipeline.to_dict(); garante reprodutibilidade
    params: Mapped[dict] = mapped_column(JSONB)
    entradas: Mapped[list] = mapped_column(JSONB)     # ids de Arquivo
    saidas: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    estatisticas: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    metadados: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    etapa: Mapped[str | None] = mapped_column(String(50), nullable=True)
    progresso: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)

    # permite reaproveitar a saida de um job anterior sem recalcular
    job_pai_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    iniciado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    concluido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    zonas: Mapped[list["Zona"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")


class Zona(Base):
    """Poligono de zona vetorizado, com a dose de prescricao."""
    __tablename__ = "zonas"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True)

    zona: Mapped[int] = mapped_column(Integer)
    area_ha: Mapped[float] = mapped_column(Float)
    indice_medio: Mapped[float | None] = mapped_column(Float, nullable=True)
    rx: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_insumo: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometria = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)

    job: Mapped[Job] = relationship(back_populates="zonas")


class PerfilRx(Base):
    """Tabela de doses reutilizavel, por cultura/insumo/cliente."""
    __tablename__ = "perfis_rx"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizacoes.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200))
    cultura: Mapped[str | None] = mapped_column(String(100), nullable=True)
    insumo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unidade: Mapped[str] = mapped_column(String(20), default="kg/ha")
    doses: Mapped[dict] = mapped_column(JSONB)       # {"1": 40, "2": 55, ...}
    inversa: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
