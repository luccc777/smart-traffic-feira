"""Invariantes dos contratos de DADO (C1, C2, C5, C7, C8).

Cada teste aqui existe por causa de um bug real — do histórico deste projeto ou da
auditoria do sistema de comparação atual. Quando um teste parecer paranoico, o
comentário diz qual número errado ele impede.
"""
from __future__ import annotations

import dataclasses
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


def test_warmup_nao_medido_e_recusado():
    """A Arena RECUSA rodar cenário com warm-up chutado.

    Não é pendência de implementação: é a recusa de medir uma janela que começa
    num transiente. `aberta.maquete` nasceu com `warmup_s=None` justamente para
    esta guarda valer até alguém medir."""
    c = cenario("aberta.maquete")
    with pytest.raises(ArenaNaoConfigurada, match="warmup_s"):
        janela_padrao(dataclasses.replace(c, warmup_s=None))


def test_cenario_aberto_carrega_o_regime_medido():
    """Os números que o agente A1 mediu (docs/CALIBRACAO_ABERTA.md). Se algum
    mudar sem o documento mudar junto, a proveniência se perdeu."""
    c = cenario("aberta.maquete")
    assert c.warmup_s == 300.0
    assert c.modelo_demanda == "arquivo"
    assert (c.reroute_period, c.depart_lane, c.od_weight) == (60, "best", "capacity")
    assert janela_padrao(c) == Janela(300.0, 3900.0)


def test_janela_padrao_do_cenario_fechado():
    c = cenario("small.maquete")
    assert janela_padrao(c) == Janela(0.0, 3600.0)
    assert janela_padrao(c, rodada=True) == Janela(0.0, 120.0)


class _ConstantsFalso:
    """Espelha o que `sim.environment.constants` expõe depois de congelado."""

    def __init__(self, cen):
        self.NET_FILE = cen.net_file
        self.SUMOCFG = cen.sumocfg
        self.MIN_GREEN = cen.restricoes.min_green
        self.DECISION_INTERVAL = cen.restricoes.decision_interval
        self.MAX_RED = float(cen.restricoes.max_red)
        self.YELLOW_DUR = cen.restricoes.yellow


def test_aplicar_compara_o_estado_congelado_nao_a_env_var(monkeypatch):
    """A guarda olha o MÓDULO, não `os.environ` — e a diferença mordeu de verdade.

    A versão anterior comparava env var, então bastava alguém importar `sim` com
    outra rede e depois devolver a env var ao lugar para a guarda passar. Foi
    assim que a Arena mediu 12 semáforos onde havia 10, sem erro
    (docs/AUDITORIA_COMPARACAO.md §12e)."""
    fechado, aberto = cenario("small.maquete"), cenario("aberta.maquete")
    monkeypatch.setitem(sys.modules, "sim.environment.constants",
                        _ConstantsFalso(fechado))
    # env var "certa" para o cenário aberto — o que enganava a guarda antiga
    for k, v in aberto.env().items():
        monkeypatch.setenv(k, v)

    with pytest.raises(CenarioJaImportado, match="NET_FILE"):
        aberto.aplicar()
    assert set(aberto.divergencias_congeladas()) >= {"NET_FILE", "SUMOCFG", "MIN_GREEN"}
    fechado.aplicar()                      # o cenário que de fato está congelado passa


def test_aplicar_pega_yellow_que_o_sim_ignora(monkeypatch):
    """`YELLOW_DUR` é literal 3 no `constants.py`, sem env var. Configurar
    `yellow != 3` seria mentira silenciosa — tem que falhar alto."""
    c = cenario("small.maquete")
    monkeypatch.setitem(sys.modules, "sim.environment.constants", _ConstantsFalso(c))
    c.aplicar()
    amarelo4 = dataclasses.replace(
        c, restricoes=dataclasses.replace(c.restricoes, yellow=4))
    assert amarelo4.divergencias_congeladas() == {"YELLOW_DUR": (3, 4)}
    with pytest.raises(CenarioJaImportado, match="YELLOW_DUR"):
        amarelo4.aplicar()


def test_sem_sim_importado_nao_ha_estado_congelado(monkeypatch):
    monkeypatch.delitem(sys.modules, "sim.environment.constants", raising=False)
    assert cenario("aberta.maquete").divergencias_congeladas() == {}
    cenario("aberta.maquete").aplicar()    # não levanta


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


