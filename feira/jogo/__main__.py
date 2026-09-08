"""`python -m feira.jogo` — a rodada jogável só com teclado, sem `pyserial`.

É o DoD (a) do agente A3 em forma executável, e é também o modo degradado da
feira: se a botoeira não subir e a projeção cair, o jogo continua acontecendo
neste terminal.

    python -m feira.jogo                       # aberta.maquete, seeds held-out
    python -m feira.jogo --rodadas 1           # uma rodada e sai
    python -m feira.jogo --rapido              # sem ritmo 1:1 (rodada em ~3 s)
    python -m feira.jogo --auto --rodadas 1    # ensaio: não espera o START
    python -m feira.jogo --seeds 100,101,102

O cenário é aplicado ANTES de qualquer import de `sim` — os escalares do
`sim.environment.constants` são congelados no import e mudar a env var depois
não muda nada, só mente (a armadilha documentada no C1).
"""
from __future__ import annotations

import argparse
import sys


def _barra(n: int, maximo: int, largura: int = 32) -> str:
    if maximo <= 0:
        return " " * largura
    cheio = int(round(largura * n / maximo))
    return "#" * cheio + "." * (largura - cheio)


def _desenha(placar: dict) -> None:
    linhas = placar.get("linhas") or []
    maximo = max([ln["entregues"] for ln in linhas] + [1])
    cab = "[%s] t=%6.1f  faltam %5.1f s" % (placar["fase"].upper(), placar["t"],
                                            placar["t_restante"])
    corpo = "  ".join("%s %4d" % (ln["rotulo"], ln["entregues"]) for ln in linhas)
    sys.stdout.write("\r%-38s %s" % (cab, corpo))
    if placar["fase"] == "resultado":
        sys.stdout.write("\n")
        for ln in linhas:
            sys.stdout.write("  %-12s %4d entregues  %s\n"
                             % (ln["rotulo"], ln["entregues"],
                                _barra(ln["entregues"], maximo)))
        venc = placar.get("vencedor")
        sys.stdout.write("  -> %s\n" % ("VENCEDOR: %s" % venc if venc
                                        else "empate / rodada sem vencedor"))
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="modo jogo da feira, no teclado")
    p.add_argument("--cenario", default="aberta.maquete")
    p.add_argument("--seeds", default="100,101,102,103,104,105")
    p.add_argument("--rodadas", type=int, default=None)
    p.add_argument("--rapido", action="store_true",
                   help="sem ritmo 1:1 — a rodada roda solta (para ensaio/teste)")
    p.add_argument("--sem-rl", action="store_true", help="só o fantasma do timer")
    p.add_argument("--sem-prefetch", action="store_true")
    p.add_argument("--grava", default=None, help="raiz onde salvar a gravação da rodada")
    p.add_argument("--auto", action="store_true",
                   help="não espera o START — para ensaio e para terminal sem console")
    a = p.parse_args(argv)

    from ..contratos import cenario as resolve_cenario

    cen = resolve_cenario(a.cenario)
    cen.aplicar(forcar=True)          # ANTES de qualquer import de `sim`

    from pathlib import Path

    from ..entrada import TecladoInput, linhas_do_mapa
    from .motor import MotorDoJogo

    seeds = tuple(int(s) for s in a.seeds.split(",") if s.strip())
    fonte = TecladoInput(12)
    motor = MotorDoJogo(
        cen, fonte=fonte, publicador=_desenha, seeds=seeds,
        bracos=("timer",) if a.sem_rl else ("timer", "rl"),
        ao_vivo=not a.rapido, prefetch=not a.sem_prefetch,
        grava_em=Path(a.grava) if a.grava else None,
    )

    print("SmartTraffic — modo jogo (%s, janela de %g s)"
          % (cen.chave, motor.janela().duracao))
    print("  teclas:")
    for linha in linhas_do_mapa(fonte.n_botoes):
        print("    " + linha)
    print("  ESPAÇO = começar / abortar   ·   Ctrl-C = sair")
    print("  grade: %s  (o botão enfileira intenção; ela vale no próximo tick)"
          % cen.restricoes.assinatura)

    feitas = 0
    try:
        while a.rodadas is None or feitas < a.rodadas:
            print("\n[ocioso] seed da vez: %d — ESPAÇO para começar" % motor.seed)
            if not a.auto and not motor.espera_start(timeout=None):
                break
            r = motor.rodada()
            feitas += 1
            print("rodada %d: seed=%d humano=%s vencedor=%s%s"
                  % (feitas, r.seed,
                     r.humano.entregues if r.humano else "-", r.vencedor,
                     "  [%s]" % r.motivo if r.motivo else ""))
    except KeyboardInterrupt:
        print("\nencerrado pelo operador")
    finally:
        fonte.close()
    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
