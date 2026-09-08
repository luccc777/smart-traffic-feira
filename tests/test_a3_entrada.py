"""Camada de entrada (C6) — teclado, replay e queda para a reserva.

Nada aqui precisa de SUMO, de `pyserial` nem de console: é o ponto do agente A3.
"""
from __future__ import annotations

import pytest

from feira.contratos import ACEITO, ARMADO, BOTAO_START, NEGADO, OFF, FonteEntrada, valida_estados
from feira.entrada import (
    MAPA_TECLAS,
    FonteComReserva,
    GravacaoRodada,
    LeitorRoteirizado,
    ReplayInput,
    TecladoInput,
    caminho_gravacao,
    linhas_do_mapa,
)


# ------------------------------------------------------------------ teclado
def test_teclado_satisfaz_o_protocolo():
    f = TecladoInput(12)
    assert isinstance(f, FonteEntrada)
    assert f.n_botoes == 12 and f.nome == "teclado"


def test_teclado_sem_pyserial_e_sem_console():
    """DoD (a): a rodada tem que subir sem `pyserial` e sem console.

    Importar o pacote de entrada não pode puxar `serial` — ele NÃO está
    instalado no venv compartilhado, e isso é de propósito."""
    import sys

    import feira.entrada  # noqa: F401

    assert "serial" not in sys.modules
    # sem console (é o caso do pytest com saída capturada) o poll devolve vazio
    # em vez de levantar: o jogo continua de pé.
    assert TecladoInput(12).poll() == []


def test_teclado_decodifica_o_bloco_3x4():
    """`Q W E R / A S D F / Z X C V` é isomorfo à ordem `H1V1..H3V4` da rede."""
    f = TecladoInput(12, leitor=LeitorRoteirizado(["qwer", "asdf", "zxcv"]))
    assert [e.indice for e in f.poll()] == [0, 1, 2, 3]
    assert [e.indice for e in f.poll()] == [4, 5, 6, 7]
    assert [e.indice for e in f.poll()] == [8, 9, 10, 11]
    assert f.poll() == []
    assert MAPA_TECLAS["q"] == 0 and MAPA_TECLAS["v"] == 11


def test_teclado_espaco_e_start_e_maiuscula_vale():
    f = TecladoInput(12, leitor=LeitorRoteirizado([" ", "Q", "?"]))
    assert f.poll()[0].e_start
    assert [e.indice for e in f.poll()] == [0]
    assert f.poll() == [] and f.n_desconhecidas == 1


def test_teclado_ignora_botao_alem_do_painel():
    """Painel de 6 botões (a rede fechada tem 6 controláveis): as teclas de
    cima existem e não fazem nada, em vez de indexar semáforo que não há."""
    f = TecladoInput(6, leitor=LeitorRoteirizado(["qz"]))
    assert [e.indice for e in f.poll()] == [0]


def test_teclado_guarda_o_feedback_para_a_projecao():
    f = TecladoInput(12)
    f.feedback([ARMADO] + [OFF] * 11)
    assert f.estados[0] == ARMADO
    with pytest.raises(ValueError, match="12 estados"):
        f.feedback([OFF] * 11)
    with pytest.raises(ValueError, match="desconhecid"):
        f.feedback(["piscando"] + [OFF] * 11)


def test_teclado_so_morre_quando_fechado():
    f = TecladoInput(12)
    assert f.viva()
    f.close()
    assert not f.viva() and f.poll() == []


def test_linhas_do_mapa_para_a_tela_do_operador():
    assert len(linhas_do_mapa(12)) == 3
    assert linhas_do_mapa(4) == ["Q=0  W=1  E=2  R=3"]


# ------------------------------------------------------------------- replay
def test_replay_satisfaz_o_protocolo_e_devolve_bordas():
    f = ReplayInput(12, [[0, 3], [], [BOTAO_START]])
    assert isinstance(f, FonteEntrada)
    assert [e.indice for e in f.poll()] == [0, 3]
    assert f.poll() == []
    assert [e.indice for e in f.poll()] == [BOTAO_START]
    assert f.poll() == [] and f.esgotado


def test_replay_rebobina():
    f = ReplayInput(12, [[1], [2]])
    assert [e.indice for e in f.poll()] == [1]
    f.rebobina()
    assert [e.indice for e in f.poll()] == [1]
    assert f.feedbacks == []


def test_replay_avisa_que_anda_por_tick():
    """`passo_por_tick` é o que impede o `bombeia()` (que existe para o LED
    responder no ato) de consumir slots fora do tick da grade."""
    assert ReplayInput().passo_por_tick is True
    assert TecladoInput().passo_por_tick is False


