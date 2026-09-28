"""A9 — o motor na gamificação: portão de saúde, START à prova de visitante, abortar
pelo operador, rodada grátis e os campos aditivos do placar (docs/GAMIFICACAO.md §5).

Roda sem SUMO: a `ArenaFalsa` de `test_a3_jogo` exercita o mesmo ciclo de vida.
"""
from __future__ import annotations

import time

import numpy as np
import pytest
from test_a3_jogo import ArenaFalsa

from feira import _fakes as F
from feira.contratos import BOTAO_START, OCIOSO, RESULTADO, Chave, Janela, Resultado
from feira.entrada import LeitorRoteirizado, ReplayInput, TecladoInput
from feira.jogo import Fantasmaria, MotorDoJogo
from feira.jogo.motor import ABORTA_OPERADOR, PREFIXO_TRAVOU


@pytest.fixture
def cenario_fake(tmp_path):
    cen = F.cenario_fake_arquivo(tmp_path)
    ger = F.GeradorDemandaFake()
    for s in (100, 101, 102):
        ger.gera(cen, s)
    return cen


@pytest.fixture
def fantasmaria(cenario_fake, tmp_path):
    return Fantasmaria(cenario_fake, raiz=tmp_path / "results", arena=ArenaFalsa())


def _motor(cenario, fantasmaria, roteiro, **kw):
    kw.setdefault("bracos", ("timer",))
    kw.setdefault("ao_vivo", False)
    kw.setdefault("prefetch", False)
    kw.setdefault("resultado_s", 0.0)
    kw.setdefault("seeds", (100, 101))
    fonte = kw.pop("fonte", None) or ReplayInput(12, roteiro)
    return MotorDoJogo(cenario, fonte=fonte, fantasmaria=fantasmaria,
                       arena=kw.pop("arena", fantasmaria._arena), **kw)


class ArenaAcumula(ArenaFalsa):
    """Como a `ArenaFalsa`, mas quem NÃO troca de fase deixa a malha encher.

    `ativos_fim` sobe com a falta de trocas. O fantasma do timer (calculado pela
    `ArenaFalsa` comum, 50 -> 50) é a referência: o `parado` acumula +80 pp sobre
    ele, o `martelo` 0 pp — os dois lados do limiar de +20 pp do A8 (§7).
    """

    def roda(self, cenario, seed, controlador, janela=None, *, ritmo=None,
             observador=None, gui=False):
        res = super().roda(cenario, seed, controlador, janela, ritmo=ritmo,
                           observador=observador, gui=gui)
        trocas = res.entregues - int((res.chave.janela.duracao) * self.base)
        return res.com(ativos_fim=50 + max(0, 40 - trocas))


# ----------------------------------------------------------- portão de saúde
def test_quem_deixa_a_malha_encher_trava_e_nao_e_coroado(cenario_fake, fantasmaria):
    """`parado`: 0 trocas, +80 pp de acúmulo sobre o timer. A rodada sai TRAVOU —
    sem vencedor (nem para o timer!), `sinais` no fio, motivo escrito."""
    m = _motor(cenario_fake, fantasmaria, [[]] * 40, arena=ArenaAcumula())
    r = m.rodada()
    assert r.humano is not None and r.travou
    assert r.vencedor is None
    assert any("acúmulo excedente" in s for s in r.sinais)
    p = r.placar.json()
    assert p["sinais"] and p["vencedor"] is None and p["pareado"] is True
    assert PREFIXO_TRAVOU in p["motivo"]
    assert m.fase == OCIOSO


def test_quem_martela_passa_no_portao_e_e_coroado(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [list(range(12))] * 40, arena=ArenaAcumula())
    r = m.rodada()
    assert r.humano is not None and not r.travou
    assert r.placar.json()["sinais"] == []
    assert r.vencedor == "humano"


def test_portao_desligado_nao_recusa_nada(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [[]] * 40, arena=ArenaAcumula(), portao_saude=False)
    r = m.rodada()
    assert not r.travou and r.vencedor == "timer"


