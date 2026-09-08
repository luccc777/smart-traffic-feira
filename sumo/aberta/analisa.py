#!/usr/bin/env python3
"""Le os `.json` que `calibra.py` escreveu e imprime a tabela que vai para
`docs/CALIBRACAO_ABERTA.md`.

Separado do `calibra.py` de proposito: reprocessar a tabela nao pode exigir
rodar 10 simulacoes de novo. Os dados brutos ficam versionados em
`sumo/aberta/calibracao/`; isto aqui e so leitura.

Uso:
    python analisa.py calibracao/varredura_taxa_s42.json
    python analisa.py calibracao/*.json --t0 1200      # ignora o transiente
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
K = 6.0


def media(serie, campo):
    return math.fsum(s[campo] for s in serie) / len(serie) if serie else 0.0


def desvio(serie, campo):
    if len(serie) < 2:
        return 0.0
    m = media(serie, campo)
    return math.sqrt(math.fsum((s[campo] - m) ** 2 for s in serie) / (len(serie) - 1))


def deriva(serie, campo):
    """(media do ultimo terco) - (media do terco do meio). Se a malha esta em
    regime, isto e ~0; se esta enchendo (ou esvaziando), denuncia o sinal."""
    n = len(serie)
    if n < 6:
        return 0.0
    return media(serie[2 * n // 3:], campo) - media(serie[n // 3:2 * n // 3], campo)


def linha(r, t0):
    s = [x for x in r["serie"] if x["t"] >= t0]
    if not s:
        return None
    return {
        "taxa": r["taxa_veh_h"], "seed": r["seed"],
        "ativos": media(s, "ativos"),
        "interno": media(s, "n_interno"),
        "coto": media(s, "n_coto"),
        "parados": 100 * media(s, "frac_parados"),
        "parados01": 100 * media(s, "frac_parados_01"),
        "vel": media(s, "vel_media"),
        "kmh_real": media(s, "vel_media") * K * 3.6,
        "vel_dp": desvio(s, "vel_media"),
        "d_ativos": deriva(s, "ativos"),
        "d_vel": deriva(s, "vel_media"),
        "backlog": media(s, "backlog"),
        "backlog_max": max(x["backlog"] for x in s),
        "chegados": r["chegados"], "partidos": r["partidos"],
        "vazao_h": r["chegados"] * 3600.0 / r["end_s"],
        "arquivo_veh": r["n_veiculos_arquivo"],
        # ESTAVEL = a populacao ativa nao esta crescendo (a deriva entre o terco do
        # meio e o ultimo cabe em 15% da populacao) E a fila de insercao nao
        # acumulou. Sem este veredito, uma run de 3600 s a 3800 veh/h "parece"
        # estavel - e a mesma seed a 7200 s termina com 552 carros e 70% parados.
        "estavel": (abs(deriva(s, "ativos")) < 0.15 * max(media(s, "ativos"), 1)
                    and max(x["backlog"] for x in s) < 20),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("arquivos", nargs="+")
    ap.add_argument("--t0", type=float, default=1200.0,
                    help="ignora amostras antes de t0 (transiente)")
    args = ap.parse_args(argv)

    caminhos = []
    for a in args.arquivos:
        caminhos.extend(sorted(glob.glob(a)) or [a])

    print("janela de medicao: t >= %.0f s\n" % args.t0)
    cab = ("taxa", "seed", "ativos", "intern", "coto", "%par", "%par.1", "v m/s",
           "km/h*", "dAtiv", "dVel", "backl", "bkMax", "vazao/h", "arq", "ok")
    print("%6s %5s %7s %7s %6s %6s %6s %6s %6s %7s %7s %6s %6s %8s %6s %4s" % cab)
    for c in caminhos:
        for r in json.loads(Path(c).read_text(encoding="utf-8")):
            ln = linha(r, args.t0)
            if ln is None:
                continue
            print("%6.0f %5d %7.0f %7.0f %6.0f %6.1f %6.1f %6.3f %6.1f %7.1f %7.4f "
                  "%6.0f %6d %8.0f %6d %4s"
                  % (ln["taxa"], ln["seed"], ln["ativos"], ln["interno"], ln["coto"],
                     ln["parados"], ln["parados01"], ln["vel"], ln["kmh_real"],
                     ln["d_ativos"], ln["d_vel"], ln["backlog"], ln["backlog_max"],
                     ln["vazao_h"], ln["arquivo_veh"],
                     "sim" if ln["estavel"] else "NAO"))
    print("\n* km/h da rede REAL equivalente (v x %g x 3,6)." % K)
    print("  %%par usa o limiar da similitude (0,1/%g m/s); %%par.1 usa o 0,1 m/s"
          " cru do SUMO." % K)
    print("  dAtiv/dVel = (media do ultimo terco) - (media do terco do meio):"
          " ~0 = regime.")
    print("  ok = |dAtiv| < 15% da populacao E backlog maximo < 20.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
