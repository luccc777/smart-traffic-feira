"""O estado neutro canônico da rodada — e a prova de que os três braços saíram dele.

O ACHADO QUE MANDA NESTE MÓDULO (agente A1, `docs/CALIBRACAO_ABERTA.md` §5)
--------------------------------------------------------------------------
`saveState` grava posição e velocidade com **2 casas decimais**. Sob similitude
1 cm é 1,7% do comprimento do carro, e num sistema com car-following isso
amplifica: `loadState` reproduz o instante `t0` na precisão do arquivo, mas a
CONTINUAÇÃO diverge (~150 veículos diferentes em 300 s). Duas consequências, e
as duas valem aqui:

1. **Não se compara uma run carregada com uma run replayada.** Se o braço humano
   sair de um `loadState` e os fantasmas de um replay do zero (ou vice-versa), o
   placar mostra uma trajetória que o adversário não teria seguido — e ninguém
   percebe, porque as duas são perfeitamente plausíveis.
2. **Replay do zero é exato e é barato.** Rodar 0→t0 duas vezes com a mesma seed
   dá estado idêntico (medido em 3 seeds), e o aquecimento de 300 s custa
   ~1,5 s de parede (a Arena roda o aquecimento SEM `Ritmo`, solto). Medido
   nesta bancada: **2,4-2,7 s por fantasma completo** (300 s de aquecimento +
   120 s de janela) no cenário `aberta.maquete`.

Por isso a origem padrão do estado neutro é o **replay** — que é a forma mais
forte do invariante que o `loadState` só aproxima —, e o que este módulo
garante não é "todos carregaram o mesmo arquivo" e sim algo verificável:
**todos os braços chegaram ao MESMO estado em t0**, provado por impressão
digital (`selo_t0`).

O SELO
------
`ControladorSelado` embrulha qualquer `Controlador` e grava o sha256 da PRIMEIRA
`Observacao` que ele recebe — que é, por construção da Arena, o estado em `t0`,
antes de qualquer ação do braço. O motor compara o selo do humano com o dos dois
fantasmas e RECUSA publicar vencedor se divergirem. É o mesmo espírito do
`Fantasma.confere()` do C8: fantasma velho parece válido na tela.

O selo cobre o que o controlador enxerga — o vetor de política `(N,D)`, a fase
corrente, o tempo no verde, o amarelo e a fila por TL. Não é a posição de cada
carro (isso a Arena não expõe ao controlador), e não precisa ser: se dois braços
divergiram no aquecimento, essas grandezas divergem junto.
"""
from __future__ import annotations

import dataclasses
import hashlib

import numpy as np

from ..contratos import Cenario, Observacao, RestricoesFase, Topologia

__all__ = ["selo_t0", "ControladorSelado", "cenario_da_seed", "SeloDivergente"]


class SeloDivergente(RuntimeError):
    """Dois braços da mesma rodada não partiram do mesmo estado em t0."""


def selo_t0(obs: Observacao) -> str:
    """Impressão digital do estado observável em `t0`. 16 hex, estável entre processos."""
    h = hashlib.sha256()
    h.update(b"selo-t0/1|")
    h.update(("%.3f|" % float(obs.t)).encode("ascii"))
    for nome in ("estado", "fase_atual", "verde_desde", "em_amarelo", "fila_por_tl"):
        v = np.asarray(getattr(obs, nome))
        h.update(nome.encode("ascii"))
        h.update(b"|")
        # round antes de hashear: o float64 cru carrega ruído de última casa que
        # não descreve estado nenhum, e faria o selo acusar divergência onde não há.
        if v.dtype == bool:
            h.update(v.astype(np.int8).tobytes())
        else:
            h.update(np.round(v.astype(np.float64), 6).tobytes())
        h.update(b"|")
    return h.hexdigest()[:16]


class ControladorSelado:
    """Embrulha um `Controlador` (C3) e sela o estado de `t0`.

    Transparente por construção: repassa `reset`/`decide` sem tocar nas ações,
    então o braço selado mede exatamente o que o braço nu mediria. Guarda também
    a sequência de ações emitidas, que é o que o teste do DoD (b) compara.
    """

    def __init__(self, alvo, *, guarda_acoes: bool = False) -> None:
        self.alvo = alvo
        self.nome = getattr(alvo, "nome", "selado")
        self.selo: str | None = None
        self.t0: float | None = None
        self.guarda_acoes = bool(guarda_acoes)
        self.acoes: list[np.ndarray] = []
        # o `verde_desde` de cada TROCA emitida — a prova direta de que a
        # intenção do humano respeita o verde mínimo.
        self.verde_nas_trocas: list[float] = []
        self.trocas_em_amarelo = 0

    @property
    def n_decisoes(self) -> int:
        return int(getattr(self.alvo, "n_decisoes", len(self.acoes)))

    def reset(self, topo: Topologia, restricoes: RestricoesFase, t0: float) -> None:
        self.selo = None
        self.t0 = None
        self.acoes = []
        self.verde_nas_trocas = []
        self.trocas_em_amarelo = 0
        self.alvo.reset(topo, restricoes, t0)

    def decide(self, obs: Observacao) -> np.ndarray:
        if self.selo is None:
            self.selo = selo_t0(obs)
            self.t0 = float(obs.t)
        a = self.alvo.decide(obs)
        troca = np.asarray(a).reshape(-1) == 1
        if troca.any():
            self.verde_nas_trocas.extend(
                float(v) for v in np.asarray(obs.verde_desde)[troca])
            self.trocas_em_amarelo += int(np.asarray(obs.em_amarelo)[troca].sum())
        if self.guarda_acoes:
            self.acoes.append(np.asarray(a).copy())
        return a


def cenario_da_seed(cenario: Cenario, seed: int) -> Cenario:
    """O `Cenario` com o `.sumocfg` DA SEED já fixado.

    DEFEITO DA ARENA, contornado aqui e reportado (não consertado — `feira/arena/`
    é de outro agente): `ArenaSumo.roda()` reaponta `constants.SUMOCFG` para o
    arquivo da seed e logo em seguida chama `self.topologia(cenario)`, que chama
    `_amarra_sim` -> `_aponta_constants` de novo e devolve `SUMOCFG` ao arquivo
    CANÔNICO. O canônico não tem `<route-files>` — de propósito, para ninguém
    medir sem saber qual seed rodou. Resultado medido: uma corrida de
    `aberta.maquete` pela Arena insere **0 veículos** e o `ultimo_diagnostico`
    ainda reporta o caminho da seed. Passando o cenário já com o `.sumocfg` da
    seed, as duas voltas de `_aponta_constants` concordam e a demanda sobe.
    """
    from ..arena.sumo import _sumocfg_da_seed

    if cenario.modelo_demanda != "arquivo":
        return cenario
    return dataclasses.replace(cenario, sumocfg=_sumocfg_da_seed(cenario, int(seed)))