def test_sem_fantasma_do_timer_o_portao_fica_desligado_e_diz(cenario_fake, fantasmaria):
    """Sem referência não há sinal pareado: a rodada degradada não pode ser recusada
    por um portão que não rodou — e o motivo registra isso."""
    m = _motor(cenario_fake, fantasmaria, [[]] * 40, arena=ArenaAcumula(), bracos=("rl",))
    r = m.rodada()
    assert not r.travou
    assert "sem portão de saúde" in r.motivo


def test_portao_nao_dispara_no_transito_de_brinquedo_sao(cenario_fake, fantasmaria):
    """Zero falso positivo: com a `ArenaFalsa` comum (população constante) ninguém trava."""
    for roteiro in ([[]] * 40, [[0], [], [1]] + [[]] * 40, [list(range(12))] * 40):
        r = _motor(cenario_fake, fantasmaria, roteiro).rodada()
        assert not r.travou


# ------------------------------------------------------------ START / abortar
def test_start_do_visitante_e_ignorado_no_modo_operador(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [[], [BOTAO_START], [0], [BOTAO_START]] + [[]] * 40,
               abortar_por=ABORTA_OPERADOR)
    r = m.rodada()
    assert not r.abortada and r.humano is not None
    assert m.starts_ignorados >= 2
    assert r.placar.json()["fase"] == RESULTADO


def test_start_ainda_aborta_no_modo_original(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [[], [BOTAO_START]] + [[]] * 40)
    r = m.rodada()
    assert r.abortada and r.humano is None


def test_modo_de_abortar_desconhecido_e_recusado(cenario_fake, fantasmaria):
    with pytest.raises(ValueError, match="abortar_por"):
        _motor(cenario_fake, fantasmaria, [[]], abortar_por="visitante")


class _FonteQueAborta(ReplayInput):
    """Um `ReplayInput` que, no N-ésimo poll, avisa o operador pedindo aborto."""

    def __init__(self, n_botoes, roteiro, *, no_poll: int) -> None:
        super().__init__(n_botoes, roteiro)
        self.ao_abortar = None
        self._no_poll = int(no_poll)
        self._polls = 0

    def poll(self):
        self._polls += 1
        if self._polls == self._no_poll and self.ao_abortar is not None:
            self.ao_abortar()
        return super().poll()


def test_o_operador_aborta_pela_fonte(cenario_fake, fantasmaria):
    """A fonte que sabe avisar (Esc no teclado, botão da página) é ligada ao motor
    no modo `operador` — e o aborto chega mesmo com o START do visitante ignorado."""
    fonte = _FonteQueAborta(12, [[]] * 40, no_poll=5)
    m = _motor(cenario_fake, fantasmaria, None, fonte=fonte, abortar_por=ABORTA_OPERADOR)
    assert fonte.ao_abortar == m.abortar
    r = m.rodada()
    assert r.abortada and "operador" in r.motivo and r.humano is None
    assert m.fase == OCIOSO


def test_abortar_fora_da_rodada_nao_faz_nada(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [[]] * 40, abortar_por=ABORTA_OPERADOR)
    m.abortar()                      # antes da rodada: o flag é zerado no início dela
    r = m.rodada()
    assert not r.abortada and r.humano is not None


def test_esc_no_teclado_avisa_o_operador_e_nao_vira_evento():
    chamadas = []
    tec = TecladoInput(12, leitor=LeitorRoteirizado(["\x1b", "q\x1b", " "]))
    tec.ao_abortar = lambda: chamadas.append(1)
    assert tec.poll() == []
    assert [e.indice for e in tec.poll()] == [0]
    assert [e.indice for e in tec.poll()] == [BOTAO_START]
    assert chamadas == [1, 1] and tec.n_abortos == 2


def test_esc_sem_ninguem_pendurado_e_ignorado():
    tec = TecladoInput(12, leitor=LeitorRoteirizado(["\x1b"]))
    assert tec.poll() == [] and tec.n_abortos == 1


