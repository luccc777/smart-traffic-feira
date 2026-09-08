"""`ControladorHumano` (C3) — a intenção do botão vive na MESMA grade da RL.

O que estes testes existem para impedir: que o humano ganhe uma grade mais fina
que a da política. Se o botão pudesse trocar a fase fora do tick, ou antes do
verde mínimo, a comparação com a RL deixaria de ser pareada e o placar da feira
mediria outra coisa.
"""
from __future__ import annotations

import dataclasses
import random

import numpy as np
import pytest

from feira import _fakes as F
from feira.contratos import (
    ACEITO,
    ARMADO,
    BOTAO_START,
    MANTER,
    NEGADO,
    OFF,
    TROCAR,
    Controlador,
    RestricoesFase,
)
from feira.controladores.humano import ControladorHumano
from feira.entrada import ReplayInput, TecladoInput


@pytest.fixture
def topo():
    return F.topologia_fake(12, n_controlaveis=12)


@pytest.fixture
def restricoes():
    return RestricoesFase(decision_interval=5, min_green=7, yellow=3)


def _humano(roteiro, n=12):
    return ControladorHumano(ReplayInput(n, roteiro))


# ------------------------------------------------------------------- C3 base
def test_humano_satisfaz_o_protocolo(topo, restricoes):
    c = _humano([[0]])
    assert isinstance(c, Controlador)
    assert c.nome.startswith("humano:")


def test_humano_decide_antes_de_reset_falha(topo):
    with pytest.raises(RuntimeError, match="antes de reset"):
        _humano([[0]]).decide(F.observacao_fake(topo))


def test_humano_reset_e_idempotente(topo, restricoes):
    """Sem isto não há fantasma nem replay que preste: a mesma gravação tem que
    produzir a mesma sequência de ações."""
    c = _humano([[0], [1], [], [2, 3]])
    obs = [F.observacao_fake(topo, t=float(i)) for i in range(4)]
    c.reset(topo, restricoes, 0.0)
    a1 = [c.decide(o).copy() for o in obs]
    c.reset(topo, restricoes, 0.0)
    a2 = [c.decide(o).copy() for o in obs]
    assert all(np.array_equal(x, y) for x, y in zip(a1, a2))
    assert c.gravacao == [(0,), (1,), (), (2, 3)]


# --------------------------------------------------- a intenção e a grade
def test_intencao_e_consumida_no_proximo_tick(topo, restricoes):
    """O botão apertado entre dois ticks vira ação NO TICK seguinte — uma vez."""
    c = _humano([[3], []])
    c.reset(topo, restricoes, 0.0)
    a0 = c.decide(F.observacao_fake(topo, t=0.0))
    assert a0[3] == TROCAR and a0.sum() == 1
    a1 = c.decide(F.observacao_fake(topo, t=5.0))
    assert a1.sum() == 0                # a intenção foi GASTA, não repete


def test_segurar_o_botao_nao_gera_uma_troca_por_tick(topo, restricoes):
    """Bordas, não nível — e várias bordas no mesmo tick colapsam em uma
    intenção, porque o espaço de ação é um bit por tick."""
    c = _humano([[2, 2, 2], []])
    c.reset(topo, restricoes, 0.0)
    a = c.decide(F.observacao_fake(topo, t=0.0))
    assert a[2] == TROCAR and int(a.sum()) == 1
    assert int(c.decide(F.observacao_fake(topo, t=5.0)).sum()) == 0


def test_intencao_negada_e_descartada_e_nao_dispara_sozinha(topo, restricoes):
    """"Consumida no próximo tick" quer dizer GASTA. Guardar a intenção para
    disparar quando o verde fechasse daria ao humano um efeito que o bit da RL
    não tem."""
    c = _humano([[1], [], []])
    c.reset(topo, restricoes, 0.0)
    obs_cedo = dataclasses.replace(F.observacao_fake(topo, t=0.0),
                                   pode_trocar=np.zeros(topo.n, dtype=bool))
    assert int(c.decide(obs_cedo).sum()) == 0
    assert c.fonte.feedbacks[-1][1] == NEGADO
    # tick seguinte, agora liberado: nada dispara sozinho
    assert int(c.decide(F.observacao_fake(topo, t=5.0)).sum()) == 0


