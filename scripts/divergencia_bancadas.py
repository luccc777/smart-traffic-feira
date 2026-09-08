"""Por que `calibra.py` e a Arena discordam sobre o MESMO baseline?

Timer 27 s, 3500 veh/h, seed 42, populacao ativa identica (157) nas duas
bancadas -- e mesmo assim `calibra.py` reporta 37,8% parados / 20,1 km/h e a
Arena 31,4% / 21,1 (docs/BASELINE_ABERTO.md, item 3 dos pendentes).

Hipotese 1 (subconjunto de faixas) JA FOI REFUTADA por medicao: fila em lanes de
aproximacao e em TODAS as lanes dao o mesmo numero (49,55 na janela [300,900]).

Hipotese 2, testada aqui: "% parados" NAO E ESTACIONARIO. A malha e metaestavel
perto da capacidade (achado do A1: a 3800 veh/h duas de seis seeds passam em 1 h
e travam em 2 h), entao a fracao parada cresce com o tempo e o numero depende de
QUANTO se mediu. Se for isso, janelas curtas dao menos e as duas bancadas estao
certas medindo coisas diferentes -- o que ainda assim precisa de UM numero so.

Uso:  python scripts/divergencia_bancadas.py [--seed 42] [--ate 7200]
"""
from __future__ import annotations

import statistics as st
import sys


def main(argv):
    seed = 42
    ate = 7200.0
    for i, a in enumerate(argv):
        if a == "--seed":
            seed = int(argv[i + 1])
        elif a == "--ate":
            ate = float(argv[i + 1])

    from feira.arena import ArenaSumo
    from feira.contratos import Janela, cenario
    from feira.controladores import ControladorTimer

    c = cenario("aberta.maquete")
    t0 = float(c.warmup_s or 300.0)
    janela = Janela(t0=t0, t1=t0 + ate)

    parados: list[int] = []
    ativos: list[int] = []
    velo: list[float] = []

    def obs(f):
        n = len(f.veiculos)
        parados.append(sum(f.heat.values()) if f.heat else 0)
        ativos.append(n)
        velo.append(st.fmean([v["speed"] for v in f.veiculos]) if n else 0.0)

    res = ArenaSumo().roda(c, seed, ControladorTimer(27), janela, observador=obs)
    if res.inseridos <= 0:
        raise SystemExit("rede vazia -- cfg da seed errado (ver ArenaSumo._sumocfg_da_seed)")

    print("seed %d | janela [%g, %g) | inseridos %d | entregues %d"
          % (seed, janela.t0, janela.t1, res.inseridos, res.entregues))
    print()
    print("  janela acumulada     %parados   ativos   km/h eq.   (x6: similitude)")
    for corte in (600, 1200, 1800, 3600, 5400, 7200):
        n = min(int(corte), len(parados))
        if n < 60:
            continue
        p = 100.0 * st.fmean(parados[:n]) / max(1e-9, st.fmean(ativos[:n]))
        print("  [%5g, %5g)        %5.1f%%    %5.1f     %5.1f"
              % (janela.t0, janela.t0 + n, p, st.fmean(ativos[:n]),
                 6.0 * 3.6 * st.fmean(velo[:n])))
    print()
    print("  fatia de 600 s       %parados   ativos   km/h eq.")
    for ini in range(0, len(parados) - 599, 600):
        fat = slice(ini, ini + 600)
        p = 100.0 * st.fmean(parados[fat]) / max(1e-9, st.fmean(ativos[fat]))
        print("  [%5g, %5g)        %5.1f%%    %5.1f     %5.1f"
              % (janela.t0 + ini, janela.t0 + ini + 600, p,
                 st.fmean(ativos[fat]), 6.0 * 3.6 * st.fmean(velo[fat])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
