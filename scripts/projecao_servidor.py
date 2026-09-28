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
    p.add_argument("--ranking", default="results/feira/ranking.json",
                   help="arquivo do quadro de recordes ('' = só em memória)")
    # --- gamificação (docs/GAMIFICACAO.md). Tudo OPT-IN: sem estas flags o script se
    # comporta como antes. `--feira` liga o conjunto que a feira usa.
    p.add_argument("--feira", action="store_true",
                   help="preset da feira: --entrada web --abortar operador --resultado-s 12 "
                        "--ranking-dir results/feira --ranking-validade 30 --ritmo 2 --anuncia-ocioso "
                        "--grava results/jogo --repete-falha --seeds 100..111")
    p.add_argument("--entrada", choices=("teclado", "web"), default=None,
                   help="web = o teclado junto do projetor, lido pela página (FonteWeb) "
                        "+ o teclado do terminal, os dois ao mesmo tempo")
    p.add_argument("--abortar", choices=("start", "operador"), default=None,
                   help="operador = o START do visitante não aborta; Esc 3x/página abortam")
    p.add_argument("--resultado-s", type=float, default=None,
                   help="segundos da tela de RESULTADO (motor: 8; feira: 10)")
    p.add_argument("--ranking-dir", default=None,
                   help="pasta com um ranking_<dia>.json por dia (substitui --ranking)")
    p.add_argument("--repete-falha", action="store_true",
                   help="falha nossa (SUMO caiu) repete a seed para o mesmo visitante")
    p.add_argument("--ritmo", type=float, default=None,
                   help="segundos simulados por segundo de parede (1 = tempo real; "
                        "feira: 2). Só apresentação: a simulação não muda")
    p.add_argument("--anuncia-ocioso", action="store_true",
                   help="ao fim da tela de RESULTADO publica um placar de `ocioso`: a "
                        "projeção volta na hora em vez de esperar o vigia")
    p.add_argument("--ranking-validade", type=float, default=None, metavar="MIN",
                   help="minutos que uma marca conta no quadro (feira: 30; 0 = para sempre)")
    a = p.parse_args(argv)

    if a.feira:
        a.entrada = a.entrada or "web"
        a.abortar = a.abortar or "operador"
        a.resultado_s = 10.0 if a.resultado_s is None else a.resultado_s
        a.anuncia_ocioso = True
        a.ranking_dir = a.ranking_dir or "results/feira"
        a.grava = a.grava or "results/jogo"          # caminho_gravacao põe o /rodadas
        a.repete_falha = True
        a.ranking_validade = 30.0 if a.ranking_validade is None else a.ranking_validade
        a.ritmo = 2.0 if a.ritmo is None else a.ritmo
        if a.seeds == p.get_default("seeds"):
            a.seeds = ",".join(str(s) for s in range(100, 112))
    a.entrada = a.entrada or "teclado"
    a.abortar = a.abortar or "start"
    a.ritmo = 1.0 if a.ritmo is None else float(a.ritmo)

    from feira.contratos import cenario as resolve_cenario

    cen = resolve_cenario(a.cenario)
    cen.aplicar(forcar=True)          # ANTES de qualquer import de `sim`

    from feira.jogo.ranking import Ranking
    from feira.jogo.web import ArenaPublicada, EstadoProjecao, PublicadorProjecao, ServidorProjecao

    # O quadro de recordes sobrevive ao processo: a feira reinicia o jogo várias vezes
    # por dia e o público espera que o recorde da manhã ainda esteja lá à tarde.
    validade = a.ranking_validade * 60.0 if a.ranking_validade else None
    if a.ranking_dir:
        ranking = Ranking.do_dia(Path(a.ranking_dir), validade_s=validade)
    else:
        ranking = Ranking(Path(a.ranking) if a.ranking else None, validade_s=validade)
    estado = EstadoProjecao(cenario=cen, ranking=ranking, ritmo=a.ritmo)
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
    from feira.entrada import FonteComposta, FonteWeb, TecladoInput, linhas_do_mapa
    from feira.jogo.motor import MotorDoJogo

    seeds = tuple(int(s) for s in a.seeds.split(",") if s.strip())
    teclado = TecladoInput(12)
    if a.entrada == "web":
        # O teclado junto do projetor: a página captura as teclas e manda por WS; o
        # feedback (os 12 LEDs) volta pelo mesmo broadcast que o placar. O teclado do
        # terminal continua lido JUNTO — quem tiver o foco manda.
        fonte_web = FonteWeb(12, ao_feedback=estado.entrega)
        estado.fonte_web = fonte_web
        fonte = FonteComposta(fonte_web, teclado)
    else:
        fonte = teclado
    kw = {}
    if a.resultado_s is not None:
        kw["resultado_s"] = float(a.resultado_s)
    motor = MotorDoJogo(
        cen, fonte=fonte, publicador=pub, seeds=seeds,
        # O braço da rodada é sempre o HUMANO: é a corrida dele que a Arena roda aqui.
        arena=ArenaPublicada(ArenaSumo(), pub, braco="humano"),
        bracos=("timer",) if a.sem_rl else ("timer", "rl"),
        ao_vivo=not a.rapido, prefetch=not a.sem_prefetch,
        grava_em=Path(a.grava) if a.grava else None,
        abortar_por=a.abortar, repete_falha=a.repete_falha, ritmo=a.ritmo,
        anuncia_ocioso=a.anuncia_ocioso, **kw,
    )
    # Os ganchos do operador e o nível da próxima seed, para a tela e para `/operador`.
    estado.ao_abortar = motor.abortar
    estado.ao_pular = motor.pula_resultado
    estado.proxima_seed = lambda: motor.seed

    print("SmartTraffic — modo jogo com projeção (%s, janela de %g s)"
          % (cen.chave, motor.janela().duracao))
    for linha in linhas_do_mapa(fonte.n_botoes):
        print("    " + linha)
    if a.abortar == "operador":
        print("  ESPAÇO = começar   ·   Esc 3x em 1,5 s = abortar (operador)   ·   Ctrl-C = sair")
    else:
        print("  ESPAÇO = começar / abortar   ·   Ctrl-C = sair")
    if a.entrada == "web":
        print("  entrada WEB ligada: a página projetada lê o teclado (foco no navegador)")
    if a.ritmo != 1.0:
        print("  ritmo %gx: %g s simulados em %.0f s de relógio (só apresentação)"
              % (a.ritmo, motor.janela().duracao, motor.janela().duracao / a.ritmo))

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
