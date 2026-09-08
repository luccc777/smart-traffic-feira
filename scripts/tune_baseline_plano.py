#!/usr/bin/env python3
"""Constrói a FAMÍLIA de planos de tempo fixo do baseline coordenado (agente A5).

O baseline honesto não é escrito à mão: ciclo e splits saem do
`tlsCycleAdaptation.py` (Webster) e os offsets do `tlsCoordinator.py` (onda
verde), os dois de `$SUMO_HOME/tools`, alimentados pela **demanda de projeto**.

A DEMANDA DE PROJETO — e por que ela não é nenhuma das seeds medidas
-------------------------------------------------------------------
Um plano de tempo fixo é calibrado para UMA hora de projeto. Se essa hora fosse
uma das seeds da varredura (42-47) o plano estaria ajustado ao ruído da própria
amostra que vai julgá-lo; se fosse uma das held-out (100-111), contaminaria o
conjunto que o agente A6 usa. Por isso a demanda de projeto é a **seed 7**, que
não pertence a nenhum dos dois conjuntos, gerada com exatamente os mesmos
parâmetros do regime congelado (3500 veh/h, OD por capacidade pow=1, k=4 rotas)
e guardada em `sumo/aberta/planos/projeto/` com sha256 no manifesto.

`escreve_cfg=False` é obrigatório aqui: sem ele o gerador reescreveria
`sumo/aberta/config/maquete_aberta_s7.sumocfg` — e essa armadilha (demanda
descartável sobrescrevendo o cfg oficial de uma seed) já custou uma medição
inteira ao projeto (`docs/CALIBRACAO_ABERTA.md` §2.1.1).

A FAMÍLIA
---------
Para cada ciclo `C` da lista, três planos, que são os três degraus da
sensibilidade — o efeito de cada peça, isolado:

    uniforme_c<C>     split igual em todas as fases, offset 0   (= o timer de hoje)
    webster_c<C>      split de Webster por interseção, offset 0
    coordenado_c<C>   split de Webster + offsets do tlsCoordinator

Todos os ciclos são múltiplos de `decision_interval` (5 s): fora da grade o
plano escorrega de ciclo em ciclo e o offset deixa de valer — ver
`PlanoFixo.realizado`.

Uso:
    python scripts/tune_baseline_plano.py                     # a família inteira
    python scripts/tune_baseline_plano.py --ciclos 40,60
    python scripts/tune_baseline_plano.py --so-demanda        # só gera a de projeto
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

PLANOS = _RAIZ / "sumo" / "aberta" / "planos"
PROJETO = PLANOS / "projeto"
FERRAMENTAS = PLANOS / "ferramentas"

SEED_PROJETO = 7            # nem varredura (42-47) nem held-out (100-111)
TAXA_PROJETO = 3500.0       # docs/CALIBRACAO_ABERTA.md §3.4 — o regime congelado
HORIZONTE_PROJETO = 5400.0
BEGIN_PROJETO = 300.0       # = warmup_s; a hora de projeto é [300, 3900] = janela_padrao

AMARELO = 3                 # RESTRICOES_ABERTA.yellow
MIN_GREEN = 7               # RESTRICOES_ABERTA.min_green
LOST_TIME = 4               # HCM: 2 s de partida + 2 s de folga por fase
GRADE = 5                   # RESTRICOES_ABERTA.decision_interval (sim-steps de 1 s)

CICLOS = (20, 30, 40, 50, 60, 70, 80, 90, 100, 120)


def _tools() -> Path:
    home = os.environ.get("SUMO_HOME")
    if not home:
        raise SystemExit("SUMO_HOME não está no ambiente — sem ele não há tlsCycleAdaptation.py")
    t = Path(home) / "tools"
    if not (t / "tlsCycleAdaptation.py").exists():
        raise SystemExit("não achei tlsCycleAdaptation.py em %s" % t)
    return t


# --------------------------------------------------------------- demanda de projeto
def demanda_de_projeto(*, forcar: bool = False) -> tuple[Path, dict]:
    """Gera (ou reaproveita) o `.rou.xml` da hora de projeto. Devolve (caminho, manifesto)."""
    from feira.contratos import cenario as resolve_cenario
    from feira.demanda import GeradorDemandaAberta

    PROJETO.mkdir(parents=True, exist_ok=True)
    cen = resolve_cenario("aberta.maquete")
    cen_proj = replace(cen, rou_pattern=str(PROJETO / "demanda_projeto_s{seed}.rou.xml"))
    ger = GeradorDemandaAberta(veh_por_hora=TAXA_PROJETO, escreve_cfg=False,
                               horizonte_s=HORIZONTE_PROJETO)
    man = ger.gera(cen_proj, SEED_PROJETO, forcar=forcar)
    rou = cen_proj.rou_file(SEED_PROJETO)
    return rou, {
        "seed": man.seed,
        "veh_por_hora": TAXA_PROJETO,
        "horizonte_s": HORIZONTE_PROJETO,
        "sha256": man.sha256,
        "n_veiculos": man.n_veiculos,
        "versao_gerador": man.versao_gerador,
        "arquivo": rou.name,
    }


# ------------------------------------------------------------------- ferramentas SUMO
def roda_webster(net: Path, rou: Path, ciclo: int, saida: Path) -> list[str]:
    cmd = [sys.executable, str(_tools() / "tlsCycleAdaptation.py"),
           "-n", str(net), "-r", str(rou), "-b", str(BEGIN_PROJETO),
           "-y", str(AMARELO), "-l", str(LOST_TIME), "-g", str(MIN_GREEN),
           "--min-cycle", str(ciclo), "--max-cycle", str(ciclo),
           "-o", str(saida), "-p", "coordenado"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("tlsCycleAdaptation falhou (%d):\n%s\n%s"
                         % (r.returncode, r.stdout[-2000:], r.stderr[-2000:]))
    return cmd


def roda_coordinator(net: Path, rou: Path, plano_add: Path, saida: Path) -> list[str]:
    cmd = [sys.executable, str(_tools() / "tlsCoordinator.py"),
           "-n", str(net), "-r", str(rou), "-a", str(plano_add), "-o", str(saida)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("tlsCoordinator falhou (%d):\n%s\n%s"
                         % (r.returncode, r.stdout[-2000:], r.stderr[-2000:]))
    return cmd


def le_programa(add_xml: Path) -> dict[str, list[tuple[float, str]]]:
    """`{tls: [(duração, state), ...]}` do `.add.xml` produzido pelas ferramentas."""
    raiz = ET.parse(add_xml).getroot()
    saida = {}
    for tl in raiz.iter("tlLogic"):
        fases = [(float(p.get("duration")), p.get("state")) for p in tl.iter("phase")]
        if fases:
            saida[tl.get("id")] = fases
    return saida


def le_offsets(add_xml: Path) -> dict[str, float]:
    raiz = ET.parse(add_xml).getroot()
    return {tl.get("id"): float(tl.get("offset", 0.0)) for tl in raiz.iter("tlLogic")}


def escreve_programa(destino: Path, verdes: dict[str, tuple[float, ...]],
                     estados: dict[str, list[str]], amarelo: int) -> Path:
    """Escreve um `.add.xml` de tlLogic a partir de um split — para alimentar o
    `tlsCoordinator.py`.

    Ele calcula o offset a partir do instante em que o movimento fica verde
    DENTRO do ciclo, e esse instante depende do split. Coordenar um plano de
    split uniforme com os offsets calculados para o split de Webster daria
    offsets errados — e é justamente a separação entre "o que o split faz" e
    "o que o offset faz" que o degrau `onda` existe para medir.
    """
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<!-- GERADO por scripts/tune_baseline_plano.py: entrada do '
              'tlsCoordinator.py. -->',
              '<additional>']
    for tls in sorted(verdes):
        st = estados[tls]
        linhas.append('    <tlLogic id="%s" type="static" programID="coordenado" '
                      'offset="0">' % tls)
        for k, g in enumerate(verdes[tls]):
            linhas.append('        <phase duration="%g" state="%s"/>' % (g, st[2 * k]))
            if len(verdes[tls]) > 1:
                linhas.append('        <phase duration="%d" state="%s"/>'
                              % (amarelo, st[2 * k + 1]))
        linhas.append('    </tlLogic>')
    linhas.append('</additional>')
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8", newline="\n")
    return destino


# ------------------------------------------------------------------------ montagem
def _verde(state: str) -> bool:
    s = state.lower()
    return ("g" in s) and ("y" not in s)


def verdes_por_tl(programa: dict[str, list[tuple[float, str]]],
                  ordem_verde: dict[str, tuple[int, ...]]) -> dict[str, tuple[float, ...]]:
    """Duração de verde por fase, NA ORDEM de `TLPhaseInfo.green_phases`.

    A ordem importa: é a mesma em que o `TrafficEnv` avança ciclicamente, e é o
    índice que chega em `Observacao.fase_atual`. O `.add.xml` das ferramentas
    preserva a ordem de fases da rede (verificado no `--verifica`), mas conferir
    aqui é barato e evita um plano deslocado em silêncio.
    """
    saida = {}
    for tls, fases in programa.items():
        idx_verdes = [i for i, (_, st) in enumerate(fases) if _verde(st)]
        esperado = list(ordem_verde[tls])
        if idx_verdes != esperado:
            raise SystemExit(
                "ordem de fases verdes divergente em %s: ferramenta deu %r, a rede "
                "tem %r — o índice do plano não casaria com Observacao.fase_atual."
                % (tls, idx_verdes, esperado))
        saida[tls] = tuple(float(fases[i][0]) for i in idx_verdes)
    return saida


def ajusta_a_grade(verdes: dict[str, tuple[float, ...]], ciclo: int,
                   amarelo: int, min_green: int, grade: int) -> dict[str, tuple[float, ...]]:
    """Põe o split de Webster na GRADE DE DECISÃO, fechando o ciclo exatamente.

    Por que isto não é cosmética. A Arena só consulta o controlador a cada
    `grade` sim-steps, e a troca só pode ser comandada num tick — então o verde
    que a malha EXECUTA é sempre `m·grade − amarelo` (com grade 5 e amarelo 3:
    7, 12, 17, 22, 27, ...). Um plano com verde de 10 s não vira "10 s com um
    errinho": ele vira 7 ou 12, e — pior — a distorção é DIFERENTE por fase,
    porque cada fronteira de fase é arredondada por conta própria. Medido num
    plano de ciclo 60: o par nominal (10, 44) executa como **(7, 47)**.

    Arredondar aqui, no plano congelado, tem três consequências que valem o
    trabalho:

    1. **o plano publicado é o plano executado** — `PlanoFixo.realizado(5)`
       devolve os mesmos verdes, e há teste para isso;
    2. a distorção deixa de ser por fase e vira um deslocamento ÚNICO por
       interseção (todas as fronteiras passam a ter o mesmo resto módulo a
       grade), que é só um offset global e não mexe na coordenação;
    3. o erro de arredondamento fica declarado no plano, em vez de aparecer
       depois como diferença inexplicada entre o papel e a medida.

    Método: maior resto (largest remainder) sobre `ciclo/grade` unidades,
    proporcional a `verde+amarelo` de Webster, com piso de
    `ceil((min_green+amarelo)/grade)` unidades por fase.
    """
    if ciclo % grade:
        raise SystemExit("ciclo %d não é múltiplo da grade de %d s" % (ciclo, grade))
    piso_u = -(-(min_green + amarelo) // grade)          # ceil
    saida = {}
    for tls, bruto in verdes.items():
        n = len(bruto)
        if n < 2:
            saida[tls] = (float(ciclo),)
            continue
        unidades = ciclo // grade
        if unidades < n * piso_u:
            raise SystemExit(
                "ciclo %d s é curto demais para %s: %d fases × (verde mín %d + amarelo "
                "%d) = %d s." % (ciclo, tls, n, min_green, amarelo,
                                 n * piso_u * grade))
        peso = [max(float(x), 0.0) + amarelo for x in bruto]
        soma = sum(peso) or 1.0
        cotas = [w / soma * unidades for w in peso]
        u = [int(c) for c in cotas]
        # as unidades que sobraram vão para as maiores frações — desempate pelo
        # maior fluxo crítico, para o critério ser determinístico
        ordem = sorted(range(n), key=lambda k: (cotas[k] - int(cotas[k]), peso[k]),
                       reverse=True)
        for k in ordem[:unidades - sum(u)]:
            u[k] += 1
        # só então o piso: quem ficou abaixo do verde mínimo sobe, e a unidade sai
        # de quem tem mais (é lá que 5 s pesam menos em porcentagem)
        for _ in range(n * unidades):
            baixo = [k for k in range(n) if u[k] < piso_u]
            if not baixo:
                break
            k = min(baixo, key=lambda k: u[k])
            doador = max(range(n), key=lambda j: u[j])
            u[k] += 1
            u[doador] -= 1
        saida[tls] = tuple(float(x * grade - amarelo) for x in u)
    return saida


def monta_planos(ciclo: int, net: Path, rou: Path, topo, ordem: dict, prov_demanda: dict,
                 *, verbose: bool = False) -> list:
    """Os três planos deste ciclo: uniforme, webster (sem offset) e coordenado."""
    from feira.controladores.coordenado import PlanoFixo

    FERRAMENTAS.mkdir(parents=True, exist_ok=True)
    add_web = FERRAMENTAS / ("webster_c%d.add.xml" % ciclo)
    add_off = FERRAMENTAS / ("offsets_c%d.add.xml" % ciclo)
    cmd_web = roda_webster(net, rou, ciclo, add_web)
    cmd_off = roda_coordinator(net, rou, add_web, add_off)

    programa = le_programa(add_web)
    webster_bruto = verdes_por_tl(programa, ordem)
    verdes = ajusta_a_grade(webster_bruto, ciclo, AMARELO, MIN_GREEN, GRADE)
    # o offset também vai para a grade, e pelo mesmo motivo: a troca só acontece
    # num tick, então a DIFERENÇA de offset que a malha executa já é múltipla da
    # grade. Arredondar aqui (para o mais próximo, não para cima) só declara isso
    # e mantém o plano publicado igual ao executado.
    offsets_brutos = {t: float(v) % ciclo for t, v in le_offsets(add_off).items()}
    faltando = [t for t in topo.tls_ids if t not in offsets_brutos]
    for t in faltando:                    # TL que não entrou em nenhum par coordenado
        offsets_brutos[t] = 0.0
    offsets = {t: float(round(v / GRADE) * GRADE % ciclo) for t, v in offsets_brutos.items()}

    # degrau 0: MESMO split em toda interseção, sem offset. Passa pelo mesmo
    # arredondamento de grade que os outros (pesos iguais) porque num ciclo com
    # número ÍMPAR de unidades de grade — 25, 35, 45 s — não existe split 50/50
    # realizável, e um plano fora da grade não seria comparável com os demais.
    # (Nesses ciclos ímpares o degrau 0 deixa de ser um controle limpo: a unidade
    # que sobra vai para a fase de índice 0, que em várias interseções é a MENOR.
    # Leia a linha `uniforme_c25/35/45` sabendo disso.)
    n_fases = {t: len(verdes[t]) for t in verdes}
    uni = ajusta_a_grade({t: tuple([1.0] * n_fases[t]) for t in verdes},
                         ciclo, AMARELO, MIN_GREEN, GRADE)
    # degrau 1b: a MESMA onda verde, mas sobre o split uniforme. Os offsets têm
    # que ser recalculados: o `tlsCoordinator` mede o instante do verde DENTRO do
    # ciclo, e esse instante muda quando o split muda.
    estados = {t: [s for _, s in programa[t]] for t in programa}
    add_uni = FERRAMENTAS / ("uniforme_c%d.add.xml" % ciclo)
    add_off_uni = FERRAMENTAS / ("offsets_uniforme_c%d.add.xml" % ciclo)
    escreve_programa(add_uni, uni, estados, AMARELO)
    cmd_off_uni = roda_coordinator(net, rou, add_uni, add_off_uni)
    off_uni_brutos = {t: float(v) % ciclo for t, v in le_offsets(add_off_uni).items()}
    for t in verdes:
        off_uni_brutos.setdefault(t, 0.0)
    off_uni = {t: float(round(v / GRADE) * GRADE % ciclo)
               for t, v in off_uni_brutos.items()}

    base_prov = {
        "gerado_por": "scripts/tune_baseline_plano.py",
        "demanda_de_projeto": prov_demanda,
        "restricoes": {"decision_interval": GRADE, "min_green": MIN_GREEN,
                       "yellow": AMARELO, "max_red": 0.0},
        "webster": {"ferramenta": "tlsCycleAdaptation.py",
                    "lost_time_s": LOST_TIME, "begin_s": BEGIN_PROJETO,
                    "saturation_headway_s": 2.0,
                    "cmd": " ".join(Path(c).name if c.endswith(".py") else c for c in cmd_web)},
        "grade_s": GRADE,
        "webster_bruto_s": {t: list(v) for t, v in sorted(webster_bruto.items())},
        "net_file": net.name,
    }

    planos = [
        PlanoFixo(nome="uniforme_c%d" % ciclo, cenario="aberta.maquete",
                  ciclo_s=float(ciclo), amarelo_s=float(AMARELO),
                  verdes=uni, offsets={t: 0.0 for t in verdes},
                  proveniencia=dict(base_prov, degrau="0 · ciclo só (split igual, sem offset)")),
        PlanoFixo(nome="onda_c%d" % ciclo, cenario="aberta.maquete",
                  ciclo_s=float(ciclo), amarelo_s=float(AMARELO),
                  verdes=uni, offsets={t: off_uni[t] for t in verdes},
                  proveniencia=dict(
                      base_prov,
                      degrau="1b · ciclo + offset (onda verde) SEM split",
                      offsets={"ferramenta": "tlsCoordinator.py", "speed_factor": 0.8,
                               "sobre": "split uniforme (recalculado, não o de Webster)",
                               "brutos_s": {t: round(v, 2)
                                            for t, v in sorted(off_uni_brutos.items())},
                               "cmd": " ".join(Path(c).name if c.endswith(".py") else c
                                               for c in cmd_off_uni)})),
        PlanoFixo(nome="webster_c%d" % ciclo, cenario="aberta.maquete",
                  ciclo_s=float(ciclo), amarelo_s=float(AMARELO),
                  verdes=verdes, offsets={t: 0.0 for t in verdes},
                  proveniencia=dict(base_prov, degrau="1 · ciclo + split de Webster")),
        PlanoFixo(nome="coordenado_c%d" % ciclo, cenario="aberta.maquete",
                  ciclo_s=float(ciclo), amarelo_s=float(AMARELO),
                  verdes=verdes, offsets={t: offsets[t] for t in verdes},
                  proveniencia=dict(
                      base_prov,
                      degrau="2 · ciclo + split + offset (onda verde)",
                      offsets={"ferramenta": "tlsCoordinator.py",
                               "speed_factor": 0.8,
                               "sem_par_coordenado": faltando,
                               "brutos_s": {t: round(v, 2)
                                            for t, v in sorted(offsets_brutos.items())},
                               "cmd": " ".join(Path(c).name if c.endswith(".py") else c
                                               for c in cmd_off)})),
    ]
    if verbose:
        for p in planos:
            print("  %-18s ciclo %3d  verdes %s" % (
                p.nome, ciclo,
                " ".join("%s=%s" % (t, "/".join("%g" % x for x in p.verdes[t]))
                         for t in p.tls_ids[:3]) + " ..."))
    return planos


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ciclos", default=",".join(str(c) for c in CICLOS))
    p.add_argument("--forcar-demanda", action="store_true")
    p.add_argument("--so-demanda", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)

    rou, prov = demanda_de_projeto(forcar=a.forcar_demanda)
    print("demanda de projeto: %s" % rou)
    print("  seed %d · %g veh/h · %d veículos · sha256 %s"
          % (prov["seed"], prov["veh_por_hora"], prov["n_veiculos"], prov["sha256"][:16]))
    (PROJETO / "PROVENIENCIA.json").write_text(
        json.dumps(prov, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    if a.so_demanda:
        return 0

    from feira.arena.sumo import ArenaSumo, _amarra_sim
    from feira.contratos import cenario as resolve_cenario

    cen = resolve_cenario("aberta.maquete")
    topo = ArenaSumo().topologia(cen)
    _amarra_sim(cen)
    from sim.environment import net_topology as nt
    # a ordem canônica das fases verdes vem da rede, não de suposição sobre
    # "verde nos índices pares": é o índice que chega em Observacao.fase_atual.
    ordem = {t: tuple(nt.TL_PHASES[t].green_phases) for t in topo.tls_ids}
    net = Path(cen.net_file)
    print("rede: %s — %d semáforos, %d controláveis"
          % (net.name, topo.n, topo.n_controlaveis))

    ciclos = [int(x) for x in a.ciclos.split(",") if x.strip()]
    escritos = []
    for c in ciclos:
        if c % GRADE:
            print("  ciclo %d NÃO é múltiplo da grade de %d s — pulado" % (c, GRADE))
            continue
        if c < max(topo.n_fases_verdes) * (MIN_GREEN + AMARELO):
            print("  ciclo %d é menor que o mínimo estrutural (%d s) — pulado"
                  % (c, max(topo.n_fases_verdes) * (MIN_GREEN + AMARELO)))
            continue
        for plano in monta_planos(c, net, rou, topo, ordem, prov, verbose=a.verbose):
            destino = plano.salva(PLANOS / ("%s.json" % plano.nome))
            escritos.append(destino)
        print("  ciclo %3d ok" % c)

    print("\n%d planos escritos em %s" % (len(escritos), PLANOS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
