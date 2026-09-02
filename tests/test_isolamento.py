"""Garante que as camadas nao se misturem.

Se processing/ passar a importar FastAPI ou SQLAlchemy, o modulo deixa de
ser testavel sem infraestrutura e a refatoracao futura fica travada.
"""
from __future__ import annotations

import ast
import pathlib

PROIBIDO_EM_PROCESSING = {
    "fastapi", "celery", "sqlalchemy", "boto3", "redis",
    "db", "api", "workers", "storage", "core",
}


def _imports(path: pathlib.Path) -> list[str]:
    arvore = ast.parse(path.read_text())
    out = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            out += [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom) and no.module:
            out.append(no.module)
    return out


def test_processing_nao_importa_infraestrutura():
    violacoes = []
    for f in pathlib.Path("processing").glob("*.py"):
        for m in _imports(f):
            if m.split(".")[0] in PROIBIDO_EM_PROCESSING:
                violacoes.append(f"{f.name} importa {m}")
    assert not violacoes, violacoes


def test_client_nao_importa_processing():
    """client.py substitui o navegador. Se importar processing/, deixa de
    testar a plataforma e passa a testar o cli.py com passos extras."""
    assert not [m for m in _imports(pathlib.Path("client.py")) if "processing" in m]
