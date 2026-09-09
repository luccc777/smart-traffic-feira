"""projecao_bench.py — a medição da DoD (b): 180+ carros a 1 Hz sem perder quadro.

A DoD tem DOIS gargalos possíveis e eles não se medem do mesmo jeito, então este
script mede os dois separados e diz qual é qual:

  TRANSPORTE  (`--transporte`) — o caminho jogo -> servidor -> WebSocket -> cliente.
      Um produtor sintetiza frames com N veículos a 1 Hz, exatamente como a Arena faz,
      e M clientes contam o que chega. Sai: quadros perdidos, atraso ponta a ponta, e o
      PIOR TEMPO que o caminho do jogo pagou por publicar. Este último é o número que
      importa para a propriedade "a projeção é observador passivo": se ele crescer, é
      porque a projeção está cobrando do jogo.

  RENDER      (`--render`) — o custo de desenhar no navegador. Roda a página real em
      `?bench=N` (Chrome), lê o resultado de volta em `/api/bench`. O headless usa
      rasterização por software (SwiftShader), então o número que sai daqui é um PISO
      pessimista: o notebook da feira, com GPU, faz melhor. O número que vale para a
      DoD é o do NOTEBOOK DA FEIRA, e sai do mesmo `?bench=N` num navegador normal.

Uso:
    python scripts/projecao_bench.py                          # os dois
    python scripts/projecao_bench.py --transporte --carros 250 --segundos 60
    python scripts/projecao_bench.py --render --carros 250 --visivel
    python scripts/projecao_bench.py --json results/a7/bench.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CHROMES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def acha_chrome() -> str | None:
    for c in CHROMES:
        if os.path.exists(c):
            return c
    for nome in ("chrome", "msedge", "chromium"):
        achado = shutil.which(nome)
        if achado:
            return achado
    return None


def _veiculos(n: int, t: float) -> list[dict]:
    """N veículos plausíveis. O tamanho do JSON é o que pesa no transporte, e este é
    o mesmo shape que `ArenaSumo._frame` produz (id/x/y/angle/speed, 2 casas)."""
    saida = []
    for i in range(n):
        fase = (t * 0.7 + i * 0.37) % 100.0
        saida.append({"id": "v%d" % i,
                      "x": round(20.0 + 130.0 * (fase / 100.0), 2),
                      "y": round(5.0 + 80.0 * math.sin(fase * 0.06 + i), 2),
                      "angle": round((fase * 3.6 + i * 7) % 360.0, 1),
                      "speed": round(random.uniform(0.0, 1.9), 2)})
    return saida


def bench_transporte(carros: int, segundos: float, clientes: int,
                     porta: int) -> dict:
    from feira.contratos.frame import frame_wire
    from feira.jogo.web import EstadoProjecao, PublicadorProjecao, ServidorProjecao

    estado = EstadoProjecao()
    pub = PublicadorProjecao(estado)
    srv = ServidorProjecao(estado, porta=porta)
    if not srv.sobe():
        raise RuntimeError("o servidor não subiu")

    from websockets.sync.client import connect

    recebidos: list[list[tuple[float, float]]] = [[] for _ in range(clientes)]
    parar = threading.Event()
    conectados = threading.Event()
    prontos = [0]
    trava = threading.Lock()

    def ouvinte(idx: int) -> None:
        try:
            with connect("ws://127.0.0.1:%d/ws" % porta, open_timeout=10) as ws:
                with trava:
                    prontos[0] += 1
                    if prontos[0] >= clientes:
                        conectados.set()
                while not parar.is_set():
                    try:
                        bruto = ws.recv(timeout=1.0)
                    except TimeoutError:
                        continue
                    m = json.loads(bruto)
                    if (m.get("type") or m.get("tipo")) == "frame":
                        recebidos[idx].append((m["t"], time.perf_counter()))
        except Exception:
            pass

    threads = [threading.Thread(target=ouvinte, args=(i,), daemon=True)
               for i in range(clientes)]
    for t in threads:
        t.start()
    conectados.wait(timeout=10)
    time.sleep(0.3)

    # -------------------------------------------------- o produtor, a 1 Hz exato
    n_frames = int(segundos)
    custos_ms: list[float] = []
    enviados: dict[float, float] = {}
    t_ini = time.perf_counter()
    for k in range(n_frames):
        t_sim = 300.0 + k
        quadro = frame_wire("humano", t_sim, decisao=k, substep=0, politica="bench",
                            tls=[{"id": "t%d" % i, "state": "GGrr"} for i in range(12)],
                            veiculos=_veiculos(carros, t_sim),
                            heat={"l%d" % i: i % 9 for i in range(200)},
                            stats={"entregues": k * 2, "ativos": carros,
                                   "tempo_medio_entregue": 40.0, "fila_media": 9.0},
                            janela=(300.0, 420.0))
        t0 = time.perf_counter()
        pub(quadro)
        custos_ms.append((time.perf_counter() - t0) * 1e3)
        enviados[t_sim] = t0
        alvo = t_ini + (k + 1) * 1.0
        atraso = alvo - time.perf_counter()
        if atraso > 0:
            time.sleep(atraso)

    time.sleep(1.0)
    parar.set()
    for t in threads:
        t.join(timeout=2.0)
    srv.desce()

    por_cliente = []
    for lista in recebidos:
        ts = sorted(t for t, _ in lista)
        buracos = 0
        for i in range(1, len(ts)):
            buracos += int(round(ts[i] - ts[i - 1])) - 1
        lat = [(rec - enviados[t]) * 1e3 for t, rec in lista if t in enviados]
        por_cliente.append({
            "recebidos": len(lista), "buracos": buracos,
            "lat_p50_ms": round(statistics.median(lat), 3) if lat else None,
            "lat_max_ms": round(max(lat), 3) if lat else None,
        })

    return {
        "carros": carros, "segundos": segundos, "clientes": clientes,
        "frames_publicados": n_frames,
        "bytes_por_frame": len(json.dumps(quadro)),
        "publicacao_ms_p50": round(statistics.median(custos_ms), 4),
        "publicacao_ms_max": round(max(custos_ms), 4),
        "descartadas_no_servidor": estado.descartadas,
        "clientes_derrubados": estado.clientes_caidos,
        "por_cliente": por_cliente,
        "perdidos_total": sum(c["buracos"] for c in por_cliente),
    }


def bench_render(carros: int, segundos: float, porta: int, cenario: str,
                 visivel: bool) -> dict:
    from feira.contratos import cenario as resolve_cenario
    from feira.jogo.web import EstadoProjecao, ServidorProjecao

    exe = acha_chrome()
    if not exe:
        return {"erro": "Chrome/Edge não encontrado — rode `?bench=%d` à mão" % carros}

    cen = resolve_cenario(cenario)
    estado = EstadoProjecao(cenario=cen)
    srv = ServidorProjecao(estado, porta=porta)
    if not srv.sobe():
        raise RuntimeError("o servidor não subiu")

    perfil = Path(os.environ.get("TEMP", ".")) / ("st-bench-%d" % porta)
    url = "http://127.0.0.1:%d/?bench=%d&diag=1" % (porta, carros)
    # As três últimas flags são load-bearing no modo VISÍVEL: o Chrome PARA o
    # `requestAnimationFrame` de uma janela ocluída (atrás do terminal, por exemplo), e
    # sem elas a página simplesmente não desenha — o sintoma é "o navegador não publicou
    # medição", não um erro.
    args = [exe, "--user-data-dir=%s" % perfil, "--no-first-run",
            "--no-default-browser-check", "--disable-extensions", "--new-window",
            "--window-size=1920,1080", "--autoplay-policy=no-user-gesture-required",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling"]
    if not visivel:
        # `--headless=new` roda o Canvas2D por SOFTWARE. O número sai pessimista de
        # propósito: um piso é útil, um número otimista não é.
        args += ["--headless=new", "--disable-gpu"]
    args.append(url)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    fim = time.perf_counter() + segundos
    ultimo: dict = {}
    try:
        import urllib.request

        while time.perf_counter() < fim:
            time.sleep(1.0)
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/api/bench" % porta, timeout=2) as r:
                    d = json.loads(r.read())
                if not d.get("vazio"):
                    ultimo = d
            except Exception:
                pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        srv.desce()
        shutil.rmtree(perfil, ignore_errors=True)

    if not ultimo:
        return {"erro": "o navegador não publicou medição (rode com --visivel para ver)"}
    ultimo["headless"] = not visivel
    ultimo["nota"] = ("headless usa rasterização por software: este número é PISO, "
                      "não o do notebook da feira" if not visivel else
                      "navegador visível nesta máquina")
    return ultimo


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--transporte", action="store_true")
    p.add_argument("--render", action="store_true")
    p.add_argument("--carros", type=int, default=250)
    p.add_argument("--segundos", type=float, default=45.0)
    p.add_argument("--clientes", type=int, default=2)
    p.add_argument("--porta", type=int, default=8123)
    p.add_argument("--cenario", default="aberta.maquete")
    p.add_argument("--visivel", action="store_true",
                   help="abre o navegador de verdade (o número que vale para a DoD)")
    p.add_argument("--json", default=None, help="grava o resultado neste arquivo")
    a = p.parse_args(argv)

    fazer_t = a.transporte or not (a.transporte or a.render)
    fazer_r = a.render or not (a.transporte or a.render)

    saida: dict = {"quando": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "python": sys.version.split()[0]}
    if fazer_t:
        print("== TRANSPORTE (%d carros, %g s, %d clientes) =="
              % (a.carros, a.segundos, a.clientes))
        r = bench_transporte(a.carros, a.segundos, a.clientes, a.porta)
        saida["transporte"] = r
        print("  frame com %d carros = %d bytes" % (r["carros"], r["bytes_por_frame"]))
        print("  custo da publicação no caminho do jogo: p50 %.4f ms · máx %.4f ms"
              % (r["publicacao_ms_p50"], r["publicacao_ms_max"]))
        print("  descartadas no servidor: %d · clientes derrubados: %d"
              % (r["descartadas_no_servidor"], r["clientes_derrubados"]))
        for i, c in enumerate(r["por_cliente"]):
            print("  cliente %d: %d/%d frames · %d buracos · atraso p50 %s ms máx %s ms"
                  % (i, c["recebidos"], r["frames_publicados"], c["buracos"],
                     c["lat_p50_ms"], c["lat_max_ms"]))
    if fazer_r:
        print("== RENDER (%d carros, %g s) ==" % (a.carros, a.segundos))
        r = bench_render(a.carros, a.segundos, a.porta + 1, a.cenario, a.visivel)
        saida["render"] = r
        for k in sorted(r):
            if k != "ua":
                print("  %-22s %s" % (k, r[k]))

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(saida, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        print("gravado %s" % a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
