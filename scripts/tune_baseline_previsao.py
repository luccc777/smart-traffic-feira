#!/usr/bin/env python3
"""Agrega o teste da previsão do agente A1 (capacidade × regime) numa tabela.

Lê os JSON de `results/a5/capacidade/` e imprime, taxa a taxa e plano a plano, as
duas metades da previsão SEPARADAS — porque elas podem dar respostas diferentes,
e é justamente isso que o A1 pediu para saber:

  (a) **capacidade** — a malha ainda entrega? Onde ela quebra, e de que jeito?
  (b) **regime** — em que faixa de "% parados" e de velocidade equivalente ela
      opera quando entrega?

E distingue os DOIS modos de falha, que o critério de estabilidade do A1
(`analisa.py`) junta num "instável" só:

  * **quebra INTERNA** — a população ativa dispara e a velocidade despenca: a
    malha travou por dentro. É o que aparece na tela da feira.
  * **borda METRADA** — a população interna e a velocidade ficam em regime, e o
    que cresce é a fila de inserção: a malha está servindo tudo o que consegue e
    segurando o resto fora. Degrada, mas não trava.

Uso:
    python scripts/tune_baseline_previsao.py results/a5/capacidade/*.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))


def media(v):
    return sum(v) / len(v) if v else float("nan")


def modo_de_falha(ls: list[dict]) -> str:
    """Como esta condição falha, se falha. Ver o cabeçalho do módulo."""
    interna = sum(1 for x in ls if x["travou"] or abs(x.get("deriva_ativos") or 0) > 40)
    borda = sum(1 for x in ls if x["backlog_final"] >= 20)
    if interna:
        return "QUEBRA INTERNA %d/%d" % (interna, len(ls))
    if borda:
        return "borda metrada %d/%d" % (borda, len(ls))
    return "estável %d/%d" % (len(ls), len(ls))


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("json", nargs="*", default=["results/a5/capacidade/*.json"])
    p.add_argument("--md", action="store_true")
    a = p.parse_args(argv)

    arquivos: list[str] = []
    for pad in a.json:
        arquivos.extend(sorted(glob.glob(pad)))
    if not arquivos:
        raise SystemExit("nenhum JSON casou com %r" % a.json)

    dados: dict[tuple[float, str], list[dict]] = {}
    for arq in arquivos:
        for ln in json.loads(Path(arq).read_text(encoding="utf-8"))["linhas"]:
            dados.setdefault((ln["taxa_veh_h"], ln["plano"]), []).append(ln)

    planos = sorted({k[1] for k in dados}, key=lambda n: (n != "timer27", n))
    taxas = sorted({k[0] for k in dados})

    cab = ("%8s %-16s %3s %8s %8s %9s %9s %9s %9s   %s"
           % ("taxa", "plano", "n", "ativos", "%par", "km/h eq", "vazão/h",
              "backlog", "dAtivos", "veredito"))
    if a.md:
        print("| taxa | plano | n | ativos | % parados | km/h eq | vazão/h | backlog |"
              " veredito |")
        print("|---|---|---|---|---|---|---|---|---|")
    else:
        print("=" * len(cab))
        print(cab)
        print("-" * len(cab))
    for taxa in taxas:
        for nome in planos:
            ls = dados.get((taxa, nome))
            if not ls:
                continue
            v = (taxa, nome, len(ls), media([x["ativos"] for x in ls]),
                 media([x["pct_parados"] for x in ls]),
                 media([x["kmh_equivalente"] for x in ls]),
                 media([x["vazao_h"] for x in ls]),
                 media([x["backlog_final"] for x in ls]),
                 media([x.get("deriva_ativos") or 0.0 for x in ls]),
                 modo_de_falha(ls))
            if a.md:
                print("| %.0f | `%s` | %d | %.0f | %.1f%% | %.1f | %.0f | %.0f | %s |"
                      % (v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[9]))
            else:
                print("%8.0f %-16s %3d %8.0f %7.1f%% %9.1f %9.0f %9.0f %+9.0f   %s" % v)
        if not a.md:
            print("-" * len(cab))
    if not a.md:
        print("%% parados usa o limiar da SIMILITUDE (0,1/6 m/s), como o A1. "
              "km/h eq = v x 6 x 3,6.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
