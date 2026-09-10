"""Motor do jogo: máquina de estados, fantasmas e placar — sem SUMO.

A rodada de verdade tem 120 s de parede e um humano dentro; nenhuma das duas
coisas cabe numa suíte. Aqui a Arena é falsa (mas obedece ao C4: mesmo ciclo de
vida, mesmo observador por sim-step) e o que se testa é o que o agente A3
escreveu: quem consome os fantasmas, como o placar é montado e o que acontece
quando alguma coisa falha na frente do público.
"""
from __future__ import annotations

import numpy as np
import pytest

from feira import _fakes as F
from feira.contratos import (
    CONTAGEM,
    JOGANDO,
    OCIOSO,
    PREPARANDO,
    RESULTADO,
    TROCAR,
    Chave,
    Fantasma,
    FantasmaIncompativel,
    Frame,
    Janela,
    Resultado,
    caminho_fantasma,
)
from feira.controladores.humano import ControladorHumano
from feira.entrada import ReplayInput
from feira.jogo import ColetorDeSerie, ControladorSelado, Fantasmaria, MotorDoJogo, selo_t0


# ------------------------------------------------------------- arena falsa
class ArenaFalsa:
    """Implementa o C4 com um modelo de trânsito de brinquedo.

    Não pretende medir tráfego: pretende exercitar EXATAMENTE o ciclo de vida
    que a `ArenaSumo` executa — `reset` no início da janela, `decide` a cada
    `decision_interval` sim-steps, observador a cada sim-step, `Resultado`
    carimbado com a `Chave`. Trocar de fase entrega um carro a mais, para que
    jogar diferente dê placar diferente.
    """

    def __init__(self, topo=None, *, passo: float = 1.0, base: float = 0.5) -> None:
        self.topo = topo or F.topologia_fake(12, n_controlaveis=12)
        self.passo = float(passo)
        self.base = float(base)
        self.ultimo_diagnostico: dict = {}

    def topologia(self, cenario):
        return self.topo

    def roda(self, cenario, seed, controlador, janela=None, *, ritmo=None,
             observador=None, gui=False):
        from feira.arena.sumo import sha_demanda

        janela = janela or Janela(t0=0.0, t1=120.0)
        chave = Chave.de(cenario, int(seed), janela, sha_demanda(cenario, seed))
        n = self.topo.n
        di = cenario.restricoes.decision_interval
        controlador.reset(self.topo, cenario.restricoes, janela.t0)
        verde = np.full(n, 99.0)
        entregues = 0
        t = janela.t0
        decisao = 0
        trocas = 0
        while t < janela.t1:
            decisao += 1
            obs = F.observacao_fake(self.topo, t=t)
            obs = obs.__class__(
                t=t, estado=obs.estado, fase_atual=obs.fase_atual, verde_desde=verde.copy(),
                em_amarelo=np.zeros(n, dtype=bool),
                pode_trocar=np.array(self.topo.controlavel) & (verde >= cenario.restricoes.min_green),
                fila_por_tl=np.full(n, 3.0))
            acoes = np.asarray(controlador.decide(obs)).reshape(-1)
            trocou = acoes == TROCAR
            verde = np.where(trocou, 0.0, verde)
            trocas += int(trocou.sum())
            for _ in range(di):
                if t >= janela.t1:
                    break
                t += self.passo
                verde += self.passo
                entregues = int((t - janela.t0) * self.base) + trocas
                if observador is not None:
                    observador(Frame(
                        braco=getattr(controlador, "nome", "?"), t=t, decisao=decisao,
                        substep=0, veiculos=[], tls=[],
                        heat={"l0": int(10 + (t % 7))},
                        stats={"entregues": entregues, "ativos": 50,
                               "tempo_medio_entregue": 40.0 + trocas * 0.1,
                               "fila_media": 8.0}))
        return Resultado(
            chave=chave, controlador=getattr(controlador, "nome", "?"),
            entregues=entregues, tempo_medio_entregue=40.0 + trocas * 0.1,
            tempo_medio_no_sistema=45.0, fila_media=8.0, espera_media=12.0,
            inseridos=entregues, ativos_fim=50, ativos_inicio=50,
            backlog_insercao=0, perdidos=0)


