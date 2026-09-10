"""A contabilidade (C5) e o detector que substitui o `coherence_gap`.

Sem SUMO: é aritmética e contabilidade. O teste que exige o SUMO de verdade
(a Arena rodando os três braços pelo mesmo laço) está em `test_a2_arena.py`.

Este arquivo é o espelho de `smart-traffic-maquete/tests/test_coherence_gap.py`:
os mesmos números medidos, o mesmo par "política sã × política que trava" — só
que passando pelo detector novo, que não supõe frota fechada.
"""
from __future__ import annotations

import math

import pytest

from feira import _fakes as F

# `teste_pareado` NAO e importado por nome: o pytest coleta `test*` e ia tentar
# rodar a funcao como se fosse um teste.
from feira import estatistica
from feira.contratos import ChavesIncompativeis, Resultado, comparar
from feira.estatistica import pareia_por_chave, resumo_pareado
from feira.metricas import (
    Contabilidade,
    diagnostico,
    lacuna_sobrevivencia,
    sinais_de_travamento,
)

# Números MEDIDOS na rede fechada, 12 seeds held-out (docs/RESULTADOS_ATS.md §4):
#   timer 27 s : 66,9 s / 12,16 / 1594     v2 (ats) : 56,2 s / 7,99 / 1904
#   variante C (descartada, travava em 2/12): 51,4 s / 7,12 / 1761
N_FROTA = 30
JANELA_S = 3600.0


def _res(**campos) -> Resultado:
    """Um `Resultado` de rede FECHADA em regime: a frota não muda de tamanho, e
    cada chegada reabre uma viagem no mesmo instante (por isso inseridos ==
    entregues)."""
    entregues = campos.pop("entregues", 1904)
    base = dict(
        entregues=entregues,
        inseridos=entregues,
        ativos_inicio=N_FROTA,
        ativos_fim=N_FROTA,
        backlog_insercao=0,
        perdidos=0,
        tempo_medio_entregue=56.2,
        tempo_medio_no_sistema=59.0,
        fila_media=7.99,
        espera_media=12.4,
    )
    base.update(campos)
    return F.resultado_fake(F.chave_fake(t0=0.0, t1=JANELA_S), **base)


# ============================================================ Contabilidade
def test_contabilidade_fecha_o_balanco_na_frota_persistente():
    """Frota fechada: a chegada NÃO tira o carro da rede — fecha uma viagem e
    abre outra. Entrega e ativação andam juntas, e o balanço fecha em zero."""
    c = Contabilidade()
    c.abre_janela(0.0, ativos=3, abertos={"car00": 0.0, "car01": 0.0, "car02": 0.0})
    for t in (10.0, 20.0, 30.0):
        c.chegou("car00", t, t_abre=t - 10.0)
        c.ativou("car00", t, fisica=False, t_abre=t)
        c.amostra_rede(2.0, 4.0)
    c.fecha_janela(60.0, ativos=3, backlog=0)

    res = c.resultado(F.chave_fake(t0=0.0, t1=60.0), "teste")
    assert res.entregues == 3 and res.inseridos == 3
    assert res.conservacao == 0
    assert res.sane()[0], res.sane()[1]
    assert res.tempo_medio_entregue == pytest.approx(10.0)


def test_contabilidade_denuncia_carro_que_evaporou():
    """A identidade só tem dentes porque `ativos_fim` vem do SUMO e os eventos
    vêm de outro lugar. Um carro que some sem virar evento quebra as duas."""
    c = Contabilidade()
    c.abre_janela(0.0, ativos=3, abertos={"a": 0.0, "b": 0.0, "c": 0.0})
    c.chegou("a", 10.0, t_abre=0.0)
    c.ativou("a", 10.0, fisica=False, t_abre=10.0)
    c.amostra_rede(1.0, 1.0)
    c.fecha_janela(60.0, ativos=2, backlog=0)      # o SUMO diz 2; a contabilidade diz 3

    res = c.resultado(F.chave_fake(t0=0.0, t1=60.0), "teste")
    assert res.conservacao == 1
    ok, motivo = res.sane()
    assert not ok and "balanço" in motivo
    assert any("conservação" in s for s in sinais_de_travamento(res))


