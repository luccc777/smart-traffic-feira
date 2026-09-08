"""A4 — o painel 3×4 é o mapa da rede, e isso é uma conta conferível.

A tese do painel: **posição do botão = posição do cruzamento no chão**. Sem isso
o visitante traduz "botão 6" para "aquele cruzamento ali" a cada aperto, e a
rodada vira decoreba. A tese só vale se a geometria do painel for a da rede — e é
isso que este arquivo cobra, contra o `.nod.xml` de verdade, sem SUMO instalado
(é só XML).

Se alguém mexer na rede aberta (mover a V4, abrir um corredor), aqui fica
vermelho — antes de virar furo errado no MDF.
"""
from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
NODES = RAIZ / "sumo" / "aberta" / "build" / "nodes_aberta.nod.xml"


def _carrega_gabarito():
    caminho = RAIZ / "hardware" / "botoeira" / "gabarito.py"
    spec = importlib.util.spec_from_file_location("botoeira_gabarito", caminho)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _carrega_gabarito()


@pytest.fixture(scope="module")
def nos_da_rede():
    if not NODES.exists():
        pytest.skip("rede aberta ainda não construída: %s" % NODES)
    return {n.get("id"): (float(n.get("x")), float(n.get("y")))
            for n in ET.parse(NODES).getroot().findall("node")
            if n.get("type") == "traffic_light"}


def test_sao_12_semaforos_e_sao_os_do_gabarito(nos_da_rede):
    """12 botões, não 6: a rede aberta tem os 12 TLs controláveis (gate da Onda 1)."""
    assert len(nos_da_rede) == 12
    assert set(nos_da_rede) == set(G.TLS)


def test_a_ordem_dos_botoes_e_a_ordem_canonica_dos_tls():
    """`TLS_IDS = sorted(...)` no `net_topology`. O índice do botão TEM que ser o
    índice do semáforo, senão o painel acende o cruzamento vizinho."""
    assert list(G.TLS) == sorted(G.TLS)


def test_a_ordem_alfabetica_e_a_ordem_de_leitura_do_painel():
    """Coincidência verificada, não suposta: alfabético (H1V1..H3V4) percorre o
    painel da esquerda para a direita, de cima para baixo. É o que dispensa a
    tabela de tradução entre índice do contrato e posição no painel."""
    pos = [G.furo(tl) for tl in G.TLS]
    for (xa, ya), (xb, yb) in zip(pos, pos[1:]):
        assert (-yb, xb) > (-ya, xa), "quebra da ordem de leitura em %r" % ((xa, ya),)


def test_cada_furo_e_a_projecao_afim_do_no_do_sumo(nos_da_rede):
    """A conta inteira: x_painel = OFFSET_X + ESCALA * x_sumo (idem y)."""
    for i, tl in enumerate(G.TLS):
        xs, ys = nos_da_rede[tl]
        esperado = (round(G.OFFSET_X + G.ESCALA * xs, 2),
                    round(G.OFFSET_Y + G.ESCALA * ys, 2))
        assert G.furo(tl) == pytest.approx(esperado, abs=0.01), \
            "botão %d (%s) fora do mapa" % (i, tl)


def test_a_razao_dos_passos_e_a_da_rede(nos_da_rede):
    """Passo horizontal / passo vertical = 71,25/45 = 1,583 = 31,667/20.

    Um painel de passo uniforme seria mais fácil de furar e mentiria sobre a rede.
    """
    passo_col = G.furo("H1V2")[0] - G.furo("H1V1")[0]
    passo_lin = G.furo("H1V1")[1] - G.furo("H2V1")[1]
    dx = nos_da_rede["H1V2"][0] - nos_da_rede["H1V1"][0]
    dy = nos_da_rede["H1V1"][1] - nos_da_rede["H2V1"][1]
    assert passo_col / passo_lin == pytest.approx(dx / dy, rel=1e-3)
    assert passo_lin == pytest.approx(45.0)


def test_o_degrau_da_v4_esta_reproduzido(nos_da_rede):
    """`H1V4` em x=98,33 e `H2V4`/`H3V4` em x=103,33: a V4 dá um degrau na rede.

    No painel são 11,25 mm de desalinhamento. NÃO é erro de furação — se alguém
    "endireitar" a coluna, este teste denuncia.
    """
    degrau_sumo = nos_da_rede["H2V4"][0] - nos_da_rede["H1V4"][0]
    degrau_painel = G.furo("H2V4")[0] - G.furo("H1V4")[0]
    assert degrau_sumo > 0
    assert degrau_painel == pytest.approx(degrau_sumo * G.ESCALA, abs=0.01)
    assert degrau_painel == pytest.approx(11.25, abs=0.01)


