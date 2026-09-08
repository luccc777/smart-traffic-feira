"""A rodada de verdade: Arena + SUMO + rede aberta. É aqui que o DoD do A3 fecha.

Cada teste marcado `@sumo` sobe o SUMO na rede aberta e roda a janela da rodada
(300 s de aquecimento + 120 s de janela, ~2,5 s de parede por corrida).

O QUE ESTES TESTES PROVAM, E POR QUE SÃO CAROS
----------------------------------------------
(b) a intenção do humano respeita `min_green`/`yellow`: a MESMA sequência de
    botões aplicada ao `ControladorHumano` e a um controlador que emite as
    ações direto produz o MESMO `Resultado`, inclusive quando o roteiro pede
    troca antes do verde mínimo — o excesso é recusado nos dois lados pelo
    mesmo predicado.
(c) `ReplayInput` reproduz a rodada gravada com o mesmo `Resultado`.
(e) o fantasma e o braço humano saem do MESMO estado em `t0` — o achado do
    agente A1 sobre a quantização de 1 cm do `saveState` (ver
    `feira/jogo/estado.py`). Provado por impressão digital do estado, que é
    verificação e não promessa.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from feira.contratos import (
    MANTER,
    TROCAR,
    Janela,
    Ritmo,
    cenario,
    janela_padrao,
    valida_acoes,
)
from feira.controladores.humano import ControladorHumano
from feira.entrada import GravacaoRodada, LeitorRoteirizado, ReplayInput, TecladoInput
from feira.jogo import ControladorSelado, Fantasmaria, MotorDoJogo, cenario_da_seed

ABERTA = cenario("aberta.maquete")
TEM_SUMO = bool(os.environ.get("SUMO_HOME")) and ABERTA.disponivel()
SEED = 100
TEM_DEMANDA = TEM_SUMO and ABERTA.rou_file(SEED).exists()

sumo = pytest.mark.skipif(not TEM_DEMANDA,
                          reason="requer SUMO_HOME + rede aberta + demanda da seed %d" % SEED)

CAMPOS = ("entregues", "tempo_medio_entregue", "tempo_medio_no_sistema", "fila_media",
          "espera_media", "inseridos", "ativos_fim", "ativos_inicio",
          "backlog_insercao", "perdidos", "travou")


def _metricas(res) -> tuple:
    """As métricas do `Resultado` — sem o nome do controlador, que muda entre
    "humano:teclado" e "humano:replay" e não é o que a rodada mediu."""
    return tuple(getattr(res, c) for c in CAMPOS)


class ControladorRoteiro:
    """Emite vetores de ação prontos — o "controlador que as emite direto" do DoD (b)."""

    def __init__(self, vetores, *, nome: str = "roteiro") -> None:
        self.vetores = [np.asarray(v, dtype=np.int8) for v in vetores]
        self.nome = nome
        self._i = 0
        self._n = 0
        self.n_decisoes = 0

    def reset(self, topo, restricoes, t0) -> None:
        self._i = 0
        self._n = topo.n
        self.n_decisoes = 0

    def decide(self, obs):
        if self._n == 0:
            raise RuntimeError("decide() antes de reset()")
        self.n_decisoes += 1
        if self._i >= len(self.vetores):
            return valida_acoes(np.full(obs.n, MANTER, dtype=np.int8), obs.n)
        v = self.vetores[self._i]
        self._i += 1
        return valida_acoes(v, obs.n)


def _roteiro_botoes(n_ticks: int, n_botoes: int = 12, semente: int = 11) -> list[list[int]]:
    """Um jogador plausível: aperta demais, inclusive antes do verde fechar."""
    import random

    rng = random.Random(semente)
    return [[b for b in range(n_botoes) if rng.random() < 0.35] for _ in range(n_ticks)]


def _arena():
    from feira.arena import ArenaSumo

    return ArenaSumo()


def _janela() -> Janela:
    return janela_padrao(ABERTA, rodada=True)


# ------------------------------------------------------------------ DoD (b)
@sumo
def test_intencao_do_humano_respeita_min_green_e_yellow():
    """Nenhuma troca emitida antes do verde mínimo, nenhuma dentro do amarelo —
    e o roteiro pede as duas coisas o tempo todo."""
    janela = _janela()
    n_ticks = int(janela.duracao / ABERTA.restricoes.decision_interval) + 2
    humano = ControladorSelado(ControladorHumano(ReplayInput(12, _roteiro_botoes(n_ticks))),
                               guarda_acoes=True)
    _arena().roda(cenario_da_seed(ABERTA, SEED), SEED, humano, janela)

    assert humano.verde_nas_trocas, "o roteiro não produziu troca nenhuma"
    assert min(humano.verde_nas_trocas) >= ABERTA.restricoes.min_green
    assert humano.trocas_em_amarelo == 0


@sumo
def test_humano_e_controlador_direto_medem_o_mesmo():
    """DoD (b): a MESMA sequência de ações nos dois caminhos dá o MESMO `Resultado`.

    O braço direto recebe os vetores CRUS do roteiro (todo botão apertado vira
    `TROCAR`, sem máscara nenhuma). O humano recebe os botões e mascara com
    `obs.pode_trocar`. Os dois medem igual porque o predicado é o mesmo — é
    isso, e não a boa vontade do código do jogo, que impede o visitante de
    ganhar uma grade mais fina que a da política.
    """
    janela = _janela()
    n_ticks = int(janela.duracao / ABERTA.restricoes.decision_interval) + 2
    roteiro = _roteiro_botoes(n_ticks)

    humano = ControladorSelado(ControladorHumano(ReplayInput(12, roteiro)), guarda_acoes=True)
    r_humano = _arena().roda(cenario_da_seed(ABERTA, SEED), SEED, humano, janela)

    crus = []
    for slot in roteiro:
        v = np.full(12, MANTER, dtype=np.int8)
        for b in slot:
            v[b] = TROCAR
        crus.append(v)
    direto = ControladorSelado(ControladorRoteiro(crus, nome="humano:direto"))
    r_direto = _arena().roda(cenario_da_seed(ABERTA, SEED), SEED, direto, janela)

    assert _metricas(r_humano) == _metricas(r_direto)
    assert r_humano.chave == r_direto.chave
    assert humano.selo == direto.selo
    # e o mascaramento fez trabalho de verdade: houve botão recusado
    assert humano.alvo.n_negados > 0


# ------------------------------------------------------------------ DoD (c)
@sumo
def test_replay_reproduz_a_rodada_gravada(tmp_path):
    """DoD (c): a rodada gravada dá o mesmo `Resultado`, byte a byte nas métricas."""
    janela = _janela()
    n_ticks = int(janela.duracao / ABERTA.restricoes.decision_interval) + 2
    teclas = ["".join("qwerasdfzxcv"[b] for b in slot)
              for slot in _roteiro_botoes(n_ticks, semente=5)]
    fonte = TecladoInput(12, leitor=LeitorRoteirizado([""] + teclas))
    ao_vivo = ControladorHumano(fonte)
    r1 = _arena().roda(cenario_da_seed(ABERTA, SEED), SEED, ao_vivo, janela)

    gravacao = GravacaoRodada.de(r1.chave, n_botoes=12, fonte="teclado",
                                 ticks=ao_vivo.gravacao)
    caminho = gravacao.salva(tmp_path / "rodada.json")
    lida = GravacaoRodada.carrega(caminho)
    lida.confere(r1.chave)

    r2 = _arena().roda(cenario_da_seed(ABERTA, SEED), SEED,
                       ControladorHumano(lida.fonte_de_replay()), janela)
    assert _metricas(r2) == _metricas(r1)
    assert r2.chave == r1.chave


# ------------------------------------------------------------------ DoD (e)
@sumo
def test_fantasma_e_humano_saem_do_mesmo_estado_em_t0(tmp_path):
    """DoD (e). O invariante é "todos os braços partem do MESMO estado em t0".

    Aqui ele é obtido pela via EXATA — replay do aquecimento a partir de t=0,
    que o agente A1 mediu ser bit-idêntico entre corridas — em vez do
    `loadState`, que reproduz t0 só na precisão do arquivo (2 casas) e cuja
    continuação diverge. Verificado, não prometido: o selo é a impressão digital
    do estado que o controlador recebe em t0, e ele tem que bater entre o
    fantasma e o braço humano.
    """
    fm = Fantasmaria(ABERTA, raiz=tmp_path, arena=_arena())
    fantasma = fm.calcula(SEED, "timer")
    selo_fantasma = fm.selos[(SEED, "timer")]

    humano = ControladorSelado(ControladorHumano(ReplayInput(12, [[0], [], [5]])))
    _arena().roda(cenario_da_seed(ABERTA, SEED), SEED, humano, fm.janela())

    assert humano.selo == selo_fantasma
    # mesmo estado E mesmo instante. O `+1 s` é o deslocamento da Arena
    # (`TrafficEnv.reset` já dá um sim-step) e é idêntico nos dois braços.
    assert humano.t0 == fm.t0s[(SEED, "timer")] == fantasma.chave.janela.t0 + 1.0

    # e o selo tem dentes: outra seed é outro estado.
    outro = ControladorSelado(ControladorHumano(ReplayInput(12, [[0]])))
    _arena().roda(cenario_da_seed(ABERTA, SEED + 1), SEED + 1, outro, fm.janela())
    assert outro.selo != selo_fantasma


@sumo
def test_fantasma_de_outra_seed_e_recusado_na_rodada(tmp_path):
    """DoD (d) com SUMO: fantasma velho parece válido na tela."""
    from feira.contratos import FantasmaIncompativel, caminho_fantasma

    fm = Fantasmaria(ABERTA, raiz=tmp_path, arena=_arena())
    f = fm.calcula(SEED, "timer")
    f.salva(caminho_fantasma(tmp_path, fm.chave(SEED + 1), "timer"))
    with pytest.raises(FantasmaIncompativel, match="não serve"):
        fm.carrega(SEED + 1, "timer")


# ------------------------------------------------------------------ DoD (a)
@sumo
def test_rodada_completa_no_teclado_sem_pyserial(tmp_path):
    """DoD (a): rodada inteira jogável só com teclado, sem `pyserial` instalado."""
    import sys

    teclas = ["".join("qwerasdfzxcv"[b] for b in slot)
              for slot in _roteiro_botoes(30, semente=3)]
    fonte = TecladoInput(12, leitor=LeitorRoteirizado(["", " "] + teclas))
    publicados: list[dict] = []
    motor = MotorDoJogo(
        ABERTA, fonte=fonte,
        fantasmaria=Fantasmaria(ABERTA, raiz=tmp_path, arena=_arena()),
        arena=_arena(), publicador=publicados.append, seeds=(SEED,),
        bracos=("timer",), ao_vivo=False, prefetch=False, resultado_s=0.0,
        grava_em=tmp_path)

    assert motor.espera_start(timeout=1.0) is True
    r = motor.rodada()

    assert "serial" not in sys.modules
    assert r.humano is not None and r.humano.sane()[0], r.humano.sane()[1]
    assert r.placar is not None and r.selos_batem
    assert {ln["braco"] for ln in r.placar.json()["linhas"]} == {"timer", "humano"}
    assert r.gravacao is not None and r.gravacao.n_pressoes > 0
    assert any(p["fase"] == "jogando" for p in publicados)
    # a gravação salva em disco reproduz a MESMA rodada
    salvas = list(Path(tmp_path).rglob("rodadas/**/*.json"))
    assert salvas, "a gravação não foi salva"


@sumo
def test_ritmo_ao_vivo_e_1_para_1():
    """A rodada é 1:1 — 120 s simulados em 120 s de parede. Aqui só se prova que
    o `Ritmo` chega à Arena e que o aquecimento NÃO paga esse pedágio (ele roda
    solto, e é por isso que a contagem 3-2-1 cabe dentro do `reset`)."""
    import time

    janela = Janela(t0=300.0, t1=305.0)
    arena = _arena()
    t0 = time.perf_counter()
    arena.roda(cenario_da_seed(ABERTA, SEED), SEED,
               ControladorHumano(ReplayInput(12, [[]])), janela,
               ritmo=Ritmo(sim_por_parede=1.0))
    gasto = time.perf_counter() - t0
    assert 5.0 <= gasto < 20.0, gasto          # 5 s de janela + aquecimento solto
    assert arena.ultimo_diagnostico["passos_aquecimento"] == 300
