"""`FonteWeb` — o teclado junto do projetor, lido pela PÁGINA projetada (C6).

POR QUE ELA EXISTE (docs/GAMIFICACAO.md §3.3)
---------------------------------------------
Os recursos da feira são um notebook, um projetor no chão e um teclado. O visitante
digita o próprio apelido e joga olhando para o chão — então o foco tem de estar na
página projetada, e quem recebe as teclas é o NAVEGADOR, não o terminal. Esta fonte
é o outro lado desse fio: a página captura `keydown`, manda por um WebSocket local
(`/entrada`, no mesmo processo do motor), o servidor chama `recebe()` e `poll()`
drena a fila a ~48 Hz como qualquer outra fonte. O `feedback()` volta pelo mesmo
caminho — `ao_feedback` recebe um dicionário `{"tipo": "leds", ...}` que o servidor
difunde, e a página desenha os 12 LEDs sobre os cruzamentos: o painel da botoeira,
projetado para a plateia.

O QUE CHEGA DA PÁGINA (JSON, um objeto por mensagem)
----------------------------------------------------
    {"tipo": "tecla",  "k": "q"}      uma tecla, no mapa `QWER/ASDF/ZXCV` (+ espaço)
    {"tipo": "botao",  "i": 3}        um botão pelo índice (0..n-1), para a botoeira virtual
    {"tipo": "start"}                 o botão grande
    {"tipo": "abortar"}               o operador (Esc) — vai para `ao_abortar`, não vira evento
    {"tipo": "ping"}                  keep-alive; só marca `viu_em`

O modo TEXTO (o visitante digitando o nome) é só da página: enquanto o campo está
aberto, ela NÃO manda `tecla`; manda o nome pronto por `POST /api/jogador`. Aqui
nunca chega letra de nome — por construção, não por filtro.

`viva()` É SEMPRE TRUE, e é decisão, não preguiça. A página recarregar (F5) e
reconectar é o caminho NORMAL de recuperação; se `viva()` caísse quando o WS cai, um
`FonteComReserva` trocaria de mão única para o teclado do terminal — que só funciona
com o terminal em foco, isto é, nunca na feira. Esta fonte só morre com `close()`,
como o teclado. A composição certa com o teclado do terminal é `FonteComposta`
(os dois ao mesmo tempo, quem tiver foco manda), não a reserva.

Thread-safe: `recebe()` é chamado da asyncio loop do servidor; `poll()` do laço do
jogo. A fila é `queue.Queue` e nada bloqueia.
"""
from __future__ import annotations

import queue
import time
from typing import Callable

from ..contratos import BOTAO_START, OFF, EventoBotao, valida_estados
from .teclado import MAPA_TECLAS, TECLA_START

__all__ = ["FonteWeb", "TECLA_ABORTAR"]

TECLA_ABORTAR = "escape"


class FonteWeb:
    """`FonteEntrada` (C6) alimentada por mensagens da página projetada."""

    passo_por_tick = False

    def __init__(self, n_botoes: int = 12, *, nome: str = "web",
                 mapa: dict[str, int] | None = None,
                 ao_feedback: Callable[[dict], None] | None = None,
                 ao_abortar: Callable[[], None] | None = None,
                 agora: Callable[[], float] = time.monotonic) -> None:
        self.n_botoes = int(n_botoes)
        self.nome = nome
        self._mapa = dict(mapa or MAPA_TECLAS)
        self.ao_feedback = ao_feedback
        self.ao_abortar = ao_abortar
        self._agora = agora
        self._fila: "queue.Queue[EventoBotao]" = queue.Queue()
        self._viva = True
        self.estados: list[str] = [OFF] * self.n_botoes
        self.start: str = OFF
        self.viu_em: float = 0.0          # última mensagem da página (monotonic)
        self.n_mensagens = 0
        self.n_desconhecidas = 0
        self.n_abortos = 0
        self.n_ticks = 0
        self.t_tick: float | None = None

    # ------------------------------------------------------- lado da página
    def recebe(self, msg: dict) -> None:
        """Uma mensagem da página. Nunca levanta: lixo é contado e ignorado."""
        try:
            self.viu_em = self._agora()
            self.n_mensagens += 1
            tipo = msg.get("tipo") or msg.get("type")
            if tipo == "tecla":
                k = str(msg.get("k") or "").lower()
                if k in ("escape", "esc"):
                    self._aborta()
                    return
                if k in (TECLA_START, "space", "enter", "\r", "\n"):
                    self._poe(BOTAO_START)
                    return
                i = self._mapa.get(k)
                if i is None:
                    self.n_desconhecidas += 1
                elif i < self.n_botoes:
                    self._poe(i)
            elif tipo == "botao":
                i = int(msg.get("i"))
                if 0 <= i < self.n_botoes:
                    self._poe(i)
                else:
                    self.n_desconhecidas += 1
            elif tipo == "start":
                self._poe(BOTAO_START)
            elif tipo == "abortar":
                self._aborta()
            elif tipo == "ping":
                pass
            else:
                self.n_desconhecidas += 1
        except Exception:
            self.n_desconhecidas += 1

    def _poe(self, indice: int) -> None:
        if self._viva:
            self._fila.put_nowait(EventoBotao(indice=int(indice), t_wall=self._agora()))

    def _aborta(self) -> None:
        self.n_abortos += 1
        if self.ao_abortar is not None:
            try:
                self.ao_abortar()
            except Exception:
                pass

    def quadro_leds(self, *, tick: bool = False, t: float | None = None) -> dict:
        """O que a página deve acender agora — o mesmo quadro que o `LEDS` serial.

        `tick=True` marca o quadro publicado NO tick da grade (com o `t` simulado):
        é o relógio exato que a página usa para o anel do pedido encher até o
        momento em que a intenção é julgada, e para sincronizar a placa com o
        farol que o mapa está mostrando (o mapa anda ~1 s simulado atrasado)."""
        d = {"tipo": "leds", "estados": list(self.estados), "start": self.start}
        if tick:
            d["tick"] = True
            d["t"] = None if t is None else float(t)
        return d

    def ao_tick(self, t: float) -> None:
        """O `ControladorHumano` acabou de julgar as intenções no instante `t`."""
        self.t_tick = float(t)
        self.n_ticks += 1
        if self.ao_feedback is None:
            return
        try:
            self.ao_feedback(self.quadro_leds(tick=True, t=t))
        except Exception:
            pass

    # ---------------------------------------------------------------- C6
    def poll(self) -> list[EventoBotao]:
        if not self._viva:
            return []
        eventos: list[EventoBotao] = []
        while True:
            try:
                eventos.append(self._fila.get_nowait())
            except queue.Empty:
                return eventos

    def feedback(self, estados: list[str], start: str | None = None) -> None:
        self.estados = list(valida_estados(estados, self.n_botoes))
        if start is not None:
            self.start = valida_estados([start], 1)[0]
        self._publica()

    def feedback_start(self, estado: str) -> None:
        self.start = valida_estados([estado], 1)[0]
        self._publica()

    def _publica(self) -> None:
        if self.ao_feedback is None:
            return
        try:
            self.ao_feedback(self.quadro_leds())
        except Exception:
            pass          # projeção caída não derruba a rodada

    def viva(self) -> bool:
        return self._viva

    def close(self) -> None:
        self._viva = False
