"""Testes de banco.

Precisam de um Postgres com PostGIS. Rodam se DATABASE_URL_TEST estiver
definida, senao sao pulados. Assim `pytest tests/` continua funcionando
sem infraestrutura nenhuma.

    DATABASE_URL_TEST=postgresql+psycopg://zon:zon@localhost:5432/zoneamento \
      pytest tests/test_db.py -v
"""
from __future__ import annotations

import os
import uuid

import pytest

URL = os.getenv("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(not URL, reason="DATABASE_URL_TEST nao definida")


@pytest.fixture(scope="module")
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(URL)
    s = sessionmaker(bind=engine)()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def org(db):
    from db import models
    o = models.Organizacao(id=uuid.uuid4(), nome="Teste")
    db.add(o)
    db.commit()
    yield o
    db.query(models.Organizacao).filter_by(id=o.id).delete()
    db.commit()


def test_postgis_habilitado(db):
    from sqlalchemy import text
    v = db.execute(text("SELECT postgis_version()")).scalar()
    assert v


def test_indices_espaciais_existem(db):
    from sqlalchemy import text
    nomes = {r[0] for r in db.execute(text(
        "SELECT indexname FROM pg_indexes WHERE indexdef LIKE '%gist%'"))}
    assert "idx_zonas_geometria" in nomes
    assert "idx_talhoes_geometria" in nomes


def test_ciclo_job_com_zonas(db, org):
    """Grava zonas reais vindas do pipeline e le de volta como GeoJSON."""
    import geopandas as gpd
    from geoalchemy2.shape import from_shape, to_shape
    from shapely.geometry import MultiPolygon

    from db import models
    from processing.params import ParamsFiltro, ParamsPipeline, ParamsZoneamento
    from processing.pipeline import executar
    from scripts.gerar_teste import gerar

    import tempfile
    tmp = tempfile.mkdtemp()
    raster = gerar(f"{tmp}/t.tif", lado=200, seed=7)
    res = executar(ParamsPipeline(
        entradas=[raster], saida=f"{tmp}/out",
        filtro=ParamsFiltro(mediana_kernel=5),
        zoneamento=ParamsZoneamento(n_zonas=3),
    ))

    job = models.Job(
        id=uuid.uuid4(), org_id=org.id, params={}, entradas=[],
        status=models.StatusJob.done, metadados=res.metadados,
        estatisticas=res.estatisticas,
    )
    db.add(job)
    db.commit()

    gdf = gpd.read_file(res.saidas["geojson"]).to_crs(4326)
    for _, row in gdf.iterrows():
        g = row.geometry
        if g.geom_type == "Polygon":
            g = MultiPolygon([g])
        db.add(models.Zona(
            id=uuid.uuid4(), job_id=job.id, zona=int(row["zona"]),
            area_ha=float(row["area_ha"]), geometria=from_shape(g, srid=4326),
        ))
    db.commit()

    db.refresh(job)
    assert len(job.zonas) == 3
    assert all(to_shape(z.geometria).is_valid for z in job.zonas)
    assert sum(z.area_ha for z in job.zonas) > 0

    # JSONB permite consultar dentro do campo
    from sqlalchemy import text
    n = db.execute(text(
        "SELECT (metadados->>'n_zonas')::int FROM jobs WHERE id = :i"),
        {"i": str(job.id)}).scalar()
    assert n == 3

    # o cascade precisa levar as zonas junto
    job_id = job.id
    db.delete(job)
    db.commit()
    assert db.query(models.Zona).filter_by(job_id=job_id).count() == 0


def test_area_calculada_pelo_postgis_bate(db, org):
    """A area do PostGIS em CRS metrico deve bater com a calculada no
    geopandas. Se divergir, ha problema de projecao em algum lado."""
    from geoalchemy2.shape import from_shape
    from shapely.geometry import MultiPolygon, box
    from sqlalchemy import text

    from db import models

    job = models.Job(id=uuid.uuid4(), org_id=org.id, params={}, entradas=[])
    db.add(job)
    # quadrado de ~1km de lado perto de Palmas
    poly = MultiPolygon([box(-48.36, -10.20, -48.3509, -10.2090)])
    z = models.Zona(id=uuid.uuid4(), job_id=job.id, zona=1, area_ha=0,
                    geometria=from_shape(poly, srid=4326))
    db.add(z)
    db.commit()

    ha = db.execute(text(
        "SELECT ST_Area(ST_Transform(geometria, 31982)) / 10000 "
        "FROM zonas WHERE id = :i"), {"i": str(z.id)}).scalar()
    assert 90 < ha < 110    # ~1km x 1km = 100 ha

    db.delete(job)
    db.commit()
