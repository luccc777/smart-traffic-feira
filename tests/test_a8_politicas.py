"""As políticas roteirizadas do A8 — o que o adversário APERTA, sem SUMO nenhum.

Estes testes guardam três coisas que, se quebrarem, produzem número errado sem
erro nenhum na tela:

1. **repetição de adversário determinístico é cópia** — e a campanha precisa
   saber disso para não inflar o intervalo de confiança com 200 clones;
2. **a política oráculo recusa decidir sem o mapa fase→aproximação** em vez de
   ler `NaN` e apertar por engano;
3. **a semente fecha a rodada**: (adversário, seed, repetição) determina a
   sequência inteira de botões, e por isso um resultado pode ser reauditado
   depois.
"""
from __future__ import annotations

import random

import numpy as np
import pytest

from feira._fakes import observacao_fake, topologia_fake
from feira.adversarios.politicas import (
    Aleatoria,
    Arterial,
    GulosaFase,
    GulosaFila,
    Limite,
    Martelo,
    Parada,
    Periodica,
    Roteirista,
    Ruido,
    Sabotador,
    de_texto,
    leitura_de,
    verde_realizado_s,
)

N = 12


def _rng():
    return random.Random(0)


def _roteirista(pol, **kw) -> Roteirista:
    r = Roteirista(politica=pol, **kw)
    r.reset(N)
    return r


# ------------------------------------------------------------------ básicas
def test_martelo_aperta_os_doze_em_todo_tick():
    r = _roteirista(Martelo())
    assert [r.aperta(t, None) for t in range(3)] == [tuple(range(N))] * 3


def test_parado_nao_aperta_nada():
    r = _roteirista(Parada())
    assert all(r.aperta(t, None) == () for t in range(5))


def test_periodica_respeita_o_periodo():
    r = _roteirista(Periodica(3))
    apertou = [bool(r.aperta(t, None)) for t in range(9)]
    assert apertou == [True, False, False, True, False, False, True, False, False]


def test_periodo_zero_e_erro_e_nao_divisao_por_zero():
    with pytest.raises(ValueError):
        Periodica(0)


def test_aleatoria_nos_extremos():
    assert _roteirista(Aleatoria(0.0)).aperta(0, None) == ()
    assert _roteirista(Aleatoria(1.0)).aperta(0, None) == tuple(range(N))


def test_aleatoria_fora_de_zero_um_falha_alto():
    with pytest.raises(ValueError):
        Aleatoria(1.5)


# -------------------------------------------------------------- modificadores
def test_ruido_de_falha_total_apaga_a_pressao():
    r = _roteirista(Martelo(), ruido=Ruido(p_falha=1.0))
    assert r.aperta(0, None) == ()


def test_ruido_extra_total_aperta_tudo_mesmo_partindo_do_parado():
    r = _roteirista(Parada(), ruido=Ruido(p_extra=1.0))
    assert r.aperta(0, None) == tuple(range(N))


def test_limite_trunca_preservando_a_prioridade_da_politica():
    assert Limite(3).aplica((7, 2, 9, 1), _rng()) == (7, 2, 9)
    assert Limite(0).aplica((7, 2, 9, 1), _rng()) == (7, 2, 9, 1)


def test_a_semente_fecha_a_rodada_e_sementes_diferentes_divergem():
    def seq(semente):
        r = _roteirista(Aleatoria(0.5), semente=semente)
        return [r.aperta(t, None) for t in range(20)]

    assert seq(7) == seq(7)
    assert seq(7) != seq(8)


def test_reset_e_idempotente_no_sorteio():
    r = _roteirista(Aleatoria(0.5), semente=3)
    a = [r.aperta(t, None) for t in range(10)]
    r.reset(N)
    assert [r.aperta(t, None) for t in range(10)] == a


def test_deterministica_so_quando_nao_ha_sorteio_nenhum():
    assert _roteirista(Martelo()).deterministica
    assert not _roteirista(Martelo(), ruido=Ruido(p_falha=0.05)).deterministica
    # a aleatória sorteia por conta própria: repetir a seed NÃO é copiar a rodada
    assert not _roteirista(Aleatoria(0.35)).deterministica


def test_nome_carrega_os_modificadores():
    r = de_texto("gulosa_fase:f=1@lag=1@falha=0.05@mao=6")
    assert r.nome == "gulosa_fase_f1+lag1+falha0.05+mao6"
    assert r.lag_ticks == 1 and r.limite.max_por_tick == 6


# -------------------------------------------------------------------- leitura
def _leitura(fila_por_tl, halting, fase, serve, capacidade=10.0):
    topo = topologia_fake(len(fila_por_tl))
    obs = observacao_fake(topo)
    estado = np.zeros((len(fila_por_tl), 26), dtype=np.float32)
    for i, quatro in enumerate(halting):
        for k, v in enumerate(quatro):
            estado[i, 4 * k] = v / capacidade
    obs = type(obs)(t=obs.t, estado=estado,
                    fase_atual=np.asarray(fase, dtype=np.int64),
                    verde_desde=np.full(len(fila_por_tl), 30.0),
                    em_amarelo=np.zeros(len(fila_por_tl), dtype=bool),
                    pode_trocar=np.ones(len(fila_por_tl), dtype=bool),
                    fila_por_tl=np.asarray(fila_por_tl, dtype=np.float64))
    return leitura_de(obs, (np.asarray(serve, dtype=bool), capacidade))