def test_contabilidade_perdido_nao_conta_como_entrega():
    """O backstop da frota persistente registra o despawn como "viagem
    concluída". Contá-lo como entrega infla a vazão com um carro que evaporou."""
    c = Contabilidade()
    c.abre_janela(0.0, ativos=2, abertos={"a": 0.0, "b": 0.0})
    c.perdeu("b", 5.0)                       # despawn
    c.ativou("b", 12.0, fisica=True, t_abre=5.0)   # backstop re-injetou e entrou
    c.amostra_rede(0.0, 0.0)
    c.fecha_janela(60.0, ativos=2, backlog=0)
    res = c.resultado(F.chave_fake(t0=0.0, t1=60.0), "teste")
    assert res.entregues == 0 and res.perdidos == 1
    assert res.conservacao == 0               # 2 + 1 - 0 - 2 - 1


def test_tempo_no_sistema_censura_quem_ficou_preso():
    """A métrica que NÃO sofre viés de sobrevivência: quem ficou preso entra com
    a idade que tem em t1."""
    c = Contabilidade()
    c.abre_janela(0.0, ativos=2, abertos={"rapido": 0.0, "preso": 0.0})
    c.chegou("rapido", 20.0, t_abre=0.0)
    c.ativou("rapido", 20.0, fisica=False, t_abre=20.0)
    c.amostra_rede(1.0, 1.0)
    c.fecha_janela(100.0, ativos=2, backlog=0)
    res = c.resultado(F.chave_fake(t0=0.0, t1=100.0), "teste")
    assert res.tempo_medio_entregue == pytest.approx(20.0)
    # população: a viagem entregue (20 s) + as duas abertas (100 s e 80 s)
    assert res.tempo_medio_no_sistema == pytest.approx((20.0 + 100.0 + 80.0) / 3)


def test_amostras_de_rede_viram_media_por_sim_step():
    c = Contabilidade()
    c.abre_janela(0.0, ativos=1, abertos={"a": 0.0})
    for q in (10.0, 20.0, 30.0):
        c.amostra_rede(q, q * 2)
    c.chegou("a", 1.0, t_abre=0.0)
    c.fecha_janela(3.0, ativos=0, backlog=0)
    assert c.fila_media == pytest.approx(20.0)
    assert c.espera_media == pytest.approx(40.0)
    assert c.n_amostras == 3


# ================================================== detector de artefato
def test_politica_sa_nao_e_acusada():
    """v1 e v2 nas 12 seeds held-out. A lacuna de sobrevivência é pequena porque
    quase todo mundo que estava na rede concluiu viagem em tempo comparável."""
    for entregues, tt in ((1822, 58.2), (1904, 56.2)):
        r = _res(entregues=entregues, tempo_medio_entregue=tt,
                 tempo_medio_no_sistema=tt * 1.05)
        assert lacuna_sobrevivencia(r) < 10.0
        assert sinais_de_travamento(r) == []
        assert r.sane()[0]


def test_travamento_e_denunciado_pela_lacuna_de_sobrevivencia():
    """A assinatura do artefato (RESULTADOS_ATS §5): a seed 111 da variante C,
    throughput 121 e espera de 19.023 s. O tempo dos ENTREGUES fica ótimo; o
    tempo NO SISTEMA denuncia a população presa.

    O `coherence_gap` precisava de `N × T / tt` para ver isto; a lacuna não usa
    nem `N` nem `T`."""
    travado = _res(entregues=121, tempo_medio_entregue=49.0,
                   tempo_medio_no_sistema=1900.0, inseridos=121)
    assert lacuna_sobrevivencia(travado) > 100.0
    sinais = sinais_de_travamento(travado)
    assert any("lacuna" in s for s in sinais), sinais


def test_tempo_melhor_com_populacao_presa_aumenta_a_lacuna():
    """O par desconfortável: a política "mais rápida" é a que tem mais gente
    presa fora da conta."""
    sao = _res(entregues=1850, tempo_medio_entregue=58.0, tempo_medio_no_sistema=61.0)
    suspeito = _res(entregues=1700, tempo_medio_entregue=50.0, tempo_medio_no_sistema=95.0)
    assert lacuna_sobrevivencia(suspeito) > lacuna_sobrevivencia(sao)
    assert suspeito.tempo_medio_entregue < sao.tempo_medio_entregue   # parece melhor
    assert suspeito.tempo_medio_no_sistema > sao.tempo_medio_no_sistema  # e não é