def test_a_arterial_h2_e_a_linha_do_meio(nos_da_rede):
    """A H2 (3 faixas, o corredor que o baseline coordenado vai priorizar) tem que
    ser a fila do MEIO do painel — é a que o visitante mais vai querer mexer."""
    ys = {tl: G.furo(tl)[1] for tl in G.TLS}
    h1 = {ys[t] for t in G.TLS if t.startswith("H1")}
    h2 = {ys[t] for t in G.TLS if t.startswith("H2")}
    h3 = {ys[t] for t in G.TLS if t.startswith("H3")}
    assert len(h1) == len(h2) == len(h3) == 1
    assert h1.pop() > h2.pop() > h3.pop()        # H1 ao norte = em cima


# ------------------------------------------------------- ergonomia e fabricação


def test_os_bezels_nao_se_tocam():
    """Botão arcade de 30 mm tem bezel de ~33 mm. Bezel encostando = painel que não
    fecha e botão que não trava."""
    folga = G.folga_minima_mm()
    assert folga > 5.0, "folga de %.2f mm entre bezels vizinhos" % folga


def test_ha_borda_para_a_porca_e_para_a_moldura():
    """Furo perto demais da borda = MDF rachando na hora de apertar a porca."""
    assert G.folga_da_borda_mm() > 15.0


def test_o_passo_e_mais_generoso_que_o_padrao_de_arcade():
    """45 mm entre linhas contra os 36 mm de um painel de arcade comercial (Sega
    2P). Se um dia encolher abaixo de 36, o dedo passa a apertar dois."""
    passo_lin = G.furo("H1V1")[1] - G.furo("H2V1")[1]
    assert passo_lin >= 36.0


def test_start_e_separado_e_centrado():
    """O botão de começar/abortar não pode ser confundível com um semáforo: fica
    fora da grade, centrado, e é maior."""
    xs, ys = G.START_XY
    assert xs == pytest.approx(G.LARGURA_MM / 2)
    mais_baixo = min(G.furo(tl)[1] for tl in G.TLS)
    assert mais_baixo - ys >= 60.0
    assert G.FURO_START_MM > G.FURO_SEMAFORO_MM


def test_gpios_sao_13_distintos_e_nao_pisam_em_nada():
    from feira.entrada_serial import N_BOTOES_PADRAO

    gpios = [*G.GPIO_SEMAFORO, G.GPIO_START]
    assert len(gpios) == 13 and len(set(gpios)) == 13
    assert len(G.GPIO_SEMAFORO) == N_BOTOES_PADRAO
    assert G.GPIO_SEMAFORO == tuple(i + 2 for i in range(12)), "a regra é GPIO = índice + 2"
    # Os pinos do painel (SPI0 + latch + /OE) não podem colidir com botão nenhum.
    assert set(gpios).isdisjoint({18, 19, 20, 21})
    # GP0/GP1 = UART0 (há build que sobe o REPL nela: botão ali é curto na TX).
    # GP23/24/25/29 são internos do Pico (SMPS, VBUS sense, LED, VSYS sense).
    assert set(gpios).isdisjoint({0, 1, 23, 24, 25, 29})


def test_o_svg_esta_gerado_e_bate_com_a_conta():
    """O `.svg` é ARTEFATO do `gabarito.py`. Se alguém editar o SVG à mão, ele
    deixa de ser o gabarito e vira um desenho — e o furo sai errado."""
    svg = RAIZ / "hardware" / "botoeira" / "gabarito_painel.svg"
    assert svg.exists(), "rode: python hardware/botoeira/gabarito.py"
    raiz = ET.parse(svg).getroot()
    assert raiz.get("width") == "%gmm" % G.LARGURA_MM
    assert raiz.get("height") == "%gmm" % G.ALTURA_MM

    ns = "{http://www.w3.org/2000/svg}"
    furos = {(round(float(c.get("cx")), 2), round(float(c.get("cy")), 2))
             for c in raiz.iter(ns + "circle") if c.get("class") == "furo"}
    assert len(furos) == 13
    for _i, _rot, x, y, _d in G.furos():
        assert (x, round(G.ALTURA_MM - y, 2)) in furos    # o SVG cresce para baixo
