"""`ControladorTimer` — o timer fixo, mínimo e sem coordenação.

Verde fixo, IGUAL em toda interseção, SEM offset e SEM split por aproximação.
É deliberadamente o plano que nenhum engenheiro instalaria numa arterial: ele
existe para (a) dar um segundo braço real à Arena antes da Onda 2 e (b)
reproduzir o `FixedTimerSim` do maquete, que é o baseline de todos os números
publicados até aqui. O baseline HONESTO — Webster + splits + offsets — é
entregável do agente A5 e vai substituir este como adversário.

Ele não guarda relógio próprio: o tempo no verde chega em `Observacao.verde_desde`,
que a Arena mede na máquina de fases. É o que impede o braço lento de "andar
menos" e ainda assim ser comparado (a regra do C3: o relógio é o `t` simulado).

Equivalência com o `FixedTimerSim._fire_timer`, linha a linha:

    if not ph.controllable: continue        -> mascarado por `topo.controlavel`
    if self._in_yellow[i]:  continue        -> mascarado por `obs.em_amarelo`
    if (now - green_since) >= green:  troca  -> `obs.verde_desde >= verde_s`

A diferença que SOBRA é a grade: o `FixedTimerSim` decide a cada sim-step, e aqui
quem decide quando perguntar é a Arena (`decision_interval`). Com verde 27 s numa
grade de 10 s a troca só é aceita aos 30 s — o baseline muda. Isso é medido e
reportado em `docs/AUDITORIA_COMPARACAO.md` §8, não escondido.
"""
from __future__ import annotations

import numpy as np

from ..contratos import MANTER, TROCAR, Observacao, RestricoesFase, Topologia, valida_acoes


class ControladorTimer:
    """Verde fixo de `verde_s` segundos em todas as interseções controláveis."""

    def __init__(self, verde_s: float, *, nome: str | None = None) -> None:
        if verde_s <= 0:
            raise ValueError("verde_s deve ser > 0 (veio %r)" % verde_s)
        self.verde_s = float(verde_s)
        self.nome = nome or "timer:uniforme_%gs" % self.verde_s
        self._topo: Topologia | None = None
        self._controlavel: np.ndarray | None = None
        self._restricoes: RestricoesFase | None = None
        self.n_decisoes = 0

    def reset(self, topo: Topologia, restricoes: RestricoesFase, t0: float) -> None:
        self._topo = topo
        self._controlavel = np.asarray(topo.controlavel, dtype=bool)
        self._restricoes = restricoes
        self.n_decisoes = 0

    def decide(self, obs: Observacao) -> np.ndarray:
        if self._topo is None or self._controlavel is None:
            raise RuntimeError("decide() antes de reset()")
        self.n_decisoes += 1
        n = obs.n
        troca = (obs.verde_desde >= self.verde_s) & (~obs.em_amarelo) & self._controlavel[:n]
        return valida_acoes(np.where(troca, TROCAR, MANTER), n)
