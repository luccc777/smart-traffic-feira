"""O quadro de recordes da feira — `feira/jogo/ranking.py`.

Ele se alimenta da MESMA mensagem `placar` do C7 que a tela já recebe, e os filtros
dele são a mesma regra que o resto da tela segue: rodada não pareada não entra, rodada
sem humano não entra. Um recorde produzido numa comparação que não vale é pior que não
ter quadro — vira um número que ninguém consegue bater porque ele nunca aconteceu nas
mesmas condições.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from feira.jogo.ranking import Ranking  # noqa: E402


def _placar(*, seed=100, humano=118, rl=120, timer=111, vencedor="rl",
            pareado=True, fase="resultado", com_humano=True) -> dict:
    linhas = [{"braco": "timer", "entregues": timer},
              {"braco": "rl", "entregues": rl}]
    if com_humano:
        linhas.append({"braco": "humano", "entregues": humano})
    return {"tipo": "placar", "fase": fase, "vencedor": vencedor, "pareado": pareado,
            "chave": {"seed": seed}, "linhas": linhas}


def test_grava_a_rodada_humana_e_guarda_com_quem_ela_competiu():
    r = Ranking()
    m = r.registra(_placar(seed=107, humano=104, rl=101, vencedor="humano"))
    assert m is not None
    assert (m.entregues, m.seed, m.venceu, m.rl) == (104, 107, True, 101)


def test_a_mesma_rodada_duas_vezes_entra_uma_vez():
    """O `ultimo_placar` é reenviado a cada cliente que conecta. Sem dedup, um
    visitante que abrisse a tela num segundo navegador duplicaria o recorde."""
    r = Ranking()
    msg = _placar()
    assert r.registra(msg) is not None
    assert r.registra(msg) is None
    assert len(r.topo(10)) == 1


def test_rodada_nao_pareada_nao_vira_recorde():
    """`pareado: false` = os braços partiram de estados diferentes em t0. A tela tira
    o placar; o quadro tem de tirar o recorde pelo mesmo motivo."""
    r = Ranking()
    assert r.registra(_placar(pareado=False, vencedor=None)) is None
    assert r.topo(10) == []


def test_rodada_sem_humano_nao_vira_recorde():
    """Abortada pelo operador, ou o SUMO caiu. Ninguém jogou: não há marca."""
    r = Ranking()
    assert r.registra(_placar(com_humano=False, vencedor=None)) is None
    assert r.topo(10) == []


def test_so_o_resultado_conta():
    r = Ranking()
    for fase in ("ocioso", "preparando", "contagem", "jogando"):
        assert r.registra(_placar(fase=fase)) is None
    assert r.topo(10) == []


def test_o_topo_e_por_entregues_e_nao_por_ordem_de_chegada():
    r = Ranking()
    for seed, n in ((100, 118), (101, 143), (102, 96), (103, 125)):
        r.registra(_placar(seed=seed, humano=n))
    assert [m.entregues for m in r.topo(3)] == [143, 125, 118]


def test_sobrevive_ao_processo(tmp_path):
    """A feira reinicia o jogo várias vezes por dia e o público espera que o recorde
    da manhã ainda esteja lá à tarde."""
    arq = tmp_path / "ranking.json"
    r1 = Ranking(arq)
    r1.registra(_placar(seed=111, humano=143, rl=131, vencedor="humano"))
    r1.registra(_placar(seed=100, humano=118))
    assert arq.exists()

    r2 = Ranking(arq)
    assert [m.entregues for m in r2.topo(5)] == [143, 118]
    # e continua deduplicando contra o que veio do disco
    assert r2.registra(_placar(seed=100, humano=118)) is None


def test_arquivo_corrompido_comeca_vazio_em_vez_de_derrubar_a_feira(tmp_path):
    arq = tmp_path / "ranking.json"
    arq.write_text("{isto não é json", encoding="utf-8")
    r = Ranking(arq)
    assert r.topo(5) == []
    assert r.registra(_placar()) is not None       # e volta a funcionar


def test_o_json_da_tela_traz_o_resumo_que_o_cabecalho_mostra():
    r = Ranking()
    r.registra(_placar(seed=107, humano=104, rl=101, vencedor="humano"))
    r.registra(_placar(seed=100, humano=118, rl=120, vencedor="rl"))
    d = r.json(5)
    assert d["total"] == 2 and d["vitorias"] == 1
    assert [m["entregues"] for m in d["topo"]] == [118, 104]
    assert all("hora" in m for m in d["topo"]), "a tela mostra a hora da marca"
    json.dumps(d)          # tem de ser serializável: vai por HTTP


def test_mensagem_antiga_sem_pareado_e_tratada_como_pareada():
    """O campo `pareado` é novo no C7. Mensagem gravada antes dele não é 'suspeita':
    é anterior à checagem, e a ausência de prova não é prova de divergência."""
    r = Ranking()
    msg = _placar()
    del msg["pareado"]
    assert r.registra(msg) is not None