def test_leitura_separa_a_fila_servida_da_parada():
    # 1 cruzamento, 2 grupos: g0 serve N+S, g1 serve E+W. Fase corrente = g0.
    serve = [[[True, True, False, False], [False, False, True, True]]]
    lei = _leitura([9.0], [[2.0, 1.0, 5.0, 1.0]], [0], serve)
    assert lei.tem_aproximacoes
    assert lei.fila_servida[0] == pytest.approx(3.0)
    assert lei.fila_parada[0] == pytest.approx(6.0)


def test_sem_mapa_a_leitura_vem_nan_e_a_oraculo_recusa():
    topo = topologia_fake(4)
    lei = leitura_de(observacao_fake(topo))
    assert not lei.tem_aproximacoes
    pol = GulosaFase()
    pol.reset(4)
    with pytest.raises(ValueError, match="mapa"):
        pol.aperta(0, lei, _rng())


def test_arterial_sem_grupo_recusa_em_vez_de_apertar_no_escuro():
    pol = Arterial()
    pol.reset(4)
    topo = topologia_fake(4)
    with pytest.raises(ValueError, match="arterial"):
        pol.aperta(0, leitura_de(observacao_fake(topo)), _rng())


# -------------------------------------------------------------------- gulosas
def test_gulosa_fila_pega_os_k_maiores_acima_do_limiar():
    topo = topologia_fake(4)
    obs = observacao_fake(topo)
    obs = type(obs)(t=obs.t, estado=obs.estado, fase_atual=obs.fase_atual,
                    verde_desde=obs.verde_desde, em_amarelo=obs.em_amarelo,
                    pode_trocar=obs.pode_trocar,
                    fila_por_tl=np.asarray([0.0, 9.0, 3.0, 7.0]))
    pol = GulosaFila(k=2, limiar=1.0)
    pol.reset(4)
    assert pol.aperta(0, leitura_de(obs), _rng()) == (1, 3)


def test_gulosa_fase_troca_quando_o_vermelho_esta_mais_cheio():
    serve = [[[True, True, False, False], [False, False, True, True]]] * 2
    #        cruzamento 0: verde servindo 3, parado 6  -> troca
    #        cruzamento 1: verde servindo 8, parado 1  -> mantém
    lei = _leitura([9.0, 9.0], [[2.0, 1.0, 5.0, 1.0], [5.0, 3.0, 1.0, 0.0]], [0, 0], serve)
    pol = GulosaFase(fator=1.0)
    pol.reset(2)
    assert pol.aperta(0, lei, _rng()) == (0,)


def test_sabotador_faz_o_contrario_da_gulosa():
    serve = [[[True, True, False, False], [False, False, True, True]]] * 2
    lei = _leitura([9.0, 9.0], [[2.0, 1.0, 5.0, 1.0], [5.0, 3.0, 1.0, 0.0]], [0, 0], serve)
    pol = Sabotador()
    pol.reset(2)
    assert pol.aperta(0, lei, _rng()) == (1,)


def test_arterial_aperta_so_quem_nao_esta_na_fase_da_arterial():
    pol = Arterial().com_grupo(np.asarray([1, 1, 0]))
    pol.reset(3)
    serve = [[[True, True, False, False], [False, False, True, True]]] * 3
    lei = _leitura([1.0] * 3, [[0.0] * 4] * 3, [0, 1, 0], serve)
    assert pol.aperta(0, lei, _rng()) == (0,)


# ----------------------------------------------------------------- de_texto
def test_de_texto_desconhecido_falha_alto():
    with pytest.raises(ValueError, match="desconhecido"):
        de_texto("martelinho")
    with pytest.raises(ValueError, match="desconhecido"):
        de_texto("martelo@turbo=1")


def test_de_texto_le_parametros_e_modificadores():
    r = de_texto("aleatoria:p=0.35@falha=0.1@extra=0.02", semente=9)
    assert isinstance(r.politica, Aleatoria) and r.politica.p == pytest.approx(0.35)
    assert r.ruido == Ruido(p_falha=0.1, p_extra=0.02)
    assert r.semente == 9


def test_verde_realizado_respeita_o_piso_da_grade():
    # di=5, min_green=7, amarelo=3: o bloco mínimo é 10 s, o verde realizado 7 s.
    assert verde_realizado_s(1, 5, 7, 3) == pytest.approx(7.0)
    assert verde_realizado_s(2, 5, 7, 3) == pytest.approx(7.0)
    assert verde_realizado_s(3, 5, 7, 3) == pytest.approx(12.0)
    assert verde_realizado_s(6, 5, 7, 3) == pytest.approx(27.0)
