#!/usr/bin/env python
"""Análise da campanha do A8 — P(humano vence) com intervalo, e a conta da duração.

    python scripts/adversarios_analise.py --entradas results/a8/campanha_d*.json \
        --saida results/a8/analise.json --md results/a8/tabelas.md

O INTERVALO DE CONFIANÇA É POR SEED, NÃO POR RODADA
---------------------------------------------------
As 240 rodadas de um adversário NÃO são 240 amostras independentes: elas são 12
seeds x 20 repetições, e duas repetições na mesma seed enfrentam a MESMA demanda.
Um intervalo binomial sobre 240 ensaios trataria isso como independente e sairia
estreito por construção — o erro que o pareamento deste projeto existe para não
cometer. Aqui o intervalo sai de um **bootstrap agrupado**: reamostra as seeds
com reposição e, dentro de cada seed sorteada, as repetições. O Wilson binomial
aparece ao lado, rotulado, só para mostrar o tamanho do erro que ele cometeria.

O QUE É "VENCER"
----------------
`entregues` do humano ESTRITAMENTE maior que o do oponente na mesma seed, mesma
janela, mesma demanda. Empate é empate e conta separado — na tela do jogo ele
aparece como "EMPATE", não como vitória de ninguém.

`tempo_medio_entregue` NÃO decide nada aqui, e a campanha mede por quê: um
adversário que trava a rede melhora essa média (os presos saem dela) — ver a
tabela do artefato de sobrevivência.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from feira.contratos import Chave, Janela, Resultado  # noqa: E402
from feira.contratos import cenario as resolve_cenario  # noqa: E402
from feira.estatistica import teste_pareado  # noqa: E402

# O ruído de jogada que o A3 mediu entre dois jogadores da MESMA habilidade,
# em rodadas de 120 s: dp de 3,39 carros. É o gatilho declarado da pergunta 2 —
# margem desta ordem faz a rodada individual virar moeda.
RUIDO_JOGADA_A3 = 3.39
BRACOS_OPONENTES = ("rl", "coordenado_c60", "timer27")

# O DETECTOR DE TRAVAMENTO QUE FUNCIONA NUMA JANELA DE 120 s.
#
# Medido nesta campanha: `sinais_de_travamento` com o limiar padrão (lacuna de
# sobrevivência > 25%) NÃO enxerga o farol congelado aqui — numa janela tão curta
# metade da população está censurada por construção e a lacuna sai NEGATIVA para
# todo mundo, inclusive para quem entrega um terço do que o timer entrega. E
# `Resultado.travou` nem pode disparar: o critério da Arena é 600 s sem chegada,
# mais que a rodada inteira. É a nota do C5 sobre limiar dependente de regime,
# acontecendo na prática.
#
# O que sobra, e vale: a malha está em REGIME, então a população ativa deveria
# ficar aproximadamente constante na janela. Crescimento sustentado é acúmulo, e
# acúmulo é a rede travando.
#
# MAS o crescimento ABSOLUTO não serve como limiar, e isto foi medido: nas seeds
# 103 e 107 a demanda sobe dentro da janela e TODOS os braços acumulam — o
# `coordenado_c60` chega a +37,5% na seed 107 sem nada de errado. Um limiar fixo
# sobre o crescimento acusaria o baseline de travar a rede.
#
# O sinal que funciona é PAREADO, como todo o resto deste projeto: o acúmulo do
# humano MENOS o acúmulo do braço de referência (`timer27`) na MESMA seed. Medido
# nas 4092 rodadas humanas de 120 s: adversário são fica entre −8 e +18 pontos
# percentuais; a família que congela o farol (parado, sabotador, arterial,
# aleatória rala) fica entre +26 e +71. O limiar de +20 pp cai no vazio entre os
# dois grupos, e a contagem de falso positivo nos braços de referência sai
# publicada ao lado.
LIMIAR_ACUMULO = 0.20


# ------------------------------------------------------------------ carga
def carrega(padroes) -> tuple[list[dict], list[dict]]:
    linhas, metas = [], []
    for padrao in padroes:
        for caminho in sorted(glob.glob(str(padrao))):
            d = json.loads(Path(caminho).read_text(encoding="utf-8"))
            meta = dict(d["meta"])
            meta["arquivo"] = caminho
            metas.append(meta)
            for linha in d["linhas"]:
                linha.setdefault("cenario", meta["cenario"])
                linhas.append(linha)
    if not linhas:
        raise SystemExit("nenhuma linha carregada de %r" % (list(padroes),))
    return linhas, metas


_SHA: dict[tuple[str, int], str] = {}


def _sha(cenario: str, seed: int) -> str:
    """O sha da demanda desta seed — o campo que fecha a `Chave` (C5).

    Recalculado do arquivo em vez de guardado no JSON de propósito: se a demanda
    em disco mudar, a `Chave` reconstruída deixa de bater e `comparar()` levanta,
    em vez de casar em silêncio números de dois regimes.
    """
    if (cenario, seed) not in _SHA:
        from feira.contratos import sha256_arquivo

        cen = resolve_cenario(cenario)
        _SHA[(cenario, seed)] = sha256_arquivo(cen.rou_file(int(seed)))
    return _SHA[(cenario, seed)]


def resultado_de(linha: dict) -> Resultado:
    """Reconstrói o `Resultado` (C5) da linha — para usar o `comparar()` oficial."""
    cen = resolve_cenario(linha["cenario"])
    chave = Chave.de(cen, int(linha["seed"]),
                     Janela(float(linha["t0"]), float(linha["t1"])),
                     _sha(linha["cenario"], int(linha["seed"])))
    return Resultado(
        chave=chave, controlador=linha["controlador"], entregues=int(linha["entregues"]),
        tempo_medio_entregue=float(linha["tempo_medio_entregue"]),
        tempo_medio_no_sistema=float(linha["tempo_medio_no_sistema"]),
        fila_media=float(linha["fila_media"]), espera_media=float(linha["espera_media"]),
        inseridos=int(linha["inseridos"]), ativos_fim=int(linha["ativos_fim"]),
        ativos_inicio=int(linha["ativos_inicio"]),
        backlog_insercao=int(linha["backlog_insercao"]), perdidos=int(linha["perdidos"]),
        travou=bool(linha["travou"]))


# ------------------------------------------------------------- estatística
def wilson(k: int, n: int, z: float = 1.959963985) -> tuple[float, float]:
    """Intervalo de Wilson — o binomial que IGNORA o agrupamento por seed."""
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1.0 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    meio = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centro - meio), min(1.0, centro + meio))


def bootstrap_agrupado(por_seed: dict[int, list[float]], *, n_boot: int = 5000,
                       semente: int = 20260908) -> tuple[float, float, float]:
    """(média, p2.5, p97.5) reamostrando SEEDS e depois repetições dentro delas.

    Duas repetições na mesma seed compartilham a demanda — a variância entre
    seeds é a que manda, e é ela que o intervalo tem que carregar.
    """
    seeds = sorted(por_seed)
    tamanhos = {len(por_seed[s]) for s in seeds}
    media = float(np.mean([np.mean(por_seed[s]) for s in seeds]))
    if len(seeds) < 2:
        return media, float("nan"), float("nan")
    rng = np.random.default_rng(semente)
    if len(tamanhos) == 1:                      # caminho rápido (o desenho da campanha)
        r = tamanhos.pop()
        mat = np.array([por_seed[s] for s in seeds], dtype=float)      # (S, R)
        si = rng.integers(0, len(seeds), size=(n_boot, len(seeds)))
        ri = rng.integers(0, r, size=(n_boot, len(seeds), r))
        amostra = mat[si[:, :, None], ri]                              # (B, S, R)
        medias = amostra.mean(axis=(1, 2))
    else:
        medias = np.empty(n_boot)
        for b in range(n_boot):
            si = rng.integers(0, len(seeds), size=len(seeds))
            vals = []
            for i in si:
                v = np.asarray(por_seed[seeds[i]], dtype=float)
                vals.append(v[rng.integers(0, len(v), size=len(v))].mean())
            medias[b] = float(np.mean(vals))
    return media, float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5))


# ---------------------------------------------------------------- pareamento
def indexa(linhas: list[dict]) -> tuple[dict, dict]:
    """(oponentes por (braço, duração, seed), rodadas humanas por (spec, duração))."""
    oponentes: dict[tuple[str, float, int], dict] = {}
    humanos: dict[tuple[str, float], list[dict]] = defaultdict(list)
    for linha in linhas:
        braco = linha.get("braco")
        dur = float(linha.get("duracao_s", linha["t1"] - linha["t0"]))
        if braco in BRACOS_OPONENTES:
            chave = (braco, dur, int(linha["seed"]))
            velho = oponentes.get(chave)
            if velho is not None and velho["entregues"] != linha["entregues"]:
                raise SystemExit(
                    "oponente %s seed=%d dur=%g medido DUAS vezes com resultados "
                    "diferentes (%d e %d) — determinismo quebrado, nada a comparar"
                    % (braco, linha["seed"], dur, velho["entregues"], linha["entregues"]))
            oponentes[chave] = linha
        elif braco == "humano":
            humanos[(linha["spec"], dur)].append(linha)
    return oponentes, humanos


def confronto(rodadas: list[dict], oponentes: dict, braco: str, dur: float) -> dict:
    """P(vitória) do adversário contra um oponente, com intervalo e margem."""
    vit: dict[int, list[float]] = defaultdict(list)
    emp: dict[int, list[float]] = defaultdict(list)
    marg: dict[int, list[float]] = defaultdict(list)
    faltando = set()
    for r in rodadas:
        alvo = oponentes.get((braco, dur, int(r["seed"])))
        if alvo is None:
            faltando.add(int(r["seed"]))
            continue
        d = int(r["entregues"]) - int(alvo["entregues"])
        s = int(r["seed"])
        vit[s].append(1.0 if d > 0 else 0.0)
        emp[s].append(1.0 if d == 0 else 0.0)
        marg[s].append(float(d))
    if not vit:
        return {"n": 0, "faltando": sorted(faltando)}
    p, lo, hi = bootstrap_agrupado(vit)
    _, lo_e, hi_e = bootstrap_agrupado(emp)
    m, m_lo, m_hi = bootstrap_agrupado(marg)
    n = sum(len(v) for v in vit.values())
    k = int(sum(sum(v) for v in vit.values()))
    todas = np.concatenate([np.asarray(v) for v in marg.values()])
    por_seed = {s: float(np.mean(v)) for s, v in marg.items()}
    return {
        "n": n, "n_seeds": len(vit), "vitorias": k,
        "p_vitoria": p, "ic95": [lo, hi],
        "p_empate": float(np.mean([np.mean(v) for v in emp.values()])),
        "ic95_empate": [lo_e, hi_e],
        "wilson_ingenuo": list(wilson(k, n)),
        "margem_media": m, "margem_ic95": [m_lo, m_hi],
        "margem_dp_rodada": float(np.std(todas, ddof=1)) if len(todas) > 1 else 0.0,
        "margem_dp_entre_seeds": (float(np.std(list(por_seed.values()), ddof=1))
                                  if len(por_seed) > 1 else 0.0),
        "seeds_vencidas": sorted(s for s, v in vit.items() if np.mean(v) > 0.5),
        "p_vitoria_por_seed": {str(s): float(np.mean(v)) for s, v in sorted(vit.items())},
        "margem_por_seed": {str(s): round(v, 2) for s, v in sorted(por_seed.items())},
        "faltando": sorted(faltando),
    }


def ruido_de_jogada(rodadas: list[dict]) -> dict:
    """O ruído de JOGADA: quanto duas rodadas do mesmo jogador, na mesma seed, diferem.

    É a medida direta do número que o A3 estimou em 3,39 carros com dois
    adversários de mesma habilidade. Aqui ela sai de dentro do próprio
    adversário: o desvio-padrão AGRUPADO das repetições dentro de cada seed
    (a demanda é a mesma; o que muda é só a mão), e o desvio da DIFERENÇA entre
    duas rodadas assim é `sqrt(2)` vezes isso.

    É o denominador da pergunta 2 do A8: margem menor que este número faz a
    rodada individual virar moeda, por mais "certa" que seja a média.
    """
    por_seed: dict[int, list[float]] = defaultdict(list)
    for r in rodadas:
        por_seed[int(r["seed"])].append(float(r["entregues"]))
    somas, gl = 0.0, 0
    for v in por_seed.values():
        if len(v) > 1:
            somas += float(np.var(v, ddof=1)) * (len(v) - 1)
            gl += len(v) - 1
    if gl == 0:
        return {"dp_intra_seed": None, "ruido_jogada": None, "gl": 0}
    dp = math.sqrt(somas / gl)
    return {"dp_intra_seed": dp, "ruido_jogada": math.sqrt(2.0) * dp, "gl": gl}


def crescimento_relativo(r: dict) -> float:
    """`(ativos_fim - ativos_inicio) / ativos_inicio` — o acúmulo da janela."""
    base = max(1, int(r["ativos_inicio"]))
    return (int(r["ativos_fim"]) - int(r["ativos_inicio"])) / base


def saude(rodadas: list[dict], *, limiar_acumulo: float = LIMIAR_ACUMULO,
          referencia: dict | None = None) -> dict:
    """A contabilidade que nunca pode ser diluída na média."""
    cresc = np.array([r["ativos_fim"] - r["ativos_inicio"] for r in rodadas], dtype=float)
    rel = np.array([crescimento_relativo(r) for r in rodadas], dtype=float)
    ref = referencia or {}
    exc = np.array([crescimento_relativo(r) - ref.get(int(r["seed"]), 0.0)
                    for r in rodadas], dtype=float)
    fila = np.array([r["fila_media"] for r in rodadas], dtype=float)
    lac = np.array([r["lacuna"] if r["lacuna"] is not None else np.nan
                    for r in rodadas], dtype=float)
    return {
        "n": len(rodadas),
        "nao_sa": [(r["seed"], r.get("rep"), r["sane_motivo"]) for r in rodadas
                   if not r["sane"]],
        "com_sinais": [(r["seed"], r.get("rep"), r["sinais"]) for r in rodadas if r["sinais"]],
        "travou": sum(1 for r in rodadas if r["travou"]),
        "inseridos_min": int(min(r["inseridos"] for r in rodadas)),
        "backlog_max": int(max(r["backlog_insercao"] for r in rodadas)),
        "perdidos_max": int(max(r["perdidos"] for r in rodadas)),
        "conservacao_max_abs": int(max(abs(r["conservacao"]) for r in rodadas)),
        "crescimento_medio": float(cresc.mean()),
        "crescimento_max": float(cresc.max()),
        "crescimento_rel_medio": float(rel.mean()),
        "crescimento_rel_max": float(rel.max()),
        "acumulo_excedente_medio": float(exc.mean()),
        "acumulo_excedente_max": float(exc.max()),
        "acumulo_acima_do_limiar": int((exc > limiar_acumulo).sum()),
        "limiar_acumulo": float(limiar_acumulo),
        "fila_media": float(fila.mean()),
        "lacuna_media": float(np.nanmean(lac)) if np.isfinite(lac).any() else None,
        "entregues_medio": float(np.mean([r["entregues"] for r in rodadas])),
        "entregues_dp": (float(np.std([r["entregues"] for r in rodadas], ddof=1))
                         if len(rodadas) > 1 else 0.0),
        "tempo_medio_entregue": float(np.mean([r["tempo_medio_entregue"] for r in rodadas])),
        "tempo_medio_no_sistema": float(np.mean([r["tempo_medio_no_sistema"] for r in rodadas])),
    }


def pareado_determinista(rodadas: list[dict], oponentes: dict, braco: str,
                         dur: float, campos=("entregues", "fila_media",
                                             "tempo_medio_no_sistema")) -> dict:
    """t-test pareado por seed — só vale quando há UMA rodada por seed.

    Usa `feira.estatistica.teste_pareado`, que passa por `contratos.comparar` —
    o ponto único onde uma vantagem percentual nasce neste repo.
    """
    por_seed = defaultdict(list)
    for r in rodadas:
        por_seed[int(r["seed"])].append(r)
    if any(len(v) != 1 for v in por_seed.values()):
        return {}
    pares = []
    for s, (r,) in sorted(por_seed.items()):
        alvo = oponentes.get((braco, dur, s))
        if alvo is None:
            return {}
        pares.append((resultado_de(alvo), resultado_de(r)))
    saida = {}
    for campo in campos:
        t = teste_pareado(pares, campo)
        saida[campo] = {"base": t.base_media, "novo": t.novo_media,
                        "delta_pct": t.delta_pct, "vitorias": t.vitorias,
                        "n_seeds": t.n_seeds, "p": t.p}
    return saida


# ------------------------------------------------------------------ relatório
def analisa(linhas: list[dict], *, n_boot: int = 5000) -> dict:
    oponentes, humanos = indexa(linhas)
    # o acúmulo do braço de referência (`timer27`) por (duração, seed)
    base_acumulo: dict[float, dict[int, float]] = defaultdict(dict)
    for (braco, dur, seed), linha in oponentes.items():
        if braco == "timer27":
            base_acumulo[float(dur)][int(seed)] = crescimento_relativo(linha)
    ref = [linha for linha in oponentes.values()]
    saida = {"oponentes": {}, "adversarios": {}, "duracoes": sorted(
        {float(k[1]) for k in humanos}),
        "calibracao_acumulo": {
            "limiar": LIMIAR_ACUMULO,
            "n_referencia": len(ref),
            "crescimento_rel_max_referencia": (max(crescimento_relativo(x) for x in ref)
                                               if ref else None),
            "crescimento_rel_medio_referencia": (float(np.mean(
                [crescimento_relativo(x) for x in ref])) if ref else None),
            # falso positivo do limiar PAREADO nos próprios braços de referência
            "falsos_positivos_referencia": sum(
                1 for (b, dur, seed), x in oponentes.items()
                if b != "timer27" and (crescimento_relativo(x)
                                       - base_acumulo[float(dur)].get(int(seed), 0.0))
                > LIMIAR_ACUMULO),
            "n_referencia_pareavel": sum(1 for (b, _, _) in oponentes if b != "timer27")}}
    for (braco, dur, seed), linha in sorted(oponentes.items()):
        saida["oponentes"].setdefault("%s@%g" % (braco, dur), {})[str(seed)] = {
            "entregues": linha["entregues"], "fila_media": round(linha["fila_media"], 2),
            "controlador": linha["controlador"],
            "crescimento": linha["ativos_fim"] - linha["ativos_inicio"],
            "sinais": linha["sinais"], "sane": linha["sane"],
            "tempo_medio_entregue": round(linha["tempo_medio_entregue"], 1),
        }
    for (spec, dur), rodadas in sorted(humanos.items()):
        item = {"spec": spec, "duracao_s": dur, "n_rodadas": len(rodadas),
                "controlador": rodadas[0]["controlador"],
                "reps": len({r.get("rep") for r in rodadas}),
                "seeds": sorted({int(r["seed"]) for r in rodadas}),
                "saude": saude(rodadas, referencia=base_acumulo.get(float(dur))),
                "ruido": ruido_de_jogada(rodadas),
                "confrontos": {}, "pareado": {}}
        for braco in BRACOS_OPONENTES:
            c = confronto(rodadas, oponentes, braco, dur)
            if c.get("n"):
                item["confrontos"][braco] = c
                p = pareado_determinista(rodadas, oponentes, braco, dur)
                if p:
                    item["pareado"][braco] = p
        saida["adversarios"]["%s@%g" % (spec, dur)] = item
    return saida


def _fmt_pct(x) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else "%.1f%%" % (100 * x)


def tabela_confronto(an: dict, braco: str, dur: float) -> str:
    linhas = ["| adversário | n | P(vitória) | IC95 agrupado | (Wilson ingênuo) | "
              "margem média | dp entre seeds | seeds vencidas |",
              "|---|---|---|---|---|---|---|---|"]
    itens = [(k, v) for k, v in an["adversarios"].items()
             if v["duracao_s"] == dur and braco in v["confrontos"]]
    itens.sort(key=lambda kv: -kv[1]["confrontos"][braco]["p_vitoria"])
    for _, v in itens:
        c = v["confrontos"][braco]
        linhas.append("| `%s` | %d | **%s** | [%s, %s] | [%s, %s] | %+.2f | %.2f | %d/%d |"
                      % (v["spec"], c["n"], _fmt_pct(c["p_vitoria"]),
                         _fmt_pct(c["ic95"][0]), _fmt_pct(c["ic95"][1]),
                         _fmt_pct(c["wilson_ingenuo"][0]), _fmt_pct(c["wilson_ingenuo"][1]),
                         c["margem_media"], c["margem_dp_entre_seeds"],
                         len(c["seeds_vencidas"]), c["n_seeds"]))
    return "\n".join(linhas)


def tabela_saude(an: dict, dur: float) -> str:
    linhas = ["| adversário | rodadas | entregues (dp) | fila | acúmulo excedente | "
              "lacuna média | não-sãs | `sinais` | travou | acúmulo>+20pp | backlog max |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    itens = [(k, v) for k, v in an["adversarios"].items() if v["duracao_s"] == dur]
    itens.sort(key=lambda kv: -kv[1]["saude"]["entregues_medio"])
    for _, v in itens:
        s = v["saude"]
        linhas.append("| `%s` | %d | %.1f (%.1f) | %.1f | %+.0f%% | %s | %d | %d | %d | %d | %d |"
                      % (v["spec"], s["n"], s["entregues_medio"], s["entregues_dp"],
                         s["fila_media"], 100 * s["acumulo_excedente_medio"],
                         "%.1f%%" % s["lacuna_media"] if s["lacuna_media"] is not None else "—",
                         len(s["nao_sa"]), len(s["com_sinais"]), s["travou"],
                         s["acumulo_acima_do_limiar"], s["backlog_max"]))
    return "\n".join(linhas)


def tabela_duracao(an: dict, spec: str, braco: str = "rl") -> str:
    """A conta da duração: sinal (margem) contra ruído DE JOGADA, por duração.

    A coluna que decide é a última. Ruído de jogada é o desvio da diferença entre
    duas rodadas do MESMO jogador na MESMA seed (§ `ruido_de_jogada`): abaixo dele
    a rodada individual é moeda, por mais rodadas que a média tenha atrás.
    """
    linhas = ["| duração | n | P(vitória) | IC95 | margem média | dp da margem | "
              "ruído de jogada | \\|margem\\|/ruído |",
              "|---|---|---|---|---|---|---|---|"]
    for dur in an["duracoes"]:
        v = an["adversarios"].get("%s@%g" % (spec, dur))
        if not v or braco not in v["confrontos"]:
            continue
        c = v["confrontos"][braco]
        ruido = (v.get("ruido") or {}).get("ruido_jogada")
        linhas.append("| %.0f s | %d | %s | [%s, %s] | %+.2f | %.2f | %s | %s |"
                      % (dur, c["n"], _fmt_pct(c["p_vitoria"]), _fmt_pct(c["ic95"][0]),
                         _fmt_pct(c["ic95"][1]), c["margem_media"], c["margem_dp_rodada"],
                         "%.2f" % ruido if ruido else "—",
                         "%.2f" % (abs(c["margem_media"]) / ruido) if ruido else "—"))
    return "\n".join(linhas)


def tabela_artefato(an: dict, dur: float) -> str:
    """A armadilha nº3, medida: quem trava a rede MELHORA o tempo médio de viagem."""
    linhas = ["| adversário | entregues | tempo médio ENTREGUE | tempo no SISTEMA | fila |",
              "|---|---|---|---|---|"]
    itens = [(k, v) for k, v in an["adversarios"].items() if v["duracao_s"] == dur]
    itens.sort(key=lambda kv: kv[1]["saude"]["tempo_medio_entregue"])
    for _, v in itens:
        s = v["saude"]
        linhas.append("| `%s` | %.1f | **%.1f s** | %.1f s | %.1f |"
                      % (v["spec"], s["entregues_medio"], s["tempo_medio_entregue"],
                         s["tempo_medio_no_sistema"], s["fila_media"]))
    return "\n".join(linhas)


def tabela_por_seed(an: dict, linhas: list[dict], spec: str, dur: float) -> str:
    """Seed a seed: os três oponentes contra o adversário em foco.

    A tabela agregada esconde a coisa que decide a feira — **em que seeds** o
    humano ganha. Se as vitórias se concentram em poucas seeds, a escolha da
    seed da demo vira parâmetro de dificuldade, e isso é decisão do dono.
    """
    v = an["adversarios"].get("%s@%g" % (spec, dur))
    if not v:
        return "(sem dados para %s@%g)" % (spec, dur)
    por_seed: dict[int, list[float]] = defaultdict(list)
    for r in linhas:
        if r.get("braco") == "humano" and r.get("spec") == spec and \
                float(r.get("duracao_s", -1)) == dur:
            por_seed[int(r["seed"])].append(float(r["entregues"]))
    op = an["oponentes"]
    out = ["| seed | RL | c60 | timer27 | `%s` média (min–max) | P(vitória) na seed | "
           "margem |" % spec, "|---|---|---|---|---|---|---|"]
    for s in sorted(por_seed):
        vals = np.asarray(por_seed[s])
        rl = op.get("rl@%g" % dur, {}).get(str(s), {}).get("entregues")
        c60 = op.get("coordenado_c60@%g" % dur, {}).get(str(s), {}).get("entregues")
        t27 = op.get("timer27@%g" % dur, {}).get(str(s), {}).get("entregues")
        pv = v["confrontos"].get("rl", {}).get("p_vitoria_por_seed", {}).get(str(s))
        marg = v["confrontos"].get("rl", {}).get("margem_por_seed", {}).get(str(s))
        out.append("| %d | %s | %s | %s | %.1f (%d–%d) | %s | %s |"
                   % (s, rl, c60, t27, vals.mean(), vals.min(), vals.max(),
                      _fmt_pct(pv) if pv is not None else "—",
                      "%+.2f" % marg if marg is not None else "—"))
    return "\n".join(out)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--foco", default=None, help="spec do adversário da tabela seed a seed")
    ap.add_argument("--entradas", nargs="+", default=[str(RAIZ / "results" / "a8" / "campanha_*.json")])
    ap.add_argument("--saida", default=str(RAIZ / "results" / "a8" / "analise.json"))
    ap.add_argument("--md", default=str(RAIZ / "results" / "a8" / "tabelas.md"))
    ap.add_argument("--duracao", type=float, default=120.0, help="duração das tabelas principais")
    ap.add_argument("--boot", type=int, default=5000)
    a = ap.parse_args(argv)

    linhas, metas = carrega(a.entradas)
    print("%d rodadas de %d arquivo(s)" % (len(linhas), len(metas)))
    an = analisa(linhas, n_boot=a.boot)
    an["meta"] = {"arquivos": [m["arquivo"] for m in metas],
                  "n_linhas": len(linhas), "ruido_jogada_a3": RUIDO_JOGADA_A3}

    partes = []
    for braco in BRACOS_OPONENTES:
        partes.append("### P(vitória) contra `%s` — janela de %.0f s\n\n%s"
                      % (braco, a.duracao, tabela_confronto(an, braco, a.duracao)))
    partes.append("### Saúde por adversário — janela de %.0f s\n\n%s"
                  % (a.duracao, tabela_saude(an, a.duracao)))
    partes.append("### O artefato de sobrevivência, medido — janela de %.0f s\n\n%s"
                  % (a.duracao, tabela_artefato(an, a.duracao)))
    if a.foco:
        partes.append("### Seed a seed — `%s` na janela de %.0f s\n\n%s"
                      % (a.foco, a.duracao, tabela_por_seed(an, linhas, a.foco, a.duracao)))
    if len(an["duracoes"]) > 1:
        for spec in sorted({v["spec"] for v in an["adversarios"].values()}):
            tab = tabela_duracao(an, spec)
            if tab.count("\n") > 2:
                partes.append("### Duração — `%s` contra a RL\n\n%s" % (spec, tab))
    texto = "\n\n".join(partes) + "\n"
    Path(a.md).parent.mkdir(parents=True, exist_ok=True)
    Path(a.md).write_text(texto, encoding="utf-8")
    Path(a.saida).write_text(json.dumps(an, ensure_ascii=False, indent=1), encoding="utf-8")
    print(texto)
    print("-> %s\n-> %s" % (a.saida, a.md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
