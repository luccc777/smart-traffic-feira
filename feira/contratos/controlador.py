"""C3 — `Controlador`: a única superfície que RL, timer fixo e humano compartilham.

Os três braços da comparação implementam ISTO e nada mais. Consequência direta e
desejada: eles não podem divergir em ciclo de vida, em grade de decisão ou em
restrição de fase, porque quem roda o laço é a `Arena` (C4) — não eles.

Isso é o conserto estrutural do que a auditoria achou: hoje `nn_runner.py` e
`timer_runner.py` são DOIS laços escritos à mão, cada um com seu controle de
tempo, e é entre eles que a deriva mora. Um laço só, três controladores.

O QUE UM CONTROLADOR **NÃO** PODE FAZER
---------------------------------------
- ler env var (`ST_*`) — as restrições chegam em `reset()`;
- falar TraCI — quem tem a sessão é a Arena;
- decidir quando é chamado — a grade é da Arena;
- guardar tempo de parede — o relógio é o `t` simulado que chega em `decide()`.

Um controlador que precise de algo fora disso está tentando burlar o pareamento.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from .cenario import RestricoesFase

# Ação por interseção. Mesma semântica do `TrafficEnv._apply_actions` do maquete —
# de propósito: é o que faz a política treinada lá plugar aqui sem tradução.
MANTER = 0
TROCAR = 1


@dataclass(frozen=True)
class Topologia:
    """A parte da rede que um controlador pode enxergar. Derivada do .net.xml.

    Montada pela Arena a partir de `sim.environment.net_topology` — este módulo
    não importa `sim` de propósito, para que os contratos e os testes rodem sem
    SUMO instalado.
    """

    tls_ids: tuple[str, ...]
    controlavel: tuple[bool, ...]      # len(green_phases) >= 2; senão TROCAR é no-op
    n_fases_verdes: tuple[int, ...]
    edge_index: np.ndarray             # (2, E) adjacência p/ a GNN
    approach_capacity: float

    def __post_init__(self) -> None:
        n = len(self.tls_ids)
        if not (len(self.controlavel) == len(self.n_fases_verdes) == n):
            raise ValueError("tls_ids/controlavel/n_fases_verdes com tamanhos diferentes")
        if self.edge_index.ndim != 2 or self.edge_index.shape[0] != 2:
            raise ValueError("edge_index deve ter shape (2, E), veio %r" % (self.edge_index.shape,))

    @property
    def n(self) -> int:
        return len(self.tls_ids)

    @property
    def n_controlaveis(self) -> int:
        """Quantos semáforos o bit de ação realmente move.

        Na rede FECHADA de hoje isto vale 8 de 12 — os outros 4 têm uma fase verde
        só, porque só têm uma aproximação de entrada. Abrir as bordas deve levar
        este número a 12 (cada nó de perímetro ganha um coto). É gate da Onda 1, e
        é o que sustenta "o jogador controla todos os cruzamentos".
        """
        return sum(self.controlavel)

    def indices_controlaveis(self) -> tuple[int, ...]:
        return tuple(i for i, c in enumerate(self.controlavel) if c)


@dataclass(frozen=True)
class Observacao:
    """O que o controlador vê num tick de decisão.

    `estado` é o vetor da POLÍTICA — `(N, D)`, normalizado, exatamente o que o
    `TrafficEnv` do maquete devolve. Os demais campos são METADADOS de fase:
    servem ao timer (que ignora `estado`) e à camada de jogo (que acende o LED
    de "não pode trocar ainda"). A política **não** consome os metadados; se
    passasse a consumir, seria outra política e outro treino.
    """

    t: float                     # tempo SIMULADO (s). Nunca tempo de parede.
    estado: np.ndarray           # (N, D) float32 em [0,1]
    fase_atual: np.ndarray       # (N,) int — índice da fase verde corrente
    verde_desde: np.ndarray      # (N,) float — s no verde atual
    em_amarelo: np.ndarray       # (N,) bool
    pode_trocar: np.ndarray      # (N,) bool — min_green cumprido, fora do amarelo, controlável
    fila_por_tl: np.ndarray      # (N,) float — parados nas aproximações (HUD/jogo)

    def __post_init__(self) -> None:
        n = self.estado.shape[0]
        for nome in ("fase_atual", "verde_desde", "em_amarelo", "pode_trocar", "fila_por_tl"):
            v = getattr(self, nome)
            if v.shape != (n,):
                raise ValueError("Observacao.%s deve ter shape (%d,), veio %r" % (nome, n, v.shape))

    @property
    def n(self) -> int:
        return int(self.estado.shape[0])


@runtime_checkable
class Controlador(Protocol):
    """RL, timer e humano falam isto.

    `reset` é chamado UMA vez por corrida, depois do warm-up e antes do primeiro
    `decide`. `decide` é chamado exatamente a cada `restricoes.decision_interval`
    sim-steps.
    """

    nome: str

    def reset(self, topo: Topologia, restricoes: RestricoesFase, t0: float) -> None:
        """Prepara o controlador para uma corrida. Deve ser idempotente."""
        ...

    def decide(self, obs: Observacao) -> np.ndarray:
        """Devolve `(N,)` int em {MANTER, TROCAR}. Sem efeito colateral no SUMO."""
        ...


def valida_acoes(acoes: np.ndarray, n: int) -> np.ndarray:
    """Normaliza e valida a saída de um `decide`. A Arena chama isto em TODO tick.

    Barato e paranoico de propósito: uma política que devolva shape errado ou
    valores fora de {0,1} produziria um episódio silenciosamente inválido, e
    episódio inválido vira número publicado.
    """
    a = np.asarray(acoes).reshape(-1)
    if a.shape[0] != n:
        raise ValueError("ações devem ter shape (%d,), veio %r" % (n, a.shape))
    if not np.isin(a, (MANTER, TROCAR)).all():
        raise ValueError("ações fora de {0,1}: %r" % (np.unique(a),))
    return a.astype(np.int8, copy=False)