@pytest.fixture
def cenario_fake(tmp_path):
    cen = F.cenario_fake_arquivo(tmp_path)
    ger = F.GeradorDemandaFake()
    for s in (100, 101, 102):
        ger.gera(cen, s)
    return cen


@pytest.fixture
def fantasmaria(cenario_fake, tmp_path):
    return Fantasmaria(cenario_fake, raiz=tmp_path / "results", arena=ArenaFalsa())


# ------------------------------------------------------------------- selo
def test_selo_e_estavel_e_tem_dentes():
    topo = F.topologia_fake()
    a = F.observacao_fake(topo, t=300.0)
    assert selo_t0(a) == selo_t0(a)
    b = F.observacao_fake(topo, t=300.0, verde_desde=98.0)
    assert selo_t0(a) != selo_t0(b)


def test_controlador_selado_e_transparente():
    topo = F.topologia_fake()
    from feira.contratos import RestricoesFase

    r = RestricoesFase(decision_interval=5, min_green=7, yellow=3)
    nu, selado = F.ControladorFake("rng", seed=3), ControladorSelado(F.ControladorFake("rng", seed=3))
    nu.reset(topo, r, 0.0)
    selado.reset(topo, r, 0.0)
    obs = [F.observacao_fake(topo, t=float(i)) for i in range(6)]
    assert all(np.array_equal(nu.decide(o), selado.decide(o)) for o in obs)
    assert selado.selo == selo_t0(obs[0])


def test_selado_registra_o_verde_de_cada_troca():
    """É a prova direta do DoD (b): nenhuma troca emitida antes do verde mínimo."""
    import dataclasses

    from feira.contratos import RestricoesFase

    topo = F.topologia_fake(12, n_controlaveis=12)
    r = RestricoesFase(decision_interval=5, min_green=7, yellow=3)
    c = ControladorSelado(ControladorHumano(ReplayInput(12, [[0], [1]])))
    c.reset(topo, r, 0.0)
    o0 = F.observacao_fake(topo, t=0.0, verde_desde=20.0)
    c.decide(o0)
    o1 = dataclasses.replace(F.observacao_fake(topo, t=5.0, verde_desde=3.0),
                             pode_trocar=np.zeros(topo.n, dtype=bool))
    c.decide(o1)
    assert c.verde_nas_trocas == [20.0]      # a segunda foi negada
    assert c.trocas_em_amarelo == 0


# -------------------------------------------------------------- fantasmas
def test_fantasmaria_calcula_salva_e_carrega(fantasmaria):
    f = fantasmaria.calcula(100, "timer")
    assert isinstance(f, Fantasma) and len(f.serie) > 0
    assert f.chave == fantasmaria.chave(100)
    de_novo = fantasmaria.carrega(100, "timer")
    assert de_novo.final.entregues == f.final.entregues
    assert de_novo.serie == f.serie


def test_fantasma_de_outra_seed_e_recusado(fantasmaria, tmp_path):
    """DoD (d): fantasma velho parece válido na tela e produz placar mentiroso."""
    f = fantasmaria.calcula(100, "timer")
    alheio = caminho_fantasma(fantasmaria.raiz, fantasmaria.chave(101), "timer")
    f.salva(alheio)                       # fantasma da seed 100 no lugar da 101
    with pytest.raises(FantasmaIncompativel, match="não serve"):
        fantasmaria.carrega(101, "timer")


