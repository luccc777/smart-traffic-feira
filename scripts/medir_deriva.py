"""Mede a DERIVA de tempo simulado entre os dois braços da demo atual (achado nº1).

O dashboard do maquete roda `nn_runner.py` e `timer_runner.py` em DOIS processos,
cada um com seu deadline de parede. Quando um deles atrasa, o código faz
`deadline = time.perf_counter()` — o atraso some da vista e nunca é recuperado. A
consequência é que os dois braços podem estar em instantes simulados DIFERENTES
enquanto a tela compara o `completed` acumulado dos dois como se fossem pareados.

Este script é um CLIENTE do WebSocket do dashboard (`/ws`). Não modifica nada do
maquete: só escuta os frames que já são publicados e anota, por frame,
`(t_parede, sim, t_simulado, completed, n_active)`.

    # coletar 10 min
    python scripts/medir_deriva.py --minutos 10 --out deriva.csv

    # analisar o csv (não precisa do dashboard de pé)
    python scripts/medir_deriva.py --analisar deriva.csv

A deriva reportada é `t_timer − t_nn` amostrada na grade de parede: positiva
significa que o braço do TIMER está ADIANTE no tempo simulado (rodou mais
simulação pelo mesmo tempo de parede) — e portanto teve mais chance de concluir
viagens que o braço da rede neural.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import sys
import time
from pathlib import Path

BRACOS = ("timer", "nn")


# ------------------------------------------------------------------ coleta
async def _coleta(url: str, segundos: float, out: Path) -> int:
    import websockets

    linhas: list[tuple] = []
    t0 = time.perf_counter()
    print("[deriva] conectando em %s ..." % url, flush=True)
    async with websockets.connect(url, max_size=None, ping_interval=20) as ws:
        print("[deriva] conectado; coletando por %.0f s" % segundos, flush=True)
        while True:
            restante = segundos - (time.perf_counter() - t0)
            if restante <= 0:
                break
            try:
                bruto = await asyncio.wait_for(ws.recv(), timeout=min(5.0, restante))
            except asyncio.TimeoutError:
                continue
            try:
                f = json.loads(bruto)
            except Exception:
                continue
            if f.get("type") != "frame":
                continue
            sim = f.get("sim")
            if sim not in BRACOS:
                continue
            st = f.get("stats") or {}
            linhas.append((
                round(time.perf_counter() - t0, 4),
                sim,
                f.get("t"),
                f.get("status"),
                st.get("completed"),
                st.get("n_active"),
                st.get("avg_travel_time"),
                f.get("decision"),
                f.get("substep"),
            ))
            n = len(linhas)
            if n % 200 == 0:
                print("[deriva] %d frames (%.0f s de parede)"
                      % (n, time.perf_counter() - t0), flush=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["t_parede", "sim", "t_sim", "status", "completed",
                    "n_active", "avg_tt", "decision", "substep"])
        w.writerows(linhas)
    print("[deriva] %d frames -> %s" % (len(linhas), out), flush=True)
    return len(linhas)


# ---------------------------------------------------------------- análise
def _serie(linhas: list[dict], sim: str) -> list[tuple[float, float]]:
    """[(t_parede, t_sim)] de um braço, em ordem, só frames válidos."""
    out = []
    for r in linhas:
        if r["sim"] != sim or r["status"] == "stopped":
            continue
        try:
            out.append((float(r["t_parede"]), float(r["t_sim"])))
        except (TypeError, ValueError):
            continue
    return out


def _interp(serie: list[tuple[float, float]], tw: float) -> float | None:
    """t_sim do braço no instante de parede `tw`, por interpolação linear."""
    if not serie or tw < serie[0][0] or tw > serie[-1][0]:
        return None
    lo, hi = 0, len(serie) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if serie[mid][0] < tw:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return serie[0][1]
    x0, y0 = serie[lo - 1]
    x1, y1 = serie[lo]
    if x1 == x0:
        return y1
    return y0 + (y1 - y0) * (tw - x0) / (x1 - x0)


def analisa(caminho: Path, passo: float = 10.0) -> dict:
    with caminho.open(encoding="utf-8") as fh:
        linhas = list(csv.DictReader(fh))
    if not linhas:
        raise SystemExit("csv vazio: %s" % caminho)

    series = {s: _serie(linhas, s) for s in BRACOS}
    for s, serie in series.items():
        if len(serie) < 2:
            raise SystemExit("braço %r com %d amostras — o dashboard estava de pé?"
                             % (s, len(serie)))

    ini = max(serie[0][0] for serie in series.values())
    fim = min(serie[-1][0] for serie in series.values())
    grade = []
    tw = ini
    while tw <= fim:
        a = _interp(series["timer"], tw)
        b = _interp(series["nn"], tw)
        if a is not None and b is not None:
            grade.append((tw, a, b, a - b))
        tw += passo

    derivas = [g[3] for g in grade]
    # ritmo médio de cada braço: s simulados por s de parede
    ritmo = {}
    for s, serie in series.items():
        dt_parede = serie[-1][0] - serie[0][0]
        dt_sim = serie[-1][1] - serie[0][1]
        ritmo[s] = (dt_sim / dt_parede) if dt_parede else float("nan")

    completos = {}
    for s in BRACOS:
        vals = [int(r["completed"]) for r in linhas
                if r["sim"] == s and r["status"] != "stopped" and r["completed"] not in ("", None)]
        completos[s] = vals[-1] if vals else 0

    # --- achado nº2: o placar compara `completed` sem olhar o `t` de cada braço.
    # Aqui o MESMO número sai das duas formas: no mesmo instante de PAREDE (o que
    # a tela faz) e no mesmo instante SIMULADO (o que seria correto).
    conta = {s: [(float(r["t_sim"]), int(r["completed"]))
                 for r in linhas
                 if r["sim"] == s and r["status"] != "stopped"
                 and r["completed"] not in ("", None)]
             for s in BRACOS}
    vies = {}
    if all(len(v) >= 2 for v in conta.values()):
        # (a) o que a tela compara: o último frame de cada braço, lado a lado
        tela_a, tela_b = conta["timer"][-1][1], conta["nn"][-1][1]
        # (b) o que seria correto: os dois no MESMO t simulado
        t_comum = min(conta["timer"][-1][0], conta["nn"][-1][0])
        just_a = _interp(conta["timer"], t_comum)
        just_b = _interp(conta["nn"], t_comum)
        vies = {
            "t_comum": t_comum,
            "tela": {"timer": tela_a, "nn": tela_b,
                     "vantagem_pct": (tela_b - tela_a) / tela_a * 100.0 if tela_a else float("nan")},
            "pareado": {"timer": just_a, "nn": just_b,
                        "vantagem_pct": (just_b - just_a) / just_a * 100.0 if just_a else float("nan")},
        }
        vies["vies_pp"] = vies["tela"]["vantagem_pct"] - vies["pareado"]["vantagem_pct"]

    res = {
        "vies_do_placar": vies,
        "arquivo": str(caminho),
        "frames": len(linhas),
        "parede_s": fim - ini,
        "ritmo_sim_por_parede": ritmo,
        "deriva_inicial_s": derivas[0] if derivas else float("nan"),
        "deriva_final_s": derivas[-1] if derivas else float("nan"),
        "deriva_max_abs_s": max((abs(d) for d in derivas), default=float("nan")),
        "deriva_media_s": statistics.fmean(derivas) if derivas else float("nan"),
        "monotona": all(derivas[i] <= derivas[i + 1] + 1e-9 for i in range(len(derivas) - 1))
                    if len(derivas) > 1 else False,
        "recupera": (min(derivas[len(derivas) // 2:]) < max(derivas[:len(derivas) // 2]) - 1.0)
                    if len(derivas) > 4 else False,
        "completed_final": completos,
        "grade": grade,
    }
    return res


def imprime(res: dict) -> None:
    print("=" * 72)
    print("DERIVA DE TEMPO SIMULADO ENTRE OS BRAÇOS  (t_timer − t_nn)")
    print("  arquivo: %s" % res["arquivo"])
    print("  frames: %d | parede pareada: %.0f s" % (res["frames"], res["parede_s"]))
    print("  ritmo (s simulado por s de parede): timer=%.4f  nn=%.4f"
          % (res["ritmo_sim_por_parede"]["timer"], res["ritmo_sim_por_parede"]["nn"]))
    print("-" * 72)
    print("  deriva inicial : %+8.1f s" % res["deriva_inicial_s"])
    print("  deriva final   : %+8.1f s" % res["deriva_final_s"])
    print("  |deriva| máx   : %8.1f s" % res["deriva_max_abs_s"])
    print("  deriva média   : %+8.1f s" % res["deriva_media_s"])
    print("  monótona (só cresce): %s | recupera em algum momento: %s"
          % (res["monotona"], res["recupera"]))
    print("  completed no fim: timer=%d  nn=%d"
          % (res["completed_final"]["timer"], res["completed_final"]["nn"]))
    v = res.get("vies_do_placar") or {}
    if v:
        print("-" * 72)
        print("  ACHADO Nº2 — o placar compara `completed` sem olhar o `t`:")
        print("    como a tela faz (último frame de cada braço): timer=%d  nn=%d  -> %+.2f%%"
              % (v["tela"]["timer"], v["tela"]["nn"], v["tela"]["vantagem_pct"]))
        print("    pareado no mesmo t=%.1f s simulado          : timer=%.1f  nn=%.1f  -> %+.2f%%"
              % (v["t_comum"], v["pareado"]["timer"], v["pareado"]["nn"],
                 v["pareado"]["vantagem_pct"]))
        print("    viés introduzido pela deriva: %+.2f pontos percentuais" % v["vies_pp"])
    print("-" * 72)
    print("  %8s %10s %10s %10s" % ("parede", "t_timer", "t_nn", "deriva"))
    grade = res["grade"]
    passo = max(1, len(grade) // 20)
    for tw, a, b, d in grade[::passo]:
        print("  %8.0f %10.1f %10.1f %+10.1f" % (tw, a, b, d))
    print("=" * 72, flush=True)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="ws://127.0.0.1:8000/ws")
    p.add_argument("--minutos", type=float, default=10.0)
    p.add_argument("--out", default=None, help="csv de saída da coleta")
    p.add_argument("--analisar", default=None, help="só analisa este csv (não coleta)")
    p.add_argument("--passo", type=float, default=10.0, help="grade de parede da análise (s)")
    a = p.parse_args(argv)

    if a.analisar:
        imprime(analisa(Path(a.analisar), a.passo))
        return 0

    out = Path(a.out) if a.out else Path("deriva.csv")
    n = asyncio.run(_coleta(a.url, a.minutos * 60.0, out))
    if n:
        imprime(analisa(out, a.passo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