def test_borda_estrangulada_e_denunciada_pelo_backlog():
    """O artefato na versão REDE ABERTA: o controlador "vence" não deixando o
    carro entrar. Fila ótima, tempo dos sobreviventes ótimo, e 40% da demanda
    parada na borda — que é onde o `coherence_gap` era cego mesmo na fechada."""
    r = _res(entregues=400, inseridos=400, backlog_insercao=300,
             ativos_inicio=0, ativos_fim=0,
             tempo_medio_entregue=30.0, tempo_medio_no_sistema=30.0, fila_media=1.0)
    ok, motivo = r.sane()
    assert not ok and "backlog" in motivo
    assert any("backlog" in s for s in sinais_de_travamento(r))


def test_degenerados_nao_explodem():
    vazio = _res(entregues=0, inseridos=0, ativos_inicio=0, ativos_fim=0,
                 tempo_medio_entregue=0.0, tempo_medio_no_sistema=0.0)
    assert math.isnan(lacuna_sobrevivencia(vazio))
    tudo_preso = _res(entregues=0, inseridos=0, ativos_inicio=30, ativos_fim=30,
                      tempo_medio_entregue=0.0, tempo_medio_no_sistema=3600.0)
    assert math.isinf(lacuna_sobrevivencia(tudo_preso))
    assert sinais_de_travamento(tudo_preso)
    assert isinstance(diagnostico(tudo_preso), str)


def test_diagnostico_lista_os_tres_sinais():
    txt = diagnostico(_res())
    for pedaco in ("entregues", "conservação", "lacuna de sobrevivência"):
        assert pedaco in txt


# ================================================== comparação e estatística
def test_comparar_entre_janelas_diferentes_levanta():
    """DoD (d) do agente A2 — na rede fechada e na aberta o bug é o mesmo:
    comparar dois braços que não estão na mesma condição."""
    a = _res()
    b = a.com(chave=F.chave_fake(t0=0.0, t1=1800.0))
    with pytest.raises(ChavesIncompativeis):
        comparar(a, b)


def test_comparar_entre_seeds_diferentes_levanta():
    a = _res()
    b = a.com(chave=F.chave_fake(seed=43, t0=0.0, t1=JANELA_S))
    with pytest.raises(ChavesIncompativeis):
        comparar(a, b)


def test_comparar_com_demanda_diferente_levanta():
    a = _res()
    b = a.com(chave=F.chave_fake(t0=0.0, t1=JANELA_S, sha="f" * 64))
    with pytest.raises(ChavesIncompativeis):
        comparar(a, b)


def test_pareia_por_chave_recusa_lista_orfa():
    base = [_res().com(chave=F.chave_fake(seed=s, t1=JANELA_S)) for s in (42, 43)]
    novo = [_res().com(chave=F.chave_fake(seed=s, t1=JANELA_S)) for s in (42, 44)]
    with pytest.raises(ChavesIncompativeis):
        pareia_por_chave(base, novo)


def test_pareia_por_chave_ignora_a_ordem():
    """Parear por posição produziria um t-test perfeito sobre pares errados."""
    chaves = [F.chave_fake(seed=s, t1=JANELA_S) for s in (42, 43, 44)]
    base = [_res(entregues=1500 + i).com(chave=k, controlador="timer")
            for i, k in enumerate(chaves)]
    novo = [_res(entregues=1900 + i).com(chave=k, controlador="rl")
            for i, k in enumerate(reversed(chaves))]
    pares = pareia_por_chave(base, novo)
    assert [b.chave.seed for b, _ in pares] == [n.chave.seed for _, n in pares]


def test_teste_pareado_reproduz_a_direcao_das_metricas():
    """`entregues` maior é melhor; `fila_media` menor é melhor. Ter a direção
    num lugar só é o que impedia o slide "+20,8% de fila"."""
    chaves = [F.chave_fake(seed=s, t1=JANELA_S) for s in range(42, 54)]
    # variação por seed de propósito: sem ela o t-test roda sobre uma constante
    base = [_res(entregues=1594 + 7 * i, fila_media=12.16 + 0.11 * i)
            .com(chave=k, controlador="timer") for i, k in enumerate(chaves)]
    novo = [_res(entregues=1904 + 5 * i, fila_media=7.99 + 0.07 * i)
            .com(chave=k, controlador="rl") for i, k in enumerate(chaves)]
    pares = pareia_por_chave(base, novo)
    t_ent = estatistica.teste_pareado(pares, "entregues")
    t_fila = estatistica.teste_pareado(pares, "fila_media")
    assert t_ent.delta_pct > 0 and t_ent.vitorias == 12
    assert t_fila.delta_pct > 0 and t_fila.vitorias == 12
    assert t_ent.n_seeds == 12


