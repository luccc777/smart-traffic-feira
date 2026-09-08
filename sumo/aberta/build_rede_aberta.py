#!/usr/bin/env python3
"""Gera o cenario `aberta.maquete`: a rede da maquete em SIMILITUDE COMPLETA e com
as BORDAS ABERTAS (cotos de origem/sorvedouro no fim de cada corredor de mao unica).

Este script e a UNICA fonte da rede aberta. Os `.xml` de saida sao artefatos --
nunca editados a mao. As fontes canonicas em ESCALA REAL vivem no repo do maquete
(`smart-traffic-maquete/sumo/small_network/network/*.xml`) e NAO sao tocadas aqui:
sao lidas, transformadas e escritas noutro lugar.

AS DUAS TRANSFORMACOES
======================

1) SIMILITUDE COMPLETA (x'=x/K, v'=v/K, a'=a/K, t'=t), K=6
--------------------------------------------------------
Herdada de `make_maquete_similitude.py` (maquete). A rede `maquete` de hoje NAO e
uma miniatura: os comprimentos estao 1/6 mas velocidades e carro ficaram em escala
real -- quarteirao de 28 m atravessado em 2,5 s. Sob similitude as trajetorias
voltam a ser as do cenario `real` a menos do fator espacial: travessia de 15,2 s,
~32 carros por faixa em jam, capacidade ~1453. E o que faz o ganho da RL vir da
POLITICA e nao do quarteirao curto.

Aqui a similitude e aplicada ANTES do netconvert (nos `<type>`), e nao como
pos-processamento do `.net.xml`. Isso obriga um cuidado que o script do maquete
resolvia de outro jeito: a velocidade das faixas INTERNAS de juncao o netconvert
calcula por `v = sqrt(a_lat * r)` com `a_lat` FIXO em 5,5 m/s2. Sob similitude
`r' = r/K`, entao `v'` sairia `sqrt(5.5*r/K) = v/sqrt(K)` -- 2,45x rapido demais.
Por isso passamos `--junctions.limit-turn-speed 5.5/K`: ai
`v' = sqrt((5.5/K)*(r/K)) = sqrt(5.5*r)/K = v/K`, que e a imagem exata da
similitude. (Aceleracao lateral e uma aceleracao: escala por 1/K, como accel e
decel do vType.)

2) BORDAS ABERTAS
-----------------
`ret_N`/`ret_S` (os arcos de retorno) somem, e com eles o U-turn interno dos
cantos que `scale_to_maquete.py` tinha criado -- era ele que des-semaforizava
H1V4/H3V4 e derrubava o numero de semaforos de 12 para 10. Sem o retorno, os dois
cantos voltam a ser `traffic_light` (como no arquivo canonico) e ganham duas
aproximacoes cada.

No lugar dos retornos entram COTOS de borda: um edge de entrada no inicio e um de
saida no fim de cada corredor de mao unica. Sao 9 corredores de mao unica
(H1, H2E, H2W, H3, V1, V2, V3, V4S, V4N) => **9 fontes e 9 sorvedouros**.

Efeito colateral desejado (e o item (b) do DoD do agente A1): as quatro juncoes
que tinham UMA aproximacao so -- H1V1, H1V3, H3V1, H3V2, terminos de corredor na
rede fechada -- ganham a segunda aproximacao pelo coto, logo passam a ter 2 fases
verdes. Resultado esperado: **12 semaforos, 12 controlaveis** (contra 10/6 hoje).

CONVENCAO DE NOMES (nao e cosmetica)
------------------------------------
`sim.environment.net_topology._classify_prefix` classifica as aproximacoes N/S/E/W
pelo PREFIXO do edge (`H2E_`/`H3_` -> E, `H2W_`/`H1_` -> W, `V*_` -> N/S pela
coordenada y da origem). Os cotos herdam o prefixo do corredor a que pertencem
justamente para cair nos mesmos baldes -- se nao caissem, o estado da politica
ficaria CEGO nas aproximacoes de borda (e o `net_topology` imprimiria o aviso de
`_UNCLASSIFIED`).

PROIBICOES DE CONVERSAO
-----------------------
Sao exatamente as 7 do arquivo canonico (`<delete>`: conversoes a esquerda
entrando/saindo da H2). NAO inventamos proibicoes novas para os cotos: a rede ja e
toda de mao unica e restringir mais estreitaria a escolha de rota, que e o risco 3
do plano. As `<connection>` explicitas do canonico sao DESCARTADAS -- todas
tratavam do retorno dos cantos, e uma `<connection>` explicita substitui TODO o
conjunto de saidas daquele edge (na rede aberta isso mataria o movimento direto
para o coto de saida).

Uso:
    python build_rede_aberta.py            # K=6, coto de 150 m (escala real)
    python build_rede_aberta.py --k 6 --coto 150
    python build_rede_aberta.py --verifica # so confere o que ja esta em disco
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

AQUI = Path(__file__).resolve().parent                 # .../sumo/aberta
_RAIZ = AQUI.parents[1]                                # .../smart-traffic-feira
_FONTES = (_RAIZ.parent / "smart-traffic-maquete" / "sumo" / "small_network"
           / "network")

SRC_NODES = _FONTES / "nodes_loop.nod.xml"
SRC_EDGES = _FONTES / "edges_loop.edg.xml"
SRC_TYPES = _FONTES / "types.typ.xml"
SRC_CONNS = _FONTES / "connections_loop.con.xml"

BUILD = AQUI / "build"
OUT_NET = AQUI / "network" / "maquete_aberta.net.xml"
OUT_CFG = AQUI / "config" / "maquete_aberta.sumocfg"
OUT_ADD = AQUI / "demanda" / "maquete_aberta.add.xml"
OUT_VIEW = AQUI / "config" / "maquete_aberta.view.xml"

VERSAO = "aberta.maquete/1.0"

# --- parametros geometricos (todos em ESCALA REAL; o K escala na saida) --------
K = 6.0                  # fator de similitude: x'=x/K, v'=v/K, a'=a/K
COTO_M = 150.0           # comprimento do coto de borda, em metros de escala real
REAL_LANE_W = 3.2        # largura default de faixa do SUMO na rede real
A_LAT_PADRAO = 5.5       # netconvert --junctions.limit-turn-speed default (m/s2)
YELLOW_S = 3             # = sim.environment.constants.YELLOW_DUR

# vType em escala real (= demand/maquete.add.xml do maquete). Tudo escala por 1/K,
# inclusive o carro -- e o que diferencia a similitude da rede so comprimida.
VTYPE_REAL = {"length": 3.5, "width": 1.4, "minGap": 1.75, "accel": 2.6, "decel": 4.5}

# Nos auxiliares do retorno fechado -- somem na rede aberta.
RET_NODES = {"RET_S", "RET_N"}

# --- os 9 corredores de mao unica e onde ficam os seus cotos -------------------
# (prefixo, no_de_entrada, coord do no de borda da ENTRADA, shape extra da entrada,
#           no_de_saida,   coord do no de borda da SAIDA,   shape extra da saida,
#           tipo do edge)
# Coordenadas em ESCALA REAL. `None` de shape = reta simples no-a-no.
_D = COTO_M
CORREDORES = [
    # id      tipo                    entra em  no borda entrada        sai de    no borda saida
    ("H1",   "secondary_2lanes",     "H1V4", ("B_H1_E", 590 + _D, 240),
                                     "H1V1", ("B_H1_W", 0 - _D, 240)),
    ("H2E",  "highway_3lanes",       "H2V1", ("B_H2_W", 0 - _D, 120),
                                     "H2V4", ("B_H2_E", 620 + _D, 120)),
    ("H2W",  "highway_3lanes",       "H2V4", ("B_H2_E", 620 + _D, 120),
                                     "H2V1", ("B_H2_W", 0 - _D, 120)),
    ("H3",   "secondary_2lanes",     "H3V1", ("B_H3_W", 0 - _D, 0),
                                     "H3V4", ("B_H3_E", 620 + _D, 0)),
    ("V1",   "secondary_2lanes",     "H1V1", ("B_V1_N", 0, 240 + _D),
                                     "H3V1", ("B_V1_S", 0, 0 - _D)),
    ("V2",   "secondary_2lanes",     "H3V2", ("B_V2_S", 190, 0 - _D),
                                     "H1V2", ("B_V2_N", 190, 240 + _D)),
    ("V3",   "secondary_2lanes",     "H1V3", ("B_V3_N", 380, 240 + _D),
                                     "H3V3", ("B_V3_S", 380, 0 - _D)),
    ("V4S",  "secondary_2lanes",     "H1V4", ("B_V4_N", 590, 240 + _D),
                                     "H3V4", ("B_V4_S", 620, 0 - _D)),
    ("V4N",  "secondary_2lanes",     "H3V4", ("B_V4_S", 620, 0 - _D),
                                     "H1V4", ("B_V4_N", 590, 240 + _D)),
]

# Offsets do eixo da H2 (canteiro de 5 m): a pista leste corre em y=112.7 e a
# oeste em y=127.3, exatamente como no arquivo canonico. Os cotos herdam isso.
H2_Y = {"H2E": 112.7, "H2W": 127.3}
H2_X = {"H2V1": 0.0, "H2V4": 620.0}


def g(v: float) -> str:
    """Formata coordenada/medida do jeito que `scale_to_maquete.py` formata."""
    return "%g" % round(v, 4)


def _ids_cotos() -> tuple[list[str], list[str]]:
    """(edges de ENTRADA, edges de SAIDA) na ordem de CORREDORES."""
    entradas, saidas = [], []
    for pref, _tipo, tl_in, (nb_in, _xi, _yi), tl_out, (nb_out, _xo, _yo) in CORREDORES:
        entradas.append("%s_%s_%s" % (pref, nb_in, tl_in))
        saidas.append("%s_%s_%s" % (pref, tl_out, nb_out))
    return entradas, saidas


EDGES_FONTE, EDGES_SORVEDOURO = _ids_cotos()


# ---------------------------------------------------------------------- nodes
def gera_nodes(k: float) -> str:
    root = ET.parse(SRC_NODES).getroot()
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<!-- GERADO por build_rede_aberta.py (%s) - NAO EDITAR A MAO.' % VERSAO,
              '     Similitude 1/%g sobre nodes_loop.nod.xml; RET_* removidos; 14 nos'
              % k,
              '     de borda acrescentados (os 9 cotos de entrada + 9 de saida). -->',
              '<nodes>']
    for n in root.findall("node"):
        nid = n.get("id")
        if nid in RET_NODES:
            continue
        x = float(n.get("x")) / k
        y = float(n.get("y")) / k
        # Os 12 cruzamentos ficam TODOS semaforizados: sem o arco de retorno, os
        # cantos H1V4/H3V4 nao precisam mais ser juncao de prioridade.
        linhas.append('    <node id="%s" x="%s" y="%s" type="%s"/>'
                      % (nid, g(x), g(y), n.get("type")))

    vistos: dict[str, tuple[float, float]] = {}
    for _pref, _tipo, _tin, borda_in, _tout, borda_out in CORREDORES:
        for nb, x, y in (borda_in, borda_out):
            if nb in vistos:
                if vistos[nb] != (x, y):
                    raise ValueError("no de borda %s com duas coordenadas" % nb)
                continue
            vistos[nb] = (x, y)
    linhas.append("    <!-- cotos de borda: fonte e/ou sorvedouro -->")
    for nb in sorted(vistos):
        x, y = vistos[nb]
        linhas.append('    <node id="%s" x="%s" y="%s" type="priority"/>'
                      % (nb, g(x / k), g(y / k)))
    linhas.append("</nodes>")
    return "\n".join(linhas) + "\n"


# ---------------------------------------------------------------------- edges
def _escala_shape(shape: str, k: float) -> str:
    pts = []
    for par in shape.split():
        x, y = (float(v) for v in par.split(","))
        pts.append("%s,%s" % (g(x / k), g(y / k)))
    return " ".join(pts)


def gera_edges(k: float) -> str:
    root = ET.parse(SRC_EDGES).getroot()
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<!-- GERADO por build_rede_aberta.py (%s) - NAO EDITAR A MAO.' % VERSAO,
              '     Similitude 1/%g; arcos ret_* removidos; 9 cotos de entrada e 9 de'
              % k,
              '     saida acrescentados (um par por corredor de mao unica). -->',
              '<edges>']
    for e in root.findall("edge"):
        if e.get("id").startswith("ret_"):
            continue
        attrs = 'id="%s" from="%s" to="%s" type="%s"' % (
            e.get("id"), e.get("from"), e.get("to"), e.get("type"))
        if e.get("shape"):
            attrs += ' shape="%s"' % _escala_shape(e.get("shape"), k)
        linhas.append("    <edge %s/>" % attrs)

    linhas.append("    <!-- ENTRADAS (fontes): 1 por corredor de mao unica -->")
    for pref, tipo, tl_in, (nb_in, xi, yi), _tl_out, _b in CORREDORES:
        eid = "%s_%s_%s" % (pref, nb_in, tl_in)
        attrs = 'id="%s" from="%s" to="%s" type="%s"' % (eid, nb_in, tl_in, tipo)
        if pref in H2_Y:                        # mantem o canteiro da avenida
            y = H2_Y[pref]
            attrs += ' shape="%s,%s %s,%s"' % (g(xi / k), g(y / k),
                                               g(H2_X[tl_in] / k), g(y / k))
        linhas.append("    <edge %s/>" % attrs)

    linhas.append("    <!-- SAIDAS (sorvedouros): 1 por corredor de mao unica -->")
    for pref, tipo, _tl_in, _b, tl_out, (nb_out, xo, yo) in CORREDORES:
        eid = "%s_%s_%s" % (pref, tl_out, nb_out)
        attrs = 'id="%s" from="%s" to="%s" type="%s"' % (eid, tl_out, nb_out, tipo)
        if pref in H2_Y:
            y = H2_Y[pref]
            attrs += ' shape="%s,%s %s,%s"' % (g(H2_X[tl_out] / k), g(y / k),
                                               g(xo / k), g(y / k))
        linhas.append("    <edge %s/>" % attrs)
    linhas.append("</edges>")
    return "\n".join(linhas) + "\n"


# ---------------------------------------------------------------------- types
def gera_types(k: float) -> str:
    """Velocidade E largura escalam por 1/K. `retorno_1lane` some junto com o arco."""
    root = ET.parse(SRC_TYPES).getroot()
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<!-- GERADO por build_rede_aberta.py (%s) - NAO EDITAR A MAO.' % VERSAO,
              '     v e largura escalados por 1/%g (similitude completa). -->' % k,
              '<types>']
    for t in root.findall("type"):
        if t.get("id") == "retorno_1lane":
            continue                            # nao ha mais retorno
        partes = ['id="%s"' % t.get("id")]
        if t.get("priority") is not None:
            partes.append('priority="%s"' % t.get("priority"))
        if t.get("numLanes") is not None:
            partes.append('numLanes="%s"' % t.get("numLanes"))
        if t.get("speed") is not None:
            partes.append('speed="%s"' % ("%.4f" % (float(t.get("speed")) / k)))
        w = (float(t.get("width")) if t.get("width") else REAL_LANE_W) / k
        partes.append('width="%s"' % g(w))
        linhas.append("    <type %s/>" % " ".join(partes))
    linhas.append("</types>")
    return "\n".join(linhas) + "\n"


# ----------------------------------------------------------------- connections
def gera_conns() -> str:
    """So os `<delete>` canonicos. Ver o cabecalho: as `<connection>` explicitas do
    arquivo canonico eram todas do retorno, e mante-las mataria o movimento direto
    para o coto de saida (uma `<connection>` explicita substitui TODAS as saidas
    daquele edge)."""
    root = ET.parse(SRC_CONNS).getroot()
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<!-- GERADO por build_rede_aberta.py (%s) - NAO EDITAR A MAO.' % VERSAO,
              '     Exatamente as 7 proibicoes de conversao a esquerda do arquivo',
              '     canonico. Nenhuma proibicao nova foi inventada para os cotos. -->',
              '<connections>']
    n = 0
    for el in root:
        if el.tag != "delete":
            continue
        refs = (el.get("from") or "") + " " + (el.get("to") or "")
        if "ret_" in refs:
            continue
        linhas.append('    <delete from="%s" to="%s"/>' % (el.get("from"), el.get("to")))
        n += 1
    linhas.append("</connections>")
    if n != 7:
        raise ValueError("esperava 7 <delete> canonicos, achei %d" % n)
    return "\n".join(linhas) + "\n"


# ------------------------------------------------------------------- add/view
def gera_add(k: float) -> str:
    v = {campo: valor / k for campo, valor in VTYPE_REAL.items()}
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!-- GERADO por build_rede_aberta.py (%s) - NAO EDITAR A MAO.\n'
        '     vType em SIMILITUDE: tudo escala por 1/%g junto com a rede (ao\n'
        '     contrario da `maquete`, onde o carro era hardware fixo de 6x4 cm).\n'
        '     Com isso a faixa volta a armazenar ~32 carros, que e a capacidade do\n'
        '     cenario `real`: o regime em que a politica foi treinada.\n'
        '     `sigma` e adimensional e NAO escala. -->\n'
        '<additional xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        '            xsi:noNamespaceSchemaLocation='
        '"http://sumo.dlr.de/xsd/additional_file.xsd">\n'
        '    <vType id="DEFAULT_VEHTYPE" length="%.3f" width="%.3f" minGap="%.3f"\n'
        '           accel="%.3f" decel="%.3f" sigma="0.5" color="1,0.85,0"/>\n'
        '</additional>\n'
        % (VERSAO, k, v["length"], v["width"], v["minGap"], v["accel"], v["decel"])
    )


def gera_view() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!-- GERADO por build_rede_aberta.py (%s) - NAO EDITAR A MAO.\n'
        '     Sob similitude o carro tem 0,58 m: no tamanho fisico ele some na tela.\n'
        '     `vehicle_exaggeration` e SO desenho: a pegada real do SUMO continua\n'
        '     por baixo (ver PLANO.md, risco 6). O fator definitivo da projecao e\n'
        '     decisao do agente A7; aqui fica um valor legivel para inspecao no GUI. -->\n'
        '<viewsettings>\n'
        '    <scheme name="aberta">\n'
        '        <edges widthExaggeration="2.00" laneShowBorders="1"\n'
        '               showLinkDecals="1" showLinkRules="1"/>\n'
        '        <vehicles vehicleQuality="2" vehicle_minSize="1.00"\n'
        '                  vehicle_exaggeration="4.00" vehicle_constantSize="0"\n'
        '                  showBlinker="1"/>\n'
        '    </scheme>\n'
        '    <delay value="60"/>\n'
        '</viewsettings>\n' % VERSAO
    )


def gera_sumocfg(reroute_period: int = 60) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!-- GERADO por build_rede_aberta.py (%s) - NAO EDITAR A MAO.\n'
        '\n'
        '     Config do cenario `aberta.maquete`: rede da maquete em similitude\n'
        '     completa, bordas abertas (9 fontes / 9 sorvedouros), 12 semaforos.\n'
        '\n'
        '     SEM <route-files>: a demanda e um .rou.xml POR SEED, gerado por\n'
        '     `feira.demanda.GeradorDemandaAberta`. Quem sobe a simulacao passa\n'
        '     `-r <arquivo>` (a opcao route-files). Rodar so com -c da rede vazia,\n'
        '     de proposito: nao ha demanda "default" que alguem possa medir sem\n'
        '     perceber qual seed estava rodando.\n'
        '\n'
        '     SEM <end>: a janela e do chamador (a Arena / o TrafficEnv).\n'
        '\n'
        '     device.rerouting: SEM ele o carro segue a rota de fluxo livre\n'
        '     calculada uma vez e nunca desvia, nem com a via parada: na Vila\n'
        '     Olimpia a malha travava em 98%% parados a qualquer densidade >=400.\n'
        '     Os parametros sao os MEDIDOS la (period=%d, adaptation 10/18) e\n'
        '     espelham `Cenario.reroute_period`. -->\n'
        '<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        '               xsi:noNamespaceSchemaLocation='
        '"http://sumo.dlr.de/xsd/sumoConfiguration.xsd">\n'
        '\n'
        '    <input>\n'
        '        <net-file value="../network/maquete_aberta.net.xml"/>\n'
        '        <additional-files value="../demanda/maquete_aberta.add.xml"/>\n'
        '    </input>\n'
        '\n'
        '    <time>\n'
        '        <begin value="0"/>\n'
        '        <step-length value="1.0"/>\n'
        '    </time>\n'
        '\n'
        '    <processing>\n'
        '        <time-to-teleport value="-1"/>\n'
        '    </processing>\n'
        '\n'
        '    <routing>\n'
        '        <device.rerouting.probability value="1"/>\n'
        '        <device.rerouting.period value="%d"/>\n'
        '        <device.rerouting.adaptation-interval value="10"/>\n'
        '        <device.rerouting.adaptation-steps value="18"/>\n'
        '        <weights.random-factor value="2.0"/>\n'
        '    </routing>\n'
        '\n'
        '    <report>\n'
        '        <no-step-log value="true"/>\n'
        '        <duration-log.statistics value="true"/>\n'
        '    </report>\n'
        '\n'
        '</configuration>\n' % (VERSAO, reroute_period, reroute_period)
    )


# ------------------------------------------------------------------ netconvert
def roda_netconvert(k: float, quieto: bool = False) -> tuple[int, str]:
    sumo_home = os.environ.get("SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo")
    netconvert = str(Path(sumo_home) / "bin" / "netconvert")
    cmd = [
        netconvert,
        "-n", str(BUILD / "nodes_aberta.nod.xml"),
        "-e", str(BUILD / "edges_aberta.edg.xml"),
        "-x", str(BUILD / "connections_aberta.con.xml"),
        "-t", str(BUILD / "types_aberta.typ.xml"),
        "-o", str(OUT_NET),
        # U-turn so onde for explicito -- e nao ha nenhum explicito na rede aberta.
        "--no-turnarounds", "true",
        "--junctions.corner-detail", "5",
        # Defaults do netconvert sao absolutos em METROS: escalam junto.
        "--default.junctions.radius", g(4.0 / k),
        "--junctions.small-radius", g(1.5 / k),
        # a_lat tambem escala (ver cabecalho): sem isto as faixas internas ficam
        # sqrt(K)=2,45x rapidas demais e a similitude quebra dentro das juncoes.
        "--junctions.limit-turn-speed", "%.6f" % (A_LAT_PADRAO / k),
        # Ninguem espera NO MEIO do cruzamento: quem precisa ceder espera ANTES de
        # entrar. Herdado do requisito fisico da maquete -- e, de quebra, e a
        # defesa mais barata contra travamento dentro da juncao (risco 2).
        "--internal-junctions.vehicle-width", "0",
        # Programas atuados como default do netconvert; RL/timer/humano substituem
        # via TraCI. O amarelo fica no YELLOW_DUR do projeto (3 s) -- o netconvert
        # o derivaria da velocidade, e sob similitude sairia 6x menor.
        "--tls.default-type", "actuated",
        "--tls.yellow.time", str(YELLOW_S),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    saida = (r.stdout or "") + (r.stderr or "")
    if not quieto and saida.strip():
        print(saida)
    if r.returncode == 0:
        tira_cabecalho(OUT_NET)
    return r.returncode, saida


def tira_cabecalho(net: Path) -> None:
    """Remove o comentario "generated on <timestamp> ..." que o netconvert poe no
    topo do `.net.xml`.

    Nao e cosmetica. Sem isso o `.net.xml` muda de sha256 a CADA build, e o
    `net_sha256` que o manifesto da demanda carimba (a prova de que aquela demanda
    foi roteada NESTA rede) vira alarme falso toda vez que alguem regera a rede.
    De quebra sai o caminho absoluto da maquina de quem gerou, que nao tem o que
    fazer num artefato versionado.
    """
    texto = net.read_text(encoding="utf-8")
    i = texto.find("<!-- generated on ")
    if i < 0:
        return
    j = texto.find("-->", i)
    if j < 0:
        return
    # `read_text` ja normalizou a quebra de linha; `write_bytes` devolve
    # exatamente o que sobrou, sem reconverter.
    net.write_bytes((texto[:i] + texto[j + 3:].lstrip()).encode("utf-8"))


# ------------------------------------------------------------------- verificacao
def confere(net: Path = OUT_NET) -> dict:
    """Conta o que o DoD pede, direto do `.net.xml`. Sem `sim`, sem traci."""
    if "SUMO_HOME" in os.environ:
        sys.path.append(str(Path(os.environ["SUMO_HOME"]) / "tools"))
    import sumolib

    n = sumolib.net.readNet(str(net))
    normais = [e for e in n.getEdges() if e.getFunction() == ""]
    fontes = sorted(e.getID() for e in normais if not e.getIncoming())
    sorvedouros = sorted(e.getID() for e in normais if not e.getOutgoing())

    root = ET.parse(net).getroot()
    tls = {}
    for tl in root.findall("tlLogic"):
        if tl.get("id") in tls and tl.get("programID") != "0":
            continue
        estados = [p.get("state") for p in tl.findall("phase")]
        verdes = [i for i, s in enumerate(estados)
                  if "g" in s.lower() and "y" not in s.lower()]
        tls[tl.get("id")] = len(verdes)
    return {
        "n_tls": len(tls),
        "controlaveis": sorted(t for t, v in tls.items() if v >= 2),
        "nao_controlaveis": sorted(t for t, v in tls.items() if v < 2),
        "fontes": fontes,
        "sorvedouros": sorvedouros,
        "n_edges_normais": len(normais),
        "v_max": max(ln.getSpeed() for e in n.getEdges() for ln in e.getLanes()),
    }


def _escreve_xml(destino: Path, texto: str) -> None:
    """Escreve e CONFERE que o XML abre.

    Existe por um bug real: `--` e ilegal dentro de comentario XML, e um comentario
    nosso citando uma opcao de linha de comando (`--route-files`) derrubou o
    netconvert e, depois, o SUMO. Falhar aqui e barato; falhar no `traci.start` sao
    dois minutos de retry ate o timeout.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8", newline="\n")
    try:
        ET.parse(destino)
    except ET.ParseError as e:
        raise SystemExit("%s nao e XML valido: %s" % (destino.name, e)) from e


