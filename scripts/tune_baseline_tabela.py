#!/usr/bin/env python3
"""Agrega a varredura do A5 em tabela — a do Apêndice A do maquete, desconfortável.

Lê os JSON de `results/a5/` (a varredura roda em vários processos, um arquivo por
seed × grupo), casa tudo por seed e imprime:

* a família inteira, ciclo a ciclo e degrau a degrau, com a coluna que PIORA;
* o teste pareado por seed contra o `timer27` — a referência é o adversário de
  hoje, não o melhor plano da família (comparar o melhor contra o melhor
  esconderia o tamanho do problema);
* travamento e sanidade por seed, fora das médias (regra 3 de
  `feira/estatistica.py`).

Uso:
    python scripts/tune_baseline_tabela.py results/a5/*.json
    python scripts/tune_baseline_tabela.py --md            # Markdown p/ o doc
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

REFERENCIA = "timer27"
CAMPOS = ("entregues", "tempo_medio_no_sistema", "tempo_medio_entregue", "fila_media")


def carrega(padroes: list[str]) -> dict[str, dict[int, dict]]:
    """`{plano: {seed: linha}}` — a última leitura de cada (plano, seed) vence."""
    por_plano: dict[str, dict[int, dict]] = {}
    arquivos: list[str] = []
    for p in padroes:
        arquivos.extend(sorted(glob.glob(p)))
    if not arquivos:
        raise SystemExit("nenhum JSON casou com %r" % padroes)
    for arq in arquivos:
        d = json.loads(Path(arq).read_text(encoding="utf-8"))
        for ln in d["linhas"]:
            por_plano.setdefault(ln["plano"], {})[int(ln["seed"])] = ln
    return por_plano


def _resultado(ln: dict):
    from feira.contratos import Chave, Janela, Resultado

    r = dict(ln["resultado"])
    k = r.pop("chave")
    chave = Chave(cenario=k["cenario"], seed=int(k["seed"]),
                  janela=Janela(**k["janela"]), demanda_sha=k["demanda_sha"],
                  restricoes=k["restricoes"])
    return Resultado(chave=chave, **r)


def _ordem(nome: str):
    grau = {"uniforme": 0, "onda": 1, "webster": 2, "coordenado": 3}
    if nome == REFERENCIA:
        return (-1, -1, nome)
    try:
        fam, c = nome.rsplit("_c", 1)
        return (int(c), grau.get(fam, 9), nome)
    except ValueError:
        return (10 ** 6, 9, nome)


def media(v):
    return sum(v) / len(v) if v else float("nan")


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("json", nargs="*", default=["results/a5/*.json"])
    p.add_argument("--md", action="store_true", help="saída em Markdown")
    p.add_argument("--ref", default=REFERENCIA)
    p.add_argument("--detalhe", default=None,
                   help="um plano: imprime seed a seed contra a referência")
    a = p.parse_args(argv)

    from feira.estatistica import pareia_por_chave, teste_pareado

    por_plano = carrega(a.json)
    if a.ref not in por_plano:
        raise SystemExit("referência %r não está nos dados (tem: %s)"
                         % (a.ref, ", ".join(sorted(por_plano))))
    seeds_ref = set(por_plano[a.ref])

    linhas = []
    for nome in sorted(por_plano, key=_ordem):
        dados = por_plano[nome]
        seeds = sorted(set(dados) & seeds_ref)
        if not seeds:
            continue
        base = [_resultado(por_plano[a.ref][s]) for s in seeds]
        novo = [_resultado(dados[s]) for s in seeds]
        try:
            pares = pareia_por_chave(base, novo)
        except Exception as e:
            print("!! %s: %s" % (nome, e))
            continue
        testes = {c: teste_pareado(pares, c) for c in CAMPOS}
        travou = sum(1 for s in seeds if dados[s]["travou"])
        nao_sa = sum(1 for s in seeds if not dados[s]["sane"][0])
        linhas.append({
            "plano": nome, "n": len(seeds), "travou": travou, "nao_sa": nao_sa,
            "vazao_h": media([dados[s]["entregues"] for s in seeds])
            / (novo[0].chave.janela.duracao / 3600.0),
            "t_sist": testes["tempo_medio_no_sistema"].novo_media,
            "d_t_sist": testes["tempo_medio_no_sistema"].delta_pct,
            "p_t_sist": testes["tempo_medio_no_sistema"].p,
            "v_t_sist": testes["tempo_medio_no_sistema"].vitorias,
            "fila": testes["fila_media"].novo_media,
            "d_fila": testes["fila_media"].delta_pct,
            "p_fila": testes["fila_media"].p,
            "v_fila": testes["fila_media"].vitorias,
            "d_ent": testes["entregues"].delta_pct,
            "v_ent": testes["entregues"].vitorias,
            "ativos_fim": media([dados[s]["ativos_fim"] for s in seeds]),
            "backlog": media([dados[s]["backlog_insercao"] for s in seeds]),
        })

    def fmtp(x):
        return "—" if x is None else ("%.1e" % x if x < 1e-3 else "%.3f" % x)

    if a.detalhe:
        if a.detalhe not in por_plano:
            raise SystemExit("plano %r não está nos dados" % a.detalhe)
        seeds = sorted(set(por_plano[a.detalhe]) & seeds_ref)
        print("%s  ×  %s   —   seed a seed" % (a.detalhe, a.ref))
        print("%5s | %18s | %18s | %14s | %12s" %
              ("seed", "entregues", "tempo no sistema", "fila", "espera"))
        for s in seeds:
            b, n = por_plano[a.ref][s], por_plano[a.detalhe][s]
            print("%5d | %8d %8d | %8.1f %8.1f | %6.2f %6.2f | %6.0f %6.0f  %s"
                  % (s, b["entregues"], n["entregues"],
                     b["tempo_medio_no_sistema"], n["tempo_medio_no_sistema"],
                     b["fila_media"], n["fila_media"],
                     b["espera_media"], n["espera_media"],
                     ("TRAVOU" if n["travou"] else "")))
        base = [_resultado(por_plano[a.ref][s]) for s in seeds]
        novo = [_resultado(por_plano[a.detalhe][s]) for s in seeds]
        pares = pareia_por_chave(base, novo)
        for campo in ("entregues", "tempo_medio_entregue", "tempo_medio_no_sistema",
                      "fila_media", "espera_media"):
            print("  " + teste_pareado(pares, campo).linha())
        print()

    if a.md:
        print("<!-- Δ na convenção do C5: POSITIVO = MELHOR que a referência, em"
              " toda coluna. -->")
        print("| plano | vazão/h | Δ+vazão | t. no sistema | Δ+ | vit | p | fila | Δ+ |"
              " vit | p | backlog | trava |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for x in linhas:
            print("| `%s` | %.0f | %+.1f%% | %.1f s | %+.1f%% | %d/%d | %s | %.2f | "
                  "%+.1f%% | %d/%d | %s | %.0f | %s |"
                  % (x["plano"], x["vazao_h"], x["d_ent"], x["t_sist"], x["d_t_sist"],
                     x["v_t_sist"], x["n"], fmtp(x["p_t_sist"]), x["fila"], x["d_fila"],
                     x["v_fila"], x["n"], fmtp(x["p_fila"]), x["backlog"],
                     ("**%d**" % x["travou"]) if x["travou"] else "0"))
    else:
        print("=" * 132)
        print("%-18s %2s %8s %9s %8s %5s %9s %8s %8s %5s %9s %8s %7s %7s %5s"
              % ("plano", "n", "vazão/h", "t_sist", "Δ+%", "vit", "p",
                 "fila", "Δ+%", "vit", "p", "Δ+vazão%", "at_fim", "backlog", "trava"))
        print("-" * 132)
        for x in linhas:
            print("%-18s %2d %8.0f %9.1f %+8.1f %5s %9s %8.2f %+8.1f %5s %9s %+8.1f "
                  "%7.0f %7.0f %5d"
                  % (x["plano"], x["n"], x["vazao_h"], x["t_sist"], x["d_t_sist"],
                     "%d/%d" % (x["v_t_sist"], x["n"]), fmtp(x["p_t_sist"]),
                     x["fila"], x["d_fila"], "%d/%d" % (x["v_fila"], x["n"]),
                     fmtp(x["p_fila"]), x["d_ent"], x["ativos_fim"], x["backlog"],
                     x["travou"]))
        print("=" * 132)
        print("`backlog` = veículos já agendados que NÃO conseguiram entrar até o fim da "
              "janela. É a versão\n     de rede aberta do artefato de sobrevivência (C5): "
              "fila baixa com backlog alto é fila que\n     ficou do lado de fora.")
        print("Δ+%% = ganho PAREADO por seed contra `%s`, na convenção do C5: "
              "POSITIVO é MELHOR em TODA coluna." % a.ref)
        print("       (em tempo e fila o sinal já vem invertido de "
              "`contratos.comparar`, o único lugar do repo onde nasce uma "
              "porcentagem.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
