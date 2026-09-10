"""A bancada do A8 contra o SUMO de verdade — rede aberta, janela da rodada.

Cada teste marcado `@sumo` roda 300 s de aquecimento + 120 s de janela (~2,6 s de
parede por corrida). O que eles guardam:

* o **mapa fase→aproximação** descreve ESTA rede (e não a que estiver congelada
  no processo — foi o primeiro defeito encontrado nesta trilha);
* toda rodada insere veículo (`res.inseridos > 0`), que é a classe de falha que
  já custou uma trilha inteira a este projeto;
* a rodada do adversário é **reproduzível**: (spec, seed, repetição) determina o
  `Resultado` inteiro;
* o **atalho C3 mede o mesmo que o caminho fiel** para o martelo — medido, não
  suposto (é a armadilha nº1 do A8, e a medida é o que autoriza citá-la);
* `sane()` e `sinais_de_travamento` **não enxergam o farol congelado numa janela
  de 120 s** — o detector padrão é cego neste regime, e o veredito tem de sair
  do balanço de população.
"""
from __future__ import annotations

import os

import pytest

from feira._fakes import ControladorFake
from feira.contratos import cenario
from feira.metricas import sinais_de_travamento

ABERTA = cenario("aberta.maquete")
SEED = 100
TEM = (bool(os.environ.get("SUMO_HOME")) and ABERTA.disponivel()
       and ABERTA.rou_file(SEED).exists())
sumo = pytest.mark.skipif(not TEM, reason="requer SUMO_HOME + rede aberta + demanda")

CAMPOS = ("entregues", "tempo_medio_entregue", "tempo_medio_no_sistema", "fila_media",
          "espera_media", "inseridos", "ativos_fim", "ativos_inicio",
          "backlog_insercao", "perdidos")


@pytest.fixture(scope="module")
def bancada():
    from feira.adversarios import bancada as b

    cen = cenario("aberta.maquete")
    cen.aplicar(forcar=True)
    arena = b.arena_do_processo()
    return b, cen, arena, b.mapa_de_fases(cen, arena=arena)


@sumo
def test_o_mapa_de_fases_descreve_a_rede_aberta(bancada):
    _, _, _, mapa = bancada
    assert len(mapa.tls_ids) == 12
    assert mapa.serve.shape == (12, 2, 4)
    # nenhum grupo de verde sem aproximação servida: grupo vazio é mapa quebrado
    assert mapa.serve.any(axis=2).all()
    # a arterial da maquete é o eixo E/W (as vias `H*`); H2 é a linha completa
    i = mapa.tls_ids.index("H2V2")
    g = int(mapa.grupo_arterial[i])
    assert mapa.serve[i, g, 2] and mapa.serve[i, g, 3]      # E e W no mesmo grupo


@sumo
def test_uma_rodada_insere_veiculos_e_fecha_o_balanco(bancada):
    b, _, arena, mapa = bancada
    linha = b.roda_adversario("martelo", SEED, arena=arena, mapa=mapa)
    assert linha["inseridos"] > 0                    # "não reclamou" não é prova
    assert linha["conservacao"] == 0
    assert linha["sane"], linha["sane_motivo"]
    assert linha["decisoes"] == 24                  # 120 s / grade de 5 s
    assert linha["aceitos"] > 0 and linha["pressoes"] == 12 * 24


@sumo
def test_a_rodada_do_adversario_e_reproduzivel(bancada):
    b, _, arena, mapa = bancada
    um = b.roda_adversario("aleatoria:p=0.35", SEED, rep=3, arena=arena, mapa=mapa)
    dois = b.roda_adversario("aleatoria:p=0.35", SEED, rep=3, arena=arena, mapa=mapa)
    assert [um[c] for c in CAMPOS] == [dois[c] for c in CAMPOS]


