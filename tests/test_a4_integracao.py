"""A4 × A3 — a botoeira dentro da plumbing real do jogo, não num laço de brinquedo.

O item (c) do DoD do A4 ("desconectar o USB no meio da rodada não derruba o
jogo") é provado em `test_a4_resiliencia.py` contra um motor de mentira. Aqui ele
é provado contra a peça **de verdade** do agente A3, `FonteComReserva` — que é
onde a queda acontece na feira.

Este arquivo é a costura entre dois agentes que rodaram em paralelo: se o A3
mudar o contrato da reserva, ou eu mudar a semântica de `viva()`, quebra aqui e
não na véspera.
"""
from __future__ import annotations

import pytest

from feira.contratos import ACEITO, ARMADO, BOTAO_START, NEGADO, OFF, FonteEntrada
from feira.entrada_serial import SerialFalso, SerialInput

entrada = pytest.importorskip("feira.entrada",
                              reason="camada de entrada do A3 ainda não entregue")
FonteComReserva = entrada.FonteComReserva
LeitorRoteirizado = entrada.LeitorRoteirizado
TecladoInput = entrada.TecladoInput


def _conjunto(roteiro_teclado=None):
    dev = SerialFalso([])
    botoeira = SerialInput(dev)
    teclado = TecladoInput(12, leitor=LeitorRoteirizado(roteiro_teclado or []))
    return dev, botoeira, FonteComReserva(botoeira, teclado)


def test_o_conjunto_botoeira_mais_teclado_satisfaz_o_c6():
    _dev, _bot, fonte = _conjunto()
    assert isinstance(fonte, FonteEntrada)
    assert fonte.n_botoes == 12
    assert "botoeira" in fonte.nome and "teclado" in fonte.nome


def test_com_a_botoeira_viva_o_teclado_nao_atrapalha():
    """As duas fontes ficam ligadas ao mesmo tempo. Enquanto a botoeira responde,
    tecla apertada por engano (ou um `p` que sobrou no buffer do console) não
    pode virar troca de fase."""
    dev, _bot, fonte = _conjunto(["q", "w"])
    dev.aperta(5)
    assert [e.indice for e in fonte.poll()] == [5]
    assert fonte.caiu is False


def test_o_cabo_saindo_troca_para_o_teclado_sem_perder_um_tick():
    """A troca não custa um tick: o mesmo `poll()` que detecta a queda já devolve
    o que o teclado tinha. Um tick perdido em cima da queda é meio segundo de
    painel morto — o momento em que o visitante mais duvida do jogo."""
    dev, _bot, fonte = _conjunto(["", "q", "w"])
    dev.aperta(2)
    assert [e.indice for e in fonte.poll()] == [2]

    dev.desconecta()                                  # <<< o cabo sai da tomada

    eventos = fonte.poll()
    assert fonte.caiu is True
    assert fonte.quedas == 1
    assert fonte.viva(), "o conjunto continua vivo — é o ponto dele"
    assert eventos, "o teclado assumiu já neste tick"
    assert [e.indice for e in fonte.poll()] != []     # e segue jogando


def test_o_feedback_continua_saindo_depois_da_queda():
    """LED que não acende não pode derrubar a rodada — e a projeção (A7) lê os
    estados do teclado, então o visitante continua vendo retorno na tela."""
    dev, _bot, fonte = _conjunto()
    estados = [ARMADO, ACEITO, NEGADO] + [OFF] * 9
    fonte.feedback(list(estados))
    assert dev.leds[:12] == estados

    dev.desconecta()
    fonte.poll()
    fonte.feedback([NEGADO] * 12)                     # não levanta
    assert fonte.reserva.estados == [NEGADO] * 12


def test_start_da_botoeira_e_start_do_teclado_chegam_iguais_ao_motor():
    dev, _bot, fonte = _conjunto(["", "\r"])
    dev.aperta(BOTAO_START)
    (a,) = fonte.poll()
    assert a.e_start

    dev.desconecta()
    (b,) = fonte.poll()                               # o "\r" do teclado, no tick da queda
    assert b.e_start and b.indice == a.indice == BOTAO_START


def test_botoeira_de_n_diferente_e_recusada_na_montagem():
    """Painel de 6 num cenário de 12: `FonteComReserva` recusa antes de rodar.

    Sem isso o índice do botão significaria coisas diferentes nas duas fontes, e a
    queda para o teclado trocaria o cruzamento errado no meio da rodada.
    """
    seis = SerialInput(SerialFalso([], n_botoes=6), n_botoes=6)
    with pytest.raises(ValueError, match="botões"):
        FonteComReserva(seis, TecladoInput(12, leitor=LeitorRoteirizado([])))


def test_reconecta_so_vale_entre_rodadas():
    """`reconecta()` do A3 pede `primaria.viva()`. A minha morte é definitiva de
    propósito: replugar o USB dá uma porta COM nova, e quem reabre é o motor."""
    dev, botoeira, fonte = _conjunto()
    dev.desconecta()
    fonte.poll()
    assert fonte.caiu
    dev._desconectada = False                         # "o cabo voltou"
    dev.ping()
    assert botoeira.viva() is False
    assert fonte.reconecta() is False, "só um `abre_botoeira()` novo ressuscita"
