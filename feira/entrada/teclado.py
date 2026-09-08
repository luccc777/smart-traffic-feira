"""`TecladoInput` — a fonte de entrada que sempre existe.

A regra do projeto é "software primeiro": a rodada tem que ser jogável sem
hardware nenhum e **sem `pyserial` instalado** (ele não está no venv
compartilhado, e isso é medido, não suposto). Este módulo não importa nada fora
da stdlib.

O MAPA
------
    Q W E R        H1V1 H1V2 H1V3 H1V4
    A S D F   ->   H2V1 H2V2 H2V3 H2V4
    Z X C V        H3V1 H3V2 H3V3 H3V4
    espaço = START / ABORTAR

O bloco é isomorfo ao painel 3x4 da botoeira (agente A4) e à ordem em que a
rede aberta entrega `tls_ids` (`H1V1..H3V4`, linha a linha, verificado no
`net_topology`). Trocar teclado por botoeira é trocar a implementação injetada
e nada mais: o índice do botão significa a mesma coisa nas duas.

LEITURA NÃO-BLOQUEANTE
----------------------
`msvcrt.kbhit()/getwch()` (stdlib, Windows). Quando não há console — pytest com
saída capturada, serviço, pipe — a leitura simplesmente devolve vazio em vez de
levantar: o jogo continua de pé e o operador cai para outra fonte. O teclado
NUNCA "morre" (`viva()` só vira False depois de `close()`), porque ele é o
fallback de todo mundo; quem morre é a botoeira.
"""
from __future__ import annotations

from typing import Callable

from ..contratos import EventoBotao, valida_estados

__all__ = ["TecladoInput", "LeitorRoteirizado", "MAPA_TECLAS", "TECLA_START", "linhas_do_mapa"]

# Ordem row-major: índice do botão = índice do semáforo na rede aberta.
LINHAS_TECLAS = ("qwer", "asdf", "zxcv")
TECLA_START = " "
MAPA_TECLAS: dict[str, int] = {
    t: linha * 4 + col
    for linha, teclas in enumerate(LINHAS_TECLAS)
    for col, t in enumerate(teclas)
}


def linhas_do_mapa(n_botoes: int = 12) -> list[str]:
    """As três linhas do bloco, para a tela do operador e para o `docs/JOGO.md`."""
    out = []
    for linha, teclas in enumerate(LINHAS_TECLAS):
        pares = ["%s=%d" % (t.upper(), linha * 4 + col)
                 for col, t in enumerate(teclas) if linha * 4 + col < n_botoes]
        if pares:
            out.append("  ".join(pares))
    return out


class LeitorRoteirizado:
    """Leitor de teclas roteirizado — o que torna o DECODIFICADOR testável.

    Cada chamada devolve a próxima string do roteiro (uma "rajada" de teclas
    vista naquele `poll`). Esgotado, devolve vazio para sempre. Existe para que
    `TecladoInput` entre na suíte de conformidade do C6 sem console.
    """

    def __init__(self, roteiro: list[str] | None = None) -> None:
        self._roteiro = list(roteiro or [])
        self._i = 0

    def __call__(self) -> str:
        if self._i >= len(self._roteiro):
            return ""
        s = self._roteiro[self._i]
        self._i += 1
        return s

    def rebobina(self) -> None:
        self._i = 0


def _leitor_msvcrt() -> Callable[[], str]:
    """Leitor não-bloqueante de console no Windows. Sem console, devolve vazio."""
    try:
        import msvcrt
    except ImportError:                                   # pragma: no cover - não-Windows
        return lambda: ""

    def le() -> str:
        buf = []
        try:
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):                # prefixo de tecla estendida
                    msvcrt.getwch()                       # descarta o código da seta/F-key
                    continue
                buf.append(ch)
        except OSError:                                   # sem console (pytest, serviço)
            return ""
        return "".join(buf)

    return le


class TecladoInput:
    """`FonteEntrada` (C6) sobre o teclado do notebook da feira."""

    passo_por_tick = False

    def __init__(self, n_botoes: int = 12, *, leitor: Callable[[], str] | None = None,
                 nome: str = "teclado", mapa: dict[str, int] | None = None) -> None:
        self.n_botoes = int(n_botoes)
        self.nome = nome
        self._leitor = leitor or _leitor_msvcrt()
        self._mapa = dict(mapa or MAPA_TECLAS)
        self._viva = True
        # Último vetor de feedback pedido pelo motor. O teclado não tem LED:
        # quem acende é a projeção (agente A7), que lê isto.
        self.estados: list[str] = ["off"] * self.n_botoes
        self.n_desconhecidas = 0

    # -------------------------------------------------------------- C6
    def poll(self) -> list[EventoBotao]:
        if not self._viva:
            return []
        eventos: list[EventoBotao] = []
        for ch in self._leitor():
            if ch == TECLA_START or ch == "\r" or ch == "\n":
                eventos.append(EventoBotao(indice=-1))
                continue
            i = self._mapa.get(ch.lower())
            if i is None:
                self.n_desconhecidas += 1
                continue
            if i < self.n_botoes:
                eventos.append(EventoBotao(indice=i))
        return eventos

    def feedback(self, estados: list[str], start: str | None = None) -> None:
        self.estados = list(valida_estados(estados, self.n_botoes))
        if start is not None:
            self.start = valida_estados([start], 1)[0]

    def feedback_start(self, estado: str) -> None:
        """O LED do botao grande (C6). Aqui e so estado guardado."""
        self.start = valida_estados([estado], 1)[0]

    def viva(self) -> bool:
        """O teclado é o fallback de todo mundo: ele só morre quando fechado."""
        return self._viva

    def close(self) -> None:
        self._viva = False
