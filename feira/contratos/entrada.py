"""C6 — `FonteEntrada`: de onde vêm os botões. Teclado hoje, botoeira depois.

A regra do projeto é "software primeiro": o jogo tem que estar jogável com teclado,
sem hardware nenhum. Este contrato é o que garante isso — o motor do jogo recebe
uma `FonteEntrada` e nunca importa `serial`. Trocar teclado por botoeira é trocar
a implementação injetada, e nada mais no jogo muda.

`pyserial` NÃO está instalado no venv compartilhado (medido). O import dele mora
dentro da implementação serial, tardio, para que a ausência do pacote não derrube
o jogo de teclado.

FEEDBACK É PARTE DO CONTRATO, NÃO ENFEITE
-----------------------------------------
O botão do visitante enfileira uma intenção e ela só é consumida no próximo tick
da grade, sujeita a verde mínimo. Sem retorno visual o visitante conclui que o
botão quebrou e para de jogar — é o detalhe que decide se a rodada funciona. Por
isso `feedback()` é obrigatório na interface, e o teclado o implementa acendendo
na tela o que a botoeira acenderia no LED.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Índice reservado: o botão grande de começar/abortar a rodada.
BOTAO_START = -1

# Estados de feedback por botão. A botoeira mapeia em LED; o teclado, em pixel.
OFF = "off"        # nada armado
ARMADO = "armed"   # intenção registrada, esperando o próximo tick
ACEITO = "on"      # a troca foi aceita neste tick
NEGADO = "deny"    # recusada: verde mínimo ainda não cumpriu, ou TL não controlável
ESTADOS = (OFF, ARMADO, ACEITO, NEGADO)


@dataclass(frozen=True)
class EventoBotao:
    """Uma BORDA de pressionamento. Nunca "o botão está apertado".

    Borda e não nível de propósito: o jogo consome intenções discretas, e um
    visitante que segura o botão não deve gerar uma troca por tick.
    """

    indice: int           # 0..n-1 = semáforo; BOTAO_START = começar/abortar
    t_wall: float = field(default_factory=time.monotonic)

    @property
    def e_start(self) -> bool:
        return self.indice == BOTAO_START


@runtime_checkable
class FonteEntrada(Protocol):
    """Teclado, botoeira serial, replay gravado ou nada — todos falam isto."""

    n_botoes: int         # semáforos controláveis (o START não conta)
    nome: str

    def poll(self) -> list[EventoBotao]:
        """Eventos desde a última chamada. NÃO bloqueia. Ordem cronológica."""
        ...

    def feedback(self, estados: list[str]) -> None:
        """Um estado de `ESTADOS` por botão. Chamado a cada tick de decisão."""
        ...

    def viva(self) -> bool:
        """A fonte ainda responde? (botoeira desconectada -> False -> cai p/ teclado.)"""
        ...

    def close(self) -> None:
        ...


def valida_estados(estados: list[str], n: int) -> list[str]:
    """Valida o vetor de feedback. Chamado pelas implementações, não pelo jogo."""
    if len(estados) != n:
        raise ValueError("feedback deve ter %d estados, veio %d" % (n, len(estados)))
    ruins = sorted(set(estados) - set(ESTADOS))
    if ruins:
        raise ValueError("estados desconhecidos %r (use %r)" % (ruins, ESTADOS))
    return estados


# --------------------------------------------------------------------- protocolo serial
# ASCII por linha, sobre USB CDC. Depurável em qualquer terminal e falsificável por
# script — é o que torna `SerialInput` testável sem a botoeira na mesa.
#
#   dispositivo -> host          host -> dispositivo
#   HELLO botoeira v1 n=12       LED <i> <off|armed|on|deny>
#   BTN <i>                      LEDS <n+1 chars, 1 por botao>
#   START                        RESET
#   PING                         (heartbeat de resposta nao e necessario)
#
# O microcontrolador NÃO tem lógica de jogo: reporta bordas e acende o que mandarem.
PROTO_VERSAO = "botoeira v1"
PROTO_BAUD = 115200          # ignorado no CDC, mas explícito p/ adaptadores FTDI
PROTO_TIMEOUT_S = 2.0        # sem PING neste prazo -> viva() vira False
PROTO_CHAR = {OFF: "o", ARMADO: "a", ACEITO: "n", NEGADO: "d"}
