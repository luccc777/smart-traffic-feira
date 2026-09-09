"""projecao_servidor.py — a rodada da feira COM a projeção. O executável do A7.

`python -m feira.jogo` continua sendo a rodada no terminal (é o modo degradado do
modo degradado, e o A7 não mexe nele). Este script é a mesma rodada com a projeção
ligada: sobe o servidor de `feira.jogo.web`, liga o `publicador` do motor nele e
espelha os frames da Arena com `ArenaPublicada`.

    python scripts/projecao_servidor.py                    # rodada + projeção
    python scripts/projecao_servidor.py --auto --rodadas 1 # ensaio, sem esperar START
    python scripts/projecao_servidor.py --so-servidor      # só a projeção (dev/bancada)
    python scripts/projecao_servidor.py --porta 8080

Abra `http://127.0.0.1:8080/` na tela do projetor e aperte **F**.

POR QUE UM SCRIPT E NÃO UMA FLAG EM `feira/jogo/__main__.py`: as fronteiras de escrita
do A7 não incluem `__main__.py`. Quando o coordenador quiser, a flag `--projecao` lá é
três linhas (`from .web import ...`), e este script vira um atalho.

O cenário é aplicado ANTES de qualquer import de `sim` — os escalares do
`sim.environment.constants` congelam no import (a armadilha do C1).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="rodada da feira com a projeção ligada")
    p.add_argument("--cenario", default="aberta.maquete")
    p.add_argument("--seeds", default="100,101,102,103,104,105")
    p.add_argument("--rodadas", type=int, default=None)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--porta", type=int, default=8080)
    p.add_argument("--rapido", action="store_true", help="sem ritmo 1:1 (ensaio)")
    p.add_argument("--sem-rl", action="store_true", help="só o fantasma do timer")
    p.add_argument("--sem-prefetch", action="store_true")
    p.add_argument("--auto", action="store_true", help="não espera o START")
    p.add_argument("--so-servidor", action="store_true",
                   help="sobe só a projeção e fica servindo (bancada, contraste, bench)")
    p.add_argument("--grava", default=None)
    a = p.parse_args(argv)

    from feira.contratos import cenario as resolve_cenario

    cen = resolve_cenario(a.cenario)
    cen.aplicar(forcar=True)          # ANTES de qualquer import de `sim`

    from feira.jogo.web import ArenaPublicada, EstadoProjecao, PublicadorProjecao, ServidorProjecao

    estado = EstadoProjecao(cenario=cen)
    pub = PublicadorProjecao(estado)
    srv = ServidorProjecao(estado, host=a.host, porta=a.porta)
    if not srv.sobe():
        print("a projeção não subiu em 15 s — seguindo sem ela", file=sys.stderr)
    print("projeção em %s   (F = tela cheia · I = régua de bancada)" % srv.url)

    if a.so_servidor:
        print("modo --so-servidor: Ctrl-C para sair")
        try:
            while True:
                import time

                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            srv.desce()
        return 0

    from feira.arena import ArenaSumo
    from feira.entrada import TecladoInput, linhas_do_mapa
    from feira.jogo.motor import MotorDoJogo

    seeds = tuple(int(s) for s in a.seeds.split(",") if s.strip())
    fonte = TecladoInput(12)
    motor = MotorDoJogo(
        cen, fonte=fonte, publicador=pub, seeds=seeds,
        # O braço da rodada é sempre o HUMANO: é a corrida dele que a Arena roda aqui.
        arena=ArenaPublicada(ArenaSumo(), pub, braco="humano"),
        bracos=("timer",) if a.sem_rl else ("timer", "rl"),
        ao_vivo=not a.rapido, prefetch=not a.sem_prefetch,
        grava_em=Path(a.grava) if a.grava else None,
    )

    print("SmartTraffic — modo jogo com projeção (%s, janela de %g s)"
          % (cen.chave, motor.janela().duracao))
    for linha in linhas_do_mapa(fonte.n_botoes):
        print("    " + linha)
    print("  ESPAÇO = começar / abortar   ·   Ctrl-C = sair")

    feitas = 0
    try:
        while a.rodadas is None or feitas < a.rodadas:
            print("\n[ocioso] seed da vez: %d — ESPAÇO para começar" % motor.seed)
            if not a.auto and not motor.espera_start(timeout=None):
                break
            r = motor.rodada()
            feitas += 1
            print("rodada %d: seed=%d humano=%s vencedor=%s%s"
                  % (feitas, r.seed, r.humano.entregues if r.humano else "-",
                     r.vencedor, "  [%s]" % r.motivo if r.motivo else ""))
            pc = pub.percentis()
            print("  projeção: %d mensagens · %d descartadas · custo de publicar "
                  "p50 %.3f · p95 %.3f · p99 %.3f · máx %.3f ms (na chamada %d de %d)"
                  % (estado.recebidas, estado.descartadas, pc["p50"], pc["p95"],
                     pc["p99"], pc["max"], pc["max_na_chamada"], pc["n"]))
    except KeyboardInterrupt:
        print("\nencerrado pelo operador")
    finally:
        fonte.close()
        srv.desce()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
