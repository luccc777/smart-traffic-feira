"""O adversário entra pela porta do visitante — a armadilha nº1 do A8, guardada.

Um adversário escrito direto como `Controlador` (C3) devolveria o vetor de ações
e pularia a camada que DEFINE o jogo: a intenção que entra numa fila, é consumida
no próximo tick da grade e só é aceita se o verde mínimo fechou. Estes testes
provam que o `AdversarioHumano` não pula nada disso — ele não emite ação nenhuma,
quem emite é o `ControladorHumano` do agente A3.

Nada aqui sobe SUMO: a Arena é substituída por observações montadas à mão, o que
permite controlar `pode_trocar` tick a tick — que é o único jeito de testar "a
intenção negada é GASTA, não guardada".
"""
from __future__ import annotations

import numpy as np
import pytest

from feira._fakes import topologia_fake
from feira.adversarios import AdversarioHumano, FonteRoteirizada
from feira.adversarios.politicas import Martelo, Roteirista, Ruido, de_texto
from feira.contratos import (
    MANTER,
    TROCAR,
    Controlador,
    FonteEntrada,
    Observacao,
    RestricoesFase,
)
from feira.controladores.humano import ControladorHumano
from feira.entrada import ReplayInput

RESTRICOES = RestricoesFase(decision_interval=5, min_green=7, yellow=3)
N = 12


def topo():
    return topologia_fake(N, n_controlaveis=N)


def obs(t: float, pode, *, fila=None, fase=None) -> Observacao:
    pode = np.asarray(pode, dtype=bool)
    n = pode.shape[0]
    return Observacao(
        t=float(t), estado=np.zeros((n, 26), dtype=np.float32),
        fase_atual=np.zeros(n, dtype=np.int64) if fase is None
        else np.asarray(fase, dtype=np.int64),
        verde_desde=np.where(pode, 30.0, 1.0),
        em_amarelo=~pode,
        pode_trocar=pode,
        fila_por_tl=np.zeros(n) if fila is None else np.asarray(fila, dtype=np.float64))


def adversario(spec: str = "martelo", **kw) -> AdversarioHumano:
    a = AdversarioHumano(de_texto(spec, semente=kw.pop("semente", 0)), **kw)
    a.reset(topo(), RESTRICOES, 300.0)
    return a


# ------------------------------------------------------------------ contratos
def test_a_fonte_roteirizada_e_uma_fonte_de_entrada():
    assert isinstance(FonteRoteirizada(N), FonteEntrada)


def test_o_adversario_e_um_controlador():
    assert isinstance(adversario(), Controlador)


def test_o_adversario_nao_emite_acao_por_conta_propria():
    """Quem decide é o `ControladorHumano` embutido — o adversário só carrega o botão."""
    a = adversario()
    assert isinstance(a.humano, ControladorHumano)
    assert a.humano.fonte is a.fonte


def test_botao_fora_da_faixa_e_erro_e_nao_no_op():
    f = FonteRoteirizada(4)
    with pytest.raises(ValueError, match="fora"):
        f.carrega([4])


# ----------------------------------------------------- a máscara é do humano
def test_martelo_so_troca_onde_pode_trocar():
    a = adversario("martelo")
    pode = np.array([True, False] * 6)
    acoes = a.decide(obs(300.0, pode))
    assert list(acoes) == [TROCAR if p else MANTER for p in pode]
    assert a.n_aceitos == 6 and a.n_negados == 6


def test_a_intencao_negada_e_gasta_e_nao_dispara_no_tick_seguinte():
    """A regra do §1.1 do JOGO.md: "consumida no próximo tick" quer dizer gasta.

    Guardá-la para disparar sozinha daria ao humano um efeito que a ação da RL
    não tem — a RL emite um bit por tick e o bit recusado se perde.
    """
    a = adversario("periodica:p=1000")          # aperta só no tick 0
    negado = a.decide(obs(300.0, np.zeros(N, dtype=bool)))
    assert list(negado) == [MANTER] * N
    depois = a.decide(obs(305.0, np.ones(N, dtype=bool)))
    assert list(depois) == [MANTER] * N         # a intenção morreu no tick anterior