# ------------------------------------------------------------ rodada grátis
def test_falha_nossa_repete_a_seed_para_o_mesmo_visitante(cenario_fake, fantasmaria):
    class ArenaQuebrada(ArenaFalsa):
        def roda(self, *a, **k):
            raise RuntimeError("Connection closed by SUMO")

    m = _motor(cenario_fake, fantasmaria, [[]] * 5, arena=ArenaQuebrada(), repete_falha=True)
    seed_antes = m.seed
    r = m.rodada()
    assert r.humano is None and r.repetir
    assert "falha nossa" in r.motivo
    assert m.seed == seed_antes                    # a mesma seed vai de novo
    assert m.n_rodadas == 1


def test_abortada_pelo_operador_nao_e_falha_nossa(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [[], [BOTAO_START]] + [[]] * 40, repete_falha=True)
    seed_antes = m.seed
    r = m.rodada()
    assert r.abortada and not r.repetir
    assert m.seed != seed_antes


def test_sem_a_opcao_a_falha_passa_a_vez(cenario_fake, fantasmaria):
    class ArenaQuebrada(ArenaFalsa):
        def roda(self, *a, **k):
            raise RuntimeError("boom")

    m = _motor(cenario_fake, fantasmaria, [[]] * 5, arena=ArenaQuebrada())
    seed_antes = m.seed
    r = m.rodada()
    assert not r.repetir and m.seed != seed_antes


# ------------------------------------------------------------ campos no fio
def test_o_placar_carrega_a_identidade_da_rodada(cenario_fake, fantasmaria):
    publicados = []
    m = _motor(cenario_fake, fantasmaria, [[0]] + [[]] * 40, publicador=publicados.append)
    m.rodada()
    m.rodada()
    assert {p["rodada"] for p in publicados} == {1, 2}
    finais = [p for p in publicados if p["fase"] == RESULTADO]
    assert [p["rodada"] for p in finais] == [1, 2]
    assert all(p["sinais"] == [] for p in finais)


def test_pular_resultado_encurta_a_espera(cenario_fake, fantasmaria):
    m = _motor(cenario_fake, fantasmaria, [[]] * 5, ao_vivo=True)
    m.pula_resultado()
    t0 = time.perf_counter()
    m._espera_resultado(5.0)
    assert time.perf_counter() - t0 < 0.5


def test_placar_recusa_sinais_com_vencedor():
    from feira.contratos import LinhaPlacar, Placar

    k = Chave(cenario="x", seed=1, janela=Janela(0.0, 10.0), demanda_sha="a" * 64,
              restricoes="di5/vm7/am3/mr0")
    ln = LinhaPlacar("humano", "VOCÊ", 10, 1.0, 2.0, False)
    with pytest.raises(ValueError, match="sinais"):
        Placar.monta("resultado", 10.0, k, [ln], vencedor="humano", sinais=["acúmulo"])


def test_resultado_com_helper():
    """`Resultado.com` (usado pela ArenaAcumula) existe e preserva o resto."""
    k = Chave(cenario="x", seed=1, janela=Janela(0.0, 10.0), demanda_sha="a" * 64,
              restricoes="di5/vm7/am3/mr0")
    r = Resultado(chave=k, controlador="t", entregues=5, tempo_medio_entregue=1.0,
                  tempo_medio_no_sistema=1.0, fila_media=1.0, espera_media=1.0,
                  inseridos=5, ativos_fim=1, ativos_inicio=1, backlog_insercao=0)
    assert r.com(ativos_fim=9).ativos_fim == 9 and r.com(ativos_fim=9).entregues == 5
    assert isinstance(np.asarray([1]), np.ndarray)


