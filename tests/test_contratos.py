"""Invariantes dos contratos de DADO (C1, C2, C5, C7, C8).

Cada teste aqui existe por causa de um bug real — do histórico deste projeto ou da
auditoria do sistema de comparação atual. Quando um teste parecer paranoico, o
comentário diz qual número errado ele impede.
"""
from __future__ import annotations

import sys

import pytest

from feira import _fakes as F
from feira.contratos import (
    RESTRICOES_ABERTA,
    RESTRICOES_FECHADA,
    Amostra,
    ArenaNaoConfigurada,
    Cenario,
    CenarioJaImportado,
    Chave,
    ChavesIncompativeis,
    Fantasma,
    FantasmaIncompativel,
    Janela,
    LinhaPlacar,
    Placar,
    RestricoesFase,
    caminho_manifesto,
    cenario,
    chaves,
    comparar,
    frame_wire,
    janela_padrao,
)

# ============================================================ C1 — Cenario


@pytest.mark.parametrize("di,mg,y,esperado", [
    # O regime HISTÓRICO (10/10/3): a doc do maquete diz "verde 17 s / ciclo 20 s",
    # e a política em produção fica no piso em 61% das fases. Se este número mudar,
    # `results/maq30_ats_full_best.pt` deixou de ser reproduzível.
    (10, 10, 3, 17),
    # O regime ABERTO proposto (5/7/3): o README do maquete diz que os verdes
    # alcançáveis viram {7, 12, 17, ...}. O piso é 7 — e é isto que dá tato ao
    # botão do visitante (grade de 5 s em vez de 10 s).
    (5, 7, 3, 7),
    # Casos de contorno da aritmética de grade.
    (5, 10, 3, 12),
    (1, 7, 3, 7),
])
def test_verde_minimo_alcancavel(di, mg, y, esperado):
    """O verde mais curto do espaço de ação não é `min_green`: é ele arredondado
    para a grade DEPOIS do amarelo. Errar isso é descrever mal o espaço de políticas."""
    assert RestricoesFase(di, mg, y).verde_minimo_alcancavel == esperado


def test_restricoes_padrao_batem_com_a_doc():
    assert RESTRICOES_FECHADA.verde_minimo_alcancavel == 17
    assert RESTRICOES_ABERTA.verde_minimo_alcancavel == 7


def test_max_red_menor_que_verde_minimo_e_recusado():
    """max_red abaixo de min_green+yellow forçaria a troca antes de o verde mínimo
    fechar: toda decisão do agente viraria no-op e o braço mediria outra coisa."""
    with pytest.raises(ValueError, match="max_red"):
        RestricoesFase(decision_interval=5, min_green=7, yellow=3, max_red=8.0)
    RestricoesFase(decision_interval=5, min_green=7, yellow=3, max_red=60.0)  # ok


def test_cenario_desconhecido_falha_alto():
    """Typo em chave de cenário não pode cair num default silencioso — foi assim que
    o projeto ficou com dois baselines diferentes (20 s e 30 s) ao mesmo tempo."""
    with pytest.raises(ValueError, match="desconhecido"):
        cenario("aberta.maqete")
    assert set(chaves()) == {"small.maquete", "aberta.maquete"}


def test_cenario_fechado_existe_em_disco():
    """A aposta do repo: o `sim` do maquete entra como pacote, sem cópia. Se a rede
    dele sumiu do caminho, todo o resto é castelo de cartas."""
    c = cenario("small.maquete")
    assert c.disponivel(), (
        "rede da maquete não encontrada em %s — o repo smart-traffic-maquete "
        "precisa estar ao lado deste." % c.net_file)


def test_cenario_aberto_ainda_nao_medido():
    """`aberta.maquete` nasce com warmup_s=None e a Arena RECUSA rodar assim.

    Não é pendência de implementação: é a recusa de medir uma janela que começa num
    warm-up chutado. O número sai do agente A1, medido."""
    c = cenario("aberta.maquete")
    assert c.warmup_s is None
    assert c.modelo_demanda == "arquivo"
    with pytest.raises(ArenaNaoConfigurada, match="warmup_s"):
        janela_padrao(c)


def test_janela_padrao_do_cenario_fechado():
    c = cenario("small.maquete")
    assert janela_padrao(c) == Janela(0.0, 3600.0)
    assert janela_padrao(c, rodada=True) == Janela(0.0, 120.0)


def test_aplicar_depois_de_importar_sim_levanta(monkeypatch):
    """A armadilha herdada: `sim.environment.constants` congela os escalares NO
    IMPORT. Aplicar cenário depois disso não muda nada — só mente. Tem que gritar."""
    monkeypatch.setitem(sys.modules, "sim.environment.constants", object())
    monkeypatch.setenv("ST_MIN_GREEN", "10")
    with pytest.raises(CenarioJaImportado, match="já importado"):
        cenario("aberta.maquete").aplicar()


