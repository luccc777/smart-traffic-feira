"""O adversário roteirizado ENTRANDO PELA PORTA DO VISITANTE.

A armadilha nº1 do A8, escrita em código: um adversário implementado direto como
`Controlador` (C3) devolve o vetor de ações e **pula** a camada que define o
jogo — a intenção que entra numa fila, é consumida só no tick seguinte da grade e
só é aceita se o verde mínimo fechou. Quem mede um adversário assim está medindo
outro jogo.

Aqui o caminho é o mesmo do público, peça por peça:

    Roteirista.aperta()  ->  FonteRoteirizada (C6)  ->  ControladorHumano  ->  Arena

`AdversarioHumano` é só a cola: ele lê a `Observacao` que já chegou, deixa a
política formar a intenção, empurra os botões na fonte e **delega o `decide` ao
`ControladorHumano`**. Nenhuma ação é emitida por ele.

O ATRASO É PARTE DO MODELO, NÃO DETALHE
---------------------------------------
`lag_ticks=0` é o visitante que vê a tela no instante do tick e ainda aperta a
tempo — um oráculo, e o teto do que um humano faria. `lag_ticks=1` é o realista:
ele reage ao que viu no tick anterior (5 s atrás, na grade `di5`). As duas
versões são medidas, e a diferença entre elas é o preço da reação humana em
carros.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from ..contratos import (
    ESTADOS,
    OFF,
    EventoBotao,
    Observacao,
    RestricoesFase,
    Topologia,
    valida_estados,
)
from ..controladores.humano import ControladorHumano
from .politicas import Leitura, Roteirista, leitura_de

__all__ = ["AdversarioHumano", "FonteRoteirizada"]


class FonteRoteirizada:
    """`FonteEntrada` (C6) alimentada por um roteiro que se decide em tempo de corrida.

    É irmã do `ReplayInput`: mesma disciplina de um SLOT por tick
    (`passo_por_tick=True`), com a diferença de que o slot não vem de um arquivo
    gravado — ele é carregado pelo `AdversarioHumano` logo antes do tick, porque
    uma política reativa só sabe o que apertar depois de ver a tela.
    """

    passo_por_tick = True

    def __init__(self, n_botoes: int = 12, *, nome: str = "roteiro") -> None:
        self.n_botoes = int(n_botoes)
        self.nome = str(nome)
        self._slot: tuple[int, ...] = ()
        self._viva = True
        self.start = OFF
        # contabilidade da rodada (diagnóstico; não entra no `Resultado`)
        self.n_pressoes = 0
        self.n_polls = 0
        self.feedbacks: list[list[str]] = []
        self.guarda_feedback = False

    # ------------------------------------------------------------------ C6
    def poll(self) -> list[EventoBotao]:
        slot, self._slot = self._slot, ()
        self.n_polls += 1
        self.n_pressoes += len(slot)
        return [EventoBotao(indice=int(b), t_wall=float(self.n_polls)) for b in slot]

    def feedback(self, estados: list[str], start: str | None = None) -> None:
        valida_estados(estados, self.n_botoes)
        if self.guarda_feedback:
            self.feedbacks.append(list(estados))
        if start is not None:
            self.feedback_start(start)

    def feedback_start(self, estado: str) -> None:
        if estado not in ESTADOS:
            raise ValueError("estado de START desconhecido: %r" % estado)
        self.start = estado

    def viva(self) -> bool:
        return self._viva

    def close(self) -> None:
        self._viva = False

    # --------------------------------------------------------------- extras
    def carrega(self, botoes) -> None:
        """Arma o slot do PRÓXIMO `poll()`. Índice fora da faixa é erro, não no-op."""
        slot = tuple(int(b) for b in botoes)
        for b in slot:
            if not (0 <= b < self.n_botoes):
                raise ValueError("botão %d fora de 0..%d" % (b, self.n_botoes - 1))
        self._slot = slot

    def rebobina(self) -> None:
        """Zera o estado. Chamado pelo `ControladorHumano.reset()` (idempotência)."""
        self._slot = ()
        self.n_pressoes = 0
        self.n_polls = 0
        self.feedbacks = []

    def avanca_tick(self) -> None:
        """No-op: `poll()` já consome o slot inteiro."""


class AdversarioHumano:
    """Um `Controlador` (C3) que é, por dentro, o `ControladorHumano` do jogo.

    Não emite ação nenhuma por conta própria: ele forma a intenção, entrega à
    fonte e devolve o que o `ControladorHumano` decidiu. Trocar isto por um
    controlador que devolvesse `TROCAR` direto mediria outro jogo (ver o
    cabeçalho do módulo).
    """

    def __init__(self, roteirista: Roteirista, *, n_botoes: int = 12,
                 mapa_fases=None, nome: str | None = None,
                 mapa_botoes: tuple[int | None, ...] | None = None) -> None:
        self.roteirista = roteirista
        self.mapa_fases = mapa_fases
        self.fonte = FonteRoteirizada(n_botoes, nome=roteirista.nome)
        self.humano = ControladorHumano(self.fonte, mapa_botoes=mapa_botoes,
                                        nome="humano:%s" % roteirista.nome)
        self.nome = nome or self.humano.nome
        self._pendentes: deque[tuple[int, ...]] = deque()
        self.tick = 0
        self.n_intencoes = 0
        self._topo: Topologia | None = None

    # ------------------------------------------------------------------ C3
    def reset(self, topo: Topologia, restricoes: RestricoesFase, t0: float) -> None:
        self._topo = topo
        n_b = min(self.fonte.n_botoes, int(topo.n))
        self.roteirista.reset(n_b)
        grupo = getattr(self.roteirista.politica, "com_grupo", None)
        if callable(grupo) and self.mapa_fases is not None:
            grupo(self.mapa_fases.grupo_arterial)
        self._pendentes = deque()
        self.tick = 0
        self.n_intencoes = 0
        self.humano.reset(topo, restricoes, t0)

    def decide(self, obs: Observacao) -> np.ndarray:
        if self._topo is None:
            raise RuntimeError("decide() antes de reset()")
        leitura = self.le(obs)
        querido = self.roteirista.aperta(self.tick, leitura)
        self.n_intencoes += len(querido)
        self._pendentes.append(tuple(querido))
        # O atraso da mão: com `lag_ticks=L`, o que a política formou olhando o
        # tick `k` só chega ao botão no tick `k+L`.
        entrega: tuple[int, ...] = ()
        if len(self._pendentes) > self.roteirista.lag_ticks:
            entrega = self._pendentes.popleft()
        self.fonte.carrega(entrega)
        self.tick += 1
        return self.humano.decide(obs)

    # -------------------------------------------------------------- leitura
    def le(self, obs: Observacao) -> Leitura:
        return leitura_de(obs, self.mapa_fases.como_par() if self.mapa_fases else None)

    # ---------------------------------------------------------- diagnóstico
    @property
    def n_decisoes(self) -> int:
        return int(self.humano.n_decisoes)

    @property
    def n_aceitos(self) -> int:
        return int(self.humano.n_aceitos)

    @property
    def n_negados(self) -> int:
        return int(self.humano.n_negados)

    @property
    def gravacao(self) -> list[tuple[int, ...]]:
        """A rodada no formato do `ReplayInput` — reproduzível byte a byte."""
        return list(self.humano.gravacao)

    def diagnostico(self) -> dict:
        return {
            "adversario": self.roteirista.nome,
            "reativa": self.roteirista.reativa,
            "deterministica": self.roteirista.deterministica,
            "lag_ticks": int(self.roteirista.lag_ticks),
            "semente": int(self.roteirista.semente),
            "decisoes": self.n_decisoes,
            "intencoes": int(self.n_intencoes),
            "pressoes": int(self.fonte.n_pressoes),
            "aceitos": self.n_aceitos,
            "negados": self.n_negados,
        }