def _imprime(info: dict) -> None:
    print("semaforos           : %d" % info["n_tls"])
    print("controlaveis (>=2 G): %d  %s" % (len(info["controlaveis"]),
                                            " ".join(info["controlaveis"])))
    if info["nao_controlaveis"]:
        print("NAO controlaveis    : %s" % " ".join(info["nao_controlaveis"]))
    print("fontes      (%d): %s" % (len(info["fontes"]), " ".join(info["fontes"])))
    print("sorvedouros (%d): %s" % (len(info["sorvedouros"]),
                                    " ".join(info["sorvedouros"])))
    print("edges normais: %d | v_max: %.4f m/s" % (info["n_edges_normais"],
                                                   info["v_max"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--k", type=float, default=K, help="fator de similitude (default 6)")
    ap.add_argument("--coto", type=float, default=COTO_M,
                    help="comprimento do coto de borda em m de escala real (default 150)")
    ap.add_argument("--verifica", action="store_true",
                    help="nao gera nada: so confere o .net.xml que ja esta em disco")
    args = ap.parse_args(argv)

    if args.verifica:
        _imprime(confere())
        return 0

    if args.coto != COTO_M:
        raise SystemExit("--coto != %g exige regerar CORREDORES; edite COTO_M no "
                         "topo do arquivo (a geometria dos cotos e versionada)."
                         % COTO_M)

    k = args.k
    for d in (BUILD, OUT_NET.parent, OUT_CFG.parent, OUT_ADD.parent):
        d.mkdir(parents=True, exist_ok=True)

    _escreve_xml(BUILD / "nodes_aberta.nod.xml", gera_nodes(k))
    _escreve_xml(BUILD / "edges_aberta.edg.xml", gera_edges(k))
    _escreve_xml(BUILD / "types_aberta.typ.xml", gera_types(k))
    _escreve_xml(BUILD / "connections_aberta.con.xml", gera_conns())

    print("similitude 1/%g | coto %g m (real) = %g m (similitude)"
          % (k, COTO_M, COTO_M / k))
    rc, saida = roda_netconvert(k)
    if rc != 0:
        print("netconvert FALHOU (%d)" % rc)
        return rc
    avisos = [ln for ln in saida.splitlines()
              if ln.lower().startswith(("warning", "error"))]
    print("netconvert: %d avisos" % len(avisos))
    for ln in avisos:
        print("  " + ln)

    _escreve_xml(OUT_ADD, gera_add(k))
    _escreve_xml(OUT_VIEW, gera_view())
    _escreve_xml(OUT_CFG, gera_sumocfg())
    print("escrito: %s" % OUT_NET.relative_to(_RAIZ))
    print("escrito: %s" % OUT_ADD.relative_to(_RAIZ))
    print("escrito: %s" % OUT_VIEW.relative_to(_RAIZ))
    print("escrito: %s" % OUT_CFG.relative_to(_RAIZ))
    _imprime(confere())
    # DoD (a) do agente A1 e "netconvert sem warning": sair != 0 se aparecer um.
    return 1 if avisos else 0


if __name__ == "__main__":
    sys.exit(main())
