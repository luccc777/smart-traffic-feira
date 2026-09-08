"""Gera a demanda canonica do cenario `aberta.maquete`, seed a seed.

    ..\\smart-traffic\\.venv\\Scripts\\python.exe -m feira.demanda            # 42-47 + 100-111
    ..\\smart-traffic\\.venv\\Scripts\\python.exe -m feira.demanda --seeds 42,43
    ..\\smart-traffic\\.venv\\Scripts\\python.exe -m feira.demanda --forcar

Escreve TRES coisas por seed: o `.rou.xml`, o manifesto e o
`config/maquete_aberta_s<seed>.sumocfg` - este ultimo porque o `TrafficEnv` do
maquete monta a linha de comando do SUMO sozinho e nao aceita route-files; sem
ele a Arena sobe a mesma demanda para toda seed, sem erro (ver
`feira/demanda/config_seed.py`).

Os `.rou.xml` e os `.sumocfg` por seed NAO vao versionados (sao regeneraveis); os
`.manifesto.json` vao - sao eles que permitem dizer "esta run usou ESTA demanda"
seis meses depois. Regerar com a mesma seed e a mesma versao do gerador tem que
devolver o MESMO sha256; se nao devolver, o manifesto denuncia.
"""
from __future__ import annotations

import argparse
import sys

from ..contratos import cenario as resolve_cenario
from .aberta import HORIZONTE_S, VEH_POR_HORA, GeradorDemandaAberta

# 42-47: as seeds de varredura/calibracao do projeto (as mesmas do baseline_sweep
# do maquete). 100-111: as 12 held-out, usadas so na validacao final.
SEEDS_PADRAO = tuple(range(42, 48)) + tuple(range(100, 112))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=str,
                    default=",".join(str(s) for s in SEEDS_PADRAO))
    ap.add_argument("--taxa", type=float, default=VEH_POR_HORA)
    ap.add_argument("--horizonte", type=float, default=HORIZONTE_S)
    ap.add_argument("--forcar", action="store_true",
                    help="regera mesmo que o arquivo em disco bata com o manifesto")
    args = ap.parse_args(argv)

    cen = resolve_cenario("aberta.maquete")
    ger = GeradorDemandaAberta(veh_por_hora=args.taxa, horizonte_s=args.horizonte)
    print("cenario=%s taxa=%.0f veh/h horizonte=%.0f s" % (cen.chave, args.taxa,
                                                           args.horizonte))
    for seed in (int(x) for x in args.seeds.split(",")):
        man = ger.gera(cen, seed, forcar=args.forcar)
        print("  seed %3d | %5d veiculos | t %.1f..%.1f | sha %s | cfg %s"
              % (seed, man.n_veiculos, man.t_primeiro, man.t_ultimo,
                 man.sha256[:16], man.parametros.get("sumocfg_seed") or "(nenhum)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