@sumo
def test_repeticoes_diferentes_sao_rodadas_diferentes(bancada):
    b, _, arena, mapa = bancada
    um = b.roda_adversario("martelo@falha=0.05@extra=0.02", SEED, rep=0,
                           arena=arena, mapa=mapa)
    dois = b.roda_adversario("martelo@falha=0.05@extra=0.02", SEED, rep=1,
                             arena=arena, mapa=mapa)
    assert um["pressoes"] != dois["pressoes"]


@sumo
def test_o_atalho_c3_mede_o_mesmo_que_o_caminho_fiel_no_martelo(bancada):
    """A armadilha nº1, MEDIDA — e o limite dela.

    Martelar todos os botões pela camada de entrada dá o mesmo `Resultado` que um
    controlador C3 emitindo `TROCAR` em tudo, porque a Arena aplica a MESMA
    máscara (`controlável ∧ ¬amarelo ∧ verde_desde ≥ min_green`) que o
    `ControladorHumano` usa para decidir entre `on` e `deny`. A equivalência vale
    para o martelo por ele apertar TUDO em TODO tick; para qualquer adversário
    com intenção seletiva ela não vale, porque a fila de intenções e o descarte
    do bit recusado mudam o que chega ao tick seguinte.
    """
    from feira.jogo.estado import cenario_da_seed
    from feira.treino.avalia import roda_um

    b, cen, arena, mapa = bancada
    fiel = b.roda_adversario("martelo", SEED, arena=arena, mapa=mapa)
    janela = b.janela_da_rodada(duracao_s=120.0)
    atalho = roda_um(cenario_da_seed(cen, SEED), SEED, ControladorFake("sempre"),
                     janela, arena=arena)
    assert [fiel[c] for c in CAMPOS] == [getattr(atalho, c) for c in CAMPOS]


@sumo
def test_o_detector_padrao_nao_ve_o_farol_congelado_em_120_s(bancada):
    """Achado do A8, guardado por teste: em 120 s o detector de travamento é cego.

    `parado` (ninguém aperta nada) entrega uma fração do que o timer entrega e
    deixa a população crescer, mas passa em `sane()` E sai sem sinal nenhum: a
    lacuna de sobrevivência é NEGATIVA porque metade da população está censurada
    por construção nesta janela, e `Resultado.travou` nem pode disparar (o
    critério da Arena é 600 s sem chegada, mais que a rodada inteira).
    O veredito de saúde da rodada de feira tem de sair do balanço de população.
    """
    b, _, arena, mapa = bancada
    parado = b.roda_adversario("parado", SEED, arena=arena, mapa=mapa)
    timer = b.roda_oponente("timer27", SEED, arena=arena)

    assert parado["entregues"] < 0.5 * timer["entregues"]
    assert parado["sane"] and not parado["sinais"]          # o detector não vê
    assert not parado["travou"]
    cresce = parado["ativos_fim"] - parado["ativos_inicio"]
    assert cresce > 3 * (timer["ativos_fim"] - timer["ativos_inicio"])
    # e a lacuna, que é o detector do regime longo, aponta para o lado errado
    assert parado["lacuna"] < 0
    assert sinais_de_travamento(_res(parado)) == []


def _res(linha: dict):
    from feira.contratos import Chave, Janela, Resultado

    return Resultado(chave=Chave.de(ABERTA, linha["seed"],
                                    Janela(linha["t0"], linha["t1"]), "x" * 64),
                     controlador=linha["controlador"], entregues=linha["entregues"],
                     tempo_medio_entregue=linha["tempo_medio_entregue"],
                     tempo_medio_no_sistema=linha["tempo_medio_no_sistema"],
                     fila_media=linha["fila_media"], espera_media=linha["espera_media"],
                     inseridos=linha["inseridos"], ativos_fim=linha["ativos_fim"],
                     ativos_inicio=linha["ativos_inicio"],
                     backlog_insercao=linha["backlog_insercao"],
                     perdidos=linha["perdidos"], travou=linha["travou"])