def test_aplicar_escreve_env(monkeypatch):
    monkeypatch.delitem(sys.modules, "sim.environment.constants", raising=False)
    c = cenario("small.maquete")
    c.aplicar()
    import os
    assert os.environ["ST_SCENARIO"] == "maquete"
    assert os.environ["ST_MIN_GREEN"] == "10"
    assert os.environ["ST_N_VEHICLES"] == "30"


def test_cenario_persistente_exige_frota():
    with pytest.raises(ValueError, match="n_vehicles"):
        Cenario(chave="x", net_file="a", sumocfg="b", add_file=None, view_file=None,
                restricoes=RESTRICOES_ABERTA, modelo_demanda="persistente")


# ============================================================ C2 — Demanda


def test_caminho_manifesto_lida_com_sufixo_composto(tmp_path):
    c = F.cenario_fake_arquivo(tmp_path)
    assert c.rou_file(42).name == "demanda_s42.rou.xml"
    assert caminho_manifesto(c, 42).name == "demanda_s42.manifesto.json"


# ============================================================ C5 — Resultado


def test_janela_invertida_e_recusada():
    with pytest.raises(ValueError, match="invertida"):
        Janela(t1=10.0, t0=20.0)


def test_comparar_recusa_condicoes_diferentes():
    """O achado nº1 da auditoria vira impossível: a projeção de hoje compara o
    `completed` acumulado de duas simulações que podem estar em tempos simulados
    diferentes, e nada checa."""
    a = F.resultado_fake(F.chave_fake(seed=42), controlador="timer")
    b = F.resultado_fake(F.chave_fake(seed=43), controlador="rl")
    with pytest.raises(ChavesIncompativeis):
        comparar(a, b)

    c = F.resultado_fake(F.chave_fake(seed=42, t1=200.0), controlador="rl")
    with pytest.raises(ChavesIncompativeis):
        comparar(a, c)

    d = F.resultado_fake(F.chave_fake(seed=42, sha="f" * 64), controlador="rl")
    with pytest.raises(ChavesIncompativeis, match="condições diferentes"):
        comparar(a, d)


def test_comparar_direcao_dos_sinais():
    """Positivo = `novo` melhor, para TODA métrica. É o que impede o slide
    "+20,8% de fila" — que existiu neste projeto e queria dizer o contrário."""
    k = F.chave_fake()
    # Os números são os de docs/RESULTADOS_ATS.md §4 (v2 contra o timer de 27 s).
    timer = F.resultado_fake(k, controlador="timer", entregues=1594, inseridos=1594,
                             tempo_medio_entregue=66.9, tempo_medio_no_sistema=70.0,
                             fila_media=12.16, espera_media=20.0)
    rl = F.resultado_fake(k, controlador="rl", entregues=1904, inseridos=1904,
                          tempo_medio_entregue=56.2, tempo_medio_no_sistema=58.0,
                          fila_media=7.99, espera_media=13.0)
    cmp = comparar(timer, rl)
    assert cmp.deltas["entregues"] == pytest.approx(19.45, abs=0.05)
    assert cmp.deltas["tempo_medio_entregue"] == pytest.approx(16.0, abs=0.05)
    assert cmp.deltas["fila_media"] == pytest.approx(34.3, abs=0.1)
    assert cmp.novo_vence_em_tudo

    # "Vence em tudo" exige melhora ESTRITA nas cinco: é a regra 3 que saiu do
    # artefato de sobrevivência (a variante C melhorava tempo e fila e destruía a
    # vazão, e por isso foi descartada).
    empata = rl.com(espera_media=timer.espera_media)
    assert not comparar(timer, empata).novo_vence_em_tudo


def test_conservacao_denuncia_veiculo_evaporado():
    """Substitui o `coherence_gap` (que assume frota fechada e morre na rede aberta).
    Balanço: ativos_inicio + inseridos = entregues + ativos_fim + perdidos."""
    r = F.resultado_fake(entregues=300, inseridos=300, ativos_inicio=150, ativos_fim=150)
    assert r.conservacao == 0
    assert r.sane()[0]

    sumiu = r.com(ativos_fim=100)          # 50 carros evaporaram
    assert sumiu.conservacao == 50
    ok, motivo = sumiu.sane()
    assert not ok and "balanço" in motivo


def test_backlog_denuncia_estrangulamento_da_borda():
    """A versão de rede aberta do artefato de sobrevivência: um controlador que
    trava a via de borda tem fila ótima e tempo ótimo — porque não deixou ninguém
    entrar. `entregues` cai, mas as médias mentem. O backlog é o que denuncia."""
    r = F.resultado_fake(entregues=100, inseridos=100, ativos_inicio=150, ativos_fim=150,
                         backlog_insercao=400, fila_media=0.5, tempo_medio_entregue=20.0)
    ok, motivo = r.sane()
    assert not ok and "backlog" in motivo


