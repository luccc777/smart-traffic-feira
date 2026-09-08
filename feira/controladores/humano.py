"""`ControladorHumano` — o braço do público, na MESMA grade da RL.

O visitante aperta um botão; o botão **enfileira uma intenção**; a intenção é
consumida no próximo tick da grade (`RestricoesFase.decision_interval`), sujeita
a `min_green`/`yellow` exatamente como a ação da rede neural. Aplicar a troca na
hora daria ao humano uma grade mais fina que a da política e o pareamento
deixaria de valer — é a decisão fechada do `docs/PLANO.md` §2 (Frente 3).

POR QUE A INTENÇÃO NEGADA É DESCARTADA, E NÃO GUARDADA
------------------------------------------------------
"Consumida no próximo tick" quer dizer **gasta**: se o verde mínimo ainda não
fechou, o botão acende `deny` e a intenção morre ali. Guardar a intenção para
disparar sozinha mais adiante daria ao humano um efeito que a ação da RL não
tem — a RL emite um bit por tick e o bit recusado se perde. Duas consequências
boas: a sequência de ações do humano é função só de "que botões foram apertados
entre dois ticks", e o `deny` ensina a restrição em vez de escondê-la.

O BIT SÓ SAI TROCAR QUANDO SERÁ ACEITO
--------------------------------------
`obs.pode_trocar` é, por construção da Arena, o MESMO predicado que o
`TrafficEnv._apply_actions` usa para aceitar um switch
(`controlável ∧ ¬amarelo ∧ verde_desde ≥ MIN_GREEN`, no mesmo instante `t`).
Então emitir `TROCAR` fora dele seria um no-op silencioso: aqui ele vira `MANTER`
mais o feedback `deny`, e o que o placar mostra é o que a rede fez.

O QUE ESTE CONTROLADOR NÃO FAZ
------------------------------
Não fala TraCI, não lê env var, não guarda relógio de parede e não decide quando
é chamado — as quatro proibições do C3. O único desvio consciente é o
`ao_abrir_janela`: um callback do MOTOR (não do controlador) invocado dentro de
`reset()`, que é o instante exato em que a janela de medição abre. É onde a
contagem 3-2-1 mora, porque o aquecimento roda solto (sem `Ritmo`) e o relógio
da rodada só nasce depois do `reset` — contar antes deixaria um buraco de ~2 s
entre o "JÁ!" e o primeiro carro andar.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from ..contratos import (
    ACEITO,
    ARMADO,
    MANTER,
    NEGADO,
    OFF,
    TROCAR,
    EventoBotao,
    FonteEntrada,
    Observacao,
    RestricoesFase,
    Topologia,
    valida_acoes,
    valida_estados,
)

__all__ = ["ControladorHumano"]


class ControladorHumano:
    """Traduz botões em `(N,)` int {MANTER, TROCAR} na grade da Arena.

    `mapa_botoes[b]` é o índice do semáforo que o botão `b` comanda; `None`
    (ou fora de `range(topo.n)`) marca botão morto — ele existe no painel e
    responde `deny`. O default é a identidade, que é o que o painel 3x4 da
    feira quer: `tls_ids` da rede aberta sai em ordem `H1V1..H3V4`, linha a
    linha, e o bloco `Q W E R / A S D F / Z X C V` é isomorfo a isso.
    """

    def __init__(self, fonte: FonteEntrada, *, nome: str | None = None,
                 mapa_botoes: tuple[int | None, ...] | None = None,
                 ao_abrir_janela: Callable[[float], None] | None = None) -> None:
        self.fonte = fonte
        self.nome = nome or "humano:%s" % getattr(fonte, "nome", "?")
        self.ao_abrir_janela = ao_abrir_janela
        self._mapa_pedido = mapa_botoes
        self._mapa: tuple[int | None, ...] = ()
        self._topo: Topologia | None = None
        self._restricoes: RestricoesFase | None = None
        # `passo_por_tick`: fontes gravadas (ReplayInput) entregam um SLOT por
        # tick da grade e não suportam ser drenadas fora dele. Para elas o
        # `bombeia()` vira no-op e o `poll()` acontece uma vez só, dentro do
        # `decide()`. É o que faz a rodada gravada reproduzir byte a byte.
        self._por_tick = bool(getattr(fonte, "passo_por_tick", False))
        n = int(getattr(fonte, "n_botoes", 0))
        self._armado = [False] * n
        self._ultimo = [OFF] * n
        # A gravação da rodada: um item por tick, com os botões que estavam
        # armados naquele tick. É EXATAMENTE o que o `ReplayInput` consome.
        self.gravacao: list[tuple[int, ...]] = []
        # Diagnóstico do jogo (não entra no `Resultado`, que é contrato):
        self.n_decisoes = 0
        self.n_aceitos = 0
        self.n_negados = 0
        self.starts: list[EventoBotao] = []

    # ------------------------------------------------------------------ C3
    def reset(self, topo: Topologia, restricoes: RestricoesFase, t0: float) -> None:
        self._topo = topo
        self._restricoes = restricoes
        n_b = len(self._armado)
        if self._mapa_pedido is not None:
            if len(self._mapa_pedido) != n_b:
                raise ValueError("mapa_botoes tem %d entradas para %d botões"
                                 % (len(self._mapa_pedido), n_b))
            mapa = tuple(self._mapa_pedido)
        else:
            mapa = tuple(range(n_b))
        self._mapa = tuple(i if (i is not None and 0 <= int(i) < topo.n) else None
                           for i in mapa)
        self._armado = [False] * n_b
        self._ultimo = [OFF] * n_b
        self.gravacao = []
        self.n_decisoes = 0
        self.n_aceitos = 0
        self.n_negados = 0
        self.starts = []
        # Idempotência (exigida pela suíte de conformidade e pelo fantasma):
        # fonte rebobinável volta ao início; fonte ao vivo é DRENADA, para que
        # a tecla apertada durante a contagem 3-2-1 não vire ação em t0.
        rebobina = getattr(self.fonte, "rebobina", None)
        if callable(rebobina):
            rebobina()
        else:
            try:
                self.fonte.poll()
            except Exception:
                pass
        self._publica()
        if self.ao_abrir_janela is not None:
            self.ao_abrir_janela(float(t0))

    def decide(self, obs: Observacao) -> np.ndarray:
        if self._topo is None:
            raise RuntimeError("decide() antes de reset()")
        self._drena()
        n = obs.n
        acoes = np.full(n, MANTER, dtype=np.int8)
        estados = list(self._ultimo)
        apertados: list[int] = []
        for b, armado in enumerate(self._armado):
            if not armado:
                estados[b] = OFF
                continue
            apertados.append(b)
            i = self._mapa[b] if b < len(self._mapa) else None
            if i is not None and i < n and bool(obs.pode_trocar[i]):
                acoes[i] = TROCAR
                estados[b] = ACEITO
                self.n_aceitos += 1
            else:
                estados[b] = NEGADO
                self.n_negados += 1
        self._armado = [False] * len(self._armado)
        self._ultimo = valida_estados(estados, len(estados))
        self.gravacao.append(tuple(apertados))
        self.n_decisoes += 1
        self.fonte.feedback(list(self._ultimo))
        avanca = getattr(self.fonte, "avanca_tick", None)
        if callable(avanca):
            avanca()
        return valida_acoes(acoes, n)

    # ---------------------------------------------------------------- jogo
    def bombeia(self) -> list[EventoBotao]:
        """Drena a fonte ENTRE ticks e publica o feedback na hora.

        Sem isto o LED só mudaria a cada `decision_interval` (5 s na rede
        aberta) e o visitante concluiria que o botão quebrou — o motivo pelo
        qual `feedback()` é obrigatório no C6. Devolve os eventos de START
        vistos, que é como o motor enxerga o ABORTAR no meio da rodada."""
        if self._topo is None:
            raise RuntimeError("bombeia() antes de reset()")
        if self._por_tick:
            return []
        return self._drena()

    def descarta(self) -> int:
        """Joga fora as intenções armadas e devolve quantas eram.

        É o que o motor chama no fim da contagem 3-2-1: quem martela o botão
        durante o "3, 2, 1" não começa a rodada com 12 trocas de graça."""
        n = sum(1 for a in self._armado if a)
        self._armado = [False] * len(self._armado)
        self._publica()
        return n

    def consome_starts(self) -> list[EventoBotao]:
        """Os STARTs acumulados desde a última chamada."""
        s, self.starts = self.starts, []
        return s

    def estados_atuais(self) -> list[str]:
        """O vetor de feedback vigente — o que o painel está acendendo agora."""
        return self._com_armados()

    # -------------------------------------------------------------- interno
    def _drena(self) -> list[EventoBotao]:
        starts: list[EventoBotao] = []
        novos = False
        for ev in self.fonte.poll():
            if ev.e_start:
                starts.append(ev)
                self.starts.append(ev)
                continue
            b = int(ev.indice)
            if 0 <= b < len(self._armado):
                if not self._armado[b]:
                    novos = True
                self._armado[b] = True
        if novos:
            self._publica()
        return starts

    def _com_armados(self) -> list[str]:
        return [ARMADO if a else e for a, e in zip(self._armado, self._ultimo)]

    def _publica(self) -> None:
        self.fonte.feedback(list(self._com_armados()))