def test_o_atraso_de_um_tick_desloca_a_pressao_inteira():
    sem = adversario("periodica:p=1000")
    com = adversario("periodica:p=1000@lag=1")
    pode = np.ones(N, dtype=bool)
    assert list(sem.decide(obs(300.0, pode))) == [TROCAR] * N
    assert list(com.decide(obs(300.0, pode))) == [MANTER] * N     # ainda reagindo
    assert list(com.decide(obs(305.0, pode))) == [TROCAR] * N     # chegou um tick depois


def test_o_lag_le_a_tela_do_tick_anterior():
    """Com `lag=1` a decisão sai da leitura VELHA — é o que "reação humana" quer dizer."""
    a = adversario("gulosa_fila:k=1@lag=1")
    pode = np.ones(N, dtype=bool)
    fila_um = np.zeros(N)
    fila_um[3] = 50.0
    a.decide(obs(300.0, pode, fila=fila_um))     # vê a fila em 3, ainda não aperta
    fila_dois = np.zeros(N)
    fila_dois[7] = 50.0
    acoes = a.decide(obs(305.0, pode, fila=fila_dois))
    assert acoes[3] == TROCAR and acoes[7] == MANTER


def test_ruido_de_falha_total_zera_a_rodada_inteira():
    a = AdversarioHumano(Roteirista(politica=Martelo(), ruido=Ruido(p_falha=1.0)))
    a.reset(topo(), RESTRICOES, 300.0)
    assert list(a.decide(obs(300.0, np.ones(N, dtype=bool)))) == [MANTER] * N


def test_mao_limitada_aperta_no_maximo_o_que_cabe():
    a = adversario("martelo@mao=3")
    acoes = a.decide(obs(300.0, np.ones(N, dtype=bool)))
    assert int(np.sum(acoes == TROCAR)) == 3


# ------------------------------------------------------------- reprodutibilidade
def test_a_gravacao_reproduz_a_rodada_no_replay_input():
    """A rodada do adversário é gravável no MESMO formato do `ReplayInput` (C6).

    Sem isto, uma rodada suspeita não poderia ser reauditada — e é assim que o
    modo jogo grava a rodada do público.
    """
    seq = [np.array([True] * 6 + [False] * 6), np.ones(N, dtype=bool),
           np.array([False] * 3 + [True] * 9)]
    a = adversario("aleatoria:p=0.5", semente=11)
    acoes_a = [a.decide(obs(300.0 + 5 * i, p)).copy() for i, p in enumerate(seq)]

    humano = ControladorHumano(ReplayInput(N, [list(t) for t in a.gravacao]))
    humano.reset(topo(), RESTRICOES, 300.0)
    acoes_b = [humano.decide(obs(300.0 + 5 * i, p)).copy() for i, p in enumerate(seq)]
    assert [list(x) for x in acoes_a] == [list(x) for x in acoes_b]


def test_reset_rebobina_a_fonte_e_a_sequencia_recomeca():
    a = adversario("aleatoria:p=0.5", semente=5)
    pode = np.ones(N, dtype=bool)
    antes = [list(a.decide(obs(300.0 + 5 * i, pode))) for i in range(6)]
    a.reset(topo(), RESTRICOES, 300.0)
    assert [list(a.decide(obs(300.0 + 5 * i, pode))) for i in range(6)] == antes


def test_o_diagnostico_conta_intencao_pressao_e_recusa():
    a = adversario("martelo")
    a.decide(obs(300.0, np.array([True] * 4 + [False] * 8)))
    d = a.diagnostico()
    assert d["intencoes"] == N and d["pressoes"] == N
    assert d["aceitos"] == 4 and d["negados"] == 8
    assert d["decisoes"] == 1 and d["deterministica"] is True
