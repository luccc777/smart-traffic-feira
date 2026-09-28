"""A9 — `FonteWeb` (o teclado junto do projetor, lido pela página) e `FonteComposta`
(várias fontes ao mesmo tempo). Ver docs/GAMIFICACAO.md §3.3.
"""
from __future__ import annotations

import pytest

from feira.contratos import ACEITO, ARMADO, BOTAO_START, NEGADO, OFF
from feira.entrada import FonteComposta, FonteWeb, LeitorRoteirizado, TecladoInput


# ----------------------------------------------------------------- FonteWeb
def test_teclas_da_pagina_viram_bordas_no_mapa_do_teclado():
    f = FonteWeb(12)
    for k in ("q", "W", "v", " ", "space", "Enter"):
        f.recebe({"tipo": "tecla", "k": k})
    assert [e.indice for e in f.poll()] == [0, 1, 11, BOTAO_START, BOTAO_START, BOTAO_START]
    assert f.poll() == []


def test_botao_por_indice_e_start_explicito():
    f = FonteWeb(12)
    f.recebe({"tipo": "botao", "i": 3})
    f.recebe({"tipo": "start"})
    f.recebe({"tipo": "botao", "i": 12})          # fora do painel: contado, ignorado
    assert [e.indice for e in f.poll()] == [3, BOTAO_START]
    assert f.n_desconhecidas == 1


def test_lixo_nao_levanta_e_e_contado():
    f = FonteWeb(12)
    f.recebe({"tipo": "tecla", "k": "ç"})
    f.recebe({"tipo": "botao", "i": "x"})
    f.recebe({"tipo": "?"})
    f.recebe({})
    f.recebe({"tipo": "ping"})
    assert f.poll() == [] and f.n_desconhecidas == 4 and f.n_mensagens == 5


def test_abortar_vai_para_o_operador_e_nao_vira_evento():
    chamadas = []
    f = FonteWeb(12, ao_abortar=lambda: chamadas.append(1))
    f.recebe({"tipo": "abortar"})
    f.recebe({"tipo": "tecla", "k": "Escape"})
    assert f.poll() == [] and chamadas == [1, 1] and f.n_abortos == 2


def test_feedback_publica_o_quadro_de_leds_para_a_pagina():
    quadros = []
    f = FonteWeb(12, ao_feedback=quadros.append)
    f.feedback([ARMADO, ACEITO, NEGADO] + [OFF] * 9, start=ACEITO)
    f.feedback_start(NEGADO)
    assert quadros[0] == {"tipo": "leds", "estados": [ARMADO, ACEITO, NEGADO] + [OFF] * 9,
                          "start": ACEITO}
    assert quadros[1]["start"] == NEGADO and quadros[1]["estados"][0] == ARMADO
    with pytest.raises(ValueError):
        f.feedback([OFF] * 11)


def test_feedback_que_explode_na_pagina_nao_derruba_a_rodada():
    def explode(_):
        raise RuntimeError("cliente morto")

    f = FonteWeb(12, ao_feedback=explode)
    f.feedback([OFF] * 12)          # não levanta


def test_a_fonte_web_so_morre_com_close():
    """`viva()` não cai quando a página some: F5 e reconectar é o caminho normal, e
    uma reserva de mão única (para o teclado do terminal, sem foco) seria pior."""
    f = FonteWeb(12)
    assert f.viva()
    f.close()
    assert not f.viva()
    f.recebe({"tipo": "start"})
    assert f.poll() == []


# ------------------------------------------------------------ FonteComposta
def test_composta_le_todas_e_ordena_por_tempo():
    t = 0.0

    def agora():
        nonlocal t
        t += 1.0
        return t

    web = FonteWeb(12, agora=agora)
    tec = TecladoInput(12, leitor=LeitorRoteirizado(["a", ""]))
    c = FonteComposta(web, tec)
    web.recebe({"tipo": "tecla", "k": "q"})
    ev = c.poll()
    assert sorted(e.indice for e in ev) == [0, 4]
    assert c.poll() == []
    assert c.n_botoes == 12 and "web" in c.nome and "teclado" in c.nome


def test_composta_repassa_feedback_e_abortar_a_todas():
    quadros, abortos = [], []
    web = FonteWeb(12, ao_feedback=quadros.append)
    tec = TecladoInput(12, leitor=LeitorRoteirizado(["\x1b"]))
    c = FonteComposta(web, tec)
    c.ao_abortar = lambda: abortos.append(1)
    c.feedback([ACEITO] + [OFF] * 11, start=ARMADO)
    c.feedback_start(NEGADO)
    assert tec.estados[0] == ACEITO and tec.start == NEGADO
    assert quadros[-1]["start"] == NEGADO
    c.poll()                                     # o Esc do teclado
    web.recebe({"tipo": "abortar"})
    assert abortos == [1, 1]


def test_composta_recusa_paineis_de_tamanhos_diferentes_e_lista_vazia():
    with pytest.raises(ValueError, match="botões diferentes"):
        FonteComposta(FonteWeb(12), FonteWeb(6))
    with pytest.raises(ValueError):
        FonteComposta()


def test_composta_esta_viva_enquanto_uma_responder():
    web, tec = FonteWeb(12), TecladoInput(12, leitor=LeitorRoteirizado([]))
    c = FonteComposta(web, tec)
    web.close()
    assert c.viva()
    c.close()
    assert not c.viva() and not tec.viva()


def test_o_tick_sai_marcado_e_com_o_t_simulado():
    quadros = []
    f = FonteWeb(12, ao_feedback=quadros.append)
    f.feedback([ARMADO] + [OFF] * 11)
    f.ao_tick(305.0)
    assert "tick" not in quadros[0]
    assert quadros[1]["tick"] is True and quadros[1]["t"] == 305.0
    assert quadros[1]["estados"][0] == ARMADO and f.n_ticks == 1 and f.t_tick == 305.0


def test_composta_repassa_o_tick():
    quadros = []
    web = FonteWeb(12, ao_feedback=quadros.append)
    c = FonteComposta(web, TecladoInput(12, leitor=LeitorRoteirizado([])))
    c.ao_tick(310.0)
    assert quadros[-1]["tick"] is True and quadros[-1]["t"] == 310.0