# ------------------------------------------------------------------- ritmo
def test_ritmo_e_apresentacao_e_vai_para_a_cadencia(cenario_fake, fantasmaria):
    """`ritmo` (s simulados por s de parede) é passado a quem impõe a cadência — a
    Arena (pelo `Ritmo`) ou o `Marcapasso` — e NÃO muda o que a rodada mede."""
    from feira.jogo.motor import Marcapasso

    class ArenaComGancho(ArenaFalsa):
        ao_esperar = None

    m = _motor(cenario_fake, fantasmaria, [[0]] + [[]] * 40, ao_vivo=True, ritmo=1.5,
               arena=ArenaComGancho())
    assert m._cadencia().sim_por_parede == 1.5
    m2 = _motor(cenario_fake, fantasmaria, [[0]] + [[]] * 40, ao_vivo=True, ritmo=2.0)
    m2._cadencia()
    assert isinstance(m2.marcapasso, Marcapasso) and m2.marcapasso.sim_por_parede == 2.0
    # a rodada em si mede o mesmo com qualquer ritmo (aqui: solto)
    a = _motor(cenario_fake, fantasmaria, [[0]] + [[]] * 40, ritmo=1.0).rodada()
    b = _motor(cenario_fake, fantasmaria, [[0]] + [[]] * 40, ritmo=2.0).rodada()
    assert a.humano.entregues == b.humano.entregues
    with pytest.raises(ValueError, match="ritmo"):
        _motor(cenario_fake, fantasmaria, [[]], ritmo=0)


def test_marcapasso_com_ritmo_encurta_o_deadline():
    from feira.jogo.motor import Marcapasso

    t = [0.0]
    dormidas = []
    mp = Marcapasso(sim_por_parede=2.0, dorme=lambda s: (dormidas.append(s), t.__setitem__(0, t[0] + s)),
                    agora=lambda: t[0])
    mp.inicia()
    mp.passo()
    assert abs(sum(dormidas) - 0.5) < 1e-6           # 1 s simulado em 0,5 s de parede


# ------------------------------------------------------------ anunciar o ocioso
def test_anuncia_ocioso_publica_a_volta_com_a_proxima_seed(cenario_fake, fantasmaria):
    """A tela só saía do RESULTADO quando o vigia declarava queda (20 s) — ou nunca, com
    o feed ocioso vivo. Com `anuncia_ocioso` o fim da tela de resultado publica um
    placar de `ocioso`, sem linhas, já com a seed da PRÓXIMA rodada."""
    publicados = []
    m = _motor(cenario_fake, fantasmaria, [[0]] + [[]] * 40, publicador=publicados.append,
               anuncia_ocioso=True)
    m.rodada()
    ultimo = publicados[-1]
    assert ultimo["fase"] == OCIOSO and ultimo["linhas"] == []
    assert ultimo["chave"]["seed"] == m.seed == 101
    assert [p["fase"] for p in publicados[-2:]] == [RESULTADO, OCIOSO]


def test_sem_anunciar_o_ultimo_placar_continua_sendo_o_resultado(cenario_fake, fantasmaria):
    publicados = []
    _motor(cenario_fake, fantasmaria, [[0]] + [[]] * 40, publicador=publicados.append).rodada()
    assert publicados[-1]["fase"] == RESULTADO


def test_o_humano_anuncia_o_tick_a_fonte_que_souber_ouvir(cenario_fake, fantasmaria):
    """O tick é onde a intenção é julgada; a página precisa do instante exato para o
    anel encher até ele (docs/GAMIFICACAO.md §2.8)."""
    class FonteComTick(ReplayInput):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.ticks = []

        def ao_tick(self, t):
            self.ticks.append(t)

    fonte = FonteComTick(12, [[0]] + [[]] * 40)
    m = _motor(cenario_fake, fantasmaria, None, fonte=fonte)
    r = m.rodada()
    assert r.humano is not None
    # a ArenaFalsa decide a cada `di` sim-steps numa janela de 120 s: 120/5 = 24 ticks
    assert len(fonte.ticks) == 24
    assert fonte.ticks == sorted(fonte.ticks) and fonte.ticks[0] >= 0.0
