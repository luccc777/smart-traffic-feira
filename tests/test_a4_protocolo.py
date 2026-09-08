"""A4 — o protocolo serial do C6, ida e volta, contra o Pico em software.

Item (b) do DoD: *"13 botões e 13 LEDs cobertos por teste de protocolo (ida e
volta)"*. Ida = o dispositivo manda `BTN`/`START` e vira `EventoBotao`; volta = o
host manda `LEDS`/`LED` e o modelo do dispositivo decodifica os 13 estados. O
`SerialFalso` não é mock permissivo: ele levanta se o quadro tiver tamanho errado
ou caractere fora do `PROTO_CHAR`, então um `feedback()` torto aparece como falha
aqui e não como "chamada registrada".
"""
from __future__ import annotations

import pytest

from feira.contratos import (
    ACEITO,
    ARMADO,
    BOTAO_START,
    ESTADOS,
    NEGADO,
    OFF,
    PROTO_CHAR,
    PROTO_VERSAO,
)
from feira.entrada_serial import (
    BotoeiraAusente,
    BotoeiraIncompativel,
    SerialFalso,
    SerialInput,
    quadro_leds,
)

TODOS_OS_BOTOES = [*range(12), BOTAO_START]


@pytest.fixture
def dupla():
    """(dispositivo, host) já com o handshake feito e sem roteiro."""
    dev = SerialFalso([])
    return dev, SerialInput(dev)


# ---------------------------------------------------------------- handshake


def test_handshake_manda_reset_e_aceita_o_hello():
    dev = SerialFalso([])
    host = SerialInput(dev)
    assert "RESET" in dev.recebido
    assert host.hellos_recebidos >= 1
    assert host.n_botoes == 12
    assert host.viva()


def test_hello_de_outra_versao_e_recusado():
    """Firmware velho na placa é o erro que dá sintoma bizarro (LED trocado, botão
    mudo). Melhor recusar alto do que jogar meia rodada com painel errado."""
    dev = SerialFalso([], versao="botoeira v0")
    with pytest.raises(BotoeiraIncompativel, match="protocolo"):
        SerialInput(dev)


def test_hello_com_n_diferente_e_recusado():
    """Painel de 6 botões num cenário de 12 (ou o inverso) — o `n=` denuncia."""
    dev = SerialFalso([], n_botoes=6)
    with pytest.raises(BotoeiraIncompativel, match="n=6"):
        SerialInput(dev, n_botoes=12)


def test_sem_hello_no_prazo_levanta_ausente():
    """Cabo só-carga (o erro clássico do USB) enumera nada; placa muda, idem."""
    dev = SerialFalso([], hello_no_boot=False)
    dev._executa = lambda linha: None            # o falso deixa de responder RESET
    with pytest.raises(BotoeiraAusente, match="sem HELLO"):
        SerialInput(dev, prazo_hello_s=0.05)


# --------------------------------------------------------- ida: 13 botões


@pytest.mark.parametrize("indice", TODOS_OS_BOTOES)
def test_cada_um_dos_13_botoes_vira_evento(indice, dupla):
    dev, host = dupla
    dev.aperta(indice)
    (evento,) = host.poll()
    assert evento.indice == indice
    assert evento.e_start == (indice == BOTAO_START)
    assert host.poll() == []                     # borda, não nível


def test_os_13_numa_rajada_saem_em_ordem_cronologica(dupla):
    dev, host = dupla
    for i in TODOS_OS_BOTOES:
        dev.aperta(i)
    assert [e.indice for e in host.poll()] == TODOS_OS_BOTOES


def test_btn_fora_de_faixa_e_ignorado_sem_derrubar(dupla):
    dev, host = dupla
    dev.emite("BTN 99")
    dev.emite("BTN abacaxi")
    dev.emite("QUALQUER COISA NOVA v2")
    dev.aperta(7)
    assert [e.indice for e in host.poll()] == [7]
    assert host.linhas_ignoradas == 3
    assert host.viva()


def test_linha_partida_entre_duas_leituras(dupla):
    """A CDC entrega meia linha quando quer. Sem o resto guardado, `BTN 11` viraria
    `BTN 1` + lixo — um semáforo errado trocando de fase na frente do público."""
    dev, host = dupla
    dev._rx.extend(b"BTN 1")
    assert host.poll() == []                     # nada completo ainda
    dev._rx.extend(b"1\nBTN 4\n")
    assert [e.indice for e in host.poll()] == [11, 4]


def test_ping_nao_vira_evento(dupla):
    dev, host = dupla
    for _ in range(5):
        dev.ping()
    assert host.poll() == []
    assert host.viva()


# --------------------------------------------------------- volta: 13 LEDs


