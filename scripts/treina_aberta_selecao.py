#!/usr/bin/env python
"""A rodada de SELEÇÃO entre as variantes do A6 — nas seeds de validação, nunca nas held-out.

Cada treino já escolheu o próprio checkpoint por vazão nas seeds 230-231 (DoD
(c)). Este script faz o passo seguinte: compara as variantes ENTRE SI nas quatro
seeds de validação (230-233), contra o `coordenado_c60`, e imprime a tabela que
justifica qual delas vai para a held-out.

Por que não decidir direto na held-out: escolher entre 6 candidatos olhando o
conjunto de teste é o mesmo sobreajuste que o `docs/BASELINE_ABERTO.md` §4.6
descreve para o plano `c50` — só que pior, porque aqui há 6 chances de um
empate virar "vitória" por acaso. As held-out são gastas UMA vez, pelo vencedor.

Cada variante roda no PRÓPRIO espaço de ação, e o baseline roda com ela: uma
política de 10/10 comparada com um `coordenado_c60` de 5/7 não tem `Chave` (C5)
compatível, e a Arena recusa a comparação — que é o comportamento certo.

    ..\\smart-traffic\\.venv\\Scripts\\python.exe scripts/treina_aberta_selecao.py \\
        --procs 4 --saida results/rl/selecao.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from feira.contratos import RESTRICOES_ABERTA  # noqa: E402
from feira.treino.ambiente import SEEDS_VALIDACAO, seeds_de_texto  # noqa: E402
from feira.treino.avalia import avalia_seeds, resumo_json  # noqa: E402

# nome -> (arquivo do checkpoint, decision_interval, min_green, max_red)
# `None` = o default do C1 (di5/vm7/am3/mr0).
VARIANTES: dict[str, tuple[str, int | None, int | None, float | None]] = {
    "v1_queue_di5":     ("results/rl/v1_queue_di5.pt",    None, None, None),
    "v2_pressure_di5":  ("results/rl/v2_pressure_di5.pt", None, None, None),
    "v3_queue_mr60":    ("results/rl/v3_queue_mr60.pt",   None, None, 60.0),
    "v4_pressure_mr60": ("results/rl/v4_pressure_mr60.pt", None, None, 60.0),
    "v5_queue_di10":    ("results/rl/v5_queue_di10.pt",   10,   10,   None),
    "v6_queue_semwarm": ("results/rl/v6_queue_semwarm.pt", None, None, None),
}


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", default=",".join(str(s) for s in SEEDS_VALIDACAO))
    ap.add_argument("--janela", type=float, default=7200.0)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--variantes", default=",".join(VARIANTES))
    ap.add_argument("--saida", default="results/rl/selecao.json")
    a = ap.parse_args(argv)

    seeds = seeds_de_texto(a.seeds)
    escolhidas = [v.strip() for v in a.variantes.split(",") if v.strip()]
    tabela: dict[str, dict] = {}
    for nome in escolhidas:
        ckpt, di, mg, mr = VARIANTES[nome]
        p = _RAIZ / ckpt
        if not p.exists():
            print("[pular] %s: %s não existe (o treino não chegou a salvar)" % (nome, p),
                  flush=True)
            continue
        print("== %s (%s) em %d seeds" % (nome, ckpt, len(seeds)), flush=True)
        bases, novos = avalia_seeds(str(p), seeds, janela_s=a.janela, procs=a.procs,
                                    decision_interval=di, min_green=mg, max_red=mr,
                                    nome_rl="rl:%s" % nome)
        r = resumo_json(bases, novos)
        tabela[nome] = r
        t = r["testes"]
        print("   entregues %+.2f%% (%d/%d)  fila %+.2f%% (%d/%d)  t_sistema %+.2f%% (%d/%d)"
              "  trincas %d/%d  travamentos %d"
              % (t["entregues"]["delta_pct"], t["entregues"]["vitorias"], r["n_seeds"],
                 t["fila_media"]["delta_pct"], t["fila_media"]["vitorias"], r["n_seeds"],
                 t["tempo_medio_no_sistema"]["delta_pct"],
                 t["tempo_medio_no_sistema"]["vitorias"], r["n_seeds"],
                 r["vitorias_trinca"], r["n_seeds"], r["saude_novo"]["travamentos"]),
              flush=True)

    if tabela:
        # O critério é o da DoD (c): VAZÃO. Empate na vazão desempata pela trinca.
        #
        # SÓ CONCORREM AS VARIANTES NA GRADE DO CONTRATO. Uma variante de 10/10
        # tem um percentual que NÃO é comparável com os de 5/7, porque o
        # `coordenado_c60` também é executado na grade nova e nela ele perde
        # 6 dos 12 splits (ver `PlanoFixo.realizado`) — o ganho percentual dela
        # mede, em parte, o adversário mutilado. Ela aparece na tabela e no JSON,
        # com o número; ela não disputa a vaga na held-out.
        grade_contrato = [n for n in tabela
                          if VARIANTES[n][1] in (None, RESTRICOES_ABERTA.decision_interval)
                          and VARIANTES[n][2] in (None, RESTRICOES_ABERTA.min_green)]
        fora_da_grade = [n for n in tabela if n not in grade_contrato]
        vencedor = max(grade_contrato or tabela,
                       key=lambda k: (tabela[k]["testes"]["entregues"]["delta_pct"],
                                      tabela[k]["vitorias_trinca"]))
        print("\nvencedor por vazão, entre as variantes NA GRADE DO CONTRATO (%s): %s (%+.2f%%)"
              % (RESTRICOES_ABERTA.assinatura, vencedor,
                 tabela[vencedor]["testes"]["entregues"]["delta_pct"]))
        for n in fora_da_grade:
            print("  (fora de concurso, outra grade: %s %+.2f%% — o baseline dele também "
                  "mudou de grade)" % (n, tabela[n]["testes"]["entregues"]["delta_pct"]))
        out = _RAIZ / a.saida
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"seeds": list(seeds), "janela_s": a.janela,
                                   "vencedor": vencedor, "variantes": tabela},
                                  indent=2, ensure_ascii=False), encoding="utf-8")
        print("saída em %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
