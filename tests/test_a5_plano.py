"""O `PlanoFixo` (agente A5): invariantes do plano, o que a grade realiza, e i/o.

Nada aqui sobe SUMO — é aritmética de plano de tempo fixo. Os testes que
precisam da rede estão em `test_a5_coordenado.py`.
"""
from __future__ import annotations

import json

import pytest

from feira.controladores.coordenado import PlanoFixo, PlanoIncompativel

PLANOS = None  # preenchido pelo fixture `planos_no_disco` quando existirem


def plano_simples(**kw) -> PlanoFixo:
    base = dict(
        nome="teste", cenario="aberta.maquete", ciclo_s=60.0, amarelo_s=3.0,
        verdes={"A": (27.0, 27.0), "B": (12.0, 42.0)},
        offsets={"A": 0.0, "B": 15.0},
    )
    base.update(kw)
    return PlanoFixo(**base)


# ------------------------------------------------------------------ invariantes
def test_plano_exige_que_o_ciclo_feche():
    """Um plano cujas fases não somam o ciclo escorrega de ciclo em ciclo — e um
    plano que escorrega não tem offset, logo não tem onda verde. Falha alto."""
    with pytest.raises(ValueError, match="não fecha o ciclo"):
        plano_simples(verdes={"A": (27.0, 27.0), "B": (12.0, 40.0)})


def test_plano_recusa_verde_nao_positivo():
    with pytest.raises(ValueError, match="verde <= 0"):
        plano_simples(verdes={"A": (54.0, 0.0), "B": (12.0, 42.0)})


def test_plano_recusa_semaforo_so_em_um_dos_dois_dicionarios():
    with pytest.raises(ValueError, match="semáforos diferentes"):
        plano_simples(offsets={"A": 0.0})


def test_semaforo_de_uma_fase_so_nao_precisa_fechar_o_ciclo():
    """Nenhum na rede aberta (12 de 12 são controláveis), 6 de 10 na fechada: um
    TL de uma fase verde só nunca troca, então o ciclo dele é irrelevante."""
    p = plano_simples(verdes={"A": (27.0, 27.0), "B": (60.0,)},
                      offsets={"A": 0.0, "B": 0.0})
    assert p.fase_alvo("B", 12.3) == 0
    assert p.fase_alvo("B", 1234.5) == 0


# --------------------------------------------------------------------- fase_alvo
def test_fase_alvo_percorre_o_ciclo_e_aponta_o_destino_do_amarelo():
    """Dentro do amarelo que drena a fase k o alvo é k+1: o amarelo é transição,
    e é essa convenção que faz o TROCAR sair no primeiro tick em que o verde
    corrente já deveria ter acabado."""
    p = plano_simples()
    assert p.fase_alvo("A", 0.0) == 0
    assert p.fase_alvo("A", 26.9) == 0
    assert p.fase_alvo("A", 27.0) == 1        # amarelo 0 -> alvo 1
    assert p.fase_alvo("A", 29.9) == 1
    assert p.fase_alvo("A", 30.0) == 1        # verde 1
    assert p.fase_alvo("A", 56.9) == 1
    assert p.fase_alvo("A", 57.0) == 0        # amarelo 1 -> alvo 0 (fecha o ciclo)
    assert p.fase_alvo("A", 59.9) == 0


def test_fase_alvo_e_periodico_no_ciclo():
    p = plano_simples()
    for t in (0.0, 7.5, 13.0, 28.0, 41.3, 58.9):
        for k in (1, 2, 37):
            assert p.fase_alvo("B", t) == p.fase_alvo("B", t + k * p.ciclo_s)


def test_offset_desloca_o_plano_inteiro():
    """A onda verde é ISTO: mesmos splits, ciclos começando em instantes
    diferentes. Com splits iguais, o plano de B é o de A deslocado do offset."""
    p = plano_simples(verdes={"A": (12.0, 42.0), "B": (12.0, 42.0)},
                      offsets={"A": 0.0, "B": 15.0})
    for t in (0.0, 5.0, 11.0, 13.5, 33.0, 50.0, 59.0):
        assert p.fase_alvo("B", t + 15.0) == p.fase_alvo("A", t)
    assert p.fase_alvo("B", 15.0) == 0        # o ciclo de B começa em t=15
    assert p.fase_alvo("B", 14.9) == 0        # amarelo que ENTRA no verde 0


def test_fase_alvo_aceita_tempo_negativo_e_gigante():
    """A Arena chama com `t` simulado absoluto, que pode ser qualquer coisa."""
    p = plano_simples()
    assert p.fase_alvo("A", -1.0) == 0        # -1 mod 60 = 59 -> amarelo 1 -> alvo 0
    assert p.fase_alvo("A", 1e6 + 10.0) in (0, 1)