def test_quadro_leds_tem_13_chars_e_o_start_e_o_ultimo(dupla):
    dev, host = dupla
    host.feedback([ARMADO] * 12)
    host.feedback_start(ACEITO)
    (linha,) = [ln for ln in dev.recebido if ln.startswith("LEDS ") and ln.endswith("n")]
    quadro = linha[5:]
    assert len(quadro) == 13
    assert quadro[:12] == PROTO_CHAR[ARMADO] * 12
    assert quadro[BOTAO_START] == PROTO_CHAR[ACEITO]      # quadro[-1] É o START
    assert dev.leds == [ARMADO] * 12 + [ACEITO]


@pytest.mark.parametrize("estado", ESTADOS)
@pytest.mark.parametrize("indice", TODOS_OS_BOTOES)
def test_cada_um_dos_13_leds_chega_no_dispositivo(indice, estado, dupla):
    """52 combinações (13 LEDs × 4 estados) pelo caminho do quadro inteiro."""
    dev, host = dupla
    estados = [OFF] * 12
    if indice == BOTAO_START:
        host.feedback_start(estado)
    else:
        estados[indice] = estado
        host.feedback(estados)
    esperado = [OFF] * 13
    esperado[indice] = estado                    # esperado[-1] = START
    assert dev.leds == esperado


@pytest.mark.parametrize("indice", TODOS_OS_BOTOES)
def test_comando_led_avulso_acende_o_led_certo(indice, dupla):
    """`LED <i> <estado>` — o caminho de bancada (`--chase`), não o do jogo."""
    dev, host = dupla
    host.led(indice, NEGADO)
    esperado = [OFF] * 13
    esperado[indice] = NEGADO
    assert dev.leds == esperado
    assert "LED %d %s" % (indice, NEGADO) in dev.recebido


def test_led_do_start_aceita_menos_um_e_doze():
    """`BOTAO_START` é -1 no contrato e a posição 12 no quadro. O firmware trata os
    dois como o MESMO LED físico — é o off-by-one mais provável desta interface."""
    dev = SerialFalso([])
    dev.write(b"LED -1 on\n")
    assert dev.leds[BOTAO_START] == ACEITO
    dev.write(b"LED 12 off\n")
    assert dev.leds[BOTAO_START] == OFF


def test_quadro_igual_nao_e_reenviado(dupla):
    """A grade de decisão chama `feedback()` a cada tick. Reenviar 20 bytes iguais
    para sempre enche a fila da CDC à toa; o espelho corta isso."""
    dev, host = dupla
    host.feedback([OFF] * 12)
    n = len([ln for ln in dev.recebido if ln.startswith("LEDS")])
    for _ in range(10):
        host.feedback([OFF] * 12)
    assert len([ln for ln in dev.recebido if ln.startswith("LEDS")]) == n
    host.feedback([ARMADO] + [OFF] * 11)         # mudou -> vai
    assert len([ln for ln in dev.recebido if ln.startswith("LEDS")]) == n + 1


def test_feedback_start_recusa_estado_invalido(dupla):
    _dev, host = dupla
    with pytest.raises(ValueError, match="desconhecid"):
        host.feedback_start("piscando")


def test_led_recusa_indice_fora_de_faixa(dupla):
    _dev, host = dupla
    with pytest.raises(ValueError, match="fora de faixa"):
        host.led(12, ACEITO)                     # 12 não é semáforo; START é -1


def test_quadro_leds_helper_recusa_estado_de_start_invalido():
    with pytest.raises(ValueError, match="START"):
        quadro_leds([OFF] * 12, "piscando")


# ------------------------------------------------ o Pico reiniciando sozinho


def test_hello_fora_de_hora_restaura_o_painel(dupla):
    """Watchdog do Pico dispara no meio da rodada: ele acorda com tudo apagado.

    Se o host não reenviar o quadro, o painel fica mentindo até a próxima MUDANÇA
    de estado — e o visitante que armou um cruzamento vê o LED apagar sozinho.
    """
    dev, host = dupla
    host.feedback([ARMADO] * 12)
    host.feedback_start(ACEITO)
    assert dev.leds == [ARMADO] * 12 + [ACEITO]
    n0 = host.hellos_recebidos

    dev.reinicia()                               # LEDs apagados + HELLO novo
    assert dev.leds == [OFF] * 13
    host.poll()                                  # é aqui que o HELLO é visto
    assert host.hellos_recebidos == n0 + 1
    assert dev.leds == [ARMADO] * 12 + [ACEITO]  # restaurado


def test_reset_do_host_apaga_tudo_e_pede_hello(dupla):
    dev, host = dupla
    host.feedback([ACEITO] * 12)
    n0 = host.hellos_recebidos
    host.reset()
    assert dev.leds == [OFF] * 13
    assert dev.resets == 2                       # o do handshake + este
    host.poll()
    assert host.hellos_recebidos == n0 + 1


def test_versao_do_protocolo_e_a_do_contrato():
    """O `HELLO` do modelo do dispositivo tem que ser o do C6, literal."""
    assert SerialFalso([])._hello() == "HELLO %s n=12" % PROTO_VERSAO
