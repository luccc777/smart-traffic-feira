"""Mede os achados nº3, nº4, nº5, nº6 e nº7 da auditoria (docs/PLANO.md §1).

Dois modos, porque os dois braços da comparação PUBLICADA não rodam na mesma
grade de decisão (o `FixedTimerSim` decide a cada sim-step; a RL, a cada 10) e
`sim.environment.constants` congela essa grade no import:

    # um processo por braço
    python scripts/mede_achados.py braco --braco timer --di 1  --seeds 42,43,100,101,102,103 --out timer.json
    python scripts/mede_achados.py braco --braco rl    --di 10 --seeds 42,43,100,101,102,103 --out rl.json

    # a leitura (não precisa de SUMO)
    python scripts/mede_achados.py analisa --base timer.json --novo rl.json

O que cada número responde:

nº3  a demo roda `SEED=42`, que é uma das `eval_seeds=(42,43)` com que o
     checkpoint foi ESCOLHIDO. O modo `analisa` separa a vantagem nas duas seeds
     in-sample da vantagem nas held-out.
nº4  `tail()` da projeção = média das últimas 20 amostras de fila recebidas. Aqui
     sai a distribuição dessa média móvel contra a média da run inteira — e a
     vantagem percentual calculada dos dois jeitos.
nº5  `LaneStream` ignora faixas `:` de junção. Sai a fração da fila que mora
     nelas, por braço.
nº6  `AQUECIMENTO = 8` viagens por lado. Sai quantos segundos SIMULADOS cada
     braço leva para chegar a 8 — e quanto tempo a tela fica dizendo
     "aquecendo a comparação…".
nº7  `coherence_gap` contra o detector novo, nos mesmos resultados.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

CKPT_PADRAO = _RAIZ.parent / "smart-traffic-maquete" / "results" / "maq30_ats_full_best.pt"
TAIL = 20              # projecao.js: tail() usa as ultimas 20 amostras
N_FROTA = 30           # frota persistente do cenario `maquete` (so o coherence_gap usa)
BUCKET = 600.0         # bucket de vazao, em s simulados
AQUECIMENTO = 8        # projecao.js: gate de viagens por lado


# ------------------------------------------------------------------- coleta
def roda_braco(argv) -> int:
    from feira.contratos import Janela
    from feira.contratos import cenario as pega_cenario

    p = argparse.ArgumentParser(prog="mede_achados.py braco")
    p.add_argument("--braco", choices=("timer", "rl"), required=True)
    p.add_argument("--di", type=int, default=None)
    p.add_argument("--seeds", default="42,43,100,101,102,103")
    p.add_argument("--segundos", type=int, default=3600)
    p.add_argument("--verde", type=int, default=27)
    p.add_argument("--ckpt", default=str(CKPT_PADRAO))
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)

    di = a.di if a.di is not None else (10 if a.braco == "rl" else 1)
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]

    cen = pega_cenario("small.maquete")
    cen = dataclasses.replace(
        cen, restricoes=dataclasses.replace(cen.restricoes, decision_interval=di))
    cen.aplicar()

    from feira.arena import ArenaSumo
    from feira.controladores import ControladorRL, ControladorTimer
    from feira.metricas import lacuna_sobrevivencia

    ctrl = ControladorTimer(a.verde) if a.braco == "timer" else ControladorRL(a.ckpt)
    arena = ArenaSumo()
    janela = Janela(t0=0.0, t1=float(a.segundos))

    linhas = []
    for s in seeds:
        print("[%s di=%d] seed %d ..." % (a.braco, di, s), flush=True)
        res = arena.roda(cen, s, ctrl, janela)
        contab = arena.ultima_contabilidade
        leitor = arena.ultimo_leitor
        serie = list(leitor.serie_desenhavel)
        moveis = [statistics.fmean(serie[i - TAIL:i]) for i in range(TAIL, len(serie) + 1)]
        entregas = list(contab.instantes_de_entrega)
        linhas.append({
            "seed": s,
            "resultado": dataclasses.asdict(res),
            "chave": {"cenario": res.chave.cenario, "seed": res.chave.seed,
                      "t0": res.chave.janela.t0, "t1": res.chave.janela.t1,
                      "demanda_sha": res.chave.demanda_sha},
            "conservacao": res.conservacao,
            "sane": list(res.sane()),
            "lacuna_sobrevivencia": lacuna_sobrevivencia(res),
            # --- nº4: a media movel de 20 amostras contra a media da run ---
            "fila_desenhavel_media": statistics.fmean(serie) if serie else 0.0,
            "fila_movel20": {
                "min": min(moveis) if moveis else 0.0,
                "p05": _pct(moveis, 5), "p50": _pct(moveis, 50), "p95": _pct(moveis, 95),
                "max": max(moveis) if moveis else 0.0,
                "desvio": statistics.pstdev(moveis) if len(moveis) > 1 else 0.0,
                "n": len(moveis),
            },
            # --- nº5: quanto da fila mora nas faixas internas de juncao ---
            "fila_por_tipo_de_faixa": leitor.fila_media_total,
            # --- nº6: quantos segundos ate a 8a viagem ---
            "t_ate_aquecimento": (entregas[AQUECIMENTO - 1] - res.chave.janela.t0
                                  if len(entregas) >= AQUECIMENTO else None),
            # --- vazão por bucket: o número da TELA cresce com o tempo de demo,
            # porque os dois braços não envelhecem igual (ver §9 do documento) ---
            "vazao_por_bucket": _buckets(entregas, res.chave.janela.t0,
                                         res.chave.janela.t1),
            "diagnostico": arena.ultimo_diagnostico,
        })
        print("   entregues=%d fila=%.2f tempo=%.1f conservacao=%d"
              % (res.entregues, res.fila_media, res.tempo_medio_entregue,
                 res.conservacao), flush=True)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(
        {"braco": a.braco, "di": di, "verde": a.verde, "segundos": a.segundos,
         "controlador": ctrl.nome, "linhas": linhas},
        indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("-> %s" % a.out, flush=True)
    return 0


def _buckets(instantes, t0, t1):
    """Viagens concluídas por bucket de `BUCKET` s simulados, na ordem."""
    n = max(1, int((t1 - t0) // BUCKET))
    out = [0] * n
    for t in instantes:
        i = int((t - t0) // BUCKET)
        if 0 <= i < n:
            out[i] += 1
    return out


def _pct(vals, q):
    if not vals:
        return 0.0
    v = sorted(vals)
    i = min(len(v) - 1, max(0, int(round(q / 100.0 * (len(v) - 1)))))
    return v[i]


# ------------------------------------------------- nº4 na versão PAREADA
def roda_tela(argv) -> int:
    """A vantagem de fila COMO A TELA CALCULA, instante a instante.

    O `tail()` da projeção é uma média móvel de 20 amostras, e a tela compara as
    duas móveis NO MESMO QUADRO. Medir a faixa dessa razão exige as duas séries
    ALINHADAS — não bastam os percentis de cada uma, que dariam um limite
    superior pessimista.

    Os dois braços rodam no MESMO processo e na MESMA grade (`--di`, default 10):
    §11 do documento mostra que a grade não muda o timer de 27 s, e rodar juntos
    é o que garante o alinhamento amostra a amostra.
    """
    from feira.contratos import Janela
    from feira.contratos import cenario as pega_cenario

    p = argparse.ArgumentParser(prog="mede_achados.py tela")
    p.add_argument("--seeds", default="42")
    p.add_argument("--segundos", type=int, default=3600)
    p.add_argument("--di", type=int, default=10)
    p.add_argument("--verde", type=int, default=27)
    p.add_argument("--ckpt", default=str(CKPT_PADRAO))
    a = p.parse_args(argv)
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]

    cen = pega_cenario("small.maquete")
    cen = dataclasses.replace(
        cen, restricoes=dataclasses.replace(cen.restricoes, decision_interval=a.di))
    cen.aplicar()

    from feira.arena import ArenaSumo
    from feira.controladores import ControladorRL, ControladorTimer

    arena = ArenaSumo()
    janela = Janela(t0=0.0, t1=float(a.segundos))
    print("=" * 96)
    print("nº4 PAREADO — vantagem de fila da TELA (média móvel de %d amostras) "
          "contra a da run inteira" % TAIL)
    print("  %5s %10s %10s %10s %10s %10s %10s %8s"
          % ("seed", "run", "p01", "p05", "p50", "p95", "p99", "<=0"))
    for s_ in seeds:
        series = {}
        for rot, ctrl in (("timer", ControladorTimer(a.verde)),
                          ("rl", ControladorRL(a.ckpt))):
            print("[%s] seed %d ..." % (rot, s_), flush=True)
            arena.roda(cen, s_, ctrl, janela)
            series[rot] = list(arena.ultimo_leitor.serie_desenhavel)
        n = min(len(series["timer"]), len(series["rl"]))
        mv = {k: [statistics.fmean(v[i - TAIL:i]) for i in range(TAIL, n + 1)]
              for k, v in series.items()}
        deltas = [100.0 * (b - r) / b if b else 0.0
                  for b, r in zip(mv["timer"], mv["rl"])]
        run = 100.0 * (statistics.fmean(series["timer"][:n])
                       - statistics.fmean(series["rl"][:n])) / statistics.fmean(series["timer"][:n])
        pior = sum(1 for d in deltas if d <= 0)
        print("  %5d %9.2f%% %9.1f%% %9.1f%% %9.1f%% %9.1f%% %9.1f%% %7.1f%%"
              % (s_, run, _pct(deltas, 1), _pct(deltas, 5), _pct(deltas, 50),
                 _pct(deltas, 95), _pct(deltas, 99), 100.0 * pior / len(deltas)))
    print("  ('<=0' = fração dos quadros em que a tela mostraria a RL EMPATANDO ou "
          "PERDENDO em fila)")
    print("=" * 96, flush=True)
    return 0


# ------------------------------------------------------------------ análise
def _resultado(d) -> "object":
    from feira.contratos import Chave, Janela, Resultado

    r = dict(d["resultado"])
    k = d["chave"]
    r["chave"] = Chave(cenario=k["cenario"], seed=k["seed"],
                       janela=Janela(t0=k["t0"], t1=k["t1"]),
                       demanda_sha=k["demanda_sha"],
                       # JSON gravado antes de a assinatura existir: assume a
                       # grade da rede fechada, que e a que estes dados usaram.
                       restricoes=k.get("restricoes", "di10/vm10/am3/mr0"))
    return Resultado(**r)


def analisa(argv) -> int:
    from feira.contratos import comparar
    from feira.estatistica import imprime_resumo, resumo_pareado
    from feira.metricas import lacuna_sobrevivencia

    p = argparse.ArgumentParser(prog="mede_achados.py analisa")
    p.add_argument("--base", required=True, help="json do braço timer")
    p.add_argument("--novo", required=True, help="json do braço rl")
    p.add_argument("--in-sample", default="42,43",
                   help="seeds usadas para ESCOLHER o checkpoint (train.py eval_seeds)")
    a = p.parse_args(argv)

    base_j = json.loads(Path(a.base).read_text(encoding="utf-8"))
    novo_j = json.loads(Path(a.novo).read_text(encoding="utf-8"))
    in_sample = {int(s) for s in a.in_sample.split(",") if s.strip()}

    base = [_resultado(x) for x in base_j["linhas"]]
    novo = [_resultado(x) for x in novo_j["linhas"]]
    por_seed_b = {r.chave.seed: r for r in base}
    por_seed_n = {r.chave.seed: r for r in novo}
    seeds = sorted(set(por_seed_b) & set(por_seed_n))

    print("=" * 96)
    print("ACHADOS 3-7 | base=%s (di=%d) | novo=%s (di=%d) | %d s por corrida"
          % (base_j["controlador"], base_j["di"], novo_j["controlador"], novo_j["di"],
             base_j["segundos"]))

    # ---------------------------------------------------- nº3 in-sample
    print("-" * 96)
    print("nº3 — SEED=42 é uma das eval_seeds que ESCOLHERAM o checkpoint")
    print("  %6s %10s %10s %10s %10s %10s %10s" %
          ("seed", "tempo↓%", "fila↓%", "vazão↑%", "in-sample", "lacuna_rl", "sane_rl"))
    grupos = {"in-sample": [], "held-out": []}
    for s in seeds:
        c = comparar(por_seed_b[s], por_seed_n[s])
        g = "in-sample" if s in in_sample else "held-out"
        grupos[g].append(c.deltas)
        print("  %6d %10.2f %10.2f %10.2f %10s %10.1f %10s"
              % (s, c.deltas["tempo_medio_entregue"], c.deltas["fila_media"],
                 c.deltas["entregues"], g,
                 lacuna_sobrevivencia(por_seed_n[s]), por_seed_n[s].sane()[0]))
    for campo in ("tempo_medio_entregue", "fila_media", "entregues"):
        med = {g: (statistics.fmean([d[campo] for d in v]) if v else float("nan"))
               for g, v in grupos.items()}
        vies = med["in-sample"] - med["held-out"]
        print("  %-24s in-sample %+7.2f%%   held-out %+7.2f%%   viés da seed 42/43: %+6.2f pp"
              % (campo, med["in-sample"], med["held-out"], vies))

    # ---------------------------------------------------- nº4 tail()
    print("-" * 96)
    print("nº4 — a fila da tela é a média das últimas %d amostras, não a da run" % TAIL)
    for rot, j in (("timer", base_j), ("rl", novo_j)):
        for ln in j["linhas"]:
            m = ln["fila_movel20"]
            print("  %-5s seed %-4d run=%7.3f  móvel20: p05=%7.3f p50=%7.3f p95=%7.3f "
                  "(faixa %+.1f%% a %+.1f%% da média da run)"
                  % (rot, ln["seed"], ln["fila_desenhavel_media"], m["p05"], m["p50"],
                     m["p95"],
                     100.0 * (m["p05"] / ln["fila_desenhavel_media"] - 1) if ln["fila_desenhavel_media"] else 0.0,
                     100.0 * (m["p95"] / ln["fila_desenhavel_media"] - 1) if ln["fila_desenhavel_media"] else 0.0))
    print("  vantagem de fila calculada dos dois jeitos (por seed):")
    for s in seeds:
        lb = next(x for x in base_j["linhas"] if x["seed"] == s)
        ln = next(x for x in novo_j["linhas"] if x["seed"] == s)
        run = 100.0 * (lb["fila_desenhavel_media"] - ln["fila_desenhavel_media"]) / lb["fila_desenhavel_media"]
        p05 = 100.0 * (lb["fila_movel20"]["p05"] - ln["fila_movel20"]["p95"]) / lb["fila_movel20"]["p05"]
        p95 = 100.0 * (lb["fila_movel20"]["p95"] - ln["fila_movel20"]["p05"]) / lb["fila_movel20"]["p95"]
        print("    seed %-4d run inteira %+6.2f%%   |   janela de 20 amostras: de %+6.2f%% a %+6.2f%%"
              % (s, run, p05, p95))

    # ---------------------------------------------------- nº5 internas
    print("-" * 96)
    print("nº5 — o `heat` da projeção ignora as faixas `:` de junção")
    for rot, j in (("timer", base_j), ("rl", novo_j)):
        fr = [ln["fila_por_tipo_de_faixa"] for ln in j["linhas"]]
        print("  %-5s desenháveis=%7.3f  internas=%7.3f  -> %.2f%% da fila fica fora da tela"
              % (rot, statistics.fmean([x["desenhaveis"] for x in fr]),
                 statistics.fmean([x["internas"] for x in fr]),
                 100.0 * statistics.fmean([x["fracao_internas"] for x in fr])))

    # ---------------------------------------------------- nº6 aquecimento
    print("-" * 96)
    print("nº6 — o gate AQUECIMENTO=%d viagens, em segundos simulados" % AQUECIMENTO)
    for rot, j in (("timer", base_j), ("rl", novo_j)):
        ts = [ln["t_ate_aquecimento"] for ln in j["linhas"] if ln["t_ate_aquecimento"]]
        print("  %-5s %s" % (rot, ["%.0f s" % t for t in ts]))
    print("  (rede FECHADA: a frota nasce cheia. Numa rede ABERTA que começa vazia o"
          " gate não é o mesmo objeto — ver o documento.)")

    # ------------------------------------- extra: a vazão envelhece?
    print("-" * 96)
    print("EXTRA — vazão por bucket de %.0f s simulados (o número da TELA acumula "
          "desde o boot)" % BUCKET)
    for rot, j in (("timer", base_j), ("rl", novo_j)):
        soma = None
        for ln in j["linhas"]:
            b = ln["vazao_por_bucket"]
            soma = b[:] if soma is None else [x + y for x, y in zip(soma, b)]
        media = [x / len(j["linhas"]) for x in soma] if soma else []
        print("  %-5s %s" % (rot, "  ".join("%.0f" % x for x in media)))

    # ---------------------------------------------------- nº7 detector
    print("-" * 96)
    print("nº7 — `coherence_gap` (supõe frota fechada) × detector novo")
    try:
        from sim.evaluation.metrics import coherence_gap
        tem_cg = True
    except Exception:
        tem_cg = False
    print("  %6s %8s %14s %14s %10s" % ("seed", "braço", "coherence_gap", "lacuna_sobrev", "sane"))
    for s in seeds:
        for rot, r in (("timer", por_seed_b[s]), ("rl", por_seed_n[s])):
            cg = (coherence_gap({"mean_travel_time": r.tempo_medio_entregue,
                                 "throughput": r.entregues},
                                N_FROTA, r.chave.janela.duracao)
                  if tem_cg else float("nan"))
            print("  %6d %8s %13.2f%% %13.2f%% %10s"
                  % (s, rot, cg, lacuna_sobrevivencia(r), r.sane()[0]))

    # ---------------------------------------------------- significância
    print("-" * 96)
    print(imprime_resumo(resumo_pareado(base, novo)))
    print("=" * 96, flush=True)
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("braco", "analisa", "tela"):
        print(__doc__)
        return 2
    if argv[0] == "braco":
        return roda_braco(argv[1:])
    if argv[0] == "tela":
        return roda_tela(argv[1:])
    return analisa(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