# --------------------------------------------------------------------- realizado
def test_realizado_devolve_o_plano_que_a_grade_de_fato_executa():
    """A Arena só pergunta a cada 5 sim-steps, então o verde alcançável é
    `k·5 − 3` (7, 12, 17, 22, 27...) e nenhum outro valor. Este é o número que
    tem que ser publicado — não o do papel."""
    p = plano_simples(verdes={"A": (12.0, 42.0)}, offsets={"A": 0.0})
    r = p.realizado(5)
    g = r.verdes["A"]
    assert sum(g) + 2 * 3.0 == p.ciclo_s               # o ciclo continua fechando
    for x in g:
        assert abs((x + 3.0) % 5.0) < 1e-9             # verde+amarelo múltiplo da grade
    assert g == (12.0, 42.0)                           # este já estava na grade


def test_verde_fora_da_grade_e_distorcido_FASE_A_FASE():
    """O motivo de `ajusta_a_grade` existir, medido.

    Cada fronteira de fase é arredondada por conta própria, então um plano fora
    da grade não vira "o plano com um errinho": (10, 44) EXECUTA como (7, 47) —
    a fase curta perde 30% do verde que Webster lhe deu, e a longa ganha. Os
    planos congelados são arredondados na origem para isto não acontecer.
    """
    p = plano_simples(verdes={"A": (10.0, 44.0)}, offsets={"A": 0.0})
    assert p.realizado(5).verdes["A"] == (7.0, 47.0)
    # e o plano já na grade executa exatamente como está escrito
    q = plano_simples(verdes={"A": (12.0, 42.0)}, offsets={"A": 0.0})
    assert q.realizado(5).verdes["A"] == (12.0, 42.0)


def test_realizado_recusa_ciclo_fora_da_grade():
    p = plano_simples(ciclo_s=63.0, verdes={"A": (27.0, 30.0)}, offsets={"A": 0.0})
    with pytest.raises(PlanoIncompativel, match="múltiplo da grade"):
        p.realizado(5)


def test_realizado_denuncia_fase_que_a_grade_engole():
    """Uma fase mais curta que a grade pode não receber NENHUM tick — e aí ela
    simplesmente não acontece, em silêncio. `realizado` recusa em vez de
    devolver um plano de 2 fases onde o papel tem 3."""
    p = plano_simples(ciclo_s=30.0, verdes={"A": (2.0, 2.0, 17.0)}, offsets={"A": 0.0})
    with pytest.raises(PlanoIncompativel, match="fases"):
        p.realizado(10)
    # na grade de 1 s as três acontecem
    assert len(p.realizado(1).verdes["A"]) == 3


def test_realizado_na_grade_de_1_e_o_proprio_plano():
    p = plano_simples()
    r = p.realizado(1)
    assert r.verdes == p.verdes
    assert r.offsets == p.offsets


def test_realizado_preserva_a_diferenca_de_offset_quando_ela_esta_na_grade():
    """É isto que sustenta a onda verde: o que a coordenação usa é a DIFERENÇA
    entre offsets, e ela sobrevive à grade quando é múltipla dela."""
    p = plano_simples(verdes={"A": (27.0, 27.0), "B": (27.0, 27.0)},
                      offsets={"A": 0.0, "B": 15.0})
    r = p.realizado(5)
    assert (r.offsets["B"] - r.offsets["A"]) % 60.0 == 15.0


# --------------------------------------------------------------------------- i/o
def test_salva_e_carrega_ida_e_volta(tmp_path):
    p = plano_simples(proveniencia={"gerado_por": "teste", "demanda": {"seed": 7}})
    caminho = p.salva(tmp_path / "p.json")
    q = PlanoFixo.carrega(caminho)
    assert q.como_dict() == p.como_dict()


def test_carrega_de_arquivo_ausente_diz_como_gerar(tmp_path):
    with pytest.raises(FileNotFoundError, match="tune_baseline_plano"):
        PlanoFixo.carrega(tmp_path / "nao_existe.json")


def test_json_e_estavel_byte_a_byte(tmp_path):
    """Determinismo do artefato versionado (DoD (d)): salvar duas vezes o mesmo
    plano tem que dar o mesmo arquivo."""
    p = plano_simples()
    a = p.salva(tmp_path / "a.json").read_bytes()
    b = PlanoFixo.carrega(tmp_path / "a.json").salva(tmp_path / "b.json").read_bytes()
    assert a == b


