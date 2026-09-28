"""A9 — o servidor da projeção na gamificação: o apelido, a fonte web, o ranking no
fio, os ganchos do operador e o nível da próxima seed (docs/GAMIFICACAO.md §6).

A primeira metade não sobe servidor (`EstadoProjecao` puro); a segunda sobe o
uvicorn de verdade, como `test_a7_transporte`, numa porta própria.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from feira.entrada import FonteWeb
from feira.jogo.ranking import Ranking
from feira.jogo.web import EstadoProjecao


def _placar(*, fase="resultado", humano=118, rl=120, timer=111, vencedor="rl",
            rodada=1, sinais=(), com_humano=True, seed=100) -> dict:
    linhas = [{"braco": "timer", "entregues": timer}, {"braco": "rl", "entregues": rl}]
    if com_humano:
        linhas.append({"braco": "humano", "entregues": humano})
    return {"tipo": "placar", "type": "placar", "fase": fase, "t": 420.0, "t_restante": 0.0,
            "chave": {"cenario": "x", "seed": seed, "janela": [300.0, 420.0], "demanda": "ab"},
            "linhas": linhas, "vencedor": vencedor, "motivo": "", "pareado": True,
            "rodada": rodada, "sinais": list(sinais)}


# ------------------------------------------------------- estado, sem servidor
def test_o_apelido_e_carimbado_na_marca_e_consumido():
    est = EstadoProjecao(ranking=Ranking())
    est.define_jogador("Ana")
    assert est.jogador == "Ana" and est.msg_jogador()["anonimo"] == "Visitante 1"
    est.absorve(_placar(rodada=1))
    assert est.ultima_marca is not None and est.ultima_marca.nome == "Ana"
    assert est.jogador is None                      # a próxima rodada não herda
    est.absorve(_placar(rodada=2, humano=119))
    assert est.ultima_marca.nome == "" and est.msg_jogador()["anonimo"] == "Visitante 3"


def test_rodada_nao_concluida_nao_consome_o_apelido():
    """SUMO caiu: sem linha do humano. A rodada grátis vai com o MESMO nome."""
    est = EstadoProjecao(ranking=Ranking())
    est.define_jogador("Ana")
    est.absorve(_placar(rodada=1, com_humano=False, vencedor=None))
    assert est.jogador == "Ana" and est.ultima_marca is None


def test_rodada_travada_consome_o_apelido_mas_nao_vira_marca():
    est = EstadoProjecao(ranking=Ranking())
    est.define_jogador("Ana")
    est.absorve(_placar(rodada=1, humano=36, vencedor=None, sinais=["acúmulo +51 pp"]))
    assert est.jogador is None and est.ultima_marca is None


def test_teste_do_operador_marca_a_proxima_e_se_apaga():
    est = EstadoProjecao(ranking=Ranking())
    est.teste_proxima = True
    est.absorve(_placar(rodada=1))
    assert est.ultima_marca.teste and est.teste_proxima is False
    assert est.ranking.topo(5) == []


def test_o_ranking_e_difundido_com_a_ultima_marca_e_a_posicao():
    import asyncio

    est = EstadoProjecao(ranking=Ranking())
    est._bcast = asyncio.Queue()
    est.define_jogador("Ana")
    est.absorve(_placar(rodada=1))
    tipos = []
    while not est._bcast.empty():
        tipos.append(est._bcast.get_nowait())
    rk = next(m for m in tipos if m.get("tipo") == "ranking")
    assert rk["ultima"]["rotulo"] == "Ana" and rk["ultima"]["posicao"] == 1
    assert rk["ultima"]["recorde"] is True and rk["ultima"]["medalha"] == "prata"
    assert [m.get("tipo") for m in tipos].count("jogador") == 2   # define + limpa


def test_status_carrega_entrada_web_jogador_e_proxima():
    est = EstadoProjecao(ranking=Ranking(), proxima_seed=lambda: 107)
    st = est.status()
    assert st["ritmo"] == 1.0 and EstadoProjecao(ritmo=1.5).status()["ritmo"] == 1.5
    assert st["entrada_web"] is False and st["jogador"] is None
    assert st["proxima"]["seed"] == 107 and st["proxima"]["nivel"] == "facil"
    assert st["proxima"]["hoje"] == {"jogaram": 0, "bateram": 0}
    est.fonte_web = FonteWeb(12)
    est.define_jogador("Bia")
    st = est.status()
    assert st["entrada_web"] is True and st["jogador"] == "Bia"
    # e o cliente novo recebe o quadro de LEDs e o jogador
    tipos = [m.get("tipo") for m in est.inicial()]
    assert "leds" in tipos and "jogador" in tipos


def test_a_grade_viaja_no_status_para_a_pagina_explicar_a_espera(tmp_path):
    from feira import _fakes as F

    cen = F.cenario_fake_arquivo(tmp_path)
    est = EstadoProjecao(cenario=cen)
    g = est.status()["grade"]
    r = cen.restricoes
    assert g == {"di": float(r.decision_interval), "min_green": float(r.min_green),
                 "yellow": float(r.yellow)}
    assert EstadoProjecao().status()["grade"] is None


def test_sem_motor_nao_ha_proxima_e_nada_quebra():
    est = EstadoProjecao()
    assert est.status()["proxima"] is None
    est.absorve(_placar())                     # sem ranking: só difunde
    assert est.ultima_marca is None


def test_a_mensagem_da_pagina_vai_para_a_fonte_web():
    fw = FonteWeb(12)
    est = EstadoProjecao(fonte_web=fw)
    est.entrada({"tipo": "tecla", "k": "q"})
    est.entrada({"tipo": "start"})
    assert [e.indice for e in fw.poll()] == [0, -1]
    EstadoProjecao().entrada({"tipo": "start"})     # sem fonte: ignorado


def test_leds_da_fonte_web_passam_pelo_caminho_normal_de_difusao():
    est = EstadoProjecao()
    fw = FonteWeb(12, ao_feedback=est.entrega)
    est.fonte_web = fw
    fw.feedback(["armed"] + ["off"] * 11, start="on")
    msg = est.fila.get_nowait()
    assert msg["tipo"] == "leds" and msg["estados"][0] == "armed" and msg["start"] == "on"


# --------------------------------------------------------- servidor de fato
@pytest.fixture()
def servidor():
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    from feira.jogo.web import ServidorProjecao

    chamadas = {"abortar": 0, "pular": 0}
    est = EstadoProjecao(ranking=Ranking(), proxima_seed=lambda: 104,
                         ao_abortar=lambda: chamadas.__setitem__("abortar", chamadas["abortar"] + 1),
                         ao_pular=lambda: chamadas.__setitem__("pular", chamadas["pular"] + 1))
    fw = FonteWeb(12, ao_feedback=est.entrega)
    est.fonte_web = fw
    srv = ServidorProjecao(est, porta=8478)
    assert srv.sobe(), "o servidor da projeção não subiu"
    try:
        yield est, srv, fw, chamadas
    finally:
        srv.desce()


def _http(metodo: str, url: str, corpo: dict | None = None) -> dict:
    import urllib.request

    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def test_o_apelido_entra_por_http_e_o_nivel_sai_por_http(servidor):
    est, srv, fw, _ = servidor
    base = srv.url.rstrip("/")
    d = _http("POST", base + "/api/jogador", {"nome": " Ana!! "})
    assert d["nome"] == "Ana" and est.jogador == "Ana"
    assert _http("GET", base + "/api/jogador")["nome"] == "Ana"
    px = _http("GET", base + "/api/proxima")
    assert px["seed"] == 104 and px["nivel"] == "dificil" and px["rotulo"] == "DIFÍCIL"
    st = _http("GET", base + "/api/estado")
    assert st["entrada_web"] is True and st["jogador"] == "Ana"


def test_os_ganchos_do_operador_respondem(servidor):
    est, srv, fw, chamadas = servidor
    base = srv.url.rstrip("/")
    assert _http("POST", base + "/api/abortar")["ok"] is True
    assert _http("POST", base + "/api/pular")["ok"] is True
    assert chamadas == {"abortar": 1, "pular": 1}
    assert _http("POST", base + "/api/teste", {"teste": True})["teste"] is True
    assert est.teste_proxima is True


def test_moderacao_do_ranking_por_http(servidor):
    est, srv, fw, _ = servidor
    base = srv.url.rstrip("/")
    est.define_jogador("Ana")
    est.absorve(_placar(rodada=1))
    est.absorve(_placar(rodada=2, humano=125))
    rk = _http("GET", base + "/api/ranking?n=5")
    assert [m["rotulo"] for m in rk["topo"]] == ["Visitante 2", "Ana"]
    assert rk["ultima"]["rotulo"] == "Visitante 2"
    ana = next(m for m in rk["topo"] if m["rotulo"] == "Ana")
    d = _http("PATCH", base + "/api/ranking/%s" % ana["id"], {"nome": "Ana Clara"})
    assert d["ok"] and d["marca"]["nome"] == "Ana Clara"
    assert _http("DELETE", base + "/api/ranking/%s" % ana["id"])["ok"]
    rk = _http("GET", base + "/api/ranking?n=5")
    assert [m["rotulo"] for m in rk["topo"]] == ["Visitante 2"]
    assert _http("DELETE", base + "/api/ranking/m999")["ok"] is False


def test_o_websocket_de_entrada_alimenta_a_fonte_e_os_leds_voltam_pelo_ws(servidor):
    est, srv, fw, _ = servidor
    connect = pytest.importorskip("websockets.sync.client").connect
    recebidas = []
    pronto, parar = threading.Event(), threading.Event()

    def cliente():
        with connect("ws://127.0.0.1:%d/ws" % srv.porta, open_timeout=10) as ws:
            pronto.set()
            while not parar.is_set():
                try:
                    recebidas.append(json.loads(ws.recv(timeout=1.0)))
                except TimeoutError:
                    continue

    t = threading.Thread(target=cliente, daemon=True)
    t.start()
    assert pronto.wait(timeout=10)
    time.sleep(0.3)
    t0 = time.perf_counter()
    with connect("ws://127.0.0.1:%d/entrada" % srv.porta, open_timeout=10) as ws:
        ws.send(json.dumps({"tipo": "tecla", "k": "q"}))
        ws.send(json.dumps({"tipo": "start"}))
        ws.send(json.dumps({"tipo": "ping"}))
        fim = time.perf_counter() + 3.0
        while fw.n_mensagens < 3 and time.perf_counter() < fim:
            time.sleep(0.01)
    latencia_ms = (time.perf_counter() - t0) * 1000.0
    assert [e.indice for e in fw.poll()] == [0, -1]
    assert latencia_ms < 1000.0, "três mensagens locais não podem levar um segundo"
    fw.feedback(["on"] + ["off"] * 11, start="armed")
    time.sleep(0.5)
    parar.set()
    t.join(timeout=3)
    tipos = [m.get("tipo") for m in recebidas]
    assert "leds" in tipos and "jogador" in tipos            # o inicial + o feedback
    led = [m for m in recebidas if m.get("tipo") == "leds"][-1]
    assert led["estados"][0] == "on" and led["start"] == "armed"
