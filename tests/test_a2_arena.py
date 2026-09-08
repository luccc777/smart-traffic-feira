"""A Arena (C4) e os dois controladores reais do agente A2.

Duas camadas:

* sem SUMO — o contrato dos controladores (a MESMA suíte parametrizada de
  `tests/test_conformidade.py`, espelhada aqui porque aquele arquivo está
  congelado até o dono do projeto registrar as implementações novas em
  `IMPLS_CONTROLADOR`), a cadência do laço e as recusas da Arena;
* com SUMO (`@pytest.mark.sumo`) — o laço de verdade na rede fechada de hoje:
  balanço fecha, os três braços passam pelo MESMO laço, e o detector novo
  denuncia um travamento injetado sem acusar a política sã.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from feira import _fakes as F
from feira.contratos import (
    MANTER,
    TROCAR,
    ArenaNaoConfigurada,
    Cenario,
    ChavesIncompativeis,
    Controlador,
    Janela,
    RestricoesFase,
    Ritmo,
    cenario,
    comparar,
    janela_padrao,
)
from feira.controladores import ControladorRL, ControladorTimer

_MAQUETE = Path(__file__).resolve().parents[2] / "smart-traffic-maquete"
CKPT = _MAQUETE / "results" / "maq30_ats_full_best.pt"

TEM_SUMO = bool(os.environ.get("SUMO_HOME")) and cenario("small.maquete").disponivel()
sumo = pytest.mark.skipif(not TEM_SUMO, reason="requer SUMO_HOME + a rede do maquete")
tem_ckpt = pytest.mark.skipif(not CKPT.exists(), reason="checkpoint da política ausente")


@pytest.fixture
def topo():
    return F.topologia_fake()


@pytest.fixture
def restricoes():
    return RestricoesFase(decision_interval=5, min_green=7, yellow=3)


# ================================================ C3 — a suíte, espelhada
# Quando o dono do projeto registrar estas duas em `test_conformidade.py:
# IMPLS_CONTROLADOR`, este bloco vira redundante e pode sair.
IMPLS = [
    pytest.param(lambda: ControladorTimer(27), id="timer-27s"),
    pytest.param(lambda: ControladorRL(CKPT), id="rl-ats", marks=tem_ckpt),
]


@pytest.mark.parametrize("fabrica", IMPLS)
def test_controlador_satisfaz_o_protocolo(fabrica):
    c = fabrica()
    assert isinstance(c, Controlador)
    assert isinstance(c.nome, str) and c.nome


@pytest.mark.parametrize("fabrica", IMPLS)
def test_controlador_devolve_acoes_validas(fabrica, topo, restricoes):
    c = fabrica()
    c.reset(topo, restricoes, t0=0.0)
    for i in range(5):
        a = c.decide(F.observacao_fake(topo, t=float(i * restricoes.decision_interval)))
        assert a.shape == (topo.n,)
        assert np.isin(a, (MANTER, TROCAR)).all()


@pytest.mark.parametrize("fabrica", IMPLS)
def test_controlador_reset_e_idempotente(fabrica, topo, restricoes):
    """Sem isto não há fantasma pré-computado que preste: a trajetória mostrada
    no placar tem que ser a que o braço realmente executaria."""
    c = fabrica()
    obs = [F.observacao_fake(topo, t=float(i)) for i in range(6)]
    c.reset(topo, restricoes, t0=0.0)
    a1 = [c.decide(o).copy() for o in obs]
    c.reset(topo, restricoes, t0=0.0)
    a2 = [c.decide(o).copy() for o in obs]
    for x, y in zip(a1, a2):
        assert np.array_equal(x, y)


@pytest.mark.parametrize("fabrica", IMPLS)
def test_controlador_decide_antes_de_reset_falha(fabrica, topo):
    c = fabrica()
    with pytest.raises(Exception):
        c.decide(F.observacao_fake(topo))


# ================================================ ControladorTimer
def test_timer_troca_exatamente_quando_o_verde_vence(topo, restricoes):
    """A regra do `FixedTimerSim._fire_timer`, linha a linha: só troca quando o
    verde venceu, nunca durante o amarelo, nunca num TL de uma fase só."""
    c = ControladorTimer(27)
    c.reset(topo, restricoes, t0=0.0)

    obs = F.observacao_fake(topo, verde_desde=26.0)
    assert (c.decide(obs) == MANTER).all()

    obs = F.observacao_fake(topo, verde_desde=27.0)
    a = c.decide(obs)
    controlaveis = np.array(topo.controlavel)
    assert (a[controlaveis] == TROCAR).all()
    assert (a[~controlaveis] == MANTER).all(), "TL com um verde só: TROCAR é no-op"


def test_timer_ignora_a_acao_durante_o_amarelo(topo, restricoes):
    c = ControladorTimer(27)
    c.reset(topo, restricoes, t0=0.0)
    obs = F.observacao_fake(topo, verde_desde=40.0)
    obs = type(obs)(t=obs.t, estado=obs.estado, fase_atual=obs.fase_atual,
                    verde_desde=obs.verde_desde,
                    em_amarelo=np.ones(topo.n, dtype=bool),
                    pode_trocar=np.zeros(topo.n, dtype=bool),
                    fila_por_tl=obs.fila_por_tl)
    assert (c.decide(obs) == MANTER).all()


def test_timer_nao_le_env_var(topo, restricoes, monkeypatch):
    """C3: um controlador RECEBE as restrições, não as escolhe."""
    monkeypatch.setenv("ST_MIN_GREEN", "999")
    monkeypatch.setenv("ST_BASELINE_GREEN", "999")
    c = ControladorTimer(27)
    c.reset(topo, restricoes, t0=0.0)
    assert (c.decide(F.observacao_fake(topo, verde_desde=27.0))
            [np.array(topo.controlavel)] == TROCAR).all()


def test_timer_recusa_verde_invalido():
    with pytest.raises(ValueError):
        ControladorTimer(0)


# ================================================ recusas da Arena
def test_arena_recusa_cenario_sem_warmup_medido():
    """`warmup_s=None` é o estado de um cenário cujo aquecimento ainda não foi
    MEDIDO. Warm-up chutado contamina toda métrica depois dele, então a Arena
    recusa — e a `janela_padrao` recusa junto, na hora de montar a janela.

    (O `aberta.maquete` já recebeu o número medido do agente A1; o cenário sem
    warm-up é construído aqui para o invariante continuar coberto.)"""
    import dataclasses

    from feira.arena import ArenaSumo

    sem_warmup = dataclasses.replace(cenario("aberta.maquete"), warmup_s=None)
    with pytest.raises(ArenaNaoConfigurada, match="warmup_s"):
        ArenaSumo().roda(sem_warmup, 42, ControladorTimer(27))
    with pytest.raises(ArenaNaoConfigurada, match="warmup_s"):
        janela_padrao(sem_warmup)


def test_arena_recusa_rede_inexistente(tmp_path):
    from feira.arena import ArenaSumo

    falso = Cenario(
        chave="falso.x", net_file=str(tmp_path / "nao.net.xml"),
        sumocfg=str(tmp_path / "nao.sumocfg"), add_file=None, view_file=None,
        restricoes=RestricoesFase(decision_interval=10, min_green=10, yellow=3),
        modelo_demanda="persistente", n_vehicles=5, warmup_s=0.0)
    with pytest.raises(ArenaNaoConfigurada, match="não existe"):
        ArenaSumo().roda(falso, 42, ControladorTimer(27))


def test_arena_satisfaz_o_protocolo():
    from feira.arena import ArenaSumo
    from feira.contratos import Arena as ProtocoloArena

    assert isinstance(ArenaSumo(), ProtocoloArena)


# ================================================ cadência (achado nº1)
def test_relogio_acumula_o_atraso_em_vez_de_reajustar_o_deadline():
    """O conserto estrutural do achado nº1. O dashboard faz
    `deadline = perf_counter()` quando fica para trás: o atraso some da vista e
    o braço passa a andar menos simulação pelo mesmo tempo de parede. Aqui o
    deadline NÃO é reajustado — o laço deixa de dormir até recuperar."""
    import time

    from feira.arena.sumo import _Relogio

    r = _Relogio(Ritmo(sim_por_parede=1000.0, recupera_atraso=True), passo_sim=1.0)
    r._deadline = time.perf_counter() - 0.5      # 0,5 s atrasado
    alvo = r._deadline
    r.espera()
    assert r.atraso_max > 0.4
    assert r._deadline == pytest.approx(alvo + 0.001, abs=1e-6), (
        "com recuperação o deadline avança um passo, não pula para o agora")

    r2 = _Relogio(Ritmo(sim_por_parede=1000.0, recupera_atraso=False), passo_sim=1.0)
    r2._deadline = time.perf_counter() - 0.5
    r2.espera()
    assert r2._deadline > alvo + 0.4, "sem recuperação o deadline pula para o agora"


def test_relogio_solto_nao_dorme():
    from feira.arena.sumo import _Relogio

    r = _Relogio(Ritmo(sim_por_parede=None), passo_sim=1.0)
    for _ in range(1000):
        r.espera()
    assert r.atraso_max == 0.0


# ================================================ integração com SUMO
@pytest.fixture(autouse=True)
def _cenario_aplicado(monkeypatch):
    """O conftest do repo apaga toda `ST_*` antes de cada teste; a Arena precisa
    delas de volta, senão `Cenario.aplicar()` acha que `sim` foi importado com
    outra configuração (e, na segunda vez, estaria certo)."""
    if TEM_SUMO:
        for k, v in cenario("small.maquete").env().items():
            monkeypatch.setenv(k, v)


@sumo
def test_topologia_da_rede_fechada_bate_com_o_medido():
    """A rede da maquete: 10 semáforos, 6 controláveis. Abrir as bordas deve
    levar isso a 12/12 — é gate da Onda 1 (agente A1)."""
    from feira.arena import ArenaSumo

    topo = ArenaSumo().topologia(cenario("small.maquete"))
    assert topo.n == 10
    assert topo.n_controlaveis == 6
    assert topo.edge_index.shape[0] == 2
    assert topo.approach_capacity > 0


@sumo
def test_arena_roda_o_timer_e_o_balanco_fecha():
    """Uma corrida curta de verdade: o balanço de veículos tem que fechar em
    zero e a corrida tem que ser declarada sã."""
    from feira.arena import ArenaSumo
    from feira.metricas import lacuna_sobrevivencia

    arena = ArenaSumo()
    res = arena.roda(cenario("small.maquete"), 42, ControladorTimer(27),
                     Janela(t0=0.0, t1=180.0))
    assert res.entregues > 0
    assert res.conservacao == 0, res.sane()[1]
    assert res.perdidos == 0
    ok, motivo = res.sane()
    assert ok, motivo
    assert lacuna_sobrevivencia(res) < 100.0
    d = arena.ultimo_diagnostico
    assert d["passos_medidos"] == 180
    assert d["amostras_rede"] == 180
    assert d["decisoes"] == 18


@sumo
def test_arena_roda_os_bracos_pelo_mesmo_laco_e_compara():
    """O ponto do C4: dois braços, um laço, e a comparação só existe porque as
    duas `Chave`s são idênticas."""
    from feira._fakes import ControladorFake
    from feira.arena import ArenaSumo

    arena = ArenaSumo()
    janela = Janela(t0=0.0, t1=120.0)
    a = arena.roda(cenario("small.maquete"), 42, ControladorTimer(27), janela)
    b = arena.roda(cenario("small.maquete"), 42, ControladorFake("sempre"), janela)
    assert a.chave == b.chave
    c = comparar(a, b)
    assert set(c.deltas) >= {"entregues", "fila_media", "tempo_medio_entregue"}

    outra = arena.roda(cenario("small.maquete"), 43, ControladorTimer(27), janela)
    with pytest.raises(ChavesIncompativeis):
        comparar(a, outra)


@sumo
def test_detector_denuncia_travamento_injetado_e_nao_acusa_politica_sa():
    """DoD (b) do agente A2.

    O travamento injetado é o farol congelado (`ControladorFake("nunca")`: todo
    MANTER, nenhum eixo cruzado nunca abre). O `coherence_gap` do maquete
    precisaria de `N × T / tt` para ver isso; a lacuna de sobrevivência vê sem
    supor frota fechada."""
    from feira._fakes import ControladorFake
    from feira.arena import ArenaSumo
    from feira.metricas import lacuna_sobrevivencia, sinais_de_travamento

    arena = ArenaSumo()
    janela = Janela(t0=0.0, t1=900.0)
    sao = arena.roda(cenario("small.maquete"), 42, ControladorTimer(27), janela)
    travado = arena.roda(cenario("small.maquete"), 42, ControladorFake("nunca"), janela)

    assert sinais_de_travamento(sao) == [], "política sã não pode ser acusada"
    assert sinais_de_travamento(travado), "o farol congelado tem que ser denunciado"
    assert lacuna_sobrevivencia(travado) > lacuna_sobrevivencia(sao)
    # a assinatura do artefato: o travado NÃO parece pior no tempo dos entregues
    assert travado.entregues < sao.entregues
    assert travado.tempo_medio_no_sistema > sao.tempo_medio_no_sistema
    # e a conservação continua fechando dos dois lados (ninguém evaporou)
    assert sao.conservacao == 0 and travado.conservacao == 0


@sumo
def test_arena_e_deterministica_na_mesma_condicao():
    """Mesma seed, mesma janela, mesmo controlador -> mesmo `Resultado`. Sem
    isto o fantasma pré-computado do modo jogo não vale nada."""
    from feira.arena import ArenaSumo

    arena = ArenaSumo()
    janela = Janela(t0=0.0, t1=120.0)
    a = arena.roda(cenario("small.maquete"), 42, ControladorTimer(27), janela)
    b = arena.roda(cenario("small.maquete"), 42, ControladorTimer(27), janela)
    assert a == b


@sumo
@tem_ckpt
def test_arena_roda_a_politica_treinada():
    from feira.arena import ArenaSumo

    arena = ArenaSumo()
    res = arena.roda(cenario("small.maquete"), 42, ControladorRL(CKPT),
                     Janela(t0=0.0, t1=120.0))
    assert res.entregues > 0 and res.conservacao == 0
    assert res.controlador.startswith("rl:")
    assert arena.ultimo_diagnostico["decisoes"] == 12


# ================================================ contabilidade da rede ABERTA
# A rede aberta é entregável do agente A1 e ainda não existe em disco, mas a
# CONTABILIDADE dela já existe e precisa estar certa antes: é ela que substitui o
# `coherence_gap` lá. Aqui o SUMO é falso e roteirizado — o que se testa é se os
# eventos do SUMO viram o balanço certo, não se o SUMO funciona.
class _SimFalsa:
    """`traci.simulation` roteirizado: um passo por entrada do roteiro."""

    def __init__(self, roteiro, pendentes=()):
        self.roteiro = list(roteiro)
        self.i = -1
        self._pendentes = list(pendentes)

    def passo(self):
        self.i += 1

    @property
    def _p(self):
        return self.roteiro[self.i] if 0 <= self.i < len(self.roteiro) else {}

    def getTime(self):
        return float(self.i + 1)

    def getDepartedIDList(self):
        return list(self._p.get("partiram", ()))

    def getArrivedIDList(self):
        return list(self._p.get("chegaram", ()))

    def getStartingTeleportIDList(self):
        return list(self._p.get("tele_ini", ()))

    def getEndingTeleportIDList(self):
        return list(self._p.get("tele_fim", ()))

    def getPendingVehicles(self):
        return list(self._pendentes)


class _VeiculoFalso:
    def __init__(self, sim):
        self.sim = sim

    def getIDList(self):
        return list(self.sim._p.get("vivos", ()))


class _TraciFalso:
    def __init__(self, roteiro, pendentes=()):
        self.simulation = _SimFalsa(roteiro, pendentes)
        self.vehicle = _VeiculoFalso(self.simulation)


def _roda_contador_aberto(roteiro, pendentes=()):
    import sys

    from feira.arena.sumo import _ContadorAberto
    from feira.metricas import Contabilidade

    falso = _TraciFalso(roteiro, pendentes)
    antigo = sys.modules.get("traci")
    sys.modules["traci"] = falso
    try:
        falso.simulation.passo()                 # estado inicial (t = 1)
        contador = _ContadorAberto.__new__(_ContadorAberto)
        contador.env = None
        contador.prefixo = ""
        contador._depart = {}
        contador._vivos = set(falso.simulation._p.get("vivos", ()))
        for vid in contador._vivos:
            contador._depart[vid] = falso.simulation.getTime()

        c = Contabilidade()
        c.abre_janela(falso.simulation.getTime(),
                      ativos=len(contador.vivos()), abertos=contador.abertos())
        while falso.simulation.i + 1 < len(roteiro):
            falso.simulation.passo()
            t = falso.simulation.getTime()
            contador.observa(t, (), c)
            c.amostra_rede(1.0, 1.0)
        c.fecha_janela(falso.simulation.getTime(),
                       ativos=len(contador.vivos()), backlog=contador.backlog())
        return c
    finally:
        if antigo is None:
            sys.modules.pop("traci", None)
        else:
            sys.modules["traci"] = antigo


def test_contabilidade_da_rede_aberta_fecha_o_balanco():
    """Um veículo nasce, viaja e some: viagem e veículo são a mesma coisa, e o
    balanço tem que fechar contra a contagem de vivos do SUMO."""
    c = _roda_contador_aberto([
        {"vivos": ()},                                        # t=1: rede vazia
        {"vivos": ("a", "b"), "partiram": ("a", "b")},        # t=2
        {"vivos": ("a", "b", "c"), "partiram": ("c",)},       # t=3
        {"vivos": ("b", "c"), "chegaram": ("a",)},            # t=4: `a` chegou
        {"vivos": ("c",), "chegaram": ("b",)},                # t=5: `b` chegou
    ])
    res = c.resultado(F.chave_fake(t0=1.0, t1=5.0), "aberta")
    assert (res.ativos_inicio, res.inseridos, res.entregues,
            res.ativos_fim, res.perdidos) == (0, 3, 2, 1, 0)
    assert res.conservacao == 0
    assert res.sane()[0]


def test_contabilidade_da_rede_aberta_denuncia_veiculo_evaporado():
    """Sumiu da rede sem constar como chegada nem como teleporte: `perdidos`.
    Numa rede aberta é o sinal de teleporte/colisão/remoção — o que na fechada o
    backstop mascarava registrando como "viagem concluída"."""
    from feira.metricas import sinais_de_travamento

    c = _roda_contador_aberto([
        {"vivos": ()},
        {"vivos": ("a", "b"), "partiram": ("a", "b")},
        {"vivos": ("a",)},                                    # `b` evaporou
    ])
    res = c.resultado(F.chave_fake(t0=1.0, t1=3.0), "aberta")
    assert res.perdidos == 1 and res.entregues == 0
    assert res.conservacao == 0        # a perda foi CONTABILIZADA...
    assert any("perdidos" in s for s in sinais_de_travamento(res)), (
        "...e mesmo assim tem que ser denunciada: `sane()` não olha `perdidos`")


def test_contabilidade_da_rede_aberta_conta_o_backlog_de_insercao():
    """O artefato de sobrevivência na versão rede aberta: o controlador estrangula
    a borda e o carro nem entra. `sane()` recusa acima de 10% dos agendados."""
    c = _roda_contador_aberto(
        [{"vivos": ()},
         {"vivos": ("a",), "partiram": ("a",)},
         {"vivos": ("a",)}],
        pendentes=("x", "y", "z"))
    res = c.resultado(F.chave_fake(t0=1.0, t1=3.0), "aberta")
    assert res.backlog_insercao == 3 and res.inseridos == 1
    ok, motivo = res.sane()
    assert not ok and "backlog" in motivo


def test_contabilidade_da_rede_aberta_ignora_teleporte():
    """Teleporte não é despawn: o veículo sai e volta às listas do SUMO, e contar
    isso como perda (e a volta como inserção) inflaria os dois lados do balanço."""
    c = _roda_contador_aberto([
        {"vivos": ()},
        {"vivos": ("a",), "partiram": ("a",)},
        {"vivos": (), "tele_ini": ("a",)},                    # em teleporte
        {"vivos": ("a",), "tele_fim": ("a",)},                # voltou
    ])
    res = c.resultado(F.chave_fake(t0=1.0, t1=4.0), "aberta")
    assert res.perdidos == 0
    assert res.inseridos == 1, "a volta do teleporte não é uma inserção nova"
    assert res.conservacao == 0


@sumo
def test_arena_declara_travamento_e_pode_abortar():
    """`TravamentoDetectado` não é falha de software: é resultado. O default é
    TERMINAR a janela marcando `travou=True` (o número da corrida travada é o dado
    que a auditoria reporta seed a seed); `abortar_travamento=True` levanta.

    O critério é model-free — segundos simulados sem NENHUMA chegada —, o que é o
    que a rede aberta permite: não usa frota fixa nem demanda esperada."""
    from feira._fakes import ControladorFake
    from feira.arena import ArenaSumo
    from feira.contratos import TravamentoDetectado

    janela = Janela(t0=0.0, t1=300.0)
    arena = ArenaSumo(seca_max_s=60.0)
    res = arena.roda(cenario("small.maquete"), 42, ControladorFake("nunca"), janela)
    assert res.travou is True
    assert res.sane()[0] is False

    with pytest.raises(TravamentoDetectado, match="sem nenhuma chegada"):
        ArenaSumo(seca_max_s=60.0, abortar_travamento=True).roda(
            cenario("small.maquete"), 42, ControladorFake("nunca"), janela)

    # e a política sã na MESMA janela não é acusada
    sao = ArenaSumo(seca_max_s=60.0).roda(
        cenario("small.maquete"), 42, ControladorTimer(27), janela)
    assert sao.travou is False and sao.sane()[0]


@sumo
def test_arena_reamarra_o_sim_quando_outro_cenario_congelou_o_pacote():
    """A armadilha do C1, na versão que a guarda do contrato NÃO pega.

    `Cenario.aplicar()` compara ENV VAR. Se alguém importou `sim` apontando para
    outra rede e depois devolveu a env var ao lugar (é o que um teste com
    `monkeypatch` faz), a guarda passa e os escalares congelados continuam
    errados — a corrida mediria 12 semáforos onde há 10, em silêncio.

    A Arena confere o ESTADO CONGELADO (`net_topology.NET_FILE`), não a env var,
    e reimporta o pacote quando ele está desalinhado. Aconteceu de verdade entre
    a suíte do agente A1 e esta."""
    import sys

    from feira.arena import ArenaSumo
    from feira.arena.sumo import _amarra_sim

    fechado = cenario("small.maquete")
    aberta = cenario("aberta.maquete")
    if not aberta.disponivel():
        pytest.skip("rede aberta ainda não existe (entregável do agente A1)")

    # envenena do mesmo jeito que a suíte do A1 envenena: aponta o `constants`
    # para a OUTRA rede, importa o `net_topology` de lá, e devolve a env var ao
    # lugar (é o que o teardown do `monkeypatch` faz).
    _amarra_sim(fechado)
    from sim.environment import constants as C

    C.NET_FILE = aberta.net_file
    sys.modules.pop("sim.environment.net_topology", None)
    import sim.environment.net_topology as poluido

    assert poluido.NET_FILE == aberta.net_file
    for k, v in fechado.env().items():
        os.environ[k] = v

    topo = ArenaSumo().topologia(fechado)
    assert topo.n == 10, "a Arena tem que reimportar `sim`, não confiar na env var"
    assert sys.modules["sim.environment.net_topology"].NET_FILE == fechado.net_file
    from sim.environment import constants as C

    assert C.N_VEHICLES == fechado.n_vehicles
