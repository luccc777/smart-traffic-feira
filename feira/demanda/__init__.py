"""Demanda do cenario `aberta.maquete` - a implementacao do contrato C2.

`GeradorDemandaAberta` escreve, por seed: o `.rou.xml`, o manifesto versionado e
o `.sumocfg` daquela seed (ver `config_seed.py` - sem ele a Arena sobe a MESMA
demanda para toda seed, e em silencio). `Malha` e a leitura de rede que ele usa
(sumolib, sem TraCI).

Nada aqui importa `sim`, `traci` ou `torch`. Precisa de `sumolib` (que vem com o
SUMO) e do `.net.xml` da rede aberta em disco - o entregavel de
`sumo/aberta/build_rede_aberta.py`.
"""
from .aberta import VERSAO, GeradorDemandaAberta
from .config_seed import (
    ConfigDaSeedAusente,
    caminho_config_seed,
    confere_config_seed,
    escreve_config_seed,
    sumocfg_da_seed,
)
from .malha import Caminho, Malha

__all__ = [
    "GeradorDemandaAberta", "Malha", "Caminho", "VERSAO",
    "sumocfg_da_seed", "caminho_config_seed", "escreve_config_seed",
    "confere_config_seed", "ConfigDaSeedAusente",
]
