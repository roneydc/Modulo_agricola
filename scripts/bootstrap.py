#!/usr/bin/env python3
"""Cria a organizacao demo usada enquanto nao ha autenticacao.

    python scripts/bootstrap.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import uuid

from db.models import Organizacao
from db.session import SessionLocal

ORG_DEMO = uuid.UUID("00000000-0000-0000-0000-000000000001")


def main() -> None:
    db = SessionLocal()
    try:
        if db.get(Organizacao, ORG_DEMO):
            print(f"Organizacao demo ja existe: {ORG_DEMO}")
            return
        db.add(Organizacao(id=ORG_DEMO, nome="Demo"))
        db.commit()
        print(f"Organizacao demo criada: {ORG_DEMO}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
