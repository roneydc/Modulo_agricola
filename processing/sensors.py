"""Perfis de sensor.

Resolve o problema dos indices de banda hardcoded do script antigo
(bandas[5], bandas[7]). Cada perfil mapeia nome logico -> indice 1-based.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PerfilSensor:
    nome: str
    n_bandas: int
    bandas: dict[str, int]      # nome logico -> indice 1-based no GeoTIFF
    descricao: str = ""

    def indice_banda(self, nome: str) -> int:
        if nome not in self.bandas:
            raise KeyError(
                f"O perfil '{self.nome}' nao tem a banda '{nome}'. "
                f"Disponiveis: {sorted(self.bandas)}"
            )
        return self.bandas[nome]

    def tem(self, *nomes: str) -> bool:
        return all(n in self.bandas for n in nomes)


PERFIS: dict[str, PerfilSensor] = {
    "planet_8b": PerfilSensor(
        nome="planet_8b",
        n_bandas=8,
        bandas={
            "coastal": 1, "blue": 2, "green_i": 3, "green": 4,
            "yellow": 5, "red": 6, "rededge": 7, "nir": 8,
        },
        descricao="PlanetScope SuperDove 8 bandas",
    ),
    "planet_4b": PerfilSensor(
        nome="planet_4b",
        n_bandas=4,
        bandas={"blue": 1, "green": 2, "red": 3, "nir": 4},
        descricao="PlanetScope 4 bandas",
    ),
    "drone_multi_5b": PerfilSensor(
        nome="drone_multi_5b",
        n_bandas=5,
        bandas={"blue": 1, "green": 2, "red": 3, "rededge": 4, "nir": 5},
        descricao="Drone multiespectral (MicaSense / Altum)",
    ),
    "drone_rgb": PerfilSensor(
        nome="drone_rgb",
        n_bandas=3,
        bandas={"red": 1, "green": 2, "blue": 3},
        descricao="Drone RGB",
    ),
    "sentinel2_4b": PerfilSensor(
        nome="sentinel2_4b",
        n_bandas=4,
        bandas={"blue": 1, "green": 2, "red": 3, "nir": 4},
        descricao="Sentinel-2 subset 10m",
    ),
    "indice_pronto": PerfilSensor(
        nome="indice_pronto",
        n_bandas=1,
        bandas={"value": 1},
        descricao="Raster de banda unica com o indice ja calculado",
    ),
}


def get_perfil(nome: str) -> PerfilSensor:
    if nome not in PERFIS:
        raise KeyError(
            f"Perfil de sensor '{nome}' desconhecido. "
            f"Disponiveis: {sorted(PERFIS)}"
        )
    return PERFIS[nome]


def perfil_customizado(nome: str, bandas: dict[str, int]) -> PerfilSensor:
    """Perfil montado pelo usuario na UI."""
    return PerfilSensor(
        nome=nome, n_bandas=max(bandas.values()), bandas=dict(bandas),
        descricao="Customizado",
    )


def inferir_perfil(n_bandas: int) -> PerfilSensor:
    """Palpite pelo numero de bandas. Usado so como sugestao na ingestao;
    a escolha final e sempre do usuario."""
    padrao = {1: "indice_pronto", 3: "drone_rgb", 4: "planet_4b",
              5: "drone_multi_5b", 8: "planet_8b"}
    if n_bandas not in padrao:
        raise ValueError(
            f"Nao foi possivel inferir o sensor para {n_bandas} bandas. "
            "Informe o perfil explicitamente."
        )
    return PERFIS[padrao[n_bandas]]
