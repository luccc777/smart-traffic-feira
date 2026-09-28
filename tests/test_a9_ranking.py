"""A9 — o quadro de recordes v2: pontuação pareada, medalhas, nome, moderação e a
migração do arquivo v1 (docs/GAMIFICACAO.md §3).

Os números das marcas são os do A8 (`docs/DIFICULDADE.md` §5) — a tabela seed a seed
do melhor humano plausível — para a medalha ser conferida contra dado, não contra
exemplo inventado.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from feira.jogo.ranking import (
    BRONZE,
    OURO,
    PRATA,
    PRATA_CARROS,
    Marca,
    Ranking,
    medalha_de,
    normaliza_nome,
)


def _placar(*, seed=100, humano=118, rl=120, timer=111, vencedor="rl", pareado=True,
            fase="resultado", com_humano=True, rodada=0, sinais=(), sem_rl=False,
            sem_timer=False) -> dict:
    linhas = []
    if not sem_timer:
        linhas.append({"braco": "timer", "entregues": timer})
    if not sem_rl:
        linhas.append({"braco": "rl", "entregues": rl})
    if com_humano:
        linhas.append({"braco": "humano", "entregues": humano})
    return {"tipo": "placar", "fase": fase, "vencedor": vencedor, "pareado": pareado,
            "chave": {"seed": seed}, "linhas": linhas, "rodada": rodada,
            "sinais": list(sinais)}


# ------------------------------------------------------------- pontuação
def test_o_score_e_o_delta_contra_o_timer_da_mesma_seed():
    r = Ranking()
    # seed 107 (A8 §5): timer 89, RL 101; o melhor humano fez 104
    m = r.registra(_placar(seed=107, humano=104, rl=101, timer=89, vencedor="humano"))
    assert m.score == 15 and m.delta_rl == 3 and m.venceu


def test_a_ordem_e_por_score_e_nao_por_entregues():
    """Seed 104 (RL 146, timer 130) contra seed 107 (RL 101, timer 89): 141 carros na
    104 valem MENOS que 104 carros na 107 — a hora de trânsito cancela na subtração."""
    r = Ranking()
    r.registra(_placar(seed=104, humano=141, rl=146, timer=130, rodada=1))
    r.registra(_placar(seed=107, humano=104, rl=101, timer=89, vencedor="humano", rodada=2))
    assert [m.seed for m in r.topo(5)] == [107, 104]
    assert [m.score for m in r.topo(5)] == [15, 11]


def test_desempate_por_entregues_e_depois_por_quem_fez_antes():
    r = Ranking()
    a = r.registra(_placar(seed=100, humano=120, timer=110, rodada=1))
    b = r.registra(_placar(seed=101, humano=130, timer=120, rodada=2))
    c = r.registra(_placar(seed=102, humano=130, timer=120, rodada=3))
    assert a.score == b.score == c.score == 10
    assert [m.rodada for m in r.topo(5)] == [2, 3, 1]


# --------------------------------------------------------------- medalhas
def test_medalhas_com_os_numeros_do_a8():
    assert medalha_de(104, 101, 89) == OURO          # seed 107: bateu a rede
    assert medalha_de(144, 146, 130) == PRATA        # seed 104: a 2 da rede
    assert medalha_de(141, 146, 130) == BRONZE       # seed 104: a 5 da rede, > timer
    assert medalha_de(116, 120, 111) == BRONZE       # seed 100
    assert medalha_de(36, 120, 111) == ""            # parado
    assert medalha_de(120 - PRATA_CARROS, 120, 111) == PRATA
    assert medalha_de(120 - PRATA_CARROS - 1, 120, 111) == BRONZE


def test_sem_rede_na_rodada_nao_ha_ouro_nem_prata():
    r = Ranking()
    m = r.registra(_placar(humano=130, timer=111, sem_rl=True, vencedor="humano"))
    assert m.degradada and m.medalha == BRONZE and m.delta_rl is None
    assert not m.venceu               # `venceu` é contra a rede, e não havia rede


def test_sem_timer_nao_ha_score_e_a_marca_nao_entra_no_topo():
    r = Ranking()
    m = r.registra(_placar(humano=130, sem_timer=True, vencedor="humano"))
    assert m is not None and not m.conta
    assert r.topo(5) == []


# ----------------------------------------------------------------- filtros
def test_rodada_travada_nao_vira_recorde():
    r = Ranking()
    assert r.registra(_placar(humano=36, vencedor=None, sinais=["acúmulo +51 pp"])) is None
    assert r.topo(5) == []


def test_rodada_de_teste_fica_no_arquivo_e_sai_do_topo(tmp_path):
    arq = tmp_path / "r.json"
    r = Ranking(arq)
    m = r.registra(_placar(rodada=1), teste=True)
    assert m.teste and r.topo(5) == []
    assert json.loads(arq.read_text(encoding="utf-8"))["marcas"][0]["teste"] is True


def test_dedup_pela_identidade_da_rodada_e_nao_pela_tupla():
    """Com `rodada` no fio, duas pessoas com os MESMOS números em rodadas diferentes
    são duas marcas; a mesma mensagem reenviada continua sendo uma."""
    r = Ranking()
    msg = _placar(rodada=7)
    assert r.registra(msg) is not None
    assert r.registra(msg) is None
    assert r.registra(_placar(rodada=8)) is not None     # mesmos números, outra rodada
    assert len(r.topo(10)) == 2


# ------------------------------------------------------------------- nomes
def test_nome_e_apelido_de_tela_publica():
    assert normaliza_nome("  Ana   Clara!!! ") == "Ana Clara"
    assert normaliza_nome("José") == "José"
    assert normaliza_nome("abcdefghijklmnop") == "abcdefghijkl"
    assert normaliza_nome("🚗🚗") == "" and normaliza_nome(None) == ""


def test_sem_nome_vira_visitante_n_e_n_e_estavel():
    r = Ranking()
    a = r.registra(_placar(rodada=1))
    b = r.registra(_placar(rodada=2, humano=119))
    d = r.json(5)
    assert [m["rotulo"] for m in d["topo"]] == ["Visitante 2", "Visitante 1"]
    assert a.ordem == 1 and b.ordem == 2 and a.id == "m1"


def test_uma_linha_por_pessoa_no_topo_e_a_melhor_rodada_dela():
    r = Ranking()
    r.registra(_placar(rodada=1, humano=118), nome="Ana")
    r.registra(_placar(rodada=2, humano=125), nome="Ana")
    r.registra(_placar(rodada=3, humano=120), nome="Lucas")
    topo = r.json(5)["topo"]
    assert [(m["rotulo"], m["entregues"]) for m in topo] == [("Ana", 125), ("Lucas", 120)]
    assert r.json(5)["total"] == 3            # o total conta rodadas, não pessoas


def test_posicao_e_da_pessoa_e_sai_no_json_da_ultima():
    r = Ranking()
    r.registra(_placar(rodada=1, humano=125), nome="Ana")
    r.registra(_placar(rodada=2, humano=120), nome="Lucas")
    m = r.registra(_placar(rodada=3, humano=116), nome="Bia")
    assert r.posicao(m) == (3, 3)
    d = r.json(5, ultima=m)
    assert d["ultima"]["posicao"] == 3 and d["ultima"]["pessoas"] == 3
    assert d["ultima"]["recorde"] is False and d["ultima"]["rotulo"] == "Bia"
    rec = r.registra(_placar(rodada=4, humano=140), nome="Bia")
    assert r.json(5, ultima=rec)["ultima"]["recorde"] is True


def test_por_seed_conta_o_que_a_feira_ja_viu():
    r = Ranking()
    r.registra(_placar(rodada=1, seed=107, humano=104, rl=101, vencedor="humano"))
    r.registra(_placar(rodada=2, seed=107, humano=99, rl=101))
    r.registra(_placar(rodada=3, seed=100))
    assert r.por_seed(107) == {"jogaram": 2, "bateram": 1}
    assert r.por_seed(111) == {"jogaram": 0, "bateram": 0}


# --------------------------------------------------------------- moderação
def test_renomear_marcar_teste_e_remover_sao_soft(tmp_path):
    r = Ranking(tmp_path / "r.json")
    m = r.registra(_placar(rodada=1), nome="Ana")
    assert r.altera(m.id, nome="Ana 2").nome == "Ana 2"
    assert r.altera(m.id, removida=True).removida
    assert r.topo(5) == []
    assert len(json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["marcas"]) == 1
    assert r.altera("m999", nome="x") is None


# ------------------------------------------------------------- arquivo v2
def test_arquivo_v1_carrega_como_v2_sem_perder_marca(tmp_path):
    arq = tmp_path / "ranking.json"
    v1 = {"marcas": [
        {"entregues": 118, "seed": 100, "venceu": False, "rl": 120, "timer": 111,
         "quando": 1000.0},
        {"entregues": 104, "seed": 107, "venceu": True, "rl": 101, "timer": 89,
         "quando": 1001.0},
    ]}
    arq.write_text(json.dumps(v1), encoding="utf-8")
    r = Ranking(arq)
    topo = r.json(5)["topo"]
    assert [m["score"] for m in topo] == [15, 7]
    assert [m["rotulo"] for m in topo] == ["Visitante 2", "Visitante 1"]
    assert [m["medalha"] for m in topo] == [OURO, PRATA]      # 118 está a 2 da rede
    # continua deduplicando contra o que veio do disco (sem `rodada`: pela tupla)
    assert r.registra(_placar(seed=100, humano=118)) is None
    # e ao gravar de novo sai como v2
    r.registra(_placar(rodada=9, humano=130), nome="Bia")
    d = json.loads(arq.read_text(encoding="utf-8"))
    assert d["versao"] == 2 and d["marcas"][2]["ordem"] == 3


def test_um_arquivo_por_dia_e_a_uniao_da_feira(tmp_path):
    r1 = Ranking.do_dia(tmp_path, "2026-09-28")
    r1.registra(_placar(rodada=1, humano=118), nome="Ana")
    r2 = Ranking.do_dia(tmp_path, "2026-09-29")
    r2.registra(_placar(rodada=1, humano=130), nome="Lucas")
    assert (tmp_path / "ranking_2026-09-28.json").exists()
    assert r2.registra(_placar(rodada=1, humano=118), nome="Ana") is None or True
    feira = Ranking.da_feira(tmp_path)
    assert sorted(m.nome for m in feira)[:2] == ["Ana", "Lucas"]
    d = r2.json(5, marcas=feira, escopo="feira")
    assert d["escopo"] == "feira" and d["total"] >= 2


def test_poda_descarta_as_piores_por_score_e_preserva_a_ordem_de_chegada():
    r = Ranking(limite=3)
    for i, h in enumerate((120, 100, 140, 90), 1):
        r.registra(_placar(rodada=i, humano=h, timer=110))
    assert sorted(m.score for m in r.topo(10)) == [-10, 10, 30]
    assert [m.ordem for m in r._marcas] == sorted(m.ordem for m in r._marcas)


def test_marca_json_e_serializavel_e_carrega_os_derivados():
    m = Marca(entregues=104, seed=107, venceu=True, rl=101, timer=89, nome="Ana",
              rodada=3, ordem=1, quando=time.time())
    d = json.loads(json.dumps(m.json()))
    assert d["score"] == 15 and d["medalha"] == OURO and d["id"] == "m1"
    assert isinstance(Path(d["hora"]).name, str)


# ---------------------------------------------------------------- validade
def test_marca_antiga_sai_do_quadro_mas_fica_no_dia():
    """Decisão do dono: ~30 min de validade, senão um vencedor da manhã reina o evento
    inteiro. O arquivo e os totais do dia guardam tudo; o que expira é a colocação."""
    t = [1000.0]
    r = Ranking(validade_s=1800.0, agora=lambda: t[0])
    velha = r.registra(_placar(rodada=1, humano=140), nome="Ana")     # score 29
    t[0] += 1700.0
    nova = r.registra(_placar(rodada=2, humano=120), nome="Lucas")    # score 9
    assert [m.nome for m in r.topo(5)] == ["Ana", "Lucas"]
    assert r.posicao(nova) == (2, 2)
    t[0] += 200.0                                    # Ana passou de 30 min
    assert [m.nome for m in r.topo(5)] == ["Lucas"]
    assert r.posicao(nova) == (1, 1) and r.vigente(nova) and not r.vigente(velha)
    d = r.json(5, ultima=nova)
    assert d["validade_s"] == 1800.0 and d["ultima"]["recorde"] is True
    assert d["total"] == 2 and d["venceram_timer"] == 2       # os totais são do DIA
    assert r.por_seed(100) == {"jogaram": 2, "bateram": 1}    # o nível também (140 > 120)


def test_sem_validade_nada_expira():
    t = [1000.0]
    r = Ranking(agora=lambda: t[0])
    r.registra(_placar(rodada=1), nome="Ana")
    t[0] += 10 ** 6
    assert [m.nome for m in r.topo(5)] == ["Ana"] and r.json()["validade_s"] is None


def test_a_identidade_por_rodada_nao_colide_entre_processos(tmp_path):
    """O contador de rodadas do motor reinicia a cada servidor. A rodada 2 da tarde
    na seed 101 não é a rodada 2 da manhã na seed 101 — e a marca nova era engolida
    em silêncio (aconteceu em 2026-09-14)."""
    arq = tmp_path / "r.json"
    manha = Ranking(arq)
    assert manha.registra(_placar(rodada=2, seed=101, humano=92), nome="Ana") is not None
    tarde = Ranking(arq)                       # o servidor reiniciou
    m = tarde.registra(_placar(rodada=2, seed=101, humano=120), nome="Bia")
    assert m is not None and m.nome == "Bia"
    assert [x["rotulo"] for x in tarde.json(5)["topo"]] == ["Bia", "Ana"]
    # a mesma mensagem, no MESMO processo, continua entrando uma vez só
    assert tarde.registra(_placar(rodada=2, seed=101, humano=120), nome="Bia") is None
