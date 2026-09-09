"""A7 — DoD (c): contraste >= o piso, para todos os elementos NOVOS.

O piso é o de `smart-traffic-maquete/scripts/projecao/contraste.py` (BOM=1,60,
LIMITE=1,30, e o modelo `E = ambiente + preto_vazado + L·branco`). Este repo não
escreve naquele, então a lógica veio portada para `scripts/projecao_contraste.py` e
o teste guarda três coisas:

  1. o port REPRODUZ o original no ponto de operação dele (a mesa de 1,30 m);
  2. nenhum par crítico reprova no ambiente de aceite;
  3. os elementos NOVOS (o placar) ficam acima de BOM, não só de LIMITE — eles são a
     mensagem, e foram resolvidos a partir da dinâmica disponível, não escolhidos;
  4. a paleta do script NÃO DIVERGE da que o front usa. Duas cópias de uma paleta
     divergem — já divergiram neste projeto — e uma auditoria de uma paleta que não
     está na tela não audita nada.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _carrega(nome: str, caminho: Path):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ct():
    return _carrega("projecao_contraste", RAIZ / "scripts" / "projecao_contraste.py")


# ------------------------------------------------------------------ o port bate
def test_o_port_reproduz_o_ponto_de_operacao_do_maquete(ct):
    """O maquete calcula 316 lux de branco e 2,1 de preto vazado na mesa de 1,30 m.
    Se o port não reproduzir isso, todo o resto está medindo outra coisa."""
    p = ct.ponto("mesa")
    assert p["branco"] == pytest.approx(316.0, abs=1.0)
    assert p["preto"] == pytest.approx(2.1, abs=0.05)


def test_a_montagem_da_feira_e_mais_dura_que_a_do_maquete(ct):
    """Torre de 2 m com TR 1,10 dá uma imagem de 1,82 m: quase o dobro da área da mesa,
    então o branco cai pela metade e TODO contraste percebido piora. Auditar a paleta
    nova no ponto de operação do maquete seria auditar outra coisa."""
    mesa, chao = ct.ponto("mesa"), ct.ponto("chao")
    assert chao["area_m2"] > 1.9 * mesa["area_m2"]
    assert chao["branco"] < 0.55 * mesa["branco"]


# --------------------------------------------------------------- a auditoria
@pytest.mark.parametrize("montagem", ["chao", "mesa"])
def test_nenhum_par_reprova_no_ambiente_de_aceite(ct, montagem):
    piores, linhas = ct.auditar(ct.ponto(montagem), [25.0], amb_aceite=25.0,
                                mostrar=False)
    ruins = [ln["par"] for ln in linhas if ln["reprova"]]
    assert piores == 0, "abaixo do piso em %s: %s" % (montagem, ruins)


def test_os_elementos_novos_ficam_acima_de_BOM_no_chao(ct):
    """LIMITE (1,30) é "dá para ler com esforço". O placar é a mensagem: ele tem que
    ficar em BOM (1,60). Isto é o que a paleta resolvida por degrau geométrico entrega,
    e é o que cai no instante em que alguém trocar uma cor "porque ficou melhor"."""
    _, linhas = ct.auditar(ct.ponto("chao"), [25.0], amb_aceite=25.0, mostrar=False)
    fracos = [(ln["par"], ln["aceite"]) for ln in linhas
              if ln["novo"] and not ln["assumido"] and ln["aceite"] < ct.BOM]
    assert not fracos, "elementos novos abaixo de BOM=%.2f: %s" % (ct.BOM, fracos)


def test_teto_de_ambiente_e_um_numero_operacional(ct):
    """Acima do teto não é problema de cor, é problema de luz na sala — e o operador
    precisa saber o número."""
    teto = ct.teto_ambiente(ct.ponto("chao"), so_novos=True)
    assert 30.0 < teto < 200.0
    assert ct.teto_ambiente(ct.ponto("mesa"), so_novos=True) > teto


def test_a_juncao_foi_reajustada_para_o_ponto_de_operacao_do_chao(ct):
    """O `#637183` herdado media 1,26 contra a via na imagem de 1,82 m — abaixo do
    piso, só por causa do ponto de operação. Foi re-resolvido; se voltar, este teste
    cai."""
    c = ct.parede(ct.lum(ct.JUNCAO), ct.lum(ct.VIA), 25.0,
                  branco=ct.ponto("chao")["branco"], preto=ct.ponto("chao")["preto"])
    assert c >= ct.LIMITE, "junção sobre a via em %.2f no chão" % c


# ------------------------------------------------- a paleta não pode divergir
def _cores_do_css() -> dict[str, str]:
    css = (RAIZ / "web" / "css" / "projecao.css").read_text(encoding="utf-8")
    return {m.group(1): m.group(2).lower()
            for m in re.finditer(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", css)}


def test_a_paleta_do_script_e_a_do_css(ct):
    css = _cores_do_css()
    pares = {
        "trilho": ct.TRILHO, "bar-timer": ct.BAR_TIMER, "bar-rl": ct.BAR_RL,
        "bar-humano": ct.BAR_HUMANO, "grade": ct.GRADE,
        "regua-flanco": ct.REGUA_FLANCO, "regua-nucleo": ct.REGUA_NUCLEO,
        "texto": ct.TEXTO, "texto-2": ct.TEXTO_2, "texto-3": ct.TEXTO_3,
        "vencedor": ct.VENCEDOR, "alerta": ct.ALERTA, "fundo": ct.FUNDO,
    }
    for var, esperado in pares.items():
        assert var in css, "--%s sumiu de web/css/projecao.css" % var
        assert css[var] == esperado.lower(), (
            "--%s: css=%s script=%s — a auditoria estaria medindo outra paleta"
            % (var, css[var], esperado))


def test_a_paleta_do_mapa_e_a_do_paint_js(ct):
    js = (RAIZ / "web" / "js" / "paint.js").read_text(encoding="utf-8")
    achados = dict(re.findall(r"(\w+):\s*'(#[0-9a-fA-F]{6})'", js))
    for chave, esperado in [("road", ct.VIA), ("junction", ct.JUNCAO),
                            ("green", ct.FAROL_V), ("yellow", ct.FAROL_A),
                            ("red", ct.FAROL_R), ("carFree", ct.CARRO_LIVRE),
                            ("carSlow", ct.CARRO_LENTO), ("carStop", ct.CARRO_PARADO)]:
        assert achados.get(chave, "").lower() == esperado.lower(), (
            "COL.%s: paint.js=%s script=%s" % (chave, achados.get(chave), esperado))
