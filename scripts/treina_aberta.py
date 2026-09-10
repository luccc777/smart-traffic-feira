#!/usr/bin/env python
"""CLI do treino da política RL no `aberta.maquete` (agente A6).

    # a variante base — grade do cenário (5/7), recompensa `queue`, warm start di5
    ..\\smart-traffic\\.venv\\Scripts\\python.exe scripts/treina_aberta.py \\
        --nome v1_queue_di5 --episodios 160

    # o A/B do espaço de ação (10/10). O baseline coordenado roda na MESMA grade.
    ... --nome v4_queue_di10 --decision-interval 10 --min-green 10 \\
        --warm-start ../smart-traffic-maquete/results/maq30_ats_full_best.pt

    # sem warm start (a alavanca 1 medida contra si mesma)
    ... --nome v5_zero --sem-warm-start --epsilon-start 1.0 --epsilon-decay 60000

Rodadas longas vão em BACKGROUND. Uma variante por processo:
`sim.environment.constants` é singleton de processo, então duas grades de decisão
no mesmo processo mediriam a mesma coisa duas vezes, em silêncio.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from feira.treino.ambiente import (  # noqa: E402
    SEEDS_TREINO,
    SEEDS_VALIDACAO,
    seeds_de_texto,
)
from feira.treino.loop import CKPT_DI5, ConfigTreino, treina  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    d = ConfigTreino(nome="_")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--nome", required=True)
    p.add_argument("--episodios", type=int, default=d.episodios)
    p.add_argument("--segundos-por-episodio", type=int, default=d.segundos_por_episodio)
    p.add_argument("--decision-interval", type=int, default=None)
    p.add_argument("--min-green", type=int, default=None)
    p.add_argument("--max-red", type=float, default=None)
    p.add_argument("--recompensa", default=d.recompensa,
                   choices=["queue", "pressure", "diff_waiting", "composite"])
    p.add_argument("--escala-recompensa", type=float, default=d.escala_recompensa)
    p.add_argument("--penalidade-troca", type=float, default=d.penalidade_troca)
    p.add_argument("--seeds-treino", default=",".join(str(s) for s in SEEDS_TREINO))
    p.add_argument("--seeds-validacao", default=",".join(str(s) for s in SEEDS_VALIDACAO[:2]))
    p.add_argument("--semente-torch", type=int, default=d.semente_torch)
    p.add_argument("--warm-start", default=str(CKPT_DI5))
    p.add_argument("--sem-warm-start", action="store_true")
    p.add_argument("--lr", type=float, default=d.lr)
    p.add_argument("--epsilon-start", type=float, default=d.epsilon_start)
    p.add_argument("--epsilon-end", type=float, default=d.epsilon_end)
    p.add_argument("--epsilon-decay", type=int, default=d.epsilon_decay_steps)
    p.add_argument("--learning-starts", type=int, default=d.learning_starts)
    p.add_argument("--target-update", type=int, default=d.target_update_freq)
    p.add_argument("--avalia-cada", type=int, default=d.avalia_cada)
    p.add_argument("--janela-validacao", type=float, default=d.janela_validacao_s)
    p.add_argument("--threads", type=int, default=d.threads)
    p.add_argument("--saida", default="")
    return p


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    a = _parser().parse_args(argv)
    cfg = ConfigTreino(
        nome=a.nome, episodios=a.episodios,
        segundos_por_episodio=a.segundos_por_episodio,
        decision_interval=a.decision_interval, min_green=a.min_green, max_red=a.max_red,
        recompensa=a.recompensa, escala_recompensa=a.escala_recompensa,
        penalidade_troca=a.penalidade_troca,
        seeds_treino=seeds_de_texto(a.seeds_treino),
        seeds_validacao=seeds_de_texto(a.seeds_validacao),
        semente_torch=a.semente_torch,
        warm_start=None if a.sem_warm_start else a.warm_start,
        lr=a.lr, epsilon_start=a.epsilon_start, epsilon_end=a.epsilon_end,
        epsilon_decay_steps=a.epsilon_decay, learning_starts=a.learning_starts,
        target_update_freq=a.target_update, avalia_cada=a.avalia_cada,
        janela_validacao_s=a.janela_validacao, threads=a.threads, saida=a.saida,
    )
    treina(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
