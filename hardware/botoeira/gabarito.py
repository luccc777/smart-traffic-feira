"""Gabarito do painel 3x4 — derivado da GEOMETRIA DA REDE, não desenhado à mão.

A tese do painel é uma só: **a posição do botão é a posição do cruzamento no
chão**. Se o painel for um teclado numérico bonito, o visitante tem que traduzir
"botão 6" para "aquele cruzamento ali" a cada aperto, e a rodada vira decoreba em
vez de trânsito. Por isso as 13 coordenadas saem de uma conta sobre
`sumo/aberta/build/nodes_aberta.nod.xml`, e não de um desenho:

    x_painel = OFFSET_X + ESCALA * x_sumo
    y_painel = OFFSET_Y + ESCALA * y_sumo

`tests/test_a4_painel.py` refaz essa conta contra o `.nod.xml` de verdade. Se
alguém mexer na rede (mover a V4, abrir um corredor novo), o gabarito fica
vermelho antes de virar furo errado no MDF.

O SVG (`gabarito_painel.svg`) é ARTEFATO: gerado por

    python hardware/botoeira/gabarito.py

Imprima em escala 1:1 (A3 paisagem, "tamanho real" / 100 %, NUNCA "ajustar à
página"), confira a régua de aferição impressa nele, cole no MDF e fure.

POR QUE O PASSO HORIZONTAL É MAIOR QUE O VERTICAL
--------------------------------------------------
Porque a rede é assim. Na similitude, a distância entre corredores verticais é
31,67 e entre horizontais é 20 — razão 1,583. O painel repete a razão
(71,25 mm contra 45 mm). Um painel de passo uniforme seria mais fácil de furar e
mentiria sobre a rede.

E A COLUNA V4 É TORTA DE PROPÓSITO
-----------------------------------
`H1V4` está em x=98,33 e `H2V4`/`H3V4` em x=103,33: na rede aberta a V4 dá um
degrau. No painel isso vira **11,25 mm** de desalinhamento entre o botão 3 e os
botões 7/11. Não é erro de furação — está no `.nod.xml` e o teste cobra.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- a conta
# 45 mm entre linhas é o passo confortável para botão arcade de 30 mm (bezel ~33):
# perto o bastante para ler como grade, longe o bastante para não apertar dois.
ESCALA = 2.25            # mm de painel por unidade de similitude (45 mm / 20)
OFFSET_X = 36.25         # centra o vão de 232,5 mm numa placa de 305 mm
OFFSET_Y = 115.0         # a linha H3 (a de baixo) sobe 115 mm da borda inferior

LARGURA_MM = 305.0
ALTURA_MM = 240.0

# Botão grande, centrado sob a grade. 70 mm abaixo da H3: longe o suficiente para
# ninguém apertar START querendo apertar um semáforo da fila de baixo.
START_XY = (152.5, 45.0)

FURO_SEMAFORO_MM = 28.0  # botão arcade "30 mm" -> furo de 28 (CONFIRMAR na peça)
FURO_START_MM = 44.0     # botão "44 mm" -> furo de 44 (CONFIRMAR na peça)
BEZEL_SEMAFORO_MM = 33.0
BEZEL_START_MM = 50.0

# Ordem canônica dos semáforos: `TLS_IDS = sorted(...)` no `net_topology` do
# maquete. Alfabética = H1V1..H1V4, H2V1..H2V4, H3V1..H3V4 — que por sorte
# (verificada, não suposta) é a ordem de leitura do painel: esquerda->direita,
# de cima para baixo. Índice do botão = índice do semáforo, sem tabela nenhuma.
TLS = ("H1V1", "H1V2", "H1V3", "H1V4",
       "H2V1", "H2V2", "H2V3", "H2V4",
       "H3V1", "H3V2", "H3V3", "H3V4")

# Coordenadas de similitude dos 12 cruzamentos (= nodes_aberta.nod.xml).
NOS_SUMO = {
    "H1V1": (0.0, 40.0), "H1V2": (31.6667, 40.0),
    "H1V3": (63.3333, 40.0), "H1V4": (98.3333, 40.0),
    "H2V1": (0.0, 20.0), "H2V2": (31.6667, 20.0),
    "H2V3": (63.3333, 20.0), "H2V4": (103.333, 20.0),
    "H3V1": (0.0, 0.0), "H3V2": (31.6667, 0.0),
    "H3V3": (63.3333, 0.0), "H3V4": (103.333, 0.0),
}

# GPIO de cada botão. Regra única: **GPIO = índice + 2**; o START mora longe, no
# GP22. Não começa em GP0 porque GP0/GP1 são a UART0 — ver `firmware/botoeira/
# main.py` §pinagem (há build de MicroPython que sobe o REPL nela, e aí o botão
# curto-circuita a TX contra o GND).
GPIO_SEMAFORO = tuple(range(2, 14))
GPIO_START = 22


def furo(tl: str) -> tuple[float, float]:
    """Centro do furo (mm), medido do canto INFERIOR ESQUERDO da placa."""
    x, y = NOS_SUMO[tl]
    return (round(OFFSET_X + ESCALA * x, 2), round(OFFSET_Y + ESCALA * y, 2))


def furos() -> list[tuple[int, str, float, float, float]]:
    """`[(indice, rotulo, x_mm, y_mm, diametro_mm)]`, START por último."""
    saida = [(i, tl, *furo(tl), FURO_SEMAFORO_MM) for i, tl in enumerate(TLS)]
    saida.append((-1, "START", START_XY[0], START_XY[1], FURO_START_MM))
    return saida


def folga_minima_mm() -> float:
    """Menor distância entre bordas de bezel vizinhas. Negativa = bezels colidem."""
    pior = float("inf")
    itens = furos()
    for i, (_ia, _ra, xa, ya, _da) in enumerate(itens):
        ra = BEZEL_START_MM if _ia == -1 else BEZEL_SEMAFORO_MM
        for _ib, _rb, xb, yb, _db in itens[i + 1:]:
            rb = BEZEL_START_MM if _ib == -1 else BEZEL_SEMAFORO_MM
            d = ((xa - xb) ** 2 + (ya - yb) ** 2) ** 0.5
            pior = min(pior, d - (ra + rb) / 2.0)
    return round(pior, 2)


def folga_da_borda_mm() -> float:
    """Menor distância entre a borda de um bezel e a borda da placa."""
    pior = float("inf")
    for indice, _rot, x, y, _d in furos():
        r = (BEZEL_START_MM if indice == -1 else BEZEL_SEMAFORO_MM) / 2.0
        pior = min(pior, x - r, y - r, LARGURA_MM - x - r, ALTURA_MM - y - r)
    return round(pior, 2)


# ------------------------------------------------------------------- SVG
_CSS = """
  .placa  { fill:#fff; stroke:#111; stroke-width:.5 }
  .furo   { fill:none; stroke:#c00; stroke-width:.4 }
  .bezel  { fill:none; stroke:#bbb; stroke-width:.3; stroke-dasharray:3 2 }
  .cruz   { stroke:#c00; stroke-width:.3 }
  .via    { stroke:#9cf; stroke-width:6; stroke-linecap:round; opacity:.55 }
  .arte   { stroke:#69c; stroke-width:10; stroke-linecap:round; opacity:.55 }
  .rot    { font:600 5px sans-serif; fill:#111; text-anchor:middle }
  .idx    { font:700 7px sans-serif; fill:#c00; text-anchor:middle }
  .nota   { font:4px sans-serif; fill:#444 }
  .regua  { stroke:#111; stroke-width:.4; fill:none }
"""


def _svg() -> str:
    L, A = LARGURA_MM, ALTURA_MM
    p = ['<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" '
         'viewBox="0 0 %g %g">' % (L, A, L, A),
         "<style>%s</style>" % _CSS,
         "<!-- GERADO por hardware/botoeira/gabarito.py — NAO EDITAR A MAO. -->",
         '<rect class="placa" x="0" y="0" width="%g" height="%g"/>' % (L, A)]

    # SVG cresce para baixo; a placa é medida de baixo para cima. Converte aqui.
    def sy(y: float) -> float:
        return A - y

    # As vias, para o painel parecer o mapa mesmo antes de ter botão em cima.
    for tl_a, tl_b, classe in [
        ("H1V1", "H1V4", "via"), ("H2V1", "H2V4", "arte"), ("H3V1", "H3V4", "via"),
        ("H1V1", "H3V1", "via"), ("H1V2", "H3V2", "via"),
        ("H1V3", "H3V3", "via"), ("H1V4", "H3V4", "via"),
    ]:
        xa, ya = furo(tl_a)
        xb, yb = furo(tl_b)
        p.append('<line class="%s" x1="%g" y1="%g" x2="%g" y2="%g"/>'
                 % (classe, xa, sy(ya), xb, sy(yb)))

    for indice, rotulo, x, y, d in furos():
        bez = BEZEL_START_MM if indice == -1 else BEZEL_SEMAFORO_MM
        p.append('<circle class="bezel" cx="%g" cy="%g" r="%g"/>' % (x, sy(y), bez / 2))
        p.append('<circle class="furo" cx="%g" cy="%g" r="%g"/>' % (x, sy(y), d / 2))
        p.append('<path class="cruz" d="M%g %gh8M%g %gv8"/>'
                 % (x - 4, sy(y), x, sy(y) - 4))
        p.append('<text class="idx" x="%g" y="%g">%s</text>'
                 % (x, sy(y) - bez / 2 - 2, "START" if indice == -1 else indice))
        p.append('<text class="rot" x="%g" y="%g">%s</text>'
                 % (x, sy(y) + bez / 2 + 6, rotulo))

    # Régua de aferição: se estes 100 mm não medirem 100 mm na régua de verdade,
    # a impressora escalou e o gabarito inteiro está errado.
    p.append('<path class="regua" d="M10 %g h100 M10 %g v-4 M60 %g v-3 M110 %g v-4"/>'
             % (A - 8, A - 8, A - 8, A - 8))
    p.append('<text class="nota" x="10" y="%g">100 mm — meça antes de furar '
             '(imprimir 1:1, sem "ajustar a pagina")</text>' % (A - 12))
    p.append('<text class="nota" x="%g" y="12">BOTOEIRA SmartTraffic — '
             'furo %g mm (semaforos) / %g mm (START) — face vista de FRENTE'
             '</text>' % (10, FURO_SEMAFORO_MM, FURO_START_MM))
    p.append("</svg>")
    return "\n".join(p) + "\n"


def escreve_svg(destino: Path | None = None) -> Path:
    destino = destino or Path(__file__).with_name("gabarito_painel.svg")
    destino.write_text(_svg(), encoding="utf-8")
    return destino


def tabela() -> str:
    linhas = ["| botão | semáforo | GPIO | x (mm) | y (mm) | furo (mm) |",
              "|------:|----------|-----:|-------:|-------:|----------:|"]
    for indice, rotulo, x, y, d in furos():
        gpio = GPIO_START if indice == -1 else GPIO_SEMAFORO[indice]
        linhas.append("| %s | %s | GP%d | %.2f | %.2f | %.0f |"
                      % ("START" if indice == -1 else indice, rotulo, gpio, x, y, d))
    return "\n".join(linhas)


if __name__ == "__main__":
    print(tabela())
    print("\nfolga mínima entre bezels: %.2f mm" % folga_minima_mm())
    print("folga mínima até a borda:  %.2f mm" % folga_da_borda_mm())
    print("SVG: %s" % escreve_svg())
