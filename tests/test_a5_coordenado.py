"""O `ControladorCoordenado` (agente A5): contrato C3, equivalência com o timer,
e a corrida real na rede aberta.

Os testes sem marca rodam numa máquina sem SUMO — eles exercitam o controlador
contra `Observacao` sintética, que é a superfície que a Arena entrega. Os
marcados `sumo`/`aberta` sobem a rede de verdade e são o que sustenta o DoD (a)
e o DoD (d).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from feira._fakes import observacao_fake, topologia_fake
from feira.contratos import MANTER, TROCAR, RestricoesFase, Topologia
from feira.controladores import ControladorTimer
from feira.controladores.coordenado import (
    ControladorCoordenado,
    PlanoFixo,
    PlanoIncompativel,
)

RAIZ = Path(__file__).resolve().parents[1]
PLANOS = RAIZ / "sumo" / "aberta" / "planos"
R = RestricoesFase(decision_interval=5, min_green=7, yellow=3, max_red=0.0)


def topo2(n: int = 4) -> Topologia:
    """Topologia com TODOS os semáforos de 2 fases — a da rede aberta (12/12)."""
    t = topologia_fake(n=n, n_controlaveis=n)
    return dataclasses.replace(t, n_fases_verdes=tuple([2] * n))


def plano_de(topo: Topologia, verdes, offsets, ciclo=60.0) -> PlanoFixo:
    return PlanoFixo(nome="t", cenario="aberta.maquete", ciclo_s=ciclo, amarelo_s=3.0,
                     verdes={t: tuple(verdes) for t in topo.tls_ids},
                     offsets={t: float(offsets.get(t, 0.0)) for t in topo.tls_ids})


# ------------------------------------------------------------------ contrato C3
def test_implementa_o_protocolo_controlador():
    from feira.contratos import Controlador

    c = ControladorCoordenado(plano_de(topo2(), (27.0, 27.0), {}))
    assert isinstance(c, Controlador)
    assert isinstance(c.nome, str) and c.nome


def test_decide_antes_de_reset_levanta():
    c = ControladorCoordenado(plano_de(topo2(), (27.0, 27.0), {}))
    with pytest.raises(RuntimeError, match="antes de reset"):
        c.decide(observacao_fake(topo2()))


def test_nao_le_env_var(monkeypatch):
    """C3: as restrições chegam no `reset()`. Um controlador que lê ST_* está
    errado por construção — aqui, mudar a env var não pode mudar nada."""
    topo = topo2()
    c = ControladorCoordenado(plano_de(topo, (27.0, 27.0), {}))
    c.reset(topo, R, 0.0)
    a1 = c.decide(observacao_fake(topo, t=30.0))
    monkeypatch.setenv("ST_MIN_GREEN", "99")
    monkeypatch.setenv("ST_BASELINE_GREEN", "5")
    c.reset(topo, R, 0.0)
    a2 = c.decide(observacao_fake(topo, t=30.0))
    assert np.array_equal(a1, a2)


def test_reset_e_idempotente():
    topo = topo2()
    c = ControladorCoordenado(plano_de(topo, (27.0, 27.0), {}))
    for _ in range(3):
        c.reset(topo, R, 300.0)
        assert c.n_decisoes == 0 and c.n_trocas == 0 and c.trocas == []


# ------------------------------------------------------- validação do plano
def test_reset_recusa_plano_que_nao_cobre_a_rede():
    topo = topo2(4)
    p = plano_de(topo2(2), (27.0, 27.0), {})       # só TL00 e TL01
    with pytest.raises(PlanoIncompativel, match="não cobre"):
        ControladorCoordenado(p).reset(topo, R, 0.0)


def test_reset_recusa_plano_com_numero_de_fases_errado():
    topo = topo2(3)
    p = PlanoFixo(nome="t", cenario="x", ciclo_s=60.0, amarelo_s=3.0,
                  verdes={t: (17.0, 17.0, 17.0) for t in topo.tls_ids},
                  offsets={t: 0.0 for t in topo.tls_ids})
    with pytest.raises(PlanoIncompativel, match="fase"):
        ControladorCoordenado(p).reset(topo, R, 0.0)


def test_reset_recusa_ciclo_fora_da_grade_de_decisao():
    topo = topo2()
    p = plano_de(topo, (27.0, 30.0), {}, ciclo=63.0)
    with pytest.raises(PlanoIncompativel, match="múltiplo da grade"):
        ControladorCoordenado(p).reset(topo, R, 0.0)


def test_reset_recusa_amarelo_diferente_do_cenario():
    """Amarelo diferente entre braços é restrição de fase diferente, e o C1 diz
    que ela é a MESMA para os três. Falha alto em vez de medir outra coisa."""
    topo = topo2()
    p = PlanoFixo(nome="t", cenario="x", ciclo_s=60.0, amarelo_s=5.0,
                  verdes={t: (25.0, 25.0) for t in topo.tls_ids},
                  offsets={t: 0.0 for t in topo.tls_ids})
    with pytest.raises(PlanoIncompativel, match="amarelo"):
        ControladorCoordenado(p).reset(topo, R, 0.0)


# --------------------------------------------------------------- a decisão
def test_manter_quando_a_fase_corrente_e_a_do_plano():
    topo = topo2()
    c = ControladorCoordenado(plano_de(topo, (27.0, 27.0), {}))
    c.reset(topo, R, 0.0)
    obs = observacao_fake(topo, t=10.0)             # fase_atual = 0, plano quer 0
    assert np.array_equal(c.decide(obs), np.zeros(topo.n, dtype=np.int8))


def test_trocar_quando_o_plano_ja_quer_a_outra_fase():
    topo = topo2()
    c = ControladorCoordenado(plano_de(topo, (27.0, 27.0), {}))
    c.reset(topo, R, 0.0)
    obs = observacao_fake(topo, t=30.0)             # t=30 -> verde 1; corrente 0
    assert np.array_equal(c.decide(obs), np.full(topo.n, TROCAR, dtype=np.int8))


def test_nunca_comanda_troca_no_amarelo():
    """A ação é ignorada no amarelo de qualquer jeito; comandar assim mesmo
    poluiria a contagem de trocas e o diagnóstico do plano executado."""
    topo = topo2()
    c = ControladorCoordenado(plano_de(topo, (27.0, 27.0), {}))
    c.reset(topo, R, 0.0)
    obs = observacao_fake(topo, t=30.0)
    obs = dataclasses.replace(obs, em_amarelo=np.ones(topo.n, dtype=bool))
    assert np.array_equal(c.decide(obs), np.zeros(topo.n, dtype=np.int8))
    assert c.n_trocas == 0


def test_nunca_comanda_troca_em_semaforo_nao_controlavel():
    topo = topologia_fake(n=6, n_controlaveis=3)     # 3 com 2 fases, 3 com 1
    verdes = {t: ((27.0, 27.0) if k else (60.0,))
              for t, k in zip(topo.tls_ids, topo.controlavel)}
    p = PlanoFixo(nome="t", cenario="x", ciclo_s=60.0, amarelo_s=3.0, verdes=verdes,
                  offsets={t: 0.0 for t in topo.tls_ids})
    c = ControladorCoordenado(p)
    c.reset(topo, R, 0.0)
    a = c.decide(observacao_fake(topo, t=30.0))
    assert list(a) == [TROCAR, TROCAR, TROCAR, MANTER, MANTER, MANTER]


def test_o_offset_separa_no_tempo_as_intersecoes():
    """A onda verde vista de dentro do controlador: com o mesmo split e offsets
    diferentes, as interseções não trocam no mesmo instante — que é exatamente o
    que o timer uniforme faz de errado."""
    topo = topo2(3)
    p = PlanoFixo(nome="t", cenario="x", ciclo_s=60.0, amarelo_s=3.0,
                  verdes={t: (27.0, 27.0) for t in topo.tls_ids},
                  offsets=dict(zip(topo.tls_ids, (0.0, 10.0, 20.0))))
    c = ControladorCoordenado(p)
    c.reset(topo, R, 0.0)
    fase = np.zeros(topo.n, dtype=np.int64)
    for t in range(0, 300, 5):
        obs = dataclasses.replace(observacao_fake(topo, t=float(t)), fase_atual=fase.copy())
        for i in np.flatnonzero(c.decide(obs)):
            fase[i] ^= 1
    # o instante em que cada interseção ABRE o ciclo (troca para a fase 0),
    # depois do transiente de convergência: separados de 10 s, que é o offset.
    inicio = {i: [t for t, j, alvo in c.trocas if j == i and alvo == 0 and t >= 60]
              for i in range(3)}
    assert [v[0] for v in inicio.values()] == [60, 70, 80], inicio
    for v in inicio.values():                       # e o ciclo se mantém em 60 s
        assert [b - a for a, b in zip(v, v[1:])] == [60] * (len(v) - 1)


def test_e_deterministico_no_tempo_absoluto():
    """Duas instâncias do mesmo plano decidem igual no mesmo `t`, com o mesmo
    histórico — é o que faz o DoD (d) valer (mesmo plano, mesma seed, mesmo
    `Resultado`)."""
    topo = topo2()
    p = PlanoFixo.carrega(PLANOS / "coordenado_c60.json") if (PLANOS / "coordenado_c60.json").exists() \
        else plano_de(topo, (17.0, 37.0), {"TL00": 15.0})
    if p.tls_ids != topo.tls_ids:
        p = dataclasses.replace(p, verdes={t: (17.0, 37.0) for t in topo.tls_ids},
                                offsets=dict(zip(topo.tls_ids, (0.0, 15.0, 30.0, 45.0))))
    a, b = ControladorCoordenado(p), ControladorCoordenado(p)
    a.reset(topo, R, 300.0)
    b.reset(topo, R, 300.0)
    fa = np.zeros(topo.n, dtype=np.int64)
    fb = np.zeros(topo.n, dtype=np.int64)
    for t in range(300, 900, 5):
        oa = dataclasses.replace(observacao_fake(topo, t=float(t)), fase_atual=fa.copy())
        ob = dataclasses.replace(observacao_fake(topo, t=float(t)), fase_atual=fb.copy())
        aa, bb = a.decide(oa), b.decide(ob)
        assert np.array_equal(aa, bb)
        fa[aa == TROCAR] ^= 1
        fb[bb == TROCAR] ^= 1
    assert a.trocas == b.trocas and a.n_trocas > 0


def test_o_plano_se_recupera_de_uma_troca_negada():
    """O ponto do relógio absoluto: um `min_green` negado NÃO desloca o plano
    para sempre. Aqui a troca é ignorada num tick (a fase não muda) e o plano
    volta ao lugar sozinho no tick seguinte, sem acumular atraso."""
    topo = topo2(1)
    p = plano_de(topo, (27.0, 27.0), {})
    c = ControladorCoordenado(p)
    c.reset(topo, R, 0.0)
    fase = np.zeros(1, dtype=np.int64)
    trocas = []
    for t in range(0, 180, 5):
        obs = dataclasses.replace(observacao_fake(topo, t=float(t)), fase_atual=fase.copy())
        a = c.decide(obs)
        if a[0] == TROCAR:
            trocas.append(t)
            if t != 30:                    # o de t=30 é NEGADO (min_green)
                fase[0] = 1 - fase[0]
    # 30 negado, reemitido em 35 e aceito; a partir daí volta ao relógio do plano
    assert trocas[:4] == [30, 35, 60, 90], trocas


# --------------------------------------------- equivalência com o timer de hoje
def test_plano_uniforme_decide_igual_ao_ControladorTimer():
    """DoD do baseline: o `ControladorCoordenado` com o plano `uniforme` é o
    `ControladorTimer(27)`. Sem isto a varredura compararia dois adversários
    diferentes e o degrau 0 não seria degrau nenhum."""
    topo = topo2(4)
    p = PlanoFixo.uniforme(topo.tls_ids, topo.n_fases_verdes, 27.0, 3.0)
    coord = ControladorCoordenado(p)
    timer = ControladorTimer(27)
    coord.reset(topo, R, 0.0)
    timer.reset(topo, R, 0.0)
    fase = np.zeros(topo.n, dtype=np.int64)
    verde_desde = np.zeros(topo.n, dtype=np.float64)
    iguais = 0
    for t in range(0, 600, 5):
        base = observacao_fake(topo, t=float(t))
        obs = dataclasses.replace(base, fase_atual=fase.copy(), verde_desde=verde_desde.copy())
        a, b = coord.decide(obs), timer.decide(obs)
        assert np.array_equal(a, b), (t, a, b)
        iguais += 1
        # avança a máquina de fases como a Arena faria: amarelo de 3 s
        troca = a == TROCAR
        verde_desde += 5.0
        verde_desde[troca] = -3.0 + 5.0            # verde novo começa em t+3
        fase[troca] ^= 1
    assert iguais == 120 and coord.n_trocas > 0


# ------------------------------------------- entrada na suíte de conformidade
def _fabrica_conformidade():
    """A fábrica que o `tests/test_conformidade.py` deve registrar no C3.

    `test_conformidade.py` está fora do escopo de escrita do agente A5, então o
    snippet vive aqui, EXERCITADO, e o relatório só pede o `pytest.param`. A
    topologia da suíte é a FAKE (12 semáforos, 8 controláveis, 1 ou 2 fases
    verdes) e não a rede aberta, por isso a fábrica monta o plano equivalente
    sobre ela em vez de carregar um plano congelado — que descreve outros
    `tls_ids`.
    """
    topo = topologia_fake()
    p = PlanoFixo.uniforme(topo.tls_ids, topo.n_fases_verdes, 27.0, 3.0,
                           nome="conformidade", cenario="small.maquete")
    return ControladorCoordenado(p)


def test_a_fabrica_de_conformidade_passa_o_que_a_suite_C3_exige():
    """As mesmas quatro asserções de `test_conformidade.py::IMPLS_CONTROLADOR`,
    para o registro poder ser feito sem surpresa."""
    from feira.contratos import Controlador

    topo = topologia_fake()
    restricoes = RestricoesFase(decision_interval=5, min_green=7, yellow=3)

    c = _fabrica_conformidade()
    assert isinstance(c, Controlador) and isinstance(c.nome, str) and c.nome

    with pytest.raises(Exception):
        c.decide(observacao_fake(topo))

    c.reset(topo, restricoes, t0=0.0)
    for i in range(5):
        a = c.decide(observacao_fake(topo, t=float(i * restricoes.decision_interval)))
        assert a.shape == (topo.n,)
        assert np.isin(a, (MANTER, TROCAR)).all()

    obs = [observacao_fake(topo, t=float(i)) for i in range(6)]
    c.reset(topo, restricoes, t0=0.0)
    a1 = [c.decide(o).copy() for o in obs]
    c.reset(topo, restricoes, t0=0.0)
    a2 = [c.decide(o).copy() for o in obs]
    for x, y in zip(a1, a2):
        assert np.array_equal(x, y)


# ------------------------------------------------------------- na Arena real
@pytest.mark.sumo
@pytest.mark.aberta
def test_uniforme_c60_reproduz_o_timer27_na_arena():
    """O degrau 0 da varredura, medido: `ControladorCoordenado(uniforme_c60)` e
    `ControladorTimer(27)` têm que devolver o MESMO `Resultado` na mesma seed —
    são o mesmo plano por dois caminhos de código."""
    cen, seed, janela = _cenario_aberto()
    from feira.arena import ArenaSumo

    arena = ArenaSumo()
    a = arena.roda(cen, seed, ControladorTimer(27), janela)
    b = arena.roda(cen, seed,
                   ControladorCoordenado(PLANOS / "uniforme_c60.json"), janela)
    assert (a.entregues, a.fila_media, a.tempo_medio_entregue) == \
           (b.entregues, b.fila_media, b.tempo_medio_entregue)


@pytest.mark.sumo
@pytest.mark.aberta
def test_mesmo_plano_mesma_seed_mesmo_resultado():
    """DoD (d): determinismo. Duas corridas da mesma condição são idênticas."""
    cen, seed, janela = _cenario_aberto()
    from feira.arena import ArenaSumo

    arena = ArenaSumo()
    r = [arena.roda(cen, seed, ControladorCoordenado(PLANOS / "coordenado_c60.json"),
                    janela) for _ in range(2)]
    assert r[0] == r[1]


@pytest.mark.sumo
@pytest.mark.aberta
def test_o_plano_executado_bate_com_o_plano_congelado():
    """O que a malha EXECUTA tem que ser o que está no arquivo — verde a verde.
    É a única forma de o número publicado descrever o plano publicado."""
    cen, seed, janela = _cenario_aberto()
    from feira.arena import ArenaSumo

    plano = PlanoFixo.carrega(PLANOS / "coordenado_c60.json")
    ctrl = ControladorCoordenado(plano)
    ArenaSumo().roda(cen, seed, ctrl, janela)
    exe = ctrl.plano_executado()
    for tls, v in exe.items():
        assert v["offset_estavel"] is True, "%s: a onda verde derivou" % tls
        alvo = sorted(plano.verdes[tls])
        assert sorted({v["verde_min_s"], v["verde_max_s"]}) == alvo, tls


def _cenario_aberto():
    """O cenário da rede aberta com o `.sumocfg` DA SEED no lugar do canônico.

    A troca não é preferência: `ArenaSumo.roda()` chama `self.topologia()`
    DEPOIS de apontar `constants.SUMOCFG` para o arquivo da seed, e
    `topologia()` chama `_amarra_sim`, que reescreve o campo de volta para o
    canônico — que não tem `<route-files>`. Sem este desvio a corrida sobe a
    rede VAZIA (0 veículos inseridos, `travou=True`) e o teste passaria a medir
    nada. Reportado ao dono do projeto; `feira/arena/**` está fora do escopo de
    escrita do agente A5.
    """
    from feira.contratos import Janela
    from feira.contratos import cenario as resolve_cenario

    cen = resolve_cenario("aberta.maquete")
    if not cen.disponivel():
        pytest.skip("rede aberta não construída")
    if not (PLANOS / "coordenado_c60.json").exists():
        pytest.skip("planos do A5 ainda não gerados")
    seed = 42
    if not cen.rou_file(seed).exists():
        pytest.skip("demanda da seed %d não gerada" % seed)
    base = Path(cen.sumocfg)
    por_seed = base.with_name("%s_s%d%s" % (base.stem, seed, base.suffix))
    if not por_seed.exists():
        pytest.skip("sumocfg da seed %d não gerado" % seed)
    cen = dataclasses.replace(cen, sumocfg=str(por_seed))
    return cen, seed, Janela(t0=float(cen.warmup_s), t1=float(cen.warmup_s) + 600.0)