def test_humano_nunca_troca_fora_de_pode_trocar(topo, restricoes):
    """Varredura aleatória: o bit TROCAR só sai onde `pode_trocar` é True — que
    é, por construção da Arena, o mesmo predicado que o `TrafficEnv` usa para
    ACEITAR o switch (controlável ∧ ¬amarelo ∧ verde_desde ≥ min_green)."""
    rng = random.Random(7)
    c = _humano([[i for i in range(12) if rng.random() < 0.4] for _ in range(200)])
    c.reset(topo, restricoes, 0.0)
    for k in range(200):
        base = F.observacao_fake(topo, t=float(k * 5), rng=rng)
        pode = np.array([rng.random() < 0.5 for _ in range(topo.n)])
        amarelo = ~pode & np.array([rng.random() < 0.5 for _ in range(topo.n)])
        vd = np.where(pode, 99.0, 1.0)
        obs = dataclasses.replace(base, pode_trocar=pode, em_amarelo=amarelo,
                                  verde_desde=vd)
        a = c.decide(obs)
        assert not (a[~pode] == TROCAR).any()
        assert not (a[amarelo] == TROCAR).any()


def test_botao_de_tl_nao_controlavel_e_negado(restricoes):
    """A rede fechada tem 6 controláveis de 10: o painel continua com 12 botões
    e os mortos respondem `deny` em vez de indexar semáforo que não existe."""
    topo = F.topologia_fake(10, n_controlaveis=6)
    c = _humano([[8, 0]])
    c.reset(topo, restricoes, 0.0)
    obs = F.observacao_fake(topo, t=0.0)
    a = c.decide(obs)
    assert a[0] == TROCAR and int(a.sum()) == 1
    fb = c.fonte.feedbacks[-1]
    assert fb[0] == ACEITO and fb[8] == NEGADO and fb[11] == OFF


def test_mapa_de_botoes_customizado(topo, restricoes):
    c = ControladorHumano(ReplayInput(3, [[0], [1], [2]]),
                          mapa_botoes=(11, None, 5))
    c.reset(topo, restricoes, 0.0)
    assert c.decide(F.observacao_fake(topo, t=0.0))[11] == TROCAR
    assert int(c.decide(F.observacao_fake(topo, t=5.0)).sum()) == 0   # botão morto
    assert c.decide(F.observacao_fake(topo, t=10.0))[5] == TROCAR
    with pytest.raises(ValueError, match="mapa_botoes"):
        ControladorHumano(ReplayInput(3), mapa_botoes=(0, 1)).reset(topo, restricoes, 0.0)


# ---------------------------------------------------------------- feedback
def test_feedback_arma_no_ato_e_resolve_no_tick(topo, restricoes):
    """Sem retorno visual imediato o visitante conclui que o botão quebrou —
    é o motivo pelo qual `feedback()` é obrigatório no C6."""
    fonte = TecladoInput(12, leitor=__import__(
        "feira.entrada", fromlist=["LeitorRoteirizado"]).LeitorRoteirizado(["", "q", ""]))
    c = ControladorHumano(fonte)
    c.reset(topo, restricoes, 0.0)
    assert c.bombeia() == []                       # nenhum START
    assert fonte.estados[0] == ARMADO              # ...mas o LED já acendeu
    c.decide(F.observacao_fake(topo, t=0.0))
    assert fonte.estados[0] == ACEITO


def test_feedback_dura_ate_o_proximo_tick(topo, restricoes):
    c = _humano([[4], [], []])
    c.reset(topo, restricoes, 0.0)
    c.decide(F.observacao_fake(topo, t=0.0))
    assert c.fonte.feedbacks[-1][4] == ACEITO
    c.decide(F.observacao_fake(topo, t=5.0))
    assert c.fonte.feedbacks[-1][4] == OFF


def test_start_no_meio_da_rodada_chega_ao_motor(topo, restricoes):
    fonte = TecladoInput(12, leitor=__import__(
        "feira.entrada", fromlist=["LeitorRoteirizado"]).LeitorRoteirizado(["", " "]))
    c = ControladorHumano(fonte)
    c.reset(topo, restricoes, 0.0)
    assert [e.indice for e in c.bombeia()] == [BOTAO_START]
    assert len(c.consome_starts()) == 1 and c.consome_starts() == []