def test_sane_e_estrutural_e_nao_ve_gridlock_sozinho():
    """Limite CONHECIDO do contrato, fixado aqui de propósito.

    Numa frota fechada travada o balanço fecha em zero e o backlog é zero — o
    carro não some, ele só nunca chega. `sane()` aprova, e está certo: ele é uma
    checagem estrutural, válida em qualquer regime. Quem enxerga gridlock é a
    lacuna de sobrevivência, cujo limiar DEPENDE do regime (medida em janelas de
    1800–10800 s; numa rodada de 120 s metade da população é censurada por
    construção). Por isso ela vive em `feira.metricas.sinais_de_travamento`, com
    limiar declarado pelo chamador, e é a Arena que carimba `travou`.

    Se algum dia alguém puser um limiar fixo de lacuna dentro de `sane()`, este
    teste quebra — e o motivo está escrito acima."""
    travado = F.resultado_fake(entregues=5, inseridos=5, ativos_inicio=150,
                               ativos_fim=150, tempo_medio_entregue=60.0,
                               tempo_medio_no_sistema=3000.0)
    assert travado.conservacao == 0 and travado.backlog_insercao == 0
    assert travado.sane()[0]                              # estrutural: passa
    assert travado.lacuna_sobrevivencia == pytest.approx(4900.0)   # a grandeza acusa

    sao = F.resultado_fake()
    assert sao.lacuna_sobrevivencia < 25.0
    assert travado.com(travou=True).sane()[0] is False     # a Arena carimba, aí reprova


def test_lacuna_infinita_quando_nada_chega():
    preso = F.resultado_fake(entregues=0, inseridos=0, ativos_inicio=300, ativos_fim=300)
    assert preso.lacuna_sobrevivencia == float("inf")
    assert not preso.sane()[0]      # aqui `sane` pega, por "nenhuma viagem concluída"


def test_sane_olha_perdidos():
    """Veículo perdido que é CONTABILIZADO fecha a conservação em zero e passava
    despercebido. Perder veículo continua sendo corrida inválida."""
    r = F.resultado_fake(entregues=280, inseridos=300, ativos_inicio=150,
                         ativos_fim=150, perdidos=20)
    assert r.conservacao == 0
    ok, motivo = r.sane()
    assert not ok and "perdidos" in motivo
    assert F.resultado_fake(entregues=299, inseridos=300, ativos_inicio=150,
                            ativos_fim=150, perdidos=1).sane()[0]   # 0,22% passa


def test_chave_carrega_o_espaco_de_acao():
    """Duas corridas com grades diferentes descrevem conjuntos de políticas
    diferentes (verde mínimo alcançável de 7 s contra 17 s) e não podem comparar
    como se fossem a mesma condição."""
    fechado, aberto = cenario("small.maquete"), cenario("aberta.maquete")
    j, sha = Janela(0.0, 120.0), "a" * 64
    k_fechado = Chave.de(fechado, 42, j, sha)
    k_aberto = Chave.de(aberto, 42, j, sha)
    assert k_fechado.restricoes == "di10/vm10/am3/mr0"
    assert k_aberto.restricoes == "di5/vm7/am3/mr0"

    a = F.resultado_fake(k_fechado, controlador="rl@10/10")
    # mesma rede, mesma seed, mesma demanda, mesma janela -- so a grade muda
    b = F.resultado_fake(dataclasses.replace(k_aberto, cenario=fechado.chave),
                         controlador="rl@5/7")
    with pytest.raises(ChavesIncompativeis, match="condições diferentes"):
        comparar(a, b)


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


def test_placar_distingue_empate_de_rodada_nao_pareada():
    """`vencedor=None` tem dois significados OPOSTOS, e o fio tem que separá-los.

    Empate e rodada não pareada saem os dois com o vencedor em branco. Para o
    público são coisas diferentes: empate é resultado; não pareada quer dizer que
    os braços partiram de estados diferentes em t0 e a comparação NÃO VALE. Sem
    `pareado`/`motivo` no fio, a projeção mostrava os dois casos idênticos e o
    servidor tinha que adivinhar (achado do agente A7).
    """
    k = F.chave_fake()
    linhas = [LinhaPlacar(b, b.upper(), 10, 1.0, 2.0, b != "humano")
              for b in ("timer", "rl", "humano")]

    empate = Placar.monta("resultado", 120.0, k, linhas).json()
    assert empate["vencedor"] is None
    assert empate["pareado"] is True and empate["motivo"] == ""

    torto = Placar.monta("resultado", 120.0, k, linhas, motivo="selo de t0 divergente",
                         pareado=False).json()
    assert torto["vencedor"] is None
    assert torto["pareado"] is False and "selo" in torto["motivo"]


def test_placar_sai_com_tipo_e_type():
    """O frame despacha por `type` (herdado do maquete) e o placar nasceu com
    `tipo`. Um cliente teria que testar os dois nomes, e o dia em que alguém
    esquecer a segunda metade a mensagem some sem erro."""
    k = F.chave_fake()
    linhas = [LinhaPlacar("rl", "REDE NEURAL", 10, 1.0, 2.0, True)]
    d = Placar.monta("jogando", 10.0, k, linhas).json()
    assert d["tipo"] == d["type"] == "placar"
    assert frame_wire("rl", 1.0, decisao=1, substep=0, politica="x",
                      tls=[], veiculos=[], heat={}, stats={})["type"] == "frame"


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
