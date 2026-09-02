#!/usr/bin/env python3
"""Simulador do navegador, etapas 4 em diante.

Fala HTTP com a API. NAO importa processing/ de proposito: se importasse,
estaria testando o cli.py com passos extras em vez da plataforma.

Quando o front-end existir, ele fara exatamente esta sequencia em JS.

    python client.py talhao.tif --zonas 5
    python client.py t1.tif t2.tif --zonas 6 --agregador media
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import httpx

# 127.0.0.1 e nao "localhost" de proposito: em muitos sistemas (Windows
# em especial) localhost resolve para ::1 primeiro, e o uvicorn com
# --host 0.0.0.0 escuta so em IPv4. O resultado e "Connection refused"
# com a API rodando normalmente.
API = "http://127.0.0.1:8000"


def enviar(c: httpx.Client, path: pathlib.Path, sensor: str) -> str:
    r = c.post("/uploads", json={
        "filename": path.name, "size": path.stat().st_size, "sensor": sensor,
    })
    r.raise_for_status()
    d = r.json()
    print(f"  {path.name}: enviando {path.stat().st_size / 1e6:.1f} MB...")
    # PUT direto no storage, sem passar pela API
    with path.open("rb") as f:
        httpx.put(d["upload_url"], content=f.read(), timeout=600).raise_for_status()
    c.post(f"/uploads/{d['arquivo_id']}/confirmar").raise_for_status()
    return d["arquivo_id"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("entradas", nargs="+")
    ap.add_argument("--api", default=API)
    ap.add_argument("--sensor", default="planet_8b")
    ap.add_argument("--indice", default="NDVI")
    ap.add_argument("--zonas", type=int, default=5)
    ap.add_argument("--agregador", default="media")
    ap.add_argument("--mediana", type=int, default=0)
    a = ap.parse_args()

    c = httpx.Client(base_url=a.api, timeout=60)
    try:
        c.get("/health").raise_for_status()
    except Exception:
        print(f"API nao respondeu em {a.api}.\n"
              "  1. suba com: uvicorn main:app --reload\n"
              "  2. se ja estiver rodando, tente --api http://127.0.0.1:8000",
              file=sys.stderr)
        return 1

    print("Upload:")
    ids = [enviar(c, pathlib.Path(e), a.sensor) for e in a.entradas]

    print("\nCriando job...")
    job = c.post("/jobs", json={
        "arquivo_ids": ids,
        "indice": {"indice": a.indice, "sensor": a.sensor},
        "composicao": {"agregador": a.agregador, "normalizar_por_imagem": True},
        "filtro": {"mediana_kernel": a.mediana, "majoritario_kernel": 5},
        "zoneamento": {"n_zonas": a.zonas, "metodo": "kmeans"},
    }).json()
    jid = job["job_id"]
    print(f"  job_id: {jid}")

    # polling. Implementado desde ja para que a migracao da etapa 4 para a
    # etapa 5 (Celery) nao mude nada neste arquivo.
    print("\nProcessando:")
    while True:
        s = c.get(f"/jobs/{jid}").json()
        print(f"\r  {s.get('etapa') or s['status']:<14} {s['progresso']:5.0%}",
              end="", flush=True)
        if s["status"] in ("done", "failed"):
            print()
            break
        time.sleep(2)

    if s["status"] == "failed":
        print(f"\nFALHOU: {s['erro']}", file=sys.stderr)
        return 1

    print(f"\nConcluido em {s['metadados']['duracao_s']}s "
          f"({s['metadados']['estrategia']})")
    for e in s["estatisticas"]:
        print(f"  zona {e['zona']:>3.0f}  {e['area_ha']:>9.2f} ha  "
              f"media {e['indice_medio']:.4f}")
    print("\nSaidas (URLs assinadas):")
    for k, v in s["saidas"].items():
        print(f"  {k:<14} {v[:80]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