def test_bombeia_e_noop_em_fonte_gravada(topo, restricoes):
    """`ReplayInput` anda um slot por `poll`: drená-la fora do tick comeria a
    gravação e a rodada reproduzida deixaria de bater."""
    c = _humano([[1], [2]])
    c.reset(topo, restricoes, 0.0)
    assert c.bombeia() == [] and c.bombeia() == []
    assert c.decide(F.observacao_fake(topo, t=0.0))[1] == TROCAR


def test_reset_drena_a_tecla_da_contagem(topo, restricoes):
    """Tecla apertada durante o 3-2-1 não vira ação em t0."""
    leitor = __import__("feira.entrada", fromlist=["LeitorRoteirizado"]).LeitorRoteirizado
    fonte = TecladoInput(12, leitor=leitor(["qqq", ""]))
    c = ControladorHumano(fonte)
    c.reset(topo, restricoes, 0.0)
    assert int(c.decide(F.observacao_fake(topo, t=0.0)).sum()) == 0


def test_ao_abrir_janela_e_chamado_no_reset(topo, restricoes):
    vistos = []
    c = ControladorHumano(ReplayInput(12), ao_abrir_janela=vistos.append)
    c.reset(topo, restricoes, 300.0)
    assert vistos == [300.0]


# ------------------------------------------------- a prova do DoD (b), offline
def test_acoes_do_humano_sao_as_mesmas_de_um_controlador_direto(topo, restricoes):
    """DoD (b), metade offline: a sequência de botões e a sequência de ações
    emitidas descrevem a MESMA política. O que sobra (que a Arena mede o mesmo
    `Resultado` nas duas) está em `test_a3_integracao.py`."""
    roteiro = [[0], [], [1, 2], [3], [], [0, 1]]
    c = _humano(roteiro)
    c.reset(topo, restricoes, 0.0)
    obs = [F.observacao_fake(topo, t=float(i * 5)) for i in range(len(roteiro))]
    emitidas = [c.decide(o).copy() for o in obs]
    esperadas = []
    for slot in roteiro:
        v = np.full(topo.n, MANTER, dtype=np.int8)
        for b in slot:
            v[b] = TROCAR
        esperadas.append(v)
    assert all(np.array_equal(x, y) for x, y in zip(emitidas, esperadas))
    assert c.n_aceitos == 6 and c.n_negados == 0


# ==================================================== conformidade, espelhada
# `tests/test_conformidade.py` está congelado até o dono do projeto registrar as
# implementações novas em `IMPLS_CONTROLADOR`. Enquanto isso, o `ControladorHumano`
# roda aqui a MESMA suíte, com a fábrica que deve entrar lá:
#
#     pytest.param(_humano_conforme, id="humano"),
#
# (fonte rebobinável é requisito: `reset()` tem que ser idempotente.)
def _humano_conforme():
    return ControladorHumano(ReplayInput(12, [[0, 3], [], [5], [], [1]]))


IMPLS = [pytest.param(_humano_conforme, id="humano")]


@pytest.mark.parametrize("fabrica", IMPLS)
def test_conformidade_protocolo(fabrica, topo, restricoes):
    c = fabrica()
    assert isinstance(c, Controlador)
    assert isinstance(c.nome, str) and c.nome


@pytest.mark.parametrize("fabrica", IMPLS)
def test_conformidade_acoes_validas(fabrica, topo, restricoes):
    c = fabrica()
    c.reset(topo, restricoes, t0=0.0)
    for i in range(5):
        a = c.decide(F.observacao_fake(topo, t=float(i * restricoes.decision_interval)))
        assert a.shape == (topo.n,)
        assert np.isin(a, (MANTER, TROCAR)).all()


@pytest.mark.parametrize("fabrica", IMPLS)
def test_conformidade_reset_idempotente(fabrica, topo, restricoes):
    c = fabrica()
    obs = [F.observacao_fake(topo, t=float(i)) for i in range(6)]
    c.reset(topo, restricoes, t0=0.0)
    a1 = [c.decide(o).copy() for o in obs]
    c.reset(topo, restricoes, t0=0.0)
    a2 = [c.decide(o).copy() for o in obs]
    assert all(np.array_equal(x, y) for x, y in zip(a1, a2))


@pytest.mark.parametrize("fabrica", IMPLS)
def test_conformidade_decide_antes_de_reset(fabrica, topo, restricoes):
    with pytest.raises(Exception):
        fabrica().decide(F.observacao_fake(topo))