def test_gravacao_round_trip_e_confere_a_chave(tmp_path):
    from feira import _fakes as F

    chave = F.chave_fake(seed=100, t0=300.0, t1=420.0)
    g = GravacaoRodada.de(chave, n_botoes=12, fonte="teclado",
                          ticks=[(0,), (), (3, 7)])
    caminho = caminho_gravacao(tmp_path, chave, "r000")
    g.salva(caminho)
    lida = GravacaoRodada.carrega(caminho)
    assert lida == g and lida.n_pressoes == 3
    lida.confere(chave)
    with pytest.raises(ValueError, match="não serve"):
        lida.confere(F.chave_fake(seed=101, t0=300.0, t1=420.0))


def test_gravacao_vira_fonte_de_replay():
    from feira import _fakes as F

    g = GravacaoRodada.de(F.chave_fake(), n_botoes=12, fonte="teclado",
                          ticks=[(0, 1), (), (5,)])
    f = g.fonte_de_replay()
    assert [e.indice for e in f.poll()] == [0, 1]
    assert f.poll() == []
    assert [e.indice for e in f.poll()] == [5]


# ------------------------------------------------------------------ reserva
def test_reserva_assume_quando_a_primaria_morre():
    """DoD (c) do agente A4, provado sem hardware: desconectar no meio da
    rodada não derruba o jogo."""
    from feira._fakes import FonteEntradaFake

    prim = FonteEntradaFake(12, [[0], [1], [2]])
    res = ReplayInput(12, [[9], [9], [9]])
    f = FonteComReserva(prim, res)
    assert [e.indice for e in f.poll()] == [0]
    prim.desconecta()
    assert [e.indice for e in f.poll()] == [9]     # caiu para a reserva
    assert f.caiu and f.quedas == 1 and f.viva()


def test_reserva_recusa_painel_de_tamanho_diferente():
    with pytest.raises(ValueError, match="botões"):
        FonteComReserva(TecladoInput(12), TecladoInput(6))


def test_reserva_publica_feedback_nas_duas():
    a, b = TecladoInput(12), TecladoInput(12)
    f = FonteComReserva(a, b)
    f.feedback([NEGADO] + [OFF] * 11)
    assert a.estados[0] == NEGADO and b.estados[0] == NEGADO
    assert valida_estados(f.ativa.estados, 12)[0] == NEGADO


def test_reserva_nao_volta_sozinha_no_meio_da_rodada():
    from feira._fakes import FonteEntradaFake

    prim = FonteEntradaFake(12, [[0], [1]])
    f = FonteComReserva(prim, ReplayInput(12, [[], []]))
    prim.desconecta()
    f.poll()
    prim._viva = True                  # o cabo voltou sozinho
    assert f.caiu                      # ...e o jogo NÃO troca no meio
    assert f.reconecta() and not f.caiu


def test_reserva_repassa_aceito_sem_derrubar_fonte_quebrada():
    class Quebrada(TecladoInput):
        def feedback(self, estados):
            raise RuntimeError("LED em curto")

    f = FonteComReserva(Quebrada(12), TecladoInput(12))
    f.feedback([ACEITO] * 12)          # não pode levantar
    assert f.reserva.estados[0] == ACEITO


# ==================================================== conformidade, espelhada
# `tests/test_conformidade.py` está congelado. As duas fábricas abaixo são as que
# devem entrar em `IMPLS_ENTRADA` — e passam a suíte de lá sem alteração nenhuma
# na sequência esperada `[0,3] -> [] -> [START] -> []`:
#
#     pytest.param(_teclado_conforme, id="teclado"),
#     pytest.param(_replay_conforme,  id="replay"),
def _teclado_conforme():
    return TecladoInput(12, leitor=LeitorRoteirizado(["qr", "", " "]))


def _replay_conforme():
    return ReplayInput(12, [[0, 3], [], [BOTAO_START]])


IMPLS_ENTRADA = [
    pytest.param(_teclado_conforme, id="teclado"),
    pytest.param(_replay_conforme, id="replay"),
]


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA)
def test_conformidade_protocolo(fabrica):
    f = fabrica()
    assert isinstance(f, FonteEntrada)
    assert f.n_botoes == 12 and isinstance(f.nome, str)


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA)
def test_conformidade_bordas_sem_bloquear(fabrica):
    f = fabrica()
    assert [e.indice for e in f.poll()] == [0, 3]
    assert f.poll() == []
    assert [e.indice for e in f.poll()] == [BOTAO_START]
    assert f.poll() == []


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA)
def test_conformidade_feedback(fabrica):
    f = fabrica()
    f.feedback([OFF] * 12)
    f.feedback([ARMADO, ACEITO, NEGADO] + [OFF] * 9)
    with pytest.raises(ValueError, match="12 estados"):
        f.feedback([OFF] * 11)
    with pytest.raises(ValueError, match="desconhecid"):
        f.feedback(["piscando"] + [OFF] * 11)


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA)
def test_conformidade_reporta_morte(fabrica):
    f = fabrica()
    assert f.viva()
    f.close()
    assert not f.viva()