def test_fantasma_de_outro_espaco_de_acao_e_recusado(fantasmaria, cenario_fake):
    """A `Chave` carrega a assinatura das restrições: verde mínimo alcançável de
    7 s e de 17 s descrevem conjuntos de políticas diferentes."""
    import dataclasses

    from feira.contratos import RestricoesFase

    f = fantasmaria.calcula(100, "timer")
    outro = dataclasses.replace(
        cenario_fake, restricoes=RestricoesFase(decision_interval=10, min_green=10, yellow=3))
    with pytest.raises(FantasmaIncompativel):
        f.confere(Fantasmaria(outro, raiz=fantasmaria.raiz).chave(100))


def test_fantasma_de_outra_politica_e_recusado_na_mesma_condicao(fantasmaria):
    """A `Chave` descreve a CONDICAO, nao quem jogou -- e o cache confiava so nela.

    Duas politicas na mesma seed, janela e grade produzem fantasmas de chave
    IDENTICA. Sem esta checagem, trocar o checkpoint da RL reaproveitava em
    silencio o fantasma da politica velha, e o projetor exibia a RL antiga com o
    nome da nova. O nome do controlador ja viajava no arquivo desde sempre; so
    nao era comparado.
    """
    f = fantasmaria.calcula(100, "timer")
    assert f.controlador == "timer:uniforme_27s"

    # mesmo arquivo, mesma chave -- so o jogador muda
    fantasmaria.verde_timer = 40.0
    assert fantasmaria.chave(100) == f.chave, "a condicao NAO mudou; e esse o ponto"
    with pytest.raises(FantasmaIncompativel, match="outro jogador"):
        fantasmaria.carrega(100, "timer")

    # e o `garante()` trata isso recalculando, em vez de derrubar a rodada
    antes = len(fantasmaria.custos)
    out = fantasmaria.garante(100, ("timer",))
    assert len(fantasmaria.custos) > antes                    # recalculou
    assert out["timer"].controlador == "timer:uniforme_40s"


def test_prefetch_leva_o_checkpoint_para_o_subprocesso(fantasmaria, monkeypatch):
    """Sem `--ckpt` o subprocesso caia no CKPT_PADRAO e computava outra politica."""
    import pathlib
    fantasmaria.ckpt_rl = pathlib.Path("uma_politica_qualquer.pt")
    vistos = []
    monkeypatch.setattr("subprocess.Popen",
                        lambda cmd, **kw: vistos.append(cmd) or _PopenFalso())
    fantasmaria.agenda(100, ("rl",))
    assert vistos, "nada foi disparado"
    cmd = vistos[0]
    assert "--ckpt" in cmd
    assert cmd[cmd.index("--ckpt") + 1] == str(fantasmaria.ckpt_rl)


class _PopenFalso:
    returncode = 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def test_garante_usa_o_cache_e_nao_recalcula(fantasmaria):
    fantasmaria.calcula(100, "timer")
    antes = len(fantasmaria.custos)
    fantasmaria.garante(100, ("timer",))
    assert len(fantasmaria.custos) == antes          # veio do disco


def test_garante_degrada_quando_um_braco_nao_existe(fantasmaria):
    """Sem checkpoint da RL o placar perde uma barra — não a feira."""
    fantasmaria.ckpt_rl = fantasmaria.raiz / "nao_existe.pt"
    fs = fantasmaria.garante(100, ("timer", "rl"))
    assert set(fs) == {"timer"}
    assert "rl" in fantasmaria.ultimo_erro


def test_coletor_usa_a_fila_instantanea_e_nao_a_media():
    """`Amostra.fila` é "parados na rede naquele instante" (C8). `stats
    ["fila_media"]` é a média corrente da janela e responde outra pergunta."""
    fr = Frame(braco="x", t=7.0, decisao=1, substep=0, veiculos=[], tls=[],
               heat={"a": 4, "b": 5}, stats={"entregues": 3, "fila_media": 99.0,
                                             "tempo_medio_entregue": 12.5})
    a = ColetorDeSerie.amostra_de(fr)
    assert a.fila == 9.0 and a.entregues == 3 and a.tempo_medio == 12.5


