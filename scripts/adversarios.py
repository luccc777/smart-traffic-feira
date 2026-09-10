#!/usr/bin/env python
"""Campanha do A8 — milhares de rodadas de adversário roteirizado, headless.

    python scripts/adversarios.py --catalogo padrao --seeds 100-111 --reps 20 \
        --duracao 120 --procs 14 --saida results/a8/campanha_d120.json

O QUE UMA "RODADA" É AQUI
-------------------------
Exatamente a do modo jogo: aquecimento de 300 s com o plano comum, janela de
`--duracao` s, grade `di5/vm7/am3/mr0`, 12 botões. A única diferença é que quem
aperta é um `Roteirista` e não um visitante — e ele aperta pela MESMA camada
(C6 -> `ControladorHumano` -> Arena), nunca emitindo ação direto.

POR QUE PROCESSOS E NÃO THREADS
-------------------------------
`sim.environment.constants` lê env var no import e congela; `net_topology`,
`demand_controller` e `traffic_env` derivam dele no import. E `traci` é uma
conexão de módulo, singleton por processo: duas Arenas na mesma interpretação
disputam a sessão. Cada worker roda SEMPRE o mesmo cenário e reusa a Arena.

O QUE É CONFERIDO EM TODA RODADA
--------------------------------
`res.inseridos > 0` (via `feira.treino.avalia.roda_um`, que levanta
`CorridaVazia`), `res.sane()` e `feira.metricas.sinais_de_travamento`. Os três
viajam em cada linha do JSON — saúde nunca é reportada separada da métrica.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from feira.adversarios.bancada import (  # noqa: E402
    CENARIO_PADRAO,
    OPONENTES,
    chave_linha,
    chave_tarefa,
    semente_de,
    tarefa_segura,
)
from feira.adversarios.politicas import de_texto  # noqa: E402
from feira.treino.ambiente import seeds_de_texto  # noqa: E402

# O ruído de mão padrão: 5% das pressões pretendidas se perdem, 2% de chance por
# botão de uma pressão que ninguém quis. Sem isto, repetir a mesma seed com o
# mesmo adversário é COPIAR a rodada — e o intervalo de confiança sairia estreito
# por construção, o que é pior que não ter intervalo nenhum.
MAO = "@falha=0.05@extra=0.02"

CATALOGOS = {
    # A campanha principal: 16 adversários, todos com ruído de mão (menos os que
    # já são estocásticos por natureza, e o `parado`, que é o piso).
    "padrao": (
        ["parado"]
        + ["martelo" + MAO]
        + ["periodica:p=%d%s" % (p, MAO) for p in (2, 3, 4, 6)]
        + ["aleatoria:p=%g" % p for p in (0.02, 0.1, 0.35, 0.6, 0.85)]
        + ["arterial" + MAO]
        + ["gulosa_fila:k=4" + MAO, "gulosa_fila:k=12" + MAO]
        + ["gulosa_fase:f=1" + MAO,
           "gulosa_fase:f=1@lag=1" + MAO,
           "gulosa_fase:f=1@lag=1@mao=6" + MAO]
        + ["sabotador" + MAO]
    ),
    # As mesmas políticas SEM ruído — a prova de que repetição de adversário
    # determinístico é cópia, e a sensibilidade do resultado ao ruído de mão.
    "puros": ["parado", "martelo", "periodica:p=2", "periodica:p=3", "periodica:p=4",
              "periodica:p=6", "arterial", "gulosa_fila:k=4", "gulosa_fila:k=12",
              "gulosa_fase:f=1", "gulosa_fase:f=1@lag=1", "sabotador"],
    # O recorte que vai à varredura de duração (a pergunta 2 do A8). Três
    # adversários que cobrem a faixa: o martelo (o visitante ingênuo forte), a
    # gulosa de fila (o que um humano de fato consegue executar) e a gulosa de
    # fase (o oráculo, o teto). Varrer o catálogo inteiro em 4 durações custaria
    # 4x a campanha principal sem responder nada a mais.
    "duracao": ["martelo" + MAO, "gulosa_fila:k=4" + MAO, "gulosa_fase:f=1" + MAO],
}


def monta_tarefas(specs, seeds, reps: int, duracao: float, cenario: str,
                  *, oponentes=OPONENTES) -> list[dict]:
    """As tarefas da campanha. Oponentes primeiro (uma por seed) e depois o humano.

    Adversário SEM ruído roda `1` repetição por seed, não `reps`: repetir seria
    copiar a mesma rodada, e 200 cópias produzem um intervalo de confiança falso.
    """
    tarefas: list[dict] = []
    for braco in oponentes:
        for s in seeds:
            tarefas.append({"braco": braco, "seed": int(s), "duracao_s": float(duracao),
                            "cenario": cenario})
    for spec in specs:
        n_reps = int(reps) if not de_texto(spec).deterministica else 1
        for rep in range(n_reps):
            for s in seeds:
                tarefas.append({"braco": "humano", "spec": spec, "seed": int(s),
                                "rep": rep, "duracao_s": float(duracao),
                                "cenario": cenario})
    return tarefas


def roda(tarefas: list[dict], *, procs: int = 1, ao_terminar=None, jsonl: Path | None = None,
         tentativas: int = 3, por_filho: int = 0) -> tuple[list[dict], list[dict], list[str]]:
    """Roda as tarefas com RETENTATIVA e diário em disco.

    Duas coisas que a primeira versão não tinha, e as duas custaram uma campanha
    inteira cada:

    * **falha transitória do TraCI não pode derrubar a campanha.** Medido nesta
      máquina, com 14 processos: `struct.error: unpack requires a buffer of
      3 bytes` no meio de uma corrida, ~1 em 1200. Com `ex.map` isso propaga e
      mata as outras 2900 rodadas. Agora o erro volta como dado, o processo se
      limpa e a rodada é REFEITA num processo novo.
    * **o diário `.jsonl`**: cada rodada terminada é gravada na hora. Uma
      campanha interrompida retoma de onde parou (`--retomar`) em vez de
      recomeçar.

    `por_filho` recicla o worker a cada N tarefas. **O default é 0 (desligado), e
    isso é resultado medido, não preguiça:** com `max_tasks_per_child=25` esta
    campanha TRAVOU duas vezes — o pool parou de repor worker depois da primeira
    leva de reciclagem, ficou com 5 dos 10 processos e nunca mais entregou
    resultado (sem erro, sem SUMO vivo, CPU ocioso, 226 de 4128 rodadas feitas).
    A limpeza depois de falha já é feita por `bancada._reseta_processo`, que é o
    que a reciclagem existia para cobrir.
    """
    saida: list[dict] = []
    erros: list[str] = []
    pendentes = list(tarefas)
    diario = open(jsonl, "a", encoding="utf-8") if jsonl else None
    try:
        for tentativa in range(1, int(tentativas) + 1):
            if not pendentes:
                break
            if tentativa > 1:
                print("  retentativa %d: %d rodada(s) que falharam"
                      % (tentativa, len(pendentes)), flush=True)
            restam: list[dict] = []
            if procs <= 1:
                resultados = ((t, tarefa_segura(t)) for t in pendentes)
                for t, linha in resultados:
                    restam += _absorve(linha, t, saida, erros, diario, ao_terminar,
                                       len(tarefas))
            else:
                extra = {"max_tasks_per_child": int(por_filho)} if por_filho else {}
                with ProcessPoolExecutor(max_workers=int(procs), **extra) as ex:
                    futuros = {ex.submit(tarefa_segura, t): t for t in pendentes}
                    for fut in as_completed(futuros):
                        restam += _absorve(fut.result(), futuros[fut], saida, erros,
                                           diario, ao_terminar, len(tarefas))
            pendentes = restam
    finally:
        if diario:
            diario.close()
    return saida, pendentes, erros


def _absorve(linha, t, saida, erros, diario, ao_terminar, total) -> list[dict]:
    if linha.get("erro"):
        erros.append("%s -> %s" % (chave_tarefa(t), linha["erro"]))
        return [t]
    saida.append(linha)
    if diario:
        diario.write(json.dumps(linha, ensure_ascii=False) + "\n")
        diario.flush()
    if ao_terminar:
        ao_terminar(linha, len(saida), total)
    return []


def ja_feitas(jsonl: Path) -> tuple[list[dict], set[str]]:
    """As rodadas já gravadas no diário — para `--retomar` não refazer nada."""
    linhas: list[dict] = []
    if not Path(jsonl).exists():
        return linhas, set()
    for bruta in Path(jsonl).read_text(encoding="utf-8").splitlines():
        bruta = bruta.strip()
        if bruta:
            linhas.append(json.loads(bruta))
    return linhas, {chave_linha(x) for x in linhas}


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cenario", default=CENARIO_PADRAO)
    ap.add_argument("--seeds", default="100-111", help="held-out do projeto")
    ap.add_argument("--catalogo", default=None, choices=sorted(CATALOGOS))
    ap.add_argument("--adversarios", default=None,
                    help="lista separada por ';' (sobrepõe --catalogo)")
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--duracao", type=float, default=120.0)
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--sem-oponentes", action="store_true",
                    help="não remede rl/coordenado_c60/timer27 (já estão em disco)")
    ap.add_argument("--tentativas", type=int, default=3,
                    help="quantas vezes refazer uma rodada que falhou (TraCI transitório)")
    ap.add_argument("--por-filho", type=int, default=0,
                    help="tarefas por worker antes de reciclá-lo (0 = nunca; ver roda())")
    ap.add_argument("--retomar", action="store_true",
                    help="aproveita o diário .jsonl e só roda o que falta")
    ap.add_argument("--saida", default=None)
    a = ap.parse_args(argv)

    if a.adversarios:
        specs = [s.strip() for s in a.adversarios.split(";") if s.strip()]
    elif a.catalogo:
        specs = list(CATALOGOS[a.catalogo])
    else:
        ap.error("informe --catalogo ou --adversarios")
    for s in specs:                       # typo falha ANTES de 3 h de corrida
        de_texto(s)

    seeds = seeds_de_texto(a.seeds)
    oponentes = () if a.sem_oponentes else OPONENTES
    tarefas = monta_tarefas(specs, seeds, a.reps, a.duracao, a.cenario, oponentes=oponentes)
    destino = Path(a.saida) if a.saida else (
        RAIZ / "results" / "a8" / ("campanha_d%d.json" % int(a.duracao)))
    destino.parent.mkdir(parents=True, exist_ok=True)
    diario = destino.with_suffix(".jsonl")

    prontas: list[dict] = []
    if a.retomar:
        prontas, feitas = ja_feitas(diario)
        antes = len(tarefas)
        tarefas = [t for t in tarefas if chave_tarefa(t) not in feitas]
        print("retomando: %d de %d rodadas já no diário %s"
              % (antes - len(tarefas), antes, diario.name), flush=True)
    elif diario.exists():
        diario.unlink()

    print("campanha: %d adversários x %d seeds x até %d reps + %d oponentes = %d rodadas "
          "(duração %.0f s, %d procs)"
          % (len(specs), len(seeds), a.reps, len(oponentes), len(tarefas), a.duracao,
             a.procs), flush=True)

    t0 = time.perf_counter()
    vazias = []

    def _log(linha, i, n):
        if linha["inseridos"] <= 0:                     # cinto e suspensório
            vazias.append(linha)
        if i % 100 == 0 or i == n:
            print("  %5d/%d  %.0f s decorridos  (última: %s seed=%d entregues=%d)"
                  % (i, n, time.perf_counter() - t0, linha["controlador"],
                     linha["seed"], linha["entregues"]), flush=True)

    novas, faltando, erros = roda(tarefas, procs=a.procs, ao_terminar=_log, jsonl=diario,
                                  tentativas=a.tentativas, por_filho=a.por_filho)
    custo = time.perf_counter() - t0
    linhas = prontas + novas
    if vazias:
        raise SystemExit("ABORTADO: %d rodada(s) com inseridos=0 (malha vazia)" % len(vazias))
    if faltando:
        raise SystemExit(
            "ABORTADO: %d rodada(s) falharam em %d tentativas — o diário %s guarda as "
            "%d que deram certo, use --retomar.\n  %s"
            % (len(faltando), a.tentativas, diario.name, len(linhas), "\n  ".join(erros[-5:])))

    saida = {
        "meta": {
            "cenario": a.cenario,
            "seeds": list(seeds),
            "reps": int(a.reps),
            "duracao_s": float(a.duracao),
            "adversarios": specs,
            "oponentes": list(oponentes),
            "n_rodadas": len(linhas),
            "custo_parede_s": round(custo, 1),
            "procs": int(a.procs),
            "semente_exemplo": semente_de(specs[0], seeds[0], 0),
            # falha transitória do TraCI: quantas rodadas precisaram ser refeitas.
            # É número medido e vai publicado — foi ele que derrubou duas campanhas
            # inteiras antes de o laço ganhar retentativa.
            "rodadas_refeitas": len(erros),
            "erros_transitorios": erros[:20],
        },
        "linhas": linhas,
    }
    destino.write_text(json.dumps(saida, ensure_ascii=False), encoding="utf-8")
    print("%d rodadas em %.0f s de parede (%d refeitas) -> %s"
          % (len(linhas), custo, len(erros), destino), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
