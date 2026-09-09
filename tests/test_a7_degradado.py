"""A7 — DoD (d): se o jogo cair, a projeção volta sozinha para RL x timer em <= 3 s.

A queda que importa é a SILENCIOSA: o motor não avisa que morreu, ele simplesmente
para de chamar o `publicador`. Nada no protocolo diz "acabou" — então quem tem que
perceber é o servidor, pelo relógio.

A RÉDEA É POR FASE, e isso não é firula. `contagem` e `jogando` têm cadência garantida
de 1 Hz (a contagem publica 3-2-1, o laço publica um placar por sim-step) e por isso
aceitam rédea curta. `preparando` fica legitimamente MUDO por até ~9,1 s calculando o
fantasma da RL sem cache, mais o tempo de subir o SUMO e rodar os 300 s de aquecimento
(JOGO.md §2); armar 2 s ali daria "queda" falsa em toda rodada. `ocioso` não publica
nada e nunca arma. Os três casos estão aqui.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from feira.jogo.web import LEASH_S, TICK_VIGIA, EstadoProjecao, PublicadorProjecao

TETO_DOD_S = 3.0


def _placar(fase, t=310.0):
    return {"tipo": "placar", "fase": fase, "t": t, "t_restante": 110.0,
            "chave": {"cenario": "aberta.maquete", "seed": 100,
                      "janela": [300.0, 420.0], "demanda": "abc123"},
            "linhas": [{"braco": "humano", "rotulo": "VOCÊ", "entregues": 5,
                        "fila": 8.0, "tempo_medio": 40.0, "fantasma": False}]}


# ------------------------------------------------------- a rédea, sem relógio real
class _Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.mark.parametrize("fase", ["contagem", "jogando"])
def test_redea_curta_nas_fases_de_cadencia_garantida(fase):
    rel = _Relogio()
    est = EstadoProjecao(relogio=rel)
    est.absorve(_placar(fase))
    assert est.vencida() <= 0
    rel.t += LEASH_S[fase] + 0.01
    assert est.vencida() > 0
    # e a rédea curta é o que faz a DoD fechar
    assert LEASH_S[fase] + TICK_VIGIA <= TETO_DOD_S


def test_preparando_tem_redea_longa_porque_o_silencio_dele_e_legitimo():
    """9,1 s é o custo MEDIDO do fantasma da RL sem cache (JOGO.md §2)."""
    rel = _Relogio()
    est = EstadoProjecao(relogio=rel)
    est.absorve(_placar("preparando"))
    rel.t += 12.0                      # 9,1 s de fantasma + boot do SUMO + aquecimento
    assert est.vencida() <= 0, "queda falsa: a projeção acusaria o motor de morto"
    rel.t += LEASH_S["preparando"]
    assert est.vencida() > 0


def test_ocioso_nunca_arma():
    rel = _Relogio()
    est = EstadoProjecao(relogio=rel)
    est.absorve(_placar("ocioso"))
    rel.t += 3600.0
    assert est.vencida() == 0.0
    assert LEASH_S["ocioso"] is None


def test_a_queda_nao_inventa_placar():
    """O placar degradado vem SEM linha. Desenhar barra com número que ninguém mediu
    é mentir na frente do público — e é justamente o que a projeção antiga fazia."""
    est = EstadoProjecao()
    est.absorve(_placar("jogando"))
    msg = est.cai("teste")
    assert msg["tipo"] == "projecao" and msg["evento"] == "queda"
    assert msg["fase"] == "ocioso" and msg["degradado"] is True
    assert "linhas" not in msg


def test_publicacao_nova_tira_do_degradado():
    est = EstadoProjecao()
    est.absorve(_placar("jogando"))
    est.cai("teste")
    assert est.degradado
    est.absorve(_placar("jogando", t=311.0))
    assert not est.degradado and est.motivo == ""


# --------------------------------------------- a medição de verdade, com servidor
@pytest.mark.parametrize("fase", ["jogando"])
def test_queda_do_jogo_volta_para_ocioso_em_menos_de_3s(fase):
    """O NÚMERO da DoD (d), medido: relógio de parede entre a última publicação do
    motor e o `ocioso` chegando no cliente."""
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    connect = pytest.importorskip("websockets.sync.client").connect
    from feira.jogo.web import ServidorProjecao

    est = EstadoProjecao()
    pub = PublicadorProjecao(est)
    srv = ServidorProjecao(est, porta=8479)
    assert srv.sobe()
    quedas: list[tuple[float, dict]] = []
    pronto = threading.Event()
    parar = threading.Event()

    def cliente():
        with connect("ws://127.0.0.1:%d/ws" % srv.porta, open_timeout=10) as ws:
            pronto.set()
            while not parar.is_set():
                try:
                    m = json.loads(ws.recv(timeout=0.5))
                except TimeoutError:
                    continue
                if m.get("tipo") == "projecao" and m.get("evento") == "queda":
                    quedas.append((time.perf_counter(), m))

    t = threading.Thread(target=cliente, daemon=True)
    t.start()
    try:
        assert pronto.wait(timeout=10)
        time.sleep(0.4)
        # a rodada acontecendo: 3 publicações a 1 Hz. `morte` é o instante da ÚLTIMA
        # publicação — é ali que o jogo para, e é dali que os 3 s da DoD contam. Marcar
        # depois de um `sleep` daria um número mais bonito e errado: parte da rédea já
        # teria queimado antes do cronômetro começar.
        for k in range(3):
            pub(_placar(fase, t=310.0 + k))
            if k < 2:
                time.sleep(1.0)
        morte = time.perf_counter()
        fim = morte + TETO_DOD_S + 1.5
        while time.perf_counter() < fim and not quedas:
            time.sleep(0.05)
    finally:
        parar.set()
        t.join(timeout=3)
        srv.desce()

    assert quedas, "a projeção NÃO voltou sozinha — o público ficaria olhando um placar morto"
    detectado, msg = quedas[0]
    atraso = detectado - morte
    assert msg["fase"] == "ocioso" and msg["degradado"] is True
    assert atraso <= TETO_DOD_S, "voltou em %.2f s (teto da DoD: %.1f s)" % (atraso, TETO_DOD_S)
    # deixa o número à vista de quem rodar com -s
    print("\n[DoD d] queda do jogo -> ocioso no cliente em %.2f s (teto %.1f s)"
          % (atraso, TETO_DOD_S))


def test_o_vigia_do_front_tambem_cabe_no_teto():
    """O front tem vigia PRÓPRIO para o caso de o servidor inteiro morrer — sem ele,
    "o jogo caiu" e "a rede caiu" teriam desfechos diferentes na tela, e para a
    plateia é a mesma coisa. Este teste lê a constante do JS e confere o teto."""
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "web" / "js" / "projecao.js").read_text(
        encoding="utf-8")
    m = re.search(r"const QUEDA_MS = (\d+);", js)
    assert m, "o vigia do front sumiu de web/js/projecao.js"
    assert int(m.group(1)) / 1000.0 <= TETO_DOD_S
