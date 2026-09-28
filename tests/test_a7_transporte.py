"""A7 — o transporte da projeção: passividade, limites e o espelho de frames.

O que estes testes guardam é UMA propriedade, dita de várias formas: **nada no
caminho do jogo pode esperar pela projeção**. Fila cheia, servidor morto, cliente
lento, braço com nome estranho — em todos, o jogo segue e a projeção perde quadro.
"""
from __future__ import annotations

import json
import queue
import threading
import time

import pytest

from feira.contratos.frame import frame_wire
from feira.jogo.web import (
    ANEL,
    ArenaPublicada,
    EstadoProjecao,
    PublicadorProjecao,
    braco_do_controlador,
)


def _placar(fase="jogando", t=310.0, janela=(300.0, 420.0), entregues=7):
    return {"tipo": "placar", "fase": fase, "t": t, "t_restante": 110.0,
            "chave": {"cenario": "aberta.maquete", "seed": 100,
                      "janela": list(janela), "demanda": "abc123def456"},
            "linhas": [{"braco": "humano", "rotulo": "VOCÊ", "entregues": entregues,
                        "fila": 8.0, "tempo_medio": 40.0, "fantasma": False}],
            "vencedor": None}


def _frame(braco="humano", t=310.0, janela=(300.0, 420.0), n=3):
    return frame_wire(braco, t, decisao=1, substep=0, politica="x",
                      tls=[{"id": "t1", "state": "GGrr"}],
                      veiculos=[{"id": "v%d" % i, "x": 1.0, "y": 2.0,
                                 "angle": 0.0, "speed": 1.0} for i in range(n)],
                      heat={"l1": 2}, stats={"entregues": 3}, janela=janela)


# --------------------------------------------------------------- passividade
def test_publicar_sem_servidor_nao_levanta_e_nao_bloqueia():
    """O caso da feira: a projeção nunca subiu, e a rodada acontece do mesmo jeito."""
    pub = PublicadorProjecao(EstadoProjecao())
    t0 = time.perf_counter()
    for k in range(200):
        pub(_placar(t=300.0 + k))
    gasto = time.perf_counter() - t0
    assert pub.chamadas == 200
    # 200 publicações sem laço nenhum do outro lado têm que custar menos que UM
    # sim-step. O número é folgado de propósito: o que se guarda aqui é a ORDEM de
    # grandeza (microssegundos por publicação), não um limiar fino.
    assert gasto < 0.5, "publicar custou %.3f s para 200 mensagens" % gasto
    assert pub.pior_ms < 50.0


def test_fila_cheia_descarta_o_mais_velho_e_continua_aceitando():
    """Projeção parada não pode virar vazamento de memória no processo do jogo."""
    est = EstadoProjecao()
    for k in range(ANEL + 50):
        assert est.entrega(_placar(t=300.0 + k)) is True
    assert est.fila.qsize() == ANEL
    assert est.descartadas == 50
    # o que sobrou é a CAUDA (o mais novo), não a cabeça
    ts = []
    while True:
        try:
            ts.append(est.fila.get_nowait()["t"])
        except queue.Empty:
            break
    assert ts[-1] == 300.0 + ANEL + 49
    assert ts[0] == 300.0 + 50