def test_coletor_amostra_uma_vez_por_segundo():
    c = ColetorDeSerie()
    for sub in range(3):
        c(Frame(braco="x", t=1.0, decisao=1, substep=sub, veiculos=[], tls=[],
                heat={}, stats={"entregues": sub}))
    assert len(c.amostras) == 1


# ------------------------------------------------------------------ motor
CAMPOS_METRICA = ("entregues", "tempo_medio_entregue", "tempo_medio_no_sistema",
                  "fila_media", "espera_media", "inseridos", "ativos_fim",
                  "ativos_inicio", "backlog_insercao", "perdidos", "travou")


def _metricas(res: Resultado) -> tuple:
    """As métricas do `Resultado`, sem o nome do controlador — que muda de
    "teclado" para "replay" e não é o que a rodada mediu."""
    return tuple(getattr(res, c) for c in CAMPOS_METRICA)


def _motor(cenario, fantasmaria, roteiro, **kw):
    kw.setdefault("bracos", ("timer",))
    kw.setdefault("ao_vivo", False)
    kw.setdefault("prefetch", False)
    kw.setdefault("resultado_s", 0.0)
    kw.setdefault("seeds", (100, 101))
    return MotorDoJogo(cenario, fonte=ReplayInput(12, roteiro),
                       fantasmaria=fantasmaria, arena=fantasmaria._arena, **kw)


def test_rodada_completa_produz_placar_com_os_tres_no_mesmo_t(cenario_fake, fantasmaria):
    publicados = []
    m = _motor(cenario_fake, fantasmaria, [[0], [], [1]] + [[]] * 40,
               publicador=publicados.append)
    r = m.rodada()
    assert r.humano is not None and r.placar is not None
    assert m.fase == OCIOSO and m.n_rodadas == 1
    fases = {p["fase"] for p in publicados}
    assert {PREPARANDO, CONTAGEM, JOGANDO, RESULTADO} <= fases
    final = publicados[-1]
    assert final["fase"] == RESULTADO
    assert {ln["braco"] for ln in final["linhas"]} == {"timer", "humano"}
    # um `t` só para os três braços — a garantia estrutural do C7
    for p in publicados:
        if p["fase"] == JOGANDO:
            assert isinstance(p["t"], float)
            assert p["chave"]["seed"] == 100


def test_manchete_e_entregues_e_o_vencedor_sai_dela(cenario_fake, fantasmaria):
    """Nunca tempo de viagem: a média só conta quem chegou, então travar a rede
    venceria pela média dos sobreviventes."""
    m = _motor(cenario_fake, fantasmaria, [list(range(12))] * 40)
    r = m.rodada()
    linhas = {ln["braco"]: ln for ln in r.placar.json()["linhas"]}
    assert linhas["humano"]["entregues"] > linhas["timer"]["entregues"]
    assert r.vencedor == "humano"
    # ...e o humano tem tempo de viagem PIOR: a manchete não é essa
    assert linhas["humano"]["tempo_medio"] > linhas["timer"]["tempo_medio"]


def test_quem_nao_joga_perde_para_o_timer(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [[]] * 40)
    r = m.rodada()
    linhas = {ln["braco"]: ln for ln in r.placar.json()["linhas"]}
    assert linhas["humano"]["entregues"] < linhas["timer"]["entregues"]
    assert r.vencedor == "timer"


def test_empate_nao_coroa_ninguem(cenario_fake, fantasmaria):
    """Empate na manchete deixa o pódio vazio em vez de escolher no desempate."""
    from feira.contratos import Amostra

    r1 = _motor(cenario_fake, fantasmaria, [[]] * 40).rodada()
    n = r1.humano.entregues
    velho = fantasmaria.carrega(100, "timer")
    gemeo = Fantasma(chave=velho.chave, controlador=velho.controlador,
                     serie=tuple(Amostra(t=a.t, entregues=n, fila=a.fila,
                                         tempo_medio=a.tempo_medio) for a in velho.serie),
                     final=velho.final.com(entregues=n))
    gemeo.salva(fantasmaria.caminho(100, "timer"))
    r2 = _motor(cenario_fake, fantasmaria, [[]] * 40).rodada()
    linhas = {ln["braco"]: ln for ln in r2.placar.json()["linhas"]}
    assert linhas["humano"]["entregues"] == linhas["timer"]["entregues"] == n
    assert r2.vencedor is None