# --------------------------------------------------------- o timer como plano
def test_plano_uniforme_reproduz_o_timer_de_27_s():
    """`uniforme` é o degrau 0 da varredura: o adversário de hoje escrito como
    plano. Verde 27 + amarelo 3, duas fases -> ciclo de 60, offset 0."""
    p = PlanoFixo.uniforme(["A", "B"], [2, 2], 27.0, 3.0)
    assert p.ciclo_s == 60.0
    assert p.verdes["A"] == (27.0, 27.0)
    assert set(p.offsets.values()) == {0.0}
    # e ele já está na grade de 5: verde alcançável exatamente 27
    assert p.realizado(5).verdes["A"] == (27.0, 27.0)


# ----------------------------------------------- os planos congelados no disco
def _planos_congelados():
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1] / "sumo" / "aberta" / "planos"
    return sorted(raiz.glob("*.json"))


@pytest.mark.parametrize("caminho", _planos_congelados(),
                         ids=lambda p: p.stem)
def test_plano_congelado_e_valido_e_cabe_na_grade(caminho):
    """Todo plano versionado em `sumo/aberta/planos/` tem que (a) fechar o
    ciclo, (b) ser múltiplo da grade de decisão de 5 s, (c) realizar todas as
    fases nessa grade e (d) carregar a proveniência da demanda de projeto."""
    p = PlanoFixo.carrega(caminho)
    assert p.cenario == "aberta.maquete"
    assert p.amarelo_s == 3.0
    assert p.ciclo_s % 5 == 0
    r = p.realizado(5)                      # levanta se alguma fase não couber
    for tls, g in r.verdes.items():
        assert min(g) >= 7.0, "%s: verde realizado abaixo do min_green" % tls
        assert abs(sum(g) + len(g) * 3.0 - p.ciclo_s) < 1e-9
    prov = p.proveniencia
    assert prov["demanda_de_projeto"]["seed"] == 7, "plano calibrado fora da hora de projeto"
    assert len(prov["demanda_de_projeto"]["sha256"]) == 64


def test_a_familia_de_planos_existe_e_cobre_os_tres_degraus():
    nomes = {c.stem for c in _planos_congelados()}
    if not nomes:
        pytest.skip("planos ainda não gerados (scripts/tune_baseline_plano.py)")
    for degrau in ("uniforme", "webster", "coordenado"):
        assert any(n.startswith(degrau + "_c") for n in nomes), degrau
    assert "uniforme_c60" in nomes, "o degrau 0 tem que ser o baseline de hoje"


def test_uniforme_c60_congelado_e_o_baseline_publicado():
    """O elo entre a varredura e o número publicado: `uniforme_c60` tem que ser,
    literalmente, verde 27 s em toda interseção com offset zero."""
    caminhos = [c for c in _planos_congelados() if c.stem == "uniforme_c60"]
    if not caminhos:
        pytest.skip("planos ainda não gerados")
    p = PlanoFixo.carrega(caminhos[0])
    assert p.ciclo_s == 60.0
    assert set(p.offsets.values()) == {0.0}
    for g in p.verdes.values():
        assert g == (27.0, 27.0)


def test_coordenado_tem_offset_e_webster_nao():
    """Os degraus têm que ser separáveis: se `webster_c*` tivesse offset, o
    efeito do split e o da onda verde ficariam somados e nenhum dos dois seria
    reportável sozinho."""
    por_nome = {c.stem: c for c in _planos_congelados()}
    if "webster_c60" not in por_nome:
        pytest.skip("planos ainda não gerados")
    w = PlanoFixo.carrega(por_nome["webster_c60"])
    c = PlanoFixo.carrega(por_nome["coordenado_c60"])
    assert set(w.offsets.values()) == {0.0}
    assert len(set(c.offsets.values())) > 1
    assert w.verdes == c.verdes            # muda o offset, e SÓ o offset


def test_proveniencia_registra_a_ferramenta_externa():
    """A escolha do ponto de operação é justificada por fora do projeto (DoD (c)),
    e o plano tem que dizer de qual ferramenta e de qual demanda ele saiu."""
    por_nome = {c.stem: c for c in _planos_congelados()}
    if "coordenado_c60" not in por_nome:
        pytest.skip("planos ainda não gerados")
    prov = json.loads(por_nome["coordenado_c60"].read_text(encoding="utf-8"))["proveniencia"]
    assert prov["webster"]["ferramenta"] == "tlsCycleAdaptation.py"
    assert prov["offsets"]["ferramenta"] == "tlsCoordinator.py"
    assert prov["restricoes"] == {"decision_interval": 5, "min_green": 7,
                                  "yellow": 3, "max_red": 0.0}
