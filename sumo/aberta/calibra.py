#!/usr/bin/env python3
"""Calibracao do regime da rede aberta: qual taxa de injecao poe a malha
CONGESTIONADA E ESTAVEL, e quanto tempo dura o transiente de enchimento.

O QUE ESTE SCRIPT MEDE (e por que cada numero)
==============================================
- **% parados** com o limiar da SIMILITUDE. O `getLastStepHaltingNumber` do SUMO
  usa 0,1 m/s FIXO. Nesta rede as velocidades estao /6, entao 0,1 m/s equivale a
  0,6 m/s da rede real: contaria como "parado" um carro andando a 2 km/h reais.
  O limiar correto aqui e 0,1/6 = 0,0167 m/s. Reportamos os DOIS (`parados` e
  `parados_01`) para o numero ser comparavel com o da Vila Olimpia sem truque.
- **velocidade media da rede**, em m/s de similitude e em km/h EQUIVALENTES da
  rede real (x6 x3,6). E a curva que denuncia o transiente: na large a
  velocidade caia de 10,2 para ~5,5 m/s e so entao estabilizava - 1200 s.
- **backlog de insercao** = quantos veiculos ja tinham `depart <= t` no arquivo e
  ainda NAO entraram. E o risco 2 do plano (travamento irreversivel): se cresce
  sem teto, a malha esta estrangulando a borda e a demanda deixou de ser a que o
  arquivo descreve.
- **ocupacao interna vs cotos**. Os 18 cotos guardam ~43% das vagas da rede: sem
  esse split, um numero global de "% parados" nao distingue "a malha congestionou"
  de "a fila de entrada encheu".

O PLANO DE SEMAFORO durante a calibracao e o TIMER FIXO de 27 s (=
`sim.environment.constants.BASELINE_GREEN`), uniforme, sem offset. E o
`warmup_plano="timer"` do `Cenario`, e o adversario declarado do projeto. O
programa `actuated` que o netconvert gera e substituido por um estatico via
TraCI - se ficasse atuado, a calibracao mediria um controlador que nenhum braco
da comparacao usa.

Uso:
    python calibra.py --varredura 600,900,1200,1500,1800 --end 1800 --seeds 42
    python calibra.py --taxa 1200 --end 3600 --seeds 42,43,44,45,46,47
    python calibra.py --taxa 1200 --end 3600 --seeds 42 --gui
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
_RAIZ = AQUI.parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

if "SUMO_HOME" in os.environ:
    sys.path.append(str(Path(os.environ["SUMO_HOME"]) / "tools"))
import traci  # noqa: E402

from feira.contratos import cenario as resolve_cenario  # noqa: E402
from feira.demanda import GeradorDemandaAberta  # noqa: E402

K_SIMILITUDE = 6.0
LIMIAR_PARADO = 0.1 / K_SIMILITUDE      # imagem de 0,1 m/s sob similitude
BASELINE_GREEN = 27                     # = sim.environment.constants.BASELINE_GREEN
YELLOW = 3
AMOSTRA_S = 10                          # passo de amostragem das series
SAIDA = AQUI / "calibracao"


# --------------------------------------------------------------------- plano fixo
def aplica_timer_fixo(verde: int = BASELINE_GREEN, amarelo: int = YELLOW) -> dict:
    """Troca o programa `actuated` de cada TL por um estatico verde/amarelo.

    Um ciclo = para cada fase verde do TL: `verde` s dela + `amarelo` s da fase
    amarela que a drena. Todos os TLs partem da fase 0 no mesmo instante: e o
    "timer uniforme, sem offset nem split" que o PLANO.md descreve como o baseline
    de hoje (e cuja fraqueza o agente A5 vai corrigir).
    """
    info = {}
    for tl in sorted(traci.trafficlight.getIDList()):
        logica = traci.trafficlight.getAllProgramLogics(tl)[0]
        estados = [p.state for p in logica.phases]
        verdes = [i for i, s in enumerate(estados)
                  if "g" in s.lower() and "y" not in s.lower()]
        fases = []
        for g in verdes:
            fases.append(traci.trafficlight.Phase(float(verde), estados[g]))
            for k in range(1, len(estados) + 1):        # 1o amarelo a frente
                j = (g + k) % len(estados)
                if "y" in estados[j].lower():
                    fases.append(traci.trafficlight.Phase(float(amarelo), estados[j]))
                    break
        nova = traci.trafficlight.Logic("timer%d" % verde, 0, 0, phases=fases)
        traci.trafficlight.setProgramLogic(tl, nova)
        traci.trafficlight.setPhase(tl, 0)
        info[tl] = len(verdes)
    return info


# ------------------------------------------------------------------------- run
def _agenda(rou: Path) -> list[float]:
    """Instantes de `depart` do arquivo, em ordem - para medir o backlog."""
    import re
    txt = rou.read_text(encoding="utf-8")
    return [float(x) for x in re.findall(r'depart="([0-9.]+)"', txt)]


def roda(taxa: float, seed: int, end_s: float, *, gui: bool = False,
         horizonte_s: float | None = None, verbose: bool = True) -> dict:
    """Uma run de calibracao. Devolve as series amostradas a cada `AMOSTRA_S`."""
    cen = resolve_cenario("aberta.maquete")
    # escreve_cfg=False: esta bancada gera demanda DESCARTAVEL em varias taxas
    # apontando para o MESMO `Cenario` canonico, e passa `-r` na linha de comando.
    # Com o cfg ligado ela sobrescreveria `config/maquete_aberta_s42.sumocfg` para
    # apontar para a demanda da ultima taxa varrida, e a proxima corrida da Arena
    # mediria essa - em silencio. Ver feira/demanda/config_seed.py.
    ger = GeradorDemandaAberta(veh_por_hora=taxa, escreve_cfg=False,
                               horizonte_s=horizonte_s or (end_s + 600.0))
    rou_dir = SAIDA / ("taxa%04d" % round(taxa))
    rou_dir.mkdir(parents=True, exist_ok=True)
    from dataclasses import replace
    cen_taxa = replace(cen, rou_pattern=str(rou_dir / "demanda_s{seed}.rou.xml"))
    man = ger.gera(cen_taxa, seed, forcar=True)
    rou = cen_taxa.rou_file(seed)
    agenda = _agenda(rou)

    binario = "sumo-gui" if gui else "sumo"
    exe = str(Path(os.environ["SUMO_HOME"]) / "bin" / binario)
    cmd = [exe, "-c", cen.sumocfg, "-r", str(rou), "--seed", str(seed),
           "--no-step-log", "true", "--duration-log.statistics", "true",
           "--end", str(end_s)]
    if gui:
        cmd += ["--start", "true", "--quit-on-end", "true",
                "--gui-settings-file", cen.view_file]

    t_parede = time.perf_counter()
    traci.start(cmd)
    aplica_timer_fixo()
    for vid in traci.simulation.getDepartedIDList():
        traci.vehicle.subscribe(vid, (traci.constants.VAR_SPEED,
                                      traci.constants.VAR_ROAD_ID))

    serie: list[dict] = []
    chegados = 0
    partidos = 0
    i_agenda = 0
    t = 0.0
    while t < end_s:
        traci.simulationStep()
        t = traci.simulation.getTime()
        novos = traci.simulation.getDepartedIDList()
        partidos += len(novos)
        for vid in novos:
            traci.vehicle.subscribe(vid, (traci.constants.VAR_SPEED,
                                          traci.constants.VAR_ROAD_ID))
        chegados += traci.simulation.getArrivedNumber()
        while i_agenda < len(agenda) and agenda[i_agenda] <= t:
            i_agenda += 1
        if t % AMOSTRA_S == 0:
            sub = traci.vehicle.getAllSubscriptionResults()
            # Veiculo EM teleporte devolve o INVALID_DOUBLE do TraCI (-1e9) em
            # getSpeed. Um unico deles arrasta a media da rede para -13 mil m/s
            # (aconteceu, medido). Filtrar e CONTAR, nunca so filtrar.
            itens = [(d[traci.constants.VAR_SPEED], d[traci.constants.VAR_ROAD_ID])
                     for d in sub.values()]
            invalidos = sum(1 for x, _ in itens if x < -1e6)
            itens = [x for x in itens if x[0] > -1e6]
            n = len(itens)
            v = [x for x, _ in itens]
            estradas = [e for _, e in itens]
            n_coto = sum(1 for e in estradas if "_B_" in e)
            parados = sum(1 for x in v if x < LIMIAR_PARADO)
            parados01 = sum(1 for x in v if x < 0.1)
            serie.append({
                "t": t,
                "ativos": n,
                "n_coto": n_coto,
                "n_interno": n - n_coto,
                "frac_parados": (parados / n) if n else 0.0,
                "frac_parados_01": (parados01 / n) if n else 0.0,
                "vel_media": (math.fsum(v) / n) if n else 0.0,
                "backlog": i_agenda - partidos,
                "chegados": chegados,
                "partidos": partidos,
                "em_teleporte": invalidos,
            })
    traci.close()
    parede = time.perf_counter() - t_parede

    res = {
        "taxa_veh_h": taxa, "seed": seed, "end_s": end_s,
        "n_veiculos_arquivo": man.n_veiculos, "demanda_sha": man.sha256,
        "chegados": chegados, "partidos": partidos,
        "backlog_final": serie[-1]["backlog"] if serie else 0,
        "parede_s": round(parede, 1),
        "x_tempo_real": round(end_s / parede, 1) if parede else 0.0,
        "serie": serie,
    }
    if verbose:
        _resumo(res)
    return res


# -------------------------------------------------------------------- analise
def janela(serie: list[dict], t0: float, t1: float) -> list[dict]:
    return [s for s in serie if t0 <= s["t"] <= t1]


def media(serie: list[dict], campo: str) -> float:
    return math.fsum(s[campo] for s in serie) / len(serie) if serie else 0.0


def binado(serie: list[dict], largura_s: float = 120.0) -> list[dict]:
    """Media por bloco de `largura_s`. O bloco final incompleto e DESCARTADO.

    Existe porque a serie crua oscila com o CICLO do semaforo (60 s): comparar
    amostras soltas mediria a fase do farol, nao o regime da malha.
    """
    blocos: dict[float, list[dict]] = {}
    for x in serie:
        blocos.setdefault(int(x["t"] // largura_s) * largura_s, []).append(x)
    if not blocos:
        return []
    esperado = max(len(v) for v in blocos.values())
    fora = []
    for t0 in sorted(blocos):
        xs = blocos[t0]
        if len(xs) < esperado:
            continue
        fora.append({"t": t0, "ativos": media(xs, "ativos"),
                     "vel_media": media(xs, "vel_media"),
                     "frac_parados": media(xs, "frac_parados"),
                     "backlog": media(xs, "backlog")})
    return fora


def detecta_warmup(serie: list[dict], *, tol: float = 0.05,
                   largura_s: float = 120.0) -> float | None:
    """Fim do transiente: o primeiro instante a partir do qual medir NAO
    contamina a media.

    Criterio (e a definicao operacional de warm-up neste projeto): o menor `t0`
    tal que a media de [t0, fim] da velocidade E da populacao ativa ja esta a
    menos de `tol` da media de REGIME (o ultimo terco da run). E o que warm-up
    significa na pratica - "de onde em diante posso comecar a janela sem que o
    enchimento puxe o numero" - e nao "onde a curva parece plana".

    Comparar bloco a bloco (o criterio ingenuo) nao serve: um unico bloco ruidoso
    perto do fim invalida todos os candidatos e a resposta vira `None`. Medido
    nesta rede: a oscilacao de regime bloco a bloco chega a 11% na populacao,
    enquanto o vies do enchimento sobre a MEDIA e o que se quer limitar.
    """
    b = binado(serie, largura_s)
    if len(b) < 6:
        return None
    cauda = b[len(b) * 2 // 3:]
    alvo_v, alvo_a = media(cauda, "vel_media"), media(cauda, "ativos")
    if alvo_v <= 0 or alvo_a <= 0:
        return None
    for i in range(len(b) - 2):
        resto = b[i:]
        if (abs(media(resto, "vel_media") - alvo_v) <= tol * alvo_v
                and abs(media(resto, "ativos") - alvo_a) <= tol * alvo_a):
            return b[i]["t"]
    return None


def _resumo(res: dict) -> None:
    s = res["serie"]
    if not s:
        print("sem amostras")
        return
    fim = s[len(s) // 2:]
    wu = detecta_warmup(s)
    print("taxa=%5.0f veh/h seed=%d | %.0f s em %.0f s de parede (%.0fx)"
          % (res["taxa_veh_h"], res["seed"], res["end_s"], res["parede_s"],
             res["x_tempo_real"]))
    print("  warmup detectado : %s" % ("%.0f s" % wu if wu is not None else "NAO estabilizou"))
    print("  2a metade: ativos %.0f (coto %.0f / interno %.0f) | parados %.1f%% "
          "(limiar 0,1: %.1f%%) | v %.3f m/s (= %.1f km/h reais)"
          % (media(fim, "ativos"), media(fim, "n_coto"), media(fim, "n_interno"),
             100 * media(fim, "frac_parados"), 100 * media(fim, "frac_parados_01"),
             media(fim, "vel_media"), media(fim, "vel_media") * K_SIMILITUDE * 3.6))
    print("  backlog: final %d | max %d | chegados %d de %d partidos"
          % (res["backlog_final"], max(x["backlog"] for x in s),
             res["chegados"], res["partidos"]))


# ----------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--taxa", type=float, default=None, help="veh/h de injecao")
    ap.add_argument("--varredura", type=str, default=None,
                    help="lista de taxas separadas por virgula")
    ap.add_argument("--seeds", type=str, default="42")
    ap.add_argument("--end", type=float, default=1800.0)
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--rotulo", type=str, default=None,
                    help="nome do .json de saida (default: automatico)")
    args = ap.parse_args(argv)

    taxas = ([float(x) for x in args.varredura.split(",")] if args.varredura
             else [args.taxa])
    if taxas == [None]:
        ap.error("passe --taxa ou --varredura")
    seeds = [int(x) for x in args.seeds.split(",")]

    SAIDA.mkdir(parents=True, exist_ok=True)
    todos = []
    for taxa in taxas:
        for seed in seeds:
            todos.append(roda(taxa, seed, args.end, gui=args.gui))
    rotulo = args.rotulo or ("varredura_end%d" % int(args.end))
    destino = SAIDA / ("%s.json" % rotulo)
    destino.write_text(json.dumps(todos, indent=1), encoding="utf-8")
    print("\nescrito: %s" % destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
