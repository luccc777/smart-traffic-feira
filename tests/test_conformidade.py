"""Suíte de CONFORMIDADE dos contratos de COMPORTAMENTO (C2, C3, C6).

Parametrizada sobre implementações: os fakes de referência e as reais. Já estão
na lista o `ControladorTimer` e o `ControladorRL` (agente A2) e o
`GeradorDemandaAberta` (A1); entram, quando forem entregues, o
`ControladorHumano` e o `TecladoInput` (A3), o `SerialInput` (A4) e o baseline
coordenado (A5).

É esta suíte que dá sentido a "controladores e camada de input plugáveis e
testáveis isoladamente": se o real não passa onde o fake passa, o real está errado.
"""
from __future__ import annotations

from pathlib import Path

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
    DemandaDivergente,
    EventoBotao,
    FonteEntrada,
    GeradorDemanda,
    RestricoesFase,
    valida_acoes,
    valida_estados,
)

# --------------------------------------------------------------- fábricas reais
# Importam tarde de propósito: `ControladorRL` puxa torch e `GeradorDemandaAberta`
# puxa sumolib, e importar qualquer um deles no topo congelaria estado antes de
# `Cenario.aplicar()` (a armadilha do C1).


def _timer():
    from feira.controladores import ControladorTimer
    return ControladorTimer(27.0)          # o baseline único do projeto


def _rl():
    from feira.contratos import cenario as _cen
    from feira.controladores import ControladorRL
    ckpt = (Path(_cen("small.maquete").net_file).parents[3]
            / "results" / "maq30_ats_full_best.pt")
    if not ckpt.exists():
        pytest.skip("checkpoint da política v2 não encontrado: %s" % ckpt)
    return ControladorRL(ckpt)


def _gerador_aberto():
    from feira.demanda import GeradorDemandaAberta
    return GeradorDemandaAberta()


# ============================================================ C3 — Controlador

IMPLS_CONTROLADOR = [
    pytest.param(lambda: F.ControladorFake("nunca"), id="fake-nunca"),
    pytest.param(lambda: F.ControladorFake("sempre"), id="fake-sempre"),
    pytest.param(lambda: F.ControladorFake("rng", seed=7), id="fake-rng"),
    pytest.param(_timer, id="timer-27s"),
    pytest.param(_rl, id="rl-ddqn", marks=pytest.mark.sumo),
    # A3: pytest.param(lambda: ControladorHumano(fonte), id="humano"),
]


@pytest.fixture
def topo():
    return F.topologia_fake()


@pytest.fixture
def restricoes():
    return RestricoesFase(decision_interval=5, min_green=7, yellow=3)


@pytest.mark.parametrize("fabrica", IMPLS_CONTROLADOR)
def test_controlador_satisfaz_o_protocolo(fabrica, topo, restricoes):
    c = fabrica()
    assert isinstance(c, Controlador)
    assert isinstance(c.nome, str) and c.nome


@pytest.mark.parametrize("fabrica", IMPLS_CONTROLADOR)
def test_controlador_devolve_acoes_validas(fabrica, topo, restricoes):
    """Shape (N,) e valores em {0,1}. Uma política que devolva outra coisa produz
    episódio silenciosamente inválido — e episódio inválido vira número publicado."""
    c = fabrica()
    c.reset(topo, restricoes, t0=0.0)
    for i in range(5):
        a = c.decide(F.observacao_fake(topo, t=float(i * restricoes.decision_interval)))
        assert a.shape == (topo.n,)
        assert np.isin(a, (MANTER, TROCAR)).all()


@pytest.mark.parametrize("fabrica", IMPLS_CONTROLADOR)
def test_controlador_reset_e_idempotente(fabrica, topo, restricoes):
    """Duas corridas com o mesmo reset produzem a MESMA sequência de ações.

    Sem isto não há fantasma pré-computado que preste: a trajetória da RL mostrada
    no placar tem que ser a que o braço realmente executaria."""
    c = fabrica()
    obs = [F.observacao_fake(topo, t=float(i)) for i in range(6)]

    c.reset(topo, restricoes, t0=0.0)
    a1 = [c.decide(o).copy() for o in obs]
    c.reset(topo, restricoes, t0=0.0)
    a2 = [c.decide(o).copy() for o in obs]

    for x, y in zip(a1, a2):
        assert np.array_equal(x, y)


@pytest.mark.parametrize("fabrica", IMPLS_CONTROLADOR)
def test_controlador_decide_antes_de_reset_falha(fabrica, topo, restricoes):
    c = fabrica()
    with pytest.raises(Exception):
        c.decide(F.observacao_fake(topo))


def test_valida_acoes_rejeita_lixo():
    with pytest.raises(ValueError, match="shape"):
        valida_acoes(np.zeros(3), 12)
    with pytest.raises(ValueError, match="fora de"):
        valida_acoes(np.array([0, 1, 2] + [0] * 9), 12)
    assert valida_acoes([1] * 12, 12).dtype == np.int8


def test_topologia_conta_controlaveis():
    """O número que decide a Frente 3: hoje 8 de 12 (medido no `net_topology` da
    rede fechada). Abrir as bordas deve levar a 12 — é gate da Onda 1."""
    t = F.topologia_fake()
    assert t.n == 12 and t.n_controlaveis == 8
    assert t.indices_controlaveis() == tuple(range(8))
    assert F.topologia_fake(12, n_controlaveis=12).n_controlaveis == 12