def test_abortar_no_meio_da_rodada(cenario_fake, fantasmaria):
    from feira.contratos import BOTAO_START

    m = _motor(cenario_fake, fantasmaria, [[], [BOTAO_START]] + [[]] * 40)
    r = m.rodada()
    assert r.abortada and r.humano is None and r.vencedor is None
    assert m.fase == OCIOSO                     # e o motor volta sozinho


def test_arena_caindo_nao_derruba_o_motor(cenario_fake, fantasmaria):
    class ArenaQuebrada(ArenaFalsa):
        def roda(self, *a, **k):
            raise RuntimeError("SUMO nao subiu")

    fantasmaria._arena = ArenaFalsa()
    m = _motor(cenario_fake, fantasmaria, [[]] * 5)
    m._arena = ArenaQuebrada()
    r = m.rodada()
    assert r.humano is None and r.vencedor is None
    assert "SUMO nao subiu" in r.motivo and m.fase == OCIOSO


def test_selo_divergente_nao_coroa_vencedor(cenario_fake, fantasmaria):
    import json

    m = _motor(cenario_fake, fantasmaria, [[0]] * 40)
    m.rodada()                                   # popula o selo do fantasma
    sidecar = fantasmaria.caminho(100, "timer").with_suffix(".selo.json")
    sidecar.write_text(json.dumps({"selo_t0": "selo_de_outra_rodada",
                                   "controlador": "timer"}), encoding="utf-8")
    r = _motor(cenario_fake, fantasmaria, [[0]] * 40).rodada()
    assert not r.selos_batem and r.vencedor is None
    assert "selo de t0 divergente" in r.motivo
    # e isso tem que CHEGAR no fio: o motor sabia, a projecao nao ficava sabendo.
    assert r.placar is not None
    d = r.placar.json()
    assert d["pareado"] is False and "selo de t0 divergente" in d["motivo"]


def test_gravacao_da_rodada_reproduz_o_mesmo_resultado(cenario_fake, fantasmaria):
    """DoD (c) na Arena falsa; a versão com SUMO está em test_a3_integracao."""
    roteiro = [[0, 4], [], [7], [1, 2]] + [[]] * 40
    m = _motor(cenario_fake, fantasmaria, roteiro)
    r1 = m.rodada()
    assert r1.gravacao is not None and r1.gravacao.n_pressoes == 5

    m2 = _motor(cenario_fake, fantasmaria, [], seeds=(100,))
    m2.fonte = r1.gravacao.fonte_de_replay()
    r2 = m2.rodada()
    assert _metricas(r2.humano) == _metricas(r1.humano)   # byte a byte nas métricas
    assert r2.humano.chave == r1.humano.chave
    assert r2.gravacao.ticks == r1.gravacao.ticks


def test_espera_start_devolve_falso_no_timeout(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [[]])
    m.dorme = lambda s: None
    assert m.espera_start(timeout=0.0) is False
    assert m.fase == OCIOSO


def test_seeds_rodam_em_rotacao(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [[]] * 40, seeds=(100, 101))
    assert m.seed == 100 and m.proxima_seed == 101
    m.rodada()
    assert m.seed == 101


# ------------------------------------------------------------- marcapasso
# O achado do agente A4: durante a rodada quem drena a `FonteEntrada` é o
# observador da Arena, chamado 1x por sim-step. Com STEP_LENGTH=1 s e ritmo 1:1
# isso é 1 Hz — latência de até 1000 ms contra um teto de 50 ms, e o LED de
# "armado" demorando um segundo, que é o efeito que o C6 existe para evitar.
def _relogio_falso():
    estado = {"t": 0.0}
    return estado, (lambda: estado["t"]), (lambda s: estado.__setitem__("t", estado["t"] + s))


