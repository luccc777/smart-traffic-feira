"""Motor do modo jogo: máquina de estados da rodada, fantasmas e placar.

Ninguém aqui importa `serial`, `torch` ou `traci` no topo — a rodada de teclado
tem que subir num ambiente sem hardware, e o pacote `sim` congela configuração
no import (a armadilha do C1). Os imports pesados moram dentro das funções.
"""
from .estado import ControladorSelado, SeloDivergente, cenario_da_seed, selo_t0
from .fantasmas import ColetorDeSerie, Fantasmaria, TarefaFantasma
from .motor import ROTULOS, MotorDoJogo, ResultadoRodada, RodadaAbortada

__all__ = [
    "MotorDoJogo", "ResultadoRodada", "RodadaAbortada", "ROTULOS",
    "Fantasmaria", "ColetorDeSerie", "TarefaFantasma",
    "ControladorSelado", "selo_t0", "cenario_da_seed", "SeloDivergente",
]
