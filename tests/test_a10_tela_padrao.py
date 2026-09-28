"""A10 — a TELA PADRÃO: os dois braços ao vivo, e o placar que os compara honestamente.

A tela ociosa mostra a RL rodando com o timer de régua. São duas simulações em DOIS
PROCESSOS (traci é conexão de módulo), e é essa separação que cria as três formas de
mentir que estes testes fecham:

1. **Comparar `t` diferentes.** A RL roda uma inferência do torch por decisão e fica
   para trás do timer em tempo simulado. Com `entregues` monotônico, exibir o último
   quadro de cada um dá ao adiantado uma vantagem de graça.
2. **Comparar SEEDS diferentes.** Cada feed tem o seu rodízio e o seu vigia de
   população — que aborta a volta no braço que congestiona mais, e só nele.
3. **Deixar o feed brigar com a rodada pela tela.** O feed não sabe que alguém apertou
   ESPAÇO; ele continua empurrando quadro no mesmo `ultimo_frame` que a rodada usa.

As três terminam na mesma tela plausível e errada. Nenhuma levanta exceção sozinha.
"""
from __future__ import annotations

import itertools

import pytest

from feira.contratos.frame import CONTAGEM, JOGANDO, OCIOSO, RESULTADO, frame_wire
from feira.jogo.ocioso import SupervisorOcioso, comando_ocioso
from feira.jogo.web import EstadoProjecao

JANELA = (300.0, 420.0)


def _frame(braco, t, *, seed=100, entregues=10, fila=3.0, tempo=50.0, janela=JANELA):
    return frame_wire(braco, t, decisao=1, substep=0, politica=braco,
                      tls=[], veiculos=[], heat={}, stats={
                          "entregues": entregues, "ativos": 12,
                          "tempo_medio_entregue": tempo, "fila_media": fila},
                      janela=janela, seed=seed)


@pytest.fixture
def estado():
    """Estado com relógio FALSO que anda 5 s por leitura: o estrangulamento de 1 Hz do
    placar nunca é o que está sendo testado aqui."""
    cen = pytest.importorskip("feira.contratos").cenario("aberta.maquete")
    return EstadoProjecao(cenario=cen, relogio=itertools.count(0.0, 5.0).__next__)


# ------------------------------------------------------- 1. o mesmo `t` para os dois
def test_placar_do_ocioso_alinha_os_bracos_no_mesmo_t(estado):
    """O caso medido na bancada: timer em t=375, RL em t=371, e a tela comparando os
    dois. O placar tem de sair no `t` que os DOIS já passaram, com o `stats` de cada um
    NAQUELE instante — não o mais recente de cada um."""
    for t in (370.0, 371.0, 372.0, 373.0, 374.0, 375.0):
        estado.absorve_externo(_frame("timer", t, entregues=int(t - 300)))
    for t in (370.0, 371.0):                       # a RL ficou 4 s para trás
        estado.absorve_externo(_frame("rl", t, entregues=int(t - 300) + 8))

    p = estado.ultimo_placar
    assert p is not None and p["fase"] == OCIOSO
    assert p["t"] == 371.0, "o placar sai no menor topo, não no maior"
    linhas = {ln["braco"]: ln for ln in p["linhas"]}
    # o timer entra com o que tinha EM 371, não com o que tem em 375
    assert linhas["timer"]["entregues"] == 71
    assert linhas["rl"]["entregues"] == 79
    assert [ln["fantasma"] for ln in p["linhas"]] == [False, False]   # os dois ao vivo


def test_um_braco_sozinho_nao_vira_placar(estado):
    estado.absorve_externo(_frame("timer", 310.0))
    assert estado.placar_ocioso() is None


def test_sem_sobreposicao_de_tempo_nao_vira_placar(estado):
    """Um braço em 310 e o outro em 400: não existe instante comum medido."""
    estado.absorve_externo(_frame("timer", 310.0))
    estado.absorve_externo(_frame("rl", 400.0))
    assert estado.placar_ocioso() is None


def test_buraco_na_serie_maior_que_a_tolerancia_nao_vira_placar(estado):
    """Quadro perdido pela fila (`entrega` descarta o mais velho sob pressão): o alvo
    comum cai DENTRO do buraco de um dos braços, e lá não há medida.

    timer: 310 ......... 330   (buraco de 20 s)
    rl:    310 ... 320
    alvo = min(330, 320) = 320, e o timer só tem 310 para oferecer ali.
    """
    estado.absorve_externo(_frame("timer", 310.0))
    estado.absorve_externo(_frame("timer", 330.0))
    estado.absorve_externo(_frame("rl", 310.0))
    estado.absorve_externo(_frame("rl", 320.0))
    assert estado.placar_ocioso() is None


def test_buraco_dentro_da_tolerancia_ainda_vira_placar(estado):
    """O contraponto: um quadro perdido isolado não pode apagar a tarja."""
    estado.absorve_externo(_frame("timer", 310.0, entregues=11))
    estado.absorve_externo(_frame("timer", 313.0, entregues=14))
    estado.absorve_externo(_frame("rl", 310.0, entregues=17))
    estado.absorve_externo(_frame("rl", 311.0, entregues=18))
    p = estado.placar_ocioso()
    assert p is not None and p["t"] == 311.0
    linhas = {ln["braco"]: ln["entregues"] for ln in p["linhas"]}
    assert linhas == {"timer": 11, "rl": 18}, "o timer entra com 310, não com 313"


def test_volta_nova_zera_a_serie(estado):
    """O `t` voltou para t0: a série anterior descreve outra corrida e não pode
    emendar com a nova — senão o alvo comum ficaria preso no passado."""
    for t in (400.0, 401.0):
        estado.absorve_externo(_frame("timer", t))
        estado.absorve_externo(_frame("rl", t))
    estado.absorve_externo(_frame("timer", 300.0, seed=101))
    estado.absorve_externo(_frame("rl", 300.0, seed=101))
    p = estado.ultimo_placar
    assert p["t"] == 300.0 and p["chave"]["seed"] == 101