def test_marcapasso_bombeia_a_pelo_menos_30_hz():
    from feira.jogo.motor import Marcapasso

    _, agora, dorme = _relogio_falso()
    bombas = []
    mp = Marcapasso(passo_sim=1.0, sim_por_parede=1.0, fatia_s=0.02,
                    bomba=lambda: bombas.append(1), dorme=dorme, agora=agora)
    mp.inicia()
    for _ in range(3):
        mp.passo()
    assert mp.hz >= 30.0, mp.hz
    assert len(bombas) == mp.n_bombas >= 3 * 30


def test_marcapasso_acumula_o_atraso_em_vez_de_reajustar_o_relogio():
    """A disciplina do `_Relogio` da Arena: reajustar o deadline em silêncio é o
    que produziu a deriva entre os dois braços do dashboard."""
    from feira.jogo.motor import Marcapasso

    estado, agora, _ = _relogio_falso()
    mp = Marcapasso(bomba=lambda: estado.__setitem__("t", estado["t"] + 4.0),
                    dorme=lambda s: None, agora=agora)
    mp.inicia()
    mp.passo()
    assert mp.atraso_final == pytest.approx(3.0)
    mp.passo()
    assert mp.atraso_final == pytest.approx(6.0)      # o deadline não foi mexido
    assert mp.estouros == 2


def test_marcapasso_deixa_o_abortar_passar():
    from feira.jogo.motor import Marcapasso, RodadaAbortada

    def bomba():
        raise RodadaAbortada("START")

    mp = Marcapasso(bomba=bomba, dorme=lambda s: None)
    mp.inicia()
    with pytest.raises(RodadaAbortada):
        mp.passo()


def test_rodada_ao_vivo_le_a_fonte_a_alta_frequencia(cenario_fake, fantasmaria):
    """A prova de ponta a ponta do conserto: numa rodada COM cadência 1:1, a
    fonte é lida dezenas de vezes por segundo, não uma."""
    import dataclasses

    curto = dataclasses.replace(cenario_fake, janela_rodada_s=3.0)
    fm = Fantasmaria(curto, raiz=fantasmaria.raiz, arena=fantasmaria._arena)
    m = MotorDoJogo(curto, fonte=ReplayInput(12, [[0]] * 5), fantasmaria=fm,
                    arena=fm._arena, seeds=(100,), bracos=("timer",), ao_vivo=True,
                    contagem_s=0.0, resultado_s=0.0, prefetch=False)
    r = m.rodada()
    assert r.humano is not None
    assert r.hz_entrada >= 30.0, r.hz_entrada
    assert 2.5 <= r.duracao_parede_s <= 8.0, r.duracao_parede_s


def test_motor_acende_o_led_do_start_em_quem_souber(cenario_fake, fantasmaria):
    """O 13º LED não cabe no `feedback()` do C6 (n estados para n+1 LEDs). Quem
    implementa `feedback_start` recebe; quem não implementa não é chamado."""
    from feira.contratos import ACEITO, ARMADO, NEGADO

    class ComStart(ReplayInput):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.starts_vistos = []

        def feedback_start(self, estado):
            self.starts_vistos.append(estado)

    fonte = ComStart(12, [[0]] * 40)
    m = MotorDoJogo(cenario_fake, fonte=fonte, fantasmaria=fantasmaria,
                    arena=fantasmaria._arena, seeds=(100,), bracos=("timer",),
                    ao_vivo=False, prefetch=False, resultado_s=0.0)
    m.rodada()
    assert set(fonte.starts_vistos) == {NEGADO, ACEITO, ARMADO}
    assert fonte.starts_vistos[0] == NEGADO      # preparando
    assert fonte.starts_vistos[-1] == ARMADO     # resultado: pode começar de novo


def test_motor_nao_quebra_em_fonte_sem_feedback_start(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [[0]] * 40)
    assert m.rodada().humano is not None
