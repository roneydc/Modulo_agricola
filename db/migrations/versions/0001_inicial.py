"""schema inicial

Revision ID: 0001_inicial
Revises:
Create Date: 2026-08-28

Cria a extensao PostGIS antes de qualquer tabela com coluna Geometry.
Sem isso o CREATE TABLE falha, e o autogenerate do Alembic nao inclui
CREATE EXTENSION sozinho.
"""
from __future__ import annotations

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_inicial"
down_revision = None
branch_labels = None
depends_on = None

STATUS = ("queued", "running", "done", "failed")
TIPOS = ("indice", "composicao", "zoneamento", "vetorizacao", "completo")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    postgresql.ENUM(*STATUS, name="statusjob").create(op.get_bind(), checkfirst=True)
    postgresql.ENUM(*TIPOS, name="tipojob").create(op.get_bind(), checkfirst=True)
    # create_type=False e obrigatorio: o tipo ja foi criado acima, e sem
    # isso o create_table tenta cria-lo de novo e a migration quebra.
    status = postgresql.ENUM(*STATUS, name="statusjob", create_type=False)
    tipo = postgresql.ENUM(*TIPOS, name="tipojob", create_type=False)

    op.create_table(
        "organizacoes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nome", sa.String(200), nullable=False),
        sa.Column("criado_em", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "usuarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizacoes.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("senha_hash", sa.String(255), nullable=False),
        sa.Column("criado_em", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_usuarios_email", "usuarios", ["email"], unique=True)

    op.create_table(
        "talhoes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizacoes.id"), nullable=False),
        sa.Column("nome", sa.String(200), nullable=False),
        sa.Column("fazenda", sa.String(200)),
        sa.Column("cultura", sa.String(100)),
        sa.Column("area_ha", sa.Float()),
        sa.Column("geometria",
                  geoalchemy2.Geometry("MULTIPOLYGON", srid=4326)),
        sa.Column("criado_em", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_talhoes_org_id", "talhoes", ["org_id"])

    op.create_table(
        "arquivos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizacoes.id"), nullable=False),
        sa.Column("talhao_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("talhoes.id")),
        sa.Column("nome_original", sa.String(500), nullable=False),
        sa.Column("storage_key", sa.String(1000), nullable=False, unique=True),
        sa.Column("tamanho_bytes", sa.BigInteger(), nullable=False),
        sa.Column("largura", sa.Integer()),
        sa.Column("altura", sa.Integer()),
        sa.Column("n_bandas", sa.Integer()),
        sa.Column("crs", sa.String(100)),
        sa.Column("resolucao_m", sa.Float()),
        sa.Column("sensor", sa.String(50)),
        sa.Column("data_imagem", sa.DateTime()),
        sa.Column("criado_em", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_arquivos_org_id", "arquivos", ["org_id"])
    op.create_index("ix_arquivos_talhao_id", "arquivos", ["talhao_id"])

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizacoes.id"), nullable=False),
        sa.Column("talhao_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("talhoes.id")),
        sa.Column("tipo", tipo, nullable=False, server_default="completo"),
        sa.Column("status", status, nullable=False, server_default="queued"),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("entradas", postgresql.JSONB(), nullable=False),
        sa.Column("saidas", postgresql.JSONB()),
        sa.Column("estatisticas", postgresql.JSONB()),
        sa.Column("metadados", postgresql.JSONB()),
        sa.Column("etapa", sa.String(50)),
        sa.Column("progresso", sa.Float(), server_default="0", nullable=False),
        sa.Column("erro", sa.Text()),
        sa.Column("job_pai_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id")),
        sa.Column("criado_em", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("iniciado_em", sa.DateTime()),
        sa.Column("concluido_em", sa.DateTime()),
    )
    op.create_index("ix_jobs_org_id", "jobs", ["org_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    # o polling do front consulta jobs em andamento da org o tempo todo
    op.create_index("ix_jobs_org_status", "jobs", ["org_id", "status"])

    op.create_table(
        "zonas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("zona", sa.Integer(), nullable=False),
        sa.Column("area_ha", sa.Float(), nullable=False),
        sa.Column("indice_medio", sa.Float()),
        sa.Column("rx", sa.Float()),
        sa.Column("total_insumo", sa.Float()),
        sa.Column("geometria",
                  geoalchemy2.Geometry("MULTIPOLYGON", srid=4326), nullable=False),
    )
    op.create_index("ix_zonas_job_id", "zonas", ["job_id"])

    op.create_table(
        "perfis_rx",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizacoes.id"), nullable=False),
        sa.Column("nome", sa.String(200), nullable=False),
        sa.Column("cultura", sa.String(100)),
        sa.Column("insumo", sa.String(100)),
        sa.Column("unidade", sa.String(20), server_default="kg/ha", nullable=False),
        sa.Column("doses", postgresql.JSONB(), nullable=False),
        sa.Column("inversa", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_perfis_rx_org_id", "perfis_rx", ["org_id"])


def downgrade() -> None:
    for t in ("perfis_rx", "zonas", "jobs", "arquivos", "talhoes",
              "usuarios", "organizacoes"):
        op.drop_table(t)
    postgresql.ENUM(name="tipojob").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="statusjob").drop(op.get_bind(), checkfirst=True)
    # a extensao nao e removida: outros schemas do banco podem usa-la
