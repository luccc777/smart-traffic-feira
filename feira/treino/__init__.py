"""Treino da política RL no cenário aberto (agente A6).

Nada aqui é importado ansiosamente pelo `feira/__init__.py`, e nada aqui importa
`sim`/`torch` no topo do módulo: importar `sim.environment.constants` congela os
escalares do espaço de ação, e isso tem que acontecer DEPOIS de
`Cenario.aplicar()` (a armadilha do C1). Por isso os imports pesados moram dentro
das funções.

    feira/treino/ambiente.py   as três faixas de seed + as variantes de cenário
    feira/treino/loop.py       o loop DDQN com demanda rotativa por episódio
    feira/treino/avalia.py     avaliação pareada contra o `coordenado_c60`
"""
from .ambiente import (
    PLANO_BASELINE,
    SEEDS_HELD_OUT,
    SEEDS_SELECAO,
    SEEDS_TREINO,
    SEEDS_VALIDACAO,
    SeedContaminada,
    cenario_variante,
    checa_disjuncao,
    seeds_de_texto,
)

__all__ = [
    "PLANO_BASELINE", "SEEDS_HELD_OUT", "SEEDS_SELECAO", "SEEDS_TREINO",
    "SEEDS_VALIDACAO", "SeedContaminada", "cenario_variante", "checa_disjuncao",
    "seeds_de_texto",
]
