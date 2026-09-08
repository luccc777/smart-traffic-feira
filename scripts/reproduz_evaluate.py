"""DoD (a) do agente A2: a Arena reproduz o `sim/evaluation/evaluate.py` atual.

Roda a implementação de REFERÊNCIA do maquete e a `ArenaSumo` no MESMO processo,
com a mesma seed, a mesma janela e o mesmo baseline, e imprime a diferença
métrica a métrica. Duas configurações, porque a referência são dois laços
diferentes:

    --braco rl     -> sim.evaluation.policy_sim.evaluate_policy   (grade de 10 s)
    --braco timer  -> sim.baselines.fixed_timer_sim.FixedTimerSim (decide a cada sim-step)

Por isso o braço `timer` roda com `--di 1`: o `FixedTimerSim` consulta o relógio
a CADA sim-step, e com a grade de 10 s da RL um verde de 27 s só pode ser
trocado aos 30 s — o baseline muda. Esse efeito é medido à parte, com
`--braco timer --di 10`, e vai para `docs/AUDITORIA_COMPARACAO.md` §8.

Cada invocação precisa de um PROCESSO NOVO quando `--di` muda: os escalares de
`sim.environment.constants` são congelados no import (ver C1).

    python scripts/reproduz_evaluate.py --braco rl    --seed 42 --segundos 3600
    python scripts/reproduz_evaluate.py --braco timer --seed 42 --segundos 3600 --di 1
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from feira.arena import ArenaSumo  # noqa: E402
from feira.contratos import Janela  # noqa: E402
from feira.contratos import cenario as pega_cenario  # noqa: E402
from feira.metricas import diagnostico, lacuna_sobrevivencia  # noqa: E402

CKPT_PADRAO = _RAIZ.parent / "smart-traffic-maquete" / "results" / "maq30_ats_full_best.pt"

# referência -> campo equivalente no Resultado (C5)
EQUIVALENTES = (
    ("mean_travel_time", "tempo_medio_entregue"),
    ("mean_queue", "fila_media"),
    ("mean_waiting", "espera_media"),
    ("throughput", "entregues"),
)


def _delta_pct(ref: float, novo: float) -> float:
    return ((novo - ref) / ref * 100.0) if ref else float("nan")


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--braco", choices=("rl", "timer"), required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--segundos", type=int, default=3600)
    p.add_argument("--verde", type=int, default=27, help="verde do timer (s)")
    p.add_argument("--di", type=int, default=None,
                   help="decision_interval; default 10 (rl) / 1 (timer)")
    p.add_argument("--ckpt", default=str(CKPT_PADRAO))
    p.add_argument("--json", default=None, help="grava o resultado bruto neste arquivo")
    p.add_argument("--so-arena", action="store_true", help="pula a referência")
    a = p.parse_args(argv)

    di = a.di if a.di is not None else (10 if a.braco == "rl" else 1)
    cen = pega_cenario("small.maquete")
    cen = dataclasses.replace(
        cen, restricoes=dataclasses.replace(cen.restricoes, decision_interval=di))
    cen.aplicar()          # ANTES de qualquer import de `sim`

    from sim.environment import constants as C

    print("cenário=%s  seed=%d  janela=%ds  di=%d  min_green=%d  yellow=%d  N=%d"
          % (cen.chave, a.seed, a.segundos, C.DECISION_INTERVAL, C.MIN_GREEN,
             C.YELLOW_DUR, C.N_VEHICLES), flush=True)

    # ------------------------------------------------------------ referência
    ref = None
    if not a.so_arena:
        t0 = time.perf_counter()
        if a.braco == "rl":
            from sim.agents.policy import load_policy
            from sim.evaluation.policy_sim import evaluate_policy

            pol = load_policy(a.ckpt)
            ref = evaluate_policy(pol, seed=a.seed, sim_seconds=a.segundos)
        else:
            from sim.baselines.fixed_timer_sim import FixedTimerSim

            ref = FixedTimerSim(green_seconds=a.verde, seed=a.seed,
                                deterministic=True).run(sim_seconds=a.segundos)
        print("[ref  ] %.1f s de parede" % (time.perf_counter() - t0), flush=True)

    # ----------------------------------------------------------------- arena
    if a.braco == "rl":
        from feira.controladores import ControladorRL

        ctrl = ControladorRL(a.ckpt)
    else:
        from feira.controladores import ControladorTimer

        ctrl = ControladorTimer(a.verde)

    arena = ArenaSumo()
    t0 = time.perf_counter()
    res = arena.roda(cen, a.seed, ctrl, Janela(t0=0.0, t1=float(a.segundos)))
    print("[arena] %.1f s de parede" % (time.perf_counter() - t0), flush=True)

    # ------------------------------------------------------------- relatório
    print("=" * 78)
    print("REPRODUÇÃO — braço %s | seed %d | %d s | di=%d" % (a.braco, a.seed, a.segundos, di))
    print("-" * 78)
    if ref is not None:
        print("  %-22s %14s %14s %10s" % ("métrica", "referência", "arena", "delta"))
        pior = 0.0
        for k_ref, k_arena in EQUIVALENTES:
            v_ref = float(ref[k_ref])
            v_new = float(getattr(res, k_arena))
            d = _delta_pct(v_ref, v_new)
            pior = max(pior, abs(d))
            print("  %-22s %14.4f %14.4f %+9.3f%%" % (k_ref, v_ref, v_new, d))
        print("-" * 78)
        print("  maior |delta| = %.3f%%   (DoD do A2: <= 0,500%%)  -> %s"
              % (pior, "OK" if pior <= 0.5 else "FALHOU"))
    print("-" * 78)
    print(diagnostico(res))
    print("  lacuna de sobrevivência = %.2f%%" % lacuna_sobrevivencia(res))
    print("  diagnóstico da arena: %s"
          % json.dumps(arena.ultimo_diagnostico, default=str, ensure_ascii=False))
    print("=" * 78, flush=True)

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({
            "braco": a.braco, "seed": a.seed, "segundos": a.segundos, "di": di,
            "referencia": ref,
            "arena": dataclasses.asdict(res) if hasattr(res, "__dataclass_fields__") else None,
            "arena_extra": {"conservacao": res.conservacao,
                            "vazao_por_min": res.vazao_por_min,
                            "lacuna_sobrevivencia": lacuna_sobrevivencia(res),
                            "sane": list(res.sane())},
            "diagnostico": arena.ultimo_diagnostico,
        }, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print("json -> %s" % a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
