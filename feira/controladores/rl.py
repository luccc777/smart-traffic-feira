"""`ControladorRL` — a política treinada, embrulhada no contrato C3.

Casca fina sobre `sim.agents.policy.load_policy`: o checkpoint, os pesos e a
arquitetura continuam sendo do maquete. Aqui só se garante o que o C3 exige —
não ler env var, não falar TraCI, não guardar tempo de parede, e ser
DETERMINÍSTICO (greedy, `explore=False`), porque sem isso não há fantasma
pré-computado que preste.

O import de `sim`/`torch` é PREGUIÇOSO, dentro do `reset`. Motivo concreto: o
`sim.environment.constants` lê env var no import e vira singleton de módulo — se
este arquivo importasse `sim` no topo, importar o pacote `feira.controladores`
já congelaria a configuração antes de `Cenario.aplicar()` rodar (ver C1).

`load_policy` só precisa de `n_intersections` e `edge_index` do ambiente para
dimensionar a rede — e os dois estão na `Topologia` que o `reset` recebe. Passar
um adaptador em vez de um `TrafficEnv()` evita construir um segundo controlador
de demanda (que relê o `.net.xml` com sumolib) só para ler dois atributos.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..contratos import Observacao, RestricoesFase, Topologia, valida_acoes


class _EnvDaTopologia:
    """Adaptador com a superfície que o `DDQNAgent.from_env` consome."""

    def __init__(self, topo: Topologia) -> None:
        self.n_intersections = topo.n
        self.edge_index = np.asarray(topo.edge_index, dtype=np.int64)


class ControladorRL:
    """Política DDQN+GNN greedy carregada de um checkpoint `.pt`."""

    def __init__(self, ckpt: str | Path, *, device: str = "cpu",
                 nome: str | None = None) -> None:
        self.ckpt = str(ckpt)
        self.device = device
        self.nome = nome or "rl:%s" % Path(self.ckpt).stem
        self._politica = None
        self._topo: Topologia | None = None
        self._restricoes: RestricoesFase | None = None
        self._assinatura: tuple | None = None
        self.n_decisoes = 0

    def reset(self, topo: Topologia, restricoes: RestricoesFase, t0: float) -> None:
        from sim.agents.policy import load_policy  # lazy: puxa torch só aqui

        assinatura = (topo.n, tuple(np.asarray(topo.edge_index).ravel().tolist()))
        if self._politica is None or assinatura != self._assinatura:
            self._politica = load_policy(self.ckpt, env=_EnvDaTopologia(topo),
                                         device=self.device)
            self._assinatura = assinatura
        self._topo = topo
        self._restricoes = restricoes
        self.n_decisoes = 0

    def decide(self, obs: Observacao) -> np.ndarray:
        if self._politica is None or self._topo is None:
            raise RuntimeError("decide() antes de reset()")
        self.n_decisoes += 1
        return valida_acoes(self._politica(obs.estado), obs.n)