# ------------------------------------------------------------- 2. a mesma seed
def test_seeds_diferentes_nao_viram_placar(estado):
    """O vigia de população abortou a volta de um braço e ele foi para a próxima seed.
    A janela continua igual nos dois — só a seed denuncia."""
    estado.absorve_externo(_frame("timer", 310.0, seed=100))
    estado.absorve_externo(_frame("rl", 310.0, seed=101))
    assert estado.placar_ocioso() is None


def test_janelas_diferentes_nao_viram_placar(estado):
    estado.absorve_externo(_frame("timer", 310.0, janela=(300.0, 420.0)))
    estado.absorve_externo(_frame("rl", 310.0, janela=(300.0, 540.0)))
    assert estado.placar_ocioso() is None


def test_frame_sem_seed_nao_vira_placar(estado):
    """Produtor antigo (`seed` é aditivo, default None): sem ela não dá para afirmar
    que os dois rodam a mesma hora de trânsito, então não se afirma nada."""
    estado.absorve_externo(_frame("timer", 310.0, seed=None))
    estado.absorve_externo(_frame("rl", 310.0, seed=None))
    assert estado.placar_ocioso() is None


# --------------------------------------------- 3. a rodada é dona da tela
@pytest.mark.parametrize("fase", [CONTAGEM, JOGANDO, RESULTADO])
def test_frame_externo_e_descartado_fora_do_ocioso(estado, fase):
    estado.absorve_externo(_frame("timer", 310.0))
    antes = dict(estado.ultimo_frame["timer"])
    estado.fase = fase
    estado.absorve_externo(_frame("timer", 999.0, entregues=999))
    assert estado.ultimo_frame["timer"]["t"] == antes["t"], "a rodada perdeu a tela"
    assert estado.descartadas >= 1


def test_o_feed_volta_a_valer_quando_a_fase_volta_ao_ocioso(estado):
    estado.fase = JOGANDO
    estado.absorve_externo(_frame("timer", 310.0))
    assert "timer" not in estado.ultimo_frame
    estado.fase = OCIOSO
    estado.absorve_externo(_frame("timer", 311.0))
    assert estado.ultimo_frame["timer"]["t"] == 311.0


def test_placar_do_motor_passa_pelo_ingest(estado):
    """O portão é só para `frame`. Quem publica `placar` é o motor; um placar que chegue
    pelo `/ingest` é ensaio de bancada e não pode ser engolido em silêncio."""
    estado.fase = JOGANDO
    estado.absorve_externo({"tipo": "placar", "fase": JOGANDO, "t": 1.0,
                            "t_restante": 0.0, "chave": {}, "linhas": []})
    assert estado.ultimo_placar is not None


# ------------------------------------------------------------- o supervisor
def test_os_dois_bracos_sobem_na_mesma_seed():
    """A trava de seed é por CONSTRUÇÃO: uma seed só, uma volta só, escolhidas aqui."""
    cmd_rl = comando_ocioso("rl", 107, cenario="aberta.maquete", duracao=120,
                            host="127.0.0.1", porta=8080)
    cmd_tm = comando_ocioso("timer", 107, cenario="aberta.maquete", duracao=120,
                            host="127.0.0.1", porta=8080)
    for cmd in (cmd_rl, cmd_tm):
        assert cmd[cmd.index("--seeds") + 1] == "107"
        assert cmd[cmd.index("--voltas") + 1] == "1"
    assert cmd_rl[cmd_rl.index("--braco") + 1] == "rl"
    assert cmd_tm[cmd_tm.index("--braco") + 1] == "timer"


class _ProcFalso:
    def __init__(self, codigo=None):
        self.codigo = codigo
        self.morto = False

    def poll(self):
        return self.codigo

    @property
    def returncode(self):
        return self.codigo


def _supervisor(estado, monkeypatch, *, seeds=(100, 101)):
    sup = SupervisorOcioso(estado, cenario="aberta.maquete", seeds=seeds, porta=8080)
    subiu = []

    def sobe_falso():
        subiu.append(sup.seed_atual)
        sup._procs = {b: _ProcFalso() for b in sup.bracos}

    monkeypatch.setattr(sup, "sobe", sobe_falso)
    monkeypatch.setattr(sup, "derruba", lambda timeout=0.0: sup._procs.clear())
    return sup, subiu


def test_supervisor_sobe_no_ocioso_e_desce_na_rodada(estado, monkeypatch):
    sup, subiu = _supervisor(estado, monkeypatch)
    sup.ronda()
    assert sup.rodando and subiu == [100]
    estado.fase = JOGANDO
    sup.ronda()
    assert not sup.rodando, "os 120 s do visitante não dividem CPU com dois SUMOs"
    estado.fase = OCIOSO
    sup._proxima_em = 0.0
    sup.ronda()
    assert sup.rodando


def test_proxima_volta_so_comeca_com_os_DOIS_bracos_terminados(estado, monkeypatch):
    sup, subiu = _supervisor(estado, monkeypatch)
    sup.ronda()
    sup._procs["rl"].codigo = 0                # a RL terminou; o timer continua
    sup.ronda()
    assert sup.rodando and subiu == [100], "meia tela viva não puxa a próxima seed"
    sup._procs["timer"].codigo = 0
    sup.ronda()                                # agora sim: recolhe e avança a seed
    assert not sup.rodando and sup.voltas == 1
    sup._proxima_em = 0.0
    sup.ronda()
    assert subiu == [100, 101]
