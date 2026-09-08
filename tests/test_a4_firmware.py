"""A4 — a lógica do firmware do Pico, exercitada no CPython.

`firmware/botoeira/protocolo.py` é escrito no subconjunto que roda igual no
MicroPython e aqui, exatamente para que debounce, parser e mapeamento dos 74HC595
não fiquem sendo "código que só a placa sabe se está certo". O arquivo importado
aqui é O MESMO que sobe para o Pico — não há reimplementação de teste.

O que continua sendo hardware e está marcado como tal em `docs/BOTOEIRA.md`:
período real do laço, corrente de LED, ruído de contato e a cascata dos 595 no fio.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from feira.contratos import (
    ACEITO,
    ARMADO,
    BOTAO_START,
    ESTADOS,
    NEGADO,
    OFF,
    PROTO_CHAR,
    PROTO_TIMEOUT_S,
    PROTO_VERSAO,
)

FIRMWARE = Path(__file__).resolve().parents[1] / "firmware" / "botoeira" / "protocolo.py"


def _carrega():
    spec = importlib.util.spec_from_file_location("botoeira_protocolo", FIRMWARE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _carrega()


# ------------------------------------------ o teste que impede a divergência


def test_constantes_do_firmware_batem_com_o_contrato():
    """O Pico não importa `feira.contratos`; as constantes estão repetidas lá.

    Duas listas divergem — já divergiram neste projeto (o `YELLOW_DUR` literal do
    maquete). Este teste é a única coisa que segura a divergência: se alguém mexer
    no C6 e esquecer do firmware, aqui fica vermelho antes da feira.
    """
    assert P.VERSAO == PROTO_VERSAO
    assert P.BOTAO_START == BOTAO_START
    assert tuple(P.ESTADOS) == tuple(ESTADOS)
    assert P.CHAR == PROTO_CHAR
    assert P.CHAR_INV == {c: e for e, c in PROTO_CHAR.items()}
    assert P.N_BOTOES == 12
    # PING a 1 Hz contra 2 s de tolerância = dois heartbeats perdidos ainda passam.
    assert P.PING_MS / 1000.0 <= PROTO_TIMEOUT_S / 2


def test_hello_do_firmware_e_o_que_o_host_espera():
    from feira.entrada_serial import SerialFalso
    assert P.linha_hello() == SerialFalso([])._hello()


@pytest.mark.parametrize("indice,esperado", [(0, "BTN 0"), (11, "BTN 11"),
                                             (BOTAO_START, "START")])
def test_linha_de_botao(indice, esperado):
    assert P.linha_btn(indice) == esperado


# ----------------------------------------------------------------- debounce


def _pressiona(deb, t, quais, n=13):
    nivel = [i in quais for i in range(n)]
    return deb.passo(t, nivel)


def test_borda_sai_na_primeira_deteccao_sem_pagar_o_debounce():
    """O ponto do desenho: 0 ms de contribuição para a latência, não 15 ms.

    Se este teste virar "só reporta depois de DEBOUNCE_MS", o orçamento de
    latência do DoD (d) precisa ser refeito.
    """
    deb = P.Debounce(13)
    deb.sincroniza([False] * 13)
    assert _pressiona(deb, 0, {4}) == [4]        # mesmo laço em que o contato desce


def test_repique_do_contato_nao_vira_dois_eventos():
    """Micro-switch ricocheteando por ~5 ms: um aperto, um evento."""
    deb = P.Debounce(13)
    deb.sincroniza([False] * 13)
    assert _pressiona(deb, 0, {4}) == [4]
    for t in (1, 2, 3, 5, 8):                    # solta/aperta dentro dos 15 ms
        assert _pressiona(deb, t, set()) == []
        assert _pressiona(deb, t, {4}) == []
    assert _pressiona(deb, 40, set()) == []      # soltou pra valer
    assert _pressiona(deb, 60, {4}) == [4]       # novo aperto legítimo


def test_botao_segurado_gera_uma_borda_so():
    """O C6 exige BORDA, não nível: quem segura não troca de fase por tick."""
    deb = P.Debounce(13)
    deb.sincroniza([False] * 13)
    assert _pressiona(deb, 0, {7}) == [7]
    for t in range(1, 3000, 7):                  # 3 s de dedo em cima
        assert _pressiona(deb, t, {7}) == []


def test_botao_emperrado_no_boot_nao_vira_aperto_fantasma():
    """Plugar o USB com um dedo no botão não pode começar a rodada sozinho."""
    deb = P.Debounce(13)
    deb.sincroniza([i == 12 for i in range(13)])     # START já apertado no boot
    assert _pressiona(deb, 0, {12}) == []
    assert _pressiona(deb, 100, set()) == []
    assert _pressiona(deb, 200, {12}) == [12]        # o primeiro aperto DE VERDADE


def test_os_13_apertados_juntos_saem_juntos():
    deb = P.Debounce(13)
    deb.sincroniza([False] * 13)
    assert _pressiona(deb, 0, set(range(13))) == list(range(13))


# -------------------------------------------------- parser de comando do host


def test_interpreta_quadro_leds_completo():
    quadro = "".join(P.CHAR[e] for e in [ARMADO] * 12) + P.CHAR[ACEITO]
    tipo, dado = P.interpreta("LEDS " + quadro)
    assert tipo == "leds"
    assert dado == [ARMADO] * 12 + [ACEITO]


@pytest.mark.parametrize("linha", [
    "LEDS ooo",                                  # curto demais
    "LEDS " + "o" * 14,                          # longo demais
    "LEDS " + "o" * 12 + "z",                    # char fora do PROTO_CHAR
    "LED 3",                                     # faltando estado
    "LED 3 piscando",                            # estado inventado
    "LED tres on",                               # índice não numérico
    "LED 12345 on",                              # índice fora de faixa
    "REBOOT",                                    # comando inexistente
    "",                                          # linha vazia
])
def test_comando_torto_e_ignorado_e_nao_derruba_o_painel(linha):
    tipo, _dado = P.interpreta(linha)
    assert tipo is None


@pytest.mark.parametrize("i_wire", [BOTAO_START, 12])
def test_led_do_start_pelos_dois_enderecos(i_wire):
    tipo, dado = P.interpreta("LED %d on" % i_wire)
    assert (tipo, dado) == ("led", (P.I_START, ACEITO))


def test_reset():
    assert P.interpreta("RESET") == ("reset", None)


def test_acumulador_de_linhas_remonta_comando_partido():
    """A CDC entrega o que quiser: `LEDS oo` agora, o resto do quadro depois."""
    lin = P.Linhas()
    assert lin.alimenta("LEDS oo") == []
    assert lin.alimenta("oooooooo") == []
    (remontada,) = lin.alimenta("oon\nRES")
    assert remontada == "LEDS " + "o" * 12 + "n"
    assert P.interpreta(remontada) == ("leds", [OFF] * 12 + [ACEITO])
    assert lin.alimenta("ET\n") == ["RESET"]


def test_acumulador_descarta_lixo_sem_quebra_de_linha():
    lin = P.Linhas(limite=64)
    for _ in range(10):
        assert lin.alimenta("x" * 64) == []
    assert lin.descartadas > 0
    assert lin.alimenta("RESET\n") == ["RESET"]  # e volta ao normal


# ---------------------------------------- piscada e mapeamento dos 74HC595


def test_os_quatro_estados_sao_distinguiveis_no_tempo():
    """Um 74HC595 liga ou desliga. A diferença entre os 4 estados é temporal."""
    janela = range(0, 1000, 5)
    ligado = {e: [P.aceso(e, t) for t in janela] for e in ESTADOS}
    assert not any(ligado[OFF])
    assert all(ligado[ACEITO])
    # 4 Hz contra 10 Hz: contagem de transições separa os dois de relance.
    def transicoes(v):
        return sum(1 for a, b in zip(v, v[1:]) if a != b)
    assert 0 < transicoes(ligado[ARMADO]) < transicoes(ligado[NEGADO])


def test_armado_pisca_a_4hz_e_negado_a_10hz():
    assert P.aceso(ARMADO, 0) and not P.aceso(ARMADO, 130)
    assert P.aceso(ARMADO, 260)                  # período 250 ms
    assert P.aceso(NEGADO, 0) and not P.aceso(NEGADO, 60)
    assert P.aceso(NEGADO, 110)                  # período 100 ms


@pytest.mark.parametrize("indice", [*range(12), 12])
def test_cada_led_acende_exatamente_um_bit_da_cascata(indice):
    """Fiação: botão i -> um bit, e só ele. Errar aqui acende o cruzamento vizinho.

    Mapa: U1 QA..QH = 0..7; U2 QA..QD = 8..11; U2 QE = START; QF = heartbeat.
    """
    estados = [OFF] * 13
    estados[indice] = ACEITO
    u2, u1 = P.palavra_595(estados, 0)
    palavra = (u2 << 8) | u1
    # U1 bit i = botão i (0..7); U2 bit j = botão 8+j (8..11) e j=4 é o START.
    esperado = 1 << indice
    assert palavra == esperado, "bit errado para o índice %d" % indice
    assert bin(palavra).count("1") == 1


def test_ordem_da_cascata_e_u2_primeiro():
    """`U1.QH'` alimenta o `U2.SER`: o PRIMEIRO byte a sair para no ÚLTIMO chip.

    Inverter isto é o erro de montagem mais caro: os 12 semáforos acendem no
    lugar do START e vice-versa, e o painel deixa de ser um mapa.
    """
    estados = [ACEITO] * 8 + [OFF] * 5           # só o U1 aceso
    assert P.palavra_595(estados, 0) == bytes([0x00, 0xFF])
    estados = [OFF] * 8 + [ACEITO] * 4 + [OFF]   # só botões 8..11 (U2 QA..QD)
    assert P.palavra_595(estados, 0) == bytes([0x0F, 0x00])


def test_heartbeat_ocupa_qf_e_nao_atrapalha_os_13():
    apagado = P.palavra_595([OFF] * 13, 0, heartbeat=False)
    batendo = P.palavra_595([OFF] * 13, 0, heartbeat=True)
    assert apagado == bytes([0x00, 0x00])
    assert batendo == bytes([0x20, 0x00])        # U2 bit5 = QF


def test_reserva_de_saidas():
    """16 saídas, 13 botões + 1 heartbeat: sobram 2. É a margem prometida no plano."""
    todos = P.palavra_595([ACEITO] * 13, 0, heartbeat=True)
    usados = bin((todos[0] << 8) | todos[1]).count("1")
    assert usados == 14
    assert 16 - usados == 2
