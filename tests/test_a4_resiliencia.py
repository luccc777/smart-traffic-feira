"""A4 — o cabo saindo da tomada no meio da rodada.

Item (c) do DoD: *"desconectar o USB no meio da rodada não derruba o jogo —
`viva()` vira `False` e o motor cai para teclado"*. Este arquivo prova as duas
metades: (1) toda operação da fonte engole a falha da porta em vez de deixar o
traceback subir, e (2) um laço de rodada com a troca de fonte no meio termina
inteiro e continua consumindo botão.

São DUAS mortes diferentes, e confundir as duas é como se perde uma feira:

  - **cabo fora**: a porta levanta em `in_waiting`/`write`. Detecção imediata.
  - **Pico travado com o cabo no lugar**: a porta está ótima e muda. Só o
    `PING` a 1 Hz denuncia, e só depois de `PROTO_TIMEOUT_S` de silêncio.
"""
from __future__ import annotations

import pytest

from feira import _fakes as F
from feira.contratos import ACEITO, ARMADO, BOTAO_START, OFF, PROTO_TIMEOUT_S
from feira.entrada_serial import SerialFalso, SerialInput


class Relogio:
    """Relógio de mentira: o teste avança o tempo em vez de dormir 2 s."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def avanca(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def dupla():
    dev = SerialFalso([])
    return dev, SerialInput(dev)


# ------------------------------------------------- 1. o cabo saiu da tomada


def test_cabo_fora_nao_levanta_em_lugar_nenhum(dupla):
    dev, host = dupla
    assert host.viva()

    dev.desconecta()

    assert host.poll() == []                     # não levanta
    assert host.viva() is False
    host.feedback([ARMADO] * 12)                 # não levanta
    host.feedback_start(ACEITO)                  # não levanta
    host.close()                                 # não levanta
    assert "erro de" in (host.motivo_morte or "")


def test_evento_apertado_antes_da_queda_nao_se_perde(dupla):
    """O visitante apertou, o cabo caiu no mesmo instante. O aperto já estava no
    buffer: entregar é mais honesto do que descartar."""
    dev, host = dupla
    dev.aperta(5)
    host.viva()                                  # bombeia: o evento entra na fila
    dev.desconecta()
    assert [e.indice for e in host.poll()] == [5]
    assert host.viva() is False


def test_morte_e_definitiva_mesmo_se_o_cabo_voltar(dupla):
    """Replugar o USB dá uma porta COM NOVA — o objeto antigo não ressuscita.

    Quem reabre é o motor do jogo, chamando `abre_botoeira()` de novo. Uma fonte
    que "voltasse a viver" sozinha esconderia o fato de que o Pico reiniciou e o
    painel está apagado.
    """
    dev, host = dupla
    dev.desconecta()
    assert host.viva() is False
    dev._desconectada = False                    # o cabo "voltou" na mesma porta
    dev.ping()
    assert host.viva() is False


def test_close_mata(dupla):
    _dev, host = dupla
    assert host.viva()
    host.close()
    assert host.viva() is False


# ------------------------------------- 2. Pico travado, cabo no lugar (PING)


def test_silencio_de_ping_mata_no_prazo_do_contrato():
    rel = Relogio()
    dev = SerialFalso([])
    host = SerialInput(dev, relogio=rel)
    assert host.viva()

    rel.avanca(PROTO_TIMEOUT_S * 0.9)
    assert host.viva(), "ainda dentro do prazo do C6"

    rel.avanca(PROTO_TIMEOUT_S * 0.2)            # total 1,1 * timeout
    assert host.viva() is False, "silêncio > PROTO_TIMEOUT_S tem que matar"

    # E a porta continua perfeita: é o dispositivo que está mudo, não o cabo.
    assert host.motivo_morte is None


def test_ping_do_firmware_segura_a_fonte_viva():
    """1 Hz contra 2 s de tolerância: dois PINGs perdidos ainda passam."""
    rel = Relogio()
    dev = SerialFalso([])
    host = SerialInput(dev, relogio=rel)
    for _ in range(10):
        rel.avanca(1.0)
        dev.ping()
        assert host.viva()


def test_qualquer_linha_renova_a_vida_nao_so_o_ping():
    """Um visitante martelando botão prova liveness tão bem quanto o heartbeat."""
    rel = Relogio()
    dev = SerialFalso([])
    host = SerialInput(dev, relogio=rel)
    for _ in range(5):
        rel.avanca(1.5)
        dev.aperta(3)
        assert host.viva()
    rel.avanca(PROTO_TIMEOUT_S + 0.1)
    assert host.viva() is False


def test_viva_bombeia_a_porta_e_nao_perde_evento():
    """`viva()` tem efeito colateral de propósito — ver o docstring do método.

    Sem isso, um motor que perguntasse `viva()` ANTES de `poll()` mataria a
    botoeira por uma ordem de chamada: o PING estaria no buffer do sistema, não
    lido ainda, e o relógio já teria passado dos 2 s.
    """
    rel = Relogio()
    dev = SerialFalso([])
    host = SerialInput(dev, relogio=rel)
    rel.avanca(PROTO_TIMEOUT_S + 0.5)
    dev.ping()
    dev.aperta(9)
    assert host.viva() is True                   # leu o PING que estava no buffer
    assert [e.indice for e in host.poll()] == [9]


# ---------------------------------------- 3. a rodada inteira, com a queda


def test_rodada_sobrevive_a_queda_e_cai_para_o_teclado():
    """O item (c) do DoD encenado: 60 ticks de rodada, cabo arrancado no tick 20.

    O motor aqui é de brinquedo (5 linhas), mas o contrato exercitado é o real:
    `poll()`, `feedback()` e `viva()` do C6, e a troca de fonte quando `viva()`
    vira `False`. Nenhum `try/except` no motor — se `SerialInput` deixasse a
    exceção subir, este teste morreria com erro, não com falha de asserção.
    """
    dev = SerialFalso([])
    botoeira = SerialInput(dev)
    teclado = F.FonteEntradaFake(12, [[i % 12] for i in range(60)])

    fonte = botoeira
    trocas: list[int] = []
    quedas: list[int] = []
    estados = [OFF] * 12

    for tick in range(60):
        if tick < 20:
            dev.aperta(tick % 12)
        if tick == 20:
            dev.desconecta()                     # <<< o cabo sai da tomada
        if tick % 5 == 0:
            dev.ping()

        if not fonte.viva():                     # o motor decide, não a fonte
            quedas.append(tick)
            fonte.close()
            fonte = teclado

        for e in fonte.poll():
            if not e.e_start:
                trocas.append(e.indice)
        estados = [ARMADO if i in trocas[-3:] else OFF for i in range(12)]
        fonte.feedback(estados)

    assert quedas == [20], "a queda tem que ser detectada no tick seguinte, e uma vez só"
    assert fonte is teclado
    assert len(trocas) >= 40, "a rodada continuou consumindo botão depois da queda"
    assert teclado.feedbacks, "e o feedback continuou saindo — o visitante segue vendo LED"


def test_start_pela_botoeira_e_pelo_teclado_sao_o_mesmo_evento():
    """A troca de fonte não pode mudar a semântica: `BOTAO_START` é `BOTAO_START`."""
    dev = SerialFalso([])
    botoeira = SerialInput(dev)
    dev.aperta(BOTAO_START)
    (a,) = botoeira.poll()

    teclado = F.FonteEntradaFake(12, [[BOTAO_START]])
    (b,) = teclado.poll()

    assert a.indice == b.indice == BOTAO_START
    assert a.e_start and b.e_start


def test_fila_de_eventos_nao_cresce_sem_limite():
    """Motor travado sem chamar `poll()` não pode virar vazamento de memória.

    Descarta o MAIS ANTIGO: se o jogo voltar a si, o que interessa é o último
    aperto do visitante, não o primeiro de um minuto atrás.
    """
    from feira.entrada_serial import LIMITE_PENDENTES

    dev = SerialFalso([])
    host = SerialInput(dev)
    for i in range(LIMITE_PENDENTES + 50):
        dev.aperta(i % 12)
        host.viva()                              # bombeia sem colher
    eventos = host.poll()
    assert len(eventos) == LIMITE_PENDENTES
    assert eventos[-1].indice == (LIMITE_PENDENTES + 49) % 12


def test_lixo_infinito_sem_quebra_de_linha_nao_estoura_memoria():
    """Firmware em pane cuspindo bytes sem `\\n` — o resto tem teto."""
    from feira.entrada_serial import LIMITE_RESTO_B

    dev = SerialFalso([])
    host = SerialInput(dev)
    for _ in range(10):
        dev._rx.extend(b"x" * LIMITE_RESTO_B)
        host.poll()
    assert len(host._resto) <= LIMITE_RESTO_B
    assert host.linhas_ignoradas > 0