def test_observacao_recusa_shape_inconsistente():
    t = F.topologia_fake(4)
    o = F.observacao_fake(t)
    import dataclasses
    with pytest.raises(ValueError, match="shape"):
        dataclasses.replace(o, fila_por_tl=np.zeros(3))


# ============================================================ C6 — FonteEntrada

IMPLS_ENTRADA = [
    pytest.param(lambda: F.FonteEntradaFake(12, [[0, 3], [], [BOTAO_START]]), id="fake"),
    # A3: pytest.param(lambda: TecladoInput(12), id="teclado"),
    # A4: pytest.param(lambda: SerialInput(porta_falsa()), id="botoeira"),
]


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA)
def test_entrada_satisfaz_o_protocolo(fabrica):
    f = fabrica()
    assert isinstance(f, FonteEntrada)
    assert f.n_botoes == 12 and isinstance(f.nome, str)


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA)
def test_entrada_devolve_bordas_e_nao_bloqueia(fabrica):
    """`poll` devolve BORDAS, não nível: quem segura o botão não gera uma troca
    por tick."""
    f = fabrica()
    e1 = f.poll()
    assert all(isinstance(e, EventoBotao) for e in e1)
    assert [e.indice for e in e1] == [0, 3]
    assert f.poll() == []
    assert [e.indice for e in f.poll()] == [BOTAO_START]
    assert f.poll() == []          # esgotado: vazio para sempre, sem bloquear


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA)
def test_entrada_valida_feedback(fabrica):
    """Feedback é parte do contrato, não enfeite: sem ele o visitante conclui que
    o botão quebrou e para de jogar."""
    f = fabrica()
    f.feedback([OFF] * 12)
    f.feedback([ARMADO, ACEITO, NEGADO] + [OFF] * 9)
    with pytest.raises(ValueError, match="12 estados"):
        f.feedback([OFF] * 11)
    with pytest.raises(ValueError, match="desconhecid"):
        f.feedback(["piscando"] + [OFF] * 11)


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA)
def test_entrada_reporta_morte(fabrica):
    """Cabo USB saindo no meio da rodada não pode derrubar o jogo: `viva()` vira
    False e o motor cai para o teclado (DoD do agente A4)."""
    f = fabrica()
    assert f.viva()
    f.close()
    assert not f.viva()


def test_valida_estados_direto():
    assert valida_estados([OFF, ARMADO], 2) == [OFF, ARMADO]
    with pytest.raises(ValueError):
        valida_estados([OFF], 2)


def test_botao_start_e_reservado():
    assert BOTAO_START == -1
    assert EventoBotao(BOTAO_START).e_start
    assert not EventoBotao(0).e_start


# ============================================================ C2 — GeradorDemanda

IMPLS_DEMANDA = [
    pytest.param(F.GeradorDemandaFake, id="fake"),
    pytest.param(_gerador_aberto, id="aberta", marks=pytest.mark.sumo),
]


@pytest.mark.parametrize("fabrica", IMPLS_DEMANDA)
def test_gerador_satisfaz_o_protocolo(fabrica):
    assert isinstance(fabrica(), GeradorDemanda)


@pytest.mark.parametrize("fabrica", IMPLS_DEMANDA)
def test_mesma_seed_mesmo_arquivo_byte_a_byte(fabrica, tmp_path):
    """O requisito inegociável do projeto, na forma mais forte: mesmo sha256.
    Não "estatisticamente equivalente" — byte-idêntico."""
    c = F.cenario_fake_arquivo(tmp_path)
    g = fabrica()
    m1 = g.gera(c, 42, forcar=True)
    m2 = g.gera(c, 42, forcar=True)
    assert m1.sha256 == m2.sha256
    assert m1.n_veiculos == m2.n_veiculos


@pytest.mark.parametrize("fabrica", IMPLS_DEMANDA)
def test_seeds_diferentes_geram_demandas_diferentes(fabrica, tmp_path):
    c = F.cenario_fake_arquivo(tmp_path)
    g = fabrica()
    assert g.gera(c, 42).sha256 != g.gera(c, 43).sha256


@pytest.mark.parametrize("fabrica", IMPLS_DEMANDA)
def test_gerador_e_idempotente(fabrica, tmp_path):
    """Rodar de novo não regera: a run que consumiu aquele arquivo continua válida."""
    c = F.cenario_fake_arquivo(tmp_path)
    g = fabrica()
    m1 = g.gera(c, 42)
    mtime = c.rou_file(42).stat().st_mtime_ns
    m2 = g.gera(c, 42)
    assert m1 == m2 and c.rou_file(42).stat().st_mtime_ns == mtime


@pytest.mark.parametrize("fabrica", IMPLS_DEMANDA)
def test_manifesto_denuncia_arquivo_adulterado(fabrica, tmp_path):
    """O manifesto vai versionado, o `.rou.xml` não. É o manifesto que permite
    dizer "esta run usou ESTA demanda" seis meses depois."""
    c = F.cenario_fake_arquivo(tmp_path)
    g = fabrica()
    man = g.gera(c, 42)
    rou = c.rou_file(42)
    rou.write_text(rou.read_text(encoding="utf-8") + "<!-- editado na mao -->\n",
                   encoding="utf-8")
    with pytest.raises(DemandaDivergente, match="não bate"):
        man.confere(rou)


@pytest.mark.parametrize("fabrica", IMPLS_DEMANDA)
def test_manifesto_round_trip(fabrica, tmp_path):
    c = F.cenario_fake_arquivo(tmp_path)
    g = fabrica()
    assert g.gera(c, 42) == g.manifesto(c, 42)
