"""A implementação do C4 — a bancada de medição (agente A2).

`ArenaSumo` é o laço único: sobe o SUMO, roda o aquecimento com o plano comum,
entrega o controle ao `Controlador` na grade certa, mede e devolve um
`Resultado` carimbado com a `Chave`. Os três braços (RL, timer, humano) passam
por ele — é o que impede que voltem a existir dois laços com dois relógios.

Nada aqui é importado ansiosamente pelo `feira/__init__.py`: importar `sim`
congela `sim.environment.constants`, e isso tem que acontecer DEPOIS de
`Cenario.aplicar()` (ver C1).
"""
from .sumo import ArenaSumo, sha_demanda

__all__ = ["ArenaSumo", "sha_demanda"]