def test_mensagem_que_levanta_na_serializacao_nao_derruba_o_publicador():
    class Explode(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")

    pub = PublicadorProjecao(EstadoProjecao())
    pub(Explode())          # não levanta
    assert pub.chamadas == 1


# ------------------------------------------------------------------- braços
@pytest.mark.parametrize("nome,esperado", [
    ("humano:teclado", "humano"),
    ("timer:uniforme_27s", "timer"),
    ("timer:coordenado_c60@grade5", "timer"),
    ("rl:maq30_ats_full_best", "rl"),
    ("humano", "humano"),
    ("qualquer_coisa", None),
    (None, None),
    ("", None),
])
def test_braco_do_controlador(nome, esperado):
    """`frame_wire` RECUSA braço fora de `BRACOS`, e recusar no caminho do jogo seria
    exatamente o que este módulo não pode fazer. A normalização mora aqui."""
    assert braco_do_controlador(nome) == esperado


# ------------------------------------------------------------ ArenaPublicada
class _ArenaFalsa:
    def __init__(self, n_frames=3):
        self.n = n_frames
        self.ao_esperar = None
        self.chamadas = []

    def topologia(self, cenario):
        return "topo"

    def roda(self, cenario, seed, controlador, janela=None, *, ritmo=None,
             observador=None, gui=False):
        self.chamadas.append((seed, ritmo, gui))
        for k in range(self.n):
            if observador is not None:
                observador(_Quadro(300.0 + k))
        return "resultado"


class _Quadro:
    def __init__(self, t):
        self.braco = "humano:teclado"
        self.t = t
        self.decisao = 1
        self.substep = 0
        self.tls = [{"id": "t1", "state": "GG"}]
        self.veiculos = [{"id": "v1", "x": 1.0, "y": 2.0, "angle": 0.0, "speed": 1.0}]
        self.heat = {"l1": 1}
        self.stats = {"entregues": 2}


class _Janela:
    t0, t1 = 300.0, 420.0


def test_arena_publicada_espelha_os_frames_e_encadeia_o_observador():
    est = EstadoProjecao()
    pub = PublicadorProjecao(est)
    arena = _ArenaFalsa(n_frames=4)
    vistos = []
    envelopada = ArenaPublicada(arena, pub, braco="humano")

    assert envelopada.roda("cen", 100, _Ctrl(), _Janela(),
                           observador=vistos.append) == "resultado"
    assert len(vistos) == 4                      # o motor continua vendo tudo
    assert est.fila.qsize() == 4                 # e a projeção também
    msg = est.fila.get_nowait()
    assert msg["type"] == "frame" and msg["braco"] == "humano"
    assert msg["janela"] == [300.0, 420.0]       # a janela viaja junto (armadilha b)


def test_arena_publicada_repassa_ao_esperar_para_dentro():
    """O motor faz `hasattr(arena, 'ao_esperar')` e depois ATRIBUI nele. Se a
    atribuição parar no decorador, a cadência de entrada volta para 1 Hz e o botão
    parece quebrado — o achado do A4."""
    arena = _ArenaFalsa()
    env = ArenaPublicada(arena, PublicadorProjecao(EstadoProjecao()))
    assert hasattr(env, "ao_esperar")
    marca = object()
    env.ao_esperar = marca
    assert arena.ao_esperar is marca
    assert env.ao_esperar is marca


def test_arena_publicada_nao_derruba_a_rodada_se_a_projecao_explodir():
    class PubQuebrado(PublicadorProjecao):
        def frame(self, *a, **k):
            raise RuntimeError("projeção morreu")

    arena = _ArenaFalsa(n_frames=2)
    env = ArenaPublicada(arena, PubQuebrado(EstadoProjecao()), braco="humano")
    vistos = []
    with pytest.raises(RuntimeError):
        env.roda("cen", 100, _Ctrl(), _Janela(), observador=vistos.append)
    # NOTA: um publicador que levanta É um defeito do publicador; o `PublicadorProjecao`
    # de verdade engole tudo. O que este teste fixa é que a `ArenaPublicada` não
    # esconde o defeito — e o motor, que engole exceção do publicador mas não da
    # Arena, veria a rodada morrer. Por isso o engolimento mora no publicador.


class _Ctrl:
    nome = "humano:teclado"


def test_publicador_de_verdade_engole_tudo():
    class EstadoQuebrado(EstadoProjecao):
        def entrega(self, msg):
            raise RuntimeError("boom")

    arena = _ArenaFalsa(n_frames=2)
    env = ArenaPublicada(arena, PublicadorProjecao(EstadoQuebrado()), braco="humano")
    vistos = []
    assert env.roda("cen", 100, _Ctrl(), _Janela(),
                    observador=vistos.append) == "resultado"
    assert len(vistos) == 2


# ------------------------------------------------------------- divergência
def test_divergencia_denuncia_janelas_diferentes():
    """A ARMADILHA (b): a `janela` viaja no frame porque a projeção antiga comparava
    contadores de simulações derivadas."""
    est = EstadoProjecao()
    est.absorve(_frame("timer", janela=(300.0, 420.0)))
    est.absorve(_frame("rl", janela=(300.0, 420.0)))
    assert est.divergencia() == ""
    est.absorve(_frame("humano", janela=(300.0, 600.0)))
    d = est.divergencia()
    assert d and "humano" in d and "600" in d


def test_divergencia_pega_frame_fora_da_janela_do_placar():
    est = EstadoProjecao()
    est.absorve(_placar(janela=(300.0, 420.0)))
    est.absorve(_frame("rl", janela=(300.0, 420.0)))
    assert est.divergencia() == ""
    est.absorve(_frame("timer", janela=(0.0, 120.0)))
    assert "timer" in est.divergencia()


# --------------------------------------------------------- servidor de fato
@pytest.fixture()
def servidor():
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    from feira.jogo.web import ServidorProjecao

    est = EstadoProjecao()
    srv = ServidorProjecao(est, porta=8477)
    assert srv.sobe(), "o servidor da projeção não subiu"
    try:
        yield est, srv
    finally:
        srv.desce()


def test_ws_entrega_o_que_o_motor_publica(servidor):
    est, srv = servidor
    connect = pytest.importorskip("websockets.sync.client").connect
    pub = PublicadorProjecao(est)
    recebidas = []
    pronto = threading.Event()
    parar = threading.Event()

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
    time.sleep(0.4)
    pub(_placar(entregues=42))
    pub(_frame("humano"))
    time.sleep(0.8)
    parar.set()
    t.join(timeout=3)

    tipos = [m.get("tipo") or m.get("type") for m in recebidas]
    assert "placar" in tipos and "frame" in tipos
    pl = next(m for m in recebidas if m.get("tipo") == "placar")
    assert pl["linhas"][0]["entregues"] == 42
    # e o caminho do jogo pagou microssegundos por isso
    assert pub.pior_ms < 50.0


def test_cliente_novo_recebe_o_estado_de_agora(servidor):
    est, srv = servidor
    connect = pytest.importorskip("websockets.sync.client").connect
    pub = PublicadorProjecao(est)
    # O PLACAR PRIMEIRO, e agora isso importa: trocar de fase começa uma ÉPOCA nova e
    # descarta os quadros da anterior (`EstadoProjecao._vira_epoca` — os quadros da
    # fase que passou carregam a janela dela e faziam a tela abrir denunciando). Este
    # teste publicava o quadro numa fase e o placar em outra, uma ordem que a rodada
    # não produz: lá a fase já está posta quando a Arena começa a espelhar.
    pub(_placar(entregues=13))
    pub(_frame("rl"))
    time.sleep(0.5)
    with connect("ws://127.0.0.1:%d/ws" % srv.porta, open_timeout=10) as ws:
        vistas = [json.loads(ws.recv(timeout=2.0)) for _ in range(3)]
    tipos = [m.get("tipo") or m.get("type") for m in vistas]
    assert tipos[0] == "projecao"          # o status vem primeiro
    assert "frame" in tipos and "placar" in tipos


def test_o_feed_do_ocioso_entra_pelo_ingest(servidor):
    """A tela `ocioso` vem de OUTRO processo (traci é conexão de módulo). Este teste
    percorre o caminho inteiro do `scripts/projecao_ocioso.py` — `Remetente` -> socket
    `/ingest` -> estado do servidor — sem subir SUMO, que é a parte que ele não pode
    provar aqui."""
    est, srv = servidor
    pytest.importorskip("websockets.sync.client")
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from scripts.projecao_ocioso import Remetente

    rem = Remetente("ws://127.0.0.1:%d/ingest" % srv.porta)
    rem.start()
    pub = PublicadorProjecao(envia=rem)

    class _Q:
        braco = "rl:ckpt"
        t, decisao, substep = 360.0, 1, 0
        tls = [{"id": "t1", "state": "GG"}]
        veiculos = [{"id": "v1", "x": 1.0, "y": 2.0, "angle": 0.0, "speed": 1.0}]
        heat = {"l1": 3}
        stats = {"entregues": 7}

    try:
        for _ in range(3):
            pub.frame(_Q(), braco="rl", janela=(300.0, 2100.0))
            time.sleep(0.3)
        fim = time.perf_counter() + 5.0
        while time.perf_counter() < fim and "rl" not in est.ultimo_frame:
            time.sleep(0.05)
    finally:
        rem.close()

    assert rem.descartadas == 0
    assert "rl" in est.ultimo_frame, "o frame do feed ocioso não chegou pelo /ingest"
    # a janela viaja junto — é o que deixa a projeção DENUNCIAR braços em condições
    # diferentes em vez de desenhar a comparação errada
    assert est.ultimo_frame["rl"]["janela"] == [300.0, 2100.0]
