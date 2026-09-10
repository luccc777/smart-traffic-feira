"""Avaliação pareada de uma política RL contra o `coordenado_c60`, pela Arena.

Este é o ÚNICO caminho de avaliação do agente A6, e a escolha não é de gosto:

* `sim.evaluation.policy_sim.evaluate_policy` e o `FixedTimerSim` do maquete
  pressupõem a FROTA FECHADA (N carros com keep-alive). Na rede aberta eles
  medem outra coisa — não há N, e "throughput" ali é a contagem de re-rotas.
* a `feira.arena.ArenaSumo` é o laço único do C4: mesmo aquecimento, mesma
  grade de decisão, mesma janela e a mesma `Chave` para os dois braços. É o que
  torna o par comparável.

`res.inseridos > 0` é conferido em TODA corrida. É barato e pega a classe de
falha que custou uma trilha inteira a este projeto: a Arena caindo num
`.sumocfg` sem `<route-files>`, rodando a malha VAZIA, com o diagnóstico ainda
reportando o caminho certo.

Uso:
    python -m feira.treino.avalia --ckpt results/rl/aberta_v1.pt \\
        --seeds 100-111 --procs 6 --janela 7200 --saida results/rl/heldout_v1.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from ..contratos import Janela, Resultado
from .ambiente import PLANO_BASELINE, cenario_variante, seeds_de_texto

__all__ = ["CorridaVazia", "avalia_seeds", "janela_de", "roda_par", "roda_um", "resumo_json"]

# As três métricas da DoD (a) + as duas que a §4.5 do BASELINE_ABERTO publica.
CAMPOS = ("entregues", "tempo_medio_no_sistema", "fila_media",
          "tempo_medio_entregue", "espera_media")
# As TRÊS que decidem o aceite: vazão, tempo no sistema e fila.
CAMPOS_DOD = ("entregues", "tempo_medio_no_sistema", "fila_media")


class CorridaVazia(RuntimeError):
    """A corrida não inseriu nenhum veículo — a malha rodou vazia.

    Sempre erro de configuração (o `.sumocfg` da seed não tem `<route-files>`,
    ou a demanda da seed não existe), nunca resultado. Levantar aqui é o que
    impede um zero silencioso de virar número publicado.
    """


def _confere_insercao(res: Resultado, rotulo: str) -> Resultado:
    if res.inseridos <= 0:
        raise CorridaVazia(
            "%s | %s inseriu 0 veículos: a malha rodou VAZIA. Confira o "
            "`.sumocfg` da seed (`<route-files>`) e a demanda em disco."
            % (rotulo, res.chave.descreve()))
    return res


def janela_de(cen, janela_s: float) -> Janela:
    """A janela que começa no fim do aquecimento MEDIDO do cenário.

    Não usa `janela_padrao` porque a duração aqui é do experimento (7200 s da
    metaestabilidade), não o `janela_eval_s` de 3600 s do C1.
    """
    t0 = float(cen.warmup_s or 0.0)
    return Janela(t0, t0 + float(janela_s))


def roda_um(cen, seed: int, controlador, janela: Janela, *, arena=None) -> Resultado:
    """Um braço, uma seed. Confere `inseridos > 0` — "não reclamou" não é prova."""
    from ..arena import ArenaSumo

    arena = arena or ArenaSumo()
    res = arena.roda(cen, int(seed), controlador, janela)
    return _confere_insercao(res, getattr(controlador, "nome", "braco"))


def roda_par(seed: int, ckpt: str, *, janela_s: float = 7200.0,
             plano: str = PLANO_BASELINE, decision_interval: int | None = None,
             min_green: int | None = None, max_red: float | None = None,
             nome_rl: str | None = None) -> tuple[Resultado, Resultado]:
    """Roda `coordenado_c60` e a política, na MESMA seed e na MESMA janela.

    Devolve `(base, novo)`. Os dois braços passam pelo mesmo aquecimento (o
    timer de `BASELINE_GREEN`, por `Cenario.warmup_plano`), então nenhum herda
    uma rede arrumada pelo concorrente.
    """
    cen = cenario_variante(decision_interval=decision_interval, min_green=min_green,
                           max_red=max_red)
    cen.aplicar(forcar=True)
    from ..arena import ArenaSumo
    from ..controladores import ControladorCoordenado, ControladorRL

    janela = janela_de(cen, janela_s)
    arena = ArenaSumo()
    base = roda_um(cen, seed, ControladorCoordenado(plano, nome="timer:coordenado_c60"),
                   janela, arena=arena)
    rl = ControladorRL(ckpt, nome=nome_rl or ("rl:%s" % Path(ckpt).stem))
    novo = roda_um(cen, seed, rl, janela, arena=arena)
    return base, novo


def _worker(args: dict) -> tuple[dict, dict]:
    """Entrada do processo filho. Devolve dicts (o `Resultado` volta reconstruído).

    Um processo por seed é o que a armadilha (4) exige: `sim.environment
    .constants` é singleton de processo, então paralelismo dentro de um processo
    é inseguro; entre processos, não.
    """
    base, novo = roda_par(
        int(args["seed"]), args["ckpt"], janela_s=float(args["janela_s"]),
        plano=args["plano"], decision_interval=args.get("decision_interval"),
        min_green=args.get("min_green"), max_red=args.get("max_red"),
        nome_rl=args.get("nome_rl"))
    return asdict(base), asdict(novo)


def _de_dict(d: dict) -> Resultado:
    from ..contratos import Chave

    ch = dict(d["chave"])
    ch["janela"] = Janela(**ch["janela"])
    d = dict(d)
    d["chave"] = Chave(**ch)
    return Resultado(**d)


def avalia_seeds(ckpt: str, seeds, *, janela_s: float = 7200.0, procs: int = 1,
                 plano: str = PLANO_BASELINE, decision_interval: int | None = None,
                 min_green: int | None = None, max_red: float | None = None,
                 nome_rl: str | None = None,
                 ao_terminar=None) -> tuple[list[Resultado], list[Resultado]]:
    """Roda o par em cada seed. `procs>1` distribui em processos separados."""
    tarefas = [{"seed": int(s), "ckpt": str(ckpt), "janela_s": float(janela_s),
                "plano": str(plano), "decision_interval": decision_interval,
                "min_green": min_green, "max_red": max_red, "nome_rl": nome_rl}
               for s in seeds]
    bases: list[Resultado] = []
    novos: list[Resultado] = []
    if procs <= 1:
        for t in tarefas:
            b, n = _worker(t)
            bases.append(_de_dict(b))
            novos.append(_de_dict(n))
            if ao_terminar:
                ao_terminar(bases[-1], novos[-1])
        return bases, novos

    with ProcessPoolExecutor(max_workers=int(procs)) as ex:
        for b, n in ex.map(_worker, tarefas):
            bases.append(_de_dict(b))
            novos.append(_de_dict(n))
            if ao_terminar:
                ao_terminar(bases[-1], novos[-1])
    return bases, novos


def resumo_json(bases: list[Resultado], novos: list[Resultado], *,
                campos=CAMPOS) -> dict:
    """`resumo_pareado` + a contabilidade de saúde, em JSON puro.

    Nenhum percentual é calculado aqui: eles vêm de `contratos.comparar`, o
    ponto único onde uma vantagem percentual nasce neste repo.
    """
    from ..estatistica import resumo_pareado
    from ..metricas import lacuna_sobrevivencia, sinais_de_travamento

    res = resumo_pareado(bases, novos, campos=tuple(campos))
    out = {
        "n_seeds": res["n_seeds"],
        "seeds": res["seeds"],
        "base": res["base"],
        "novo": res["novo"],
        "testes": {k: asdict(v) for k, v in res["testes"].items()},
        "saude_base": {"travamentos": res["saude_base"]["travamentos"],
                       "nao_sa": res["saude_base"]["nao_sa"]},
        "saude_novo": {"travamentos": res["saude_novo"]["travamentos"],
                       "nao_sa": res["saude_novo"]["nao_sa"]},
        "por_seed": [],
    }
    # O balanço de veículos entra por seed porque é ele que EXPLICA a vazão nesta
    # rede: `entregues = ativos_inicio + inseridos − ativos_fim − perdidos`, e
    # `ativos_inicio`/`inseridos` são praticamente iguais nos dois braços (mesmo
    # aquecimento, mesma demanda, backlog zero). Sobra `ativos_fim` — a população
    # presa no fim da janela — como única fonte de diferença de vazão. Sem estes
    # campos, "a vazão empatou" é uma observação sem mecanismo.
    balanco = ("inseridos", "ativos_inicio", "ativos_fim", "backlog_insercao", "perdidos")
    for b, n in zip(bases, novos):
        out["por_seed"].append({
            "seed": b.chave.seed,
            "base": {c: getattr(b, c) for c in tuple(campos) + balanco},
            "novo": {c: getattr(n, c) for c in tuple(campos) + balanco},
            "base_lacuna": _num(lacuna_sobrevivencia(b)),
            "novo_lacuna": _num(lacuna_sobrevivencia(n)),
            "novo_sinais": sinais_de_travamento(n),
            "base_sinais": sinais_de_travamento(b),
            "novo_sane": n.sane()[0], "base_sane": b.sane()[0],
            "novo_backlog": n.backlog_insercao, "base_backlog": b.backlog_insercao,
            "novo_travou": n.travou, "base_travou": b.travou,
        })
    # vitórias na DoD: em quantas seeds o `novo` ganha nas TRÊS métricas ao mesmo tempo
    from ..contratos import comparar

    trincas = 0
    for b, n in zip(bases, novos):
        d = comparar(b, n).deltas
        if all(d[c] > 0 for c in CAMPOS_DOD):
            trincas += 1
    out["vitorias_trinca"] = trincas
    return out


def _num(x: float):
    """`inf`/`nan` não são JSON válidos — viram `None` (e o motivo fica no sinal)."""
    return None if (x is None or math.isinf(x) or math.isnan(x)) else round(float(x), 4)


def imprime(res: dict) -> str:
    linhas = ["%s  vs  %s   (%d seeds: %s)"
              % (res["novo"], res["base"], res["n_seeds"], res["seeds"])]
    for campo, t in res["testes"].items():
        p = ("p=%.3g" % t["p"]) if t["p"] is not None else "p=n/a"
        linhas.append("  %-24s base=%9.3f  novo=%9.3f  %+7.2f%%  vitórias %d/%d  %s"
                      % (campo, t["base_media"], t["novo_media"], t["delta_pct"],
                         t["vitorias"], t["n_seeds"], p))
    linhas.append("  vitórias na TRINCA (%s): %d/%d"
                  % ("+".join(CAMPOS_DOD), res["vitorias_trinca"], res["n_seeds"]))
    for lado in ("base", "novo"):
        s = res["saude_%s" % lado]
        linhas.append("  saúde %-4s: travamentos=%d  não-sãs=%s"
                      % (lado, s["travamentos"], s["nao_sa"] or "nenhuma"))
    return "\n".join(linhas)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ckpt", required=True, help="checkpoint .pt da política")
    ap.add_argument("--seeds", default="100-111")
    ap.add_argument("--janela", type=float, default=7200.0, help="s da janela de medição")
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--plano", default=PLANO_BASELINE)
    ap.add_argument("--decision-interval", type=int, default=None)
    ap.add_argument("--min-green", type=int, default=None)
    ap.add_argument("--max-red", type=float, default=None)
    ap.add_argument("--nome", default=None, help="rótulo do braço RL no Resultado")
    ap.add_argument("--saida", default=None, help="JSON de saída")
    a = ap.parse_args(argv)

    seeds = seeds_de_texto(a.seeds)
    print("avaliando %s em %d seeds (janela %.0f s, %d proc)"
          % (a.ckpt, len(seeds), a.janela, a.procs), flush=True)

    def _log(b, n):
        print("  seed %3d | base entregues=%d fila=%.2f | rl entregues=%d fila=%.2f%s"
              % (b.chave.seed, b.entregues, b.fila_media, n.entregues, n.fila_media,
                 "  TRAVOU" if n.travou else ""), flush=True)

    bases, novos = avalia_seeds(a.ckpt, seeds, janela_s=a.janela, procs=a.procs,
                                plano=a.plano, decision_interval=a.decision_interval,
                                min_green=a.min_green, max_red=a.max_red,
                                nome_rl=a.nome, ao_terminar=_log)
    res = resumo_json(bases, novos)
    print(imprime(res))
    if a.saida:
        p = Path(a.saida)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(res)
        payload["ckpt"] = str(a.ckpt)
        payload["janela_s"] = a.janela
        payload["plano"] = str(a.plano)
        payload["restricoes"] = bases[0].chave.restricoes if bases else None
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print("saída em %s" % p, flush=True)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