def test_travamento_declarado_nao_e_sano():
    assert not F.resultado_fake(travou=True).sane()[0]


def test_comparacao_avisa_quando_um_lado_e_insano():
    """Comparar segue possível (o dado é dado), mas o aviso viaja junto — a regra
    do projeto é reportar travamento seed a seed, separado das médias."""
    k = F.chave_fake()
    base = F.resultado_fake(k, controlador="timer")
    ruim = F.resultado_fake(k, controlador="humano", travou=True)
    cmp = comparar(base, ruim)
    assert not cmp.novo_sane and "travamento" in cmp.aviso


# ============================================================ C7 — fio


def test_placar_recusa_braco_e_fase_desconhecidos():
    k = F.chave_fake()
    linha = LinhaPlacar(braco="rl", rotulo="REDE NEURAL", entregues=10, fila=3.0,
                        tempo_medio=50.0, fantasma=True)
    with pytest.raises(ValueError, match="fase"):
        Placar.monta("jogandoo", 10.0, k, [linha])
    ruim = LinhaPlacar(braco="humanoo", rotulo="VOCÊ", entregues=1, fila=1.0,
                       tempo_medio=1.0, fantasma=False)
    with pytest.raises(ValueError, match="braço"):
        Placar.monta("jogando", 10.0, k, [ruim])


def test_placar_carrega_a_condicao_e_um_t_unico():
    """Um `t` só para os três braços: é a garantia estrutural de que o público não
    vê um braço comparado com outro em instantes diferentes."""
    k = F.chave_fake(seed=101, t0=1200.0, t1=1320.0, sha="ab" * 32)
    linhas = [LinhaPlacar(b, b.upper(), 10, 1.0, 2.0, b != "humano") for b in ("timer", "rl", "humano")]
    p = Placar.monta("jogando", 1260.0, k, linhas, t_restante=60.0)
    d = p.json()
    assert d["t"] == 1260.0 and d["chave"]["seed"] == 101
    assert d["chave"]["janela"] == [1200.0, 1320.0]
    assert d["chave"]["demanda"] == "ab" * 6      # sha[:12]


def test_frame_wire_recusa_braco_desconhecido():
    with pytest.raises(ValueError, match="braço"):
        frame_wire("nn", 1.0, decisao=1, substep=0, politica="x",
                   tls=[], veiculos=[], heat={}, stats={})


# ============================================================ C8 — Fantasma


def _fantasma(chave: Chave) -> Fantasma:
    serie = tuple(Amostra(t=chave.janela.t0 + i, entregues=i * 2, fila=float(i),
                          tempo_medio=50.0) for i in range(int(chave.janela.duracao)))
    return Fantasma(chave=chave, controlador="rl:v3", serie=serie,
                    final=F.resultado_fake(chave, controlador="rl:v3"))


def test_fantasma_de_outra_rodada_e_recusado():
    """Fantasma velho parece perfeitamente válido na tela e produz placar mentiroso
    na frente do público. Tem que levantar."""
    g = _fantasma(F.chave_fake(seed=42))
    g.confere(F.chave_fake(seed=42))                       # ok
    with pytest.raises(FantasmaIncompativel, match="não serve"):
        g.confere(F.chave_fake(seed=43))


def test_fantasma_em_t_e_degrau_nao_interpolacao():
    """`entregues` é contagem: interpolar inventa meia viagem no placar."""
    g = _fantasma(F.chave_fake(t0=0.0, t1=10.0))
    assert g.em(0.0).entregues == 0
    assert g.em(3.9).entregues == 6      # a amostra de t=3, não 3,9 do caminho p/ t=4
    assert g.em(4.0).entregues == 8
    assert g.em(999.0).entregues == g.serie[-1].entregues   # satura no fim


def test_fantasma_com_amostra_fora_da_janela_e_recusado():
    k = F.chave_fake(t0=100.0, t1=110.0)
    with pytest.raises(ValueError, match="fora da janela"):
        Fantasma(chave=k, controlador="rl", final=F.resultado_fake(k),
                 serie=(Amostra(t=99.0, entregues=0, fila=0.0, tempo_medio=0.0),))


def test_fantasma_round_trip_em_disco(tmp_path):
    g = _fantasma(F.chave_fake(seed=7, t0=1200.0, t1=1210.0))
    p = g.salva(tmp_path / "g.json")
    lido = Fantasma.carrega(p)
    assert lido.chave == g.chave
    assert lido.serie == g.serie
    assert lido.final == g.final
