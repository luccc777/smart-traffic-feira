"""DoD (b) do agente A2: o detector novo denuncia um travamento INJETADO e não
acusa uma política sã.

Os três braços passam pelo MESMO laço (é o ponto do C4), na mesma seed e na
mesma janela:

    timer   `ControladorTimer(27)`        — o baseline publicado
    rl      `ControladorRL(<ckpt>)`       — a política em produção
    travado `ControladorFake("nunca")`    — TRAVAMENTO INJETADO: todo MANTER, o
                                            farol congela no eixo de referência
                                            e o cruzado nunca abre

O travamento injetado é o pior caso honesto desta rede: nada é removido, nada
teleporta, a conservação continua fechando em zero — ou seja, é exatamente o
caso em que a conservação sozinha é CEGA e a lacuna de sobrevivência tem que
falar. Na rede aberta o outro caso (borda estrangulada) é coberto pelo backlog,
e está no teste de unidade `tests/test_a2_metricas.py`.

    python scripts/detector_travamento.py --seeds 42,43,100 --segundos 1800
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

CKPT_PADRAO = _RAIZ.parent / "smart-traffic-maquete" / "results" / "maq30_ats_full_best.pt"


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seeds", default="42,43,100")
    p.add_argument("--segundos", type=int, default=1800)
    p.add_argument("--verde", type=int, default=27)
    p.add_argument("--ckpt", default=str(CKPT_PADRAO))
    p.add_argument("--json", default=None)
    a = p.parse_args(argv)
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]

    from feira.contratos import Janela
    from feira.contratos import cenario as pega_cenario

    cen = pega_cenario("small.maquete")
    cen.aplicar()

    from feira._fakes import ControladorFake
    from feira.arena import ArenaSumo
    from feira.controladores import ControladorRL, ControladorTimer
    from feira.metricas import lacuna_sobrevivencia, sinais_de_travamento

    try:
        from sim.evaluation.metrics import coherence_gap
    except Exception:
        coherence_gap = None

    bracos = [
        ("timer", ControladorTimer(a.verde)),
        ("rl", ControladorRL(a.ckpt)),
        ("travado", ControladorFake("nunca")),
    ]
    arena = ArenaSumo()
    janela = Janela(t0=0.0, t1=float(a.segundos))
    linhas = []

    for s in seeds:
        for rot, ctrl in bracos:
            print("[%s] seed %d ..." % (rot, s), flush=True)
            res = arena.roda(cen, s, ctrl, janela)
            sinais = sinais_de_travamento(res)
            cg = (coherence_gap({"mean_travel_time": res.tempo_medio_entregue,
                                 "throughput": res.entregues},
                                cen.n_vehicles, janela.duracao)
                  if coherence_gap else float("nan"))
            linhas.append({
                "braco": rot, "seed": s,
                "entregues": res.entregues,
                "tempo_medio_entregue": res.tempo_medio_entregue,
                "tempo_medio_no_sistema": res.tempo_medio_no_sistema,
                "fila_media": res.fila_media,
                "conservacao": res.conservacao,
                "backlog": res.backlog_insercao,
                "perdidos": res.perdidos,
                "travou": res.travou,
                "maior_seca_s": arena.ultimo_diagnostico["maior_seca_s"],
                "lacuna": lacuna_sobrevivencia(res),
                "coherence_gap": cg,
                "sane": list(res.sane()),
                "sinais": sinais,
                "resultado": dataclasses.asdict(res),
            })

    print("=" * 108)
    print("DETECTOR DE ARTEFATO — %d s por corrida, cenário %s (frota fechada de %d)"
          % (a.segundos, cen.chave, cen.n_vehicles))
    print("-" * 108)
    print("  %-8s %5s %9s %11s %11s %8s %8s %10s %11s %6s"
          % ("braço", "seed", "entregues", "tempo_entr", "tempo_sist", "fila",
             "conserv", "seca(s)", "lacuna", "sane"))
    for ln in linhas:
        print("  %-8s %5d %9d %11.1f %11.1f %8.2f %8d %10.0f %10.1f%% %6s"
              % (ln["braco"], ln["seed"], ln["entregues"], ln["tempo_medio_entregue"],
                 ln["tempo_medio_no_sistema"], ln["fila_media"], ln["conservacao"],
                 ln["maior_seca_s"], ln["lacuna"], ln["sane"][0]))
    print("-" * 108)
    print("  veredito do detector, braço a braço:")
    for ln in linhas:
        print("    %-8s seed %-4d -> %s" % (ln["braco"], ln["seed"],
                                            "; ".join(ln["sinais"]) or "sã (nenhum sinal)"))
    print("-" * 108)
    print("  comparação com o `coherence_gap` do maquete (que precisa de N e de frota fechada):")
    for ln in linhas:
        print("    %-8s seed %-4d  coherence_gap=%7.2f%%   lacuna_sobrevivencia=%9.2f%%"
              % (ln["braco"], ln["seed"], ln["coherence_gap"], ln["lacuna"]))
    print("=" * 108, flush=True)

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(linhas, indent=2, ensure_ascii=False, default=str),
                                encoding="utf-8")
        print("json -> %s" % a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
