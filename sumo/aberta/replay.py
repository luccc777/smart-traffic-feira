#!/usr/bin/env python3
"""Replay deterministico da rede aberta - o DoD (e) do agente A1.

POR QUE ISSO E UM ENTREGAVEL, E NAO UM DETALHE
==============================================
A Frente 3 (modo jogo) parte de um **estado neutro canonico da seed**: a rede e
aquecida com o plano fixo e, dali, os tres bracos (RL, timer, humano) jogam a
mesma rodada. Para isso o aquecimento tem que ser REPRODUTIVEL - senao "a mesma
rodada" e so uma figura de linguagem e o pareamento nao existe.

O risco 3 do plano ("replay deterministico nao fecha") tem tres suspeitos: o RNG
do SUMO, o `weights.random-factor=2.0` do reroteamento e a fila de insercao. Aqui
eles sao testados de frente, com duas perguntas separadas:

  (1) **replay do zero**: rodar 0->t0 duas vezes com a mesma seed da o MESMO
      estado? (o fallback aceitavel segundo o plano)
  (2) **save/load de estado**: `traci.simulation.saveState` em t0 e
      `loadState` depois reproduzem a continuacao ate t1? (o caminho barato, se
      funcionar)

A impressao digital NAO e a contagem de veiculos: e `(id, edge, posicao,
velocidade)` de todo veiculo vivo, ordenado. Duas runs com 700 carros cada e os
carros em lugares diferentes tem a mesma contagem e nao sao o mesmo estado.

Uso:
    python replay.py --seeds 42,43,44 --t0 1200
    python replay.py --seeds 42 --t0 600 --t1 900     # inclui save/load
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
_RAIZ = AQUI.parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))
if "SUMO_HOME" in os.environ:
    sys.path.append(str(Path(os.environ["SUMO_HOME"]) / "tools"))
import traci  # noqa: E402

from feira.contratos import cenario as resolve_cenario  # noqa: E402

# `aplica_timer_fixo` mora no calibra.py: o plano de aquecimento tem que ser o
# MESMO nos dois scripts, senao "o estado canonico" depende de qual arquivo rodou.
sys.path.insert(0, str(AQUI))
from calibra import aplica_timer_fixo  # noqa: E402

PRECISAO_POS = 3        # m; a rede toda tem ~160 m de lado
PRECISAO_VEL = 4        # m/s
# O ARQUIVO de estado do SUMO (`saveState`) grava posicao e velocidade com 2 casas
# decimais. Comparar um estado carregado com o estado salvo na precisao fina acusa
# 100% de divergencia so por arredondamento (medido). A comparacao GROSSA usa a
# precisao do proprio formato - e a unica pergunta honesta a fazer a ele.
PRECISAO_ARQUIVO = 2


def _cmd(rou: str, seed: int, end: float, *, extra: list[str] | None = None) -> list[str]:
    cen = resolve_cenario("aberta.maquete")
    exe = str(Path(os.environ["SUMO_HOME"]) / "bin" / "sumo")
    return [exe, "-c", cen.sumocfg, "-r", rou, "--seed", str(seed),
            "--no-step-log", "true", "--end", str(end)] + (extra or [])


def _impressao(casas: int | None = None) -> tuple[tuple, ...]:
    """Estado observavel da simulacao AGORA, em forma comparavel e ordenada.

    `casas` sobrepoe a precisao (usado para comparar contra o arquivo de estado,
    que so guarda 2 decimais - ver PRECISAO_ARQUIVO).
    """
    pos = casas if casas is not None else PRECISAO_POS
    vel = casas if casas is not None else PRECISAO_VEL
    fora = []
    for vid in traci.vehicle.getIDList():
        fora.append((vid,
                     traci.vehicle.getRoadID(vid),
                     round(traci.vehicle.getLanePosition(vid), pos),
                     round(traci.vehicle.getSpeed(vid), vel)))
    fora.sort()
    # as fases dos 12 semaforos entram tambem: estado da rede inclui o controlador
    fases = tuple((tl, traci.trafficlight.getPhase(tl))
                  for tl in sorted(traci.trafficlight.getIDList()))
    return tuple(fora) + (("__fases__", json.dumps(fases)),)


def impressao_em(rou: str, seed: int, t0: float) -> tuple[tuple, ...]:
    """Roda 0->t0 com o timer fixo e devolve a impressao digital do estado em t0."""
    traci.start(_cmd(rou, seed, t0 + 1))
    aplica_timer_fixo()
    while traci.simulation.getTime() < t0:
        traci.simulationStep()
    imp = _impressao()
    traci.close()
    return imp


def save_load_fecha(rou: str, seed: int, t0: float, t1: float) -> dict:
    """`saveState` em t0, segue ate t1; depois `loadState` e segue de novo ate t1.

    Devolve o que bateu e o que nao bateu. Se `igual_t1` for True, o warm-up do
    jogo pode ser um arquivo de estado em vez de um replay - varias ordens de
    grandeza mais barato.
    """
    estado = AQUI / "calibracao" / ("estado_s%d_t%d.xml.gz" % (seed, int(t0)))
    estado.parent.mkdir(parents=True, exist_ok=True)

    traci.start(_cmd(rou, seed, t1 + 1))
    aplica_timer_fixo()
    while traci.simulation.getTime() < t0:
        traci.simulationStep()
    imp_t0, imp_t0g = _impressao(), _impressao(PRECISAO_ARQUIVO)
    traci.simulation.saveState(str(estado))
    while traci.simulation.getTime() < t1:
        traci.simulationStep()
    imp_t1 = _impressao()
    traci.close()

    traci.start(_cmd(rou, seed, t1 + 1))
    aplica_timer_fixo()
    traci.simulation.loadState(str(estado))
    imp_t0b, imp_t0bg = _impressao(), _impressao(PRECISAO_ARQUIVO)
    while traci.simulation.getTime() < t1:
        traci.simulationStep()
    imp_t1b = _impressao()
    traci.close()

    return {
        "seed": seed, "t0": t0, "t1": t1,
        "igual_t0_fino": imp_t0 == imp_t0b,
        "igual_t0_arquivo": imp_t0g == imp_t0bg,
        "igual_t1": imp_t1 == imp_t1b,
        "n_t0": len(imp_t0) - 1, "n_t0_load": len(imp_t0b) - 1,
        "n_t1": len(imp_t1) - 1, "n_t1_load": len(imp_t1b) - 1,
        "difs_t0_fino": sum(1 for a, b in zip(imp_t0, imp_t0b) if a != b),
        "difs_t1": sum(1 for a, b in zip(sorted(imp_t1), sorted(imp_t1b)) if a != b),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=str, default="42,43,44")
    ap.add_argument("--t0", type=float, default=1200.0)
    ap.add_argument("--t1", type=float, default=None,
                    help="se dado, testa tambem saveState/loadState de t0 ate t1")
    ap.add_argument("--taxa", type=float, default=None,
                    help="regera a demanda nesta taxa (default: a do cenario em disco)")
    args = ap.parse_args(argv)

    from dataclasses import replace

    from feira.demanda import GeradorDemandaAberta
    cen = resolve_cenario("aberta.maquete")
    resultados = []
    for seed in (int(x) for x in args.seeds.split(",")):
        if args.taxa:
            ger = GeradorDemandaAberta(veh_por_hora=args.taxa,
                                       horizonte_s=(args.t1 or args.t0) + 600)
            alvo = AQUI / "calibracao" / ("taxa%04d" % round(args.taxa))
            cen_i = replace(cen, rou_pattern=str(alvo / "demanda_s{seed}.rou.xml"))
            ger.gera(cen_i, seed)
            rou = str(cen_i.rou_file(seed))
        else:
            rou = str(cen.rou_file(seed))
        a = impressao_em(rou, seed, args.t0)
        b = impressao_em(rou, seed, args.t0)
        igual = a == b
        print("seed %d | replay 0->%.0f duas vezes: %s (%d veiculos)"
              % (seed, args.t0, "IDENTICO" if igual else "DIVERGIU", len(a) - 1))
        linha = {"seed": seed, "t0": args.t0, "replay_igual": igual,
                 "n_veiculos": len(a) - 1}
        if not igual:
            difs = [(x, y) for x, y in zip(a, b) if x != y][:5]
            print("   primeiras divergencias: %r" % (difs,))
            linha["difs"] = str(difs)
        if args.t1:
            sl = save_load_fecha(rou, seed, args.t0, args.t1)
            print("   saveState/loadState: t0 fino %s (%d difs) | t0 na precisao "
                  "do arquivo %s | continuacao ate t1 %s (%d difs)"
                  % ("OK" if sl["igual_t0_fino"] else "FALHOU", sl["difs_t0_fino"],
                     "OK" if sl["igual_t0_arquivo"] else "FALHOU",
                     "OK" if sl["igual_t1"] else "FALHOU", sl["difs_t1"]))
            linha["save_load"] = sl
        resultados.append(linha)

    destino = AQUI / "calibracao" / "replay.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(resultados, indent=1), encoding="utf-8")
    print("escrito: %s" % destino)
    return 0 if all(r["replay_igual"] for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