def test_resumo_pareado_reporta_travamento_por_seed_e_nao_na_media():
    """Regra 2 do RESULTADOS_ATS §5.2: travamento vai reportado seed a seed,
    separado das médias."""
    chaves = [F.chave_fake(seed=s, t1=JANELA_S) for s in range(42, 46)]
    base = [_res().com(chave=k, controlador="timer") for k in chaves]
    novo = [_res().com(chave=k, controlador="rl") for k in chaves]
    novo[2] = novo[2].com(travou=True)
    r = resumo_pareado(base, novo)
    assert r["saude_novo"]["travamentos"] == 1
    assert r["saude_novo"]["nao_sa"][0][0] == 44
    assert r["saude_base"]["travamentos"] == 0


# ---------------------------------------------------------- acúmulo excedente
# Os sinais acima são CEGOS em janela de 120 s. Medido pelo agente A8 em 4752
# rodadas: zero disparos, nem para o farol congelado que entrega 36 carros contra
# os 112 do timer. Estes testes guardam o portão que funciona lá.


def _rodada(controlador: str, ini: int, fim: int, *, entregues: int = 112,
            seed: int = 100) -> Resultado:
    """Uma rodada de 120 s com a população indo de `ini` a `fim`.

    `inseridos` sai da identidade de conservação do C5 — quem cresce na janela é
    porque entrou mais do que saiu. Sem isso o fake dispararia o sinal de
    conservação e mascararia o que estes testes medem.
    """
    return F.resultado_fake(F.chave_fake(seed=seed, t0=300.0, t1=420.0),
                            controlador=controlador, entregues=entregues,
                            inseridos=entregues + fim - ini,
                            ativos_inicio=ini, ativos_fim=fim)


def test_acumulo_excedente_e_pareado_e_nao_absoluto():
    """Crescimento ABSOLUTO não serve de limiar, e o motivo foi medido: nas seeds
    103 e 107 a demanda sobe dentro da janela e TODOS os braços acumulam — o
    `coordenado_c60` chega a +37,5% na seed 107 sem nada de errado."""
    from feira.metricas import acumulo_excedente, crescimento_relativo

    timer = _rodada("timer:uniforme_27s", 150, 206)          # +37,3%: a demanda subiu
    humano = _rodada("humano", 150, 210)                     # +40,0%
    assert crescimento_relativo(timer) == pytest.approx(0.3733, abs=1e-3)
    # os dois cresceram MUITO, e mesmo assim o excedente é pequeno
    assert acumulo_excedente(humano, timer) == pytest.approx(2.67, abs=0.1)
    assert sinais_de_travamento(humano, referencia=timer) == []


def test_rodada_curta_travada_so_e_pega_com_referencia():
    """O achado do A8, em miniatura: sem `referencia` o portão fica DESLIGADO."""
    timer = _rodada("timer:uniforme_27s", 150, 160)          # +6,7%
    congelado = _rodada("humano", 150, 210, entregues=36)    # +40,0% -> excedente 33,3 pp

    # os sinais de janela longa não veem nada de errado — é exatamente o buraco
    assert sinais_de_travamento(congelado) == []
    assert congelado.sane()[0] is True

    fora = sinais_de_travamento(congelado, referencia=timer)
    assert len(fora) == 1 and "acúmulo excedente" in fora[0]
    assert "+33.3 pp" in fora[0]


def test_o_limiar_cai_no_vazio_entre_os_dois_grupos():
    """+18,1 pp foi o pior adversário SÃO; +26 pp o melhor da família congelada."""
    from feira.metricas import LIMIAR_ACUMULO_PP

    timer = _rodada("timer:uniforme_27s", 100, 100)
    sao = _rodada("humano", 100, 118)                        # +18 pp: o pior são
    congelado = _rodada("humano", 100, 126)                  # +26 pp: o melhor ruim
    assert 18.1 < LIMIAR_ACUMULO_PP < 26.0
    assert sinais_de_travamento(sao, referencia=timer) == []
    assert sinais_de_travamento(congelado, referencia=timer) != []


def test_referencia_de_outra_condicao_levanta():
    """Pareado quer dizer MESMA seed e MESMA janela — senão não cancela nada."""
    timer = _rodada("timer:uniforme_27s", 150, 160)
    outra = _rodada("humano", 150, 210, seed=101)
    with pytest.raises(ChavesIncompativeis):
        sinais_de_travamento(outra, referencia=timer)
