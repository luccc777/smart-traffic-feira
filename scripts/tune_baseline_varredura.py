#!/usr/bin/env python3
"""Varredura de sensibilidade do baseline coordenado (agente A5), na Arena real.

Roda a família de planos de `sumo/aberta/planos/` pelo MESMO laço da comparação
(`feira/arena/sumo.py`), na mesma janela e nas mesmas seeds, e grava tudo em
JSON — inclusive o que piorou.

POR QUE ISTO É UMA VARREDURA DE SENSIBILIDADE, E NÃO UMA BUSCA
--------------------------------------------------------------
A tentação, num projeto que compara RL contra baseline, é procurar o plano fixo
que faz a RL parecer melhor. O compromisso do §1 do `RESULTADOS_MAQUETE.md` é o
oposto: o baseline vai para o número na sua melhor versão defensável, e a
escolha do ponto de operação é justificada POR FORA (Webster / NACTO / CET),
não pelo resultado. Então:

* a varredura inteira é publicada, com a coluna que piora;
* o ponto escolhido é declarado ANTES de olhar qual venceria a RL;
* os três degraus (uniforme → +split → +offset) rodam sempre juntos, para o
  ganho de cada peça ficar separado do ganho do ciclo.

JANELA: 7200 s, NUNCA 3600
--------------------------
A 3800 veh/h as 6 seeds passam folgadas em 1 h e duas travam em 2 h
(`docs/CALIBRACAO_ABERTA.md` §3.4). Perto da capacidade esta malha é
metaestável, e uma hora mente. O default aqui é 7200 s.

Uso (SEMPRE em background — 7200 s × 6 seeds × N planos leva dezenas de minutos):
    python scripts/tune_baseline_varredura.py --planos familia --seeds 42 --dur 3600
    python scripts/tune_baseline_varredura.py --planos coordenado_c40,uniforme_c60 \
        --seeds 42,43,44,45,46,47 --dur 7200 --json results/a5_final.json
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

PLANOS = _RAIZ / "sumo" / "aberta" / "planos"
LONGA = PLANOS / "demanda_longa"
SAIDA = _RAIZ / "results" / "a5"

REFERENCIA = "timer27"          # o adversário de hoje: verde 27 s uniforme, sem offset

HORIZONTE_LONGO = 8400.0        # cobre a janela de 7200 s a partir de t0=300 com folga


def prepara_demanda_longa(cen, seeds: list[int], taxa: float = 3500.0):
    """Demanda com horizonte suficiente para uma janela de 7200 s. Devolve o `Cenario`.

    POR QUE A CANÔNICA NÃO SERVE PARA 7200 s — e este é um achado, não um detalhe
    de encanamento. Os `.rou.xml` de `sumo/aberta/demanda/` têm
    `horizonte_s = 5400`. Uma janela `[300, 7500]` passa 2100 s DEPOIS do último
    `depart` do arquivo: nesse trecho a malha só drena, e os dois braços acabam
    entregando literalmente todo mundo. Medido, seed 42, 7200 s na demanda
    canônica: `timer27` e `coordenado_c60` entregam **5017 cada um** — a vazão
    deixa de discriminar porque não sobrou demanda para discriminar.

    (É por isso que o `calibra.py` do agente A1 gera demanda própria com
    `horizonte_s = end + 600`: as runs de 7200 s da calibração nunca usaram os
    arquivos canônicos.)

    A demanda longa fica em `sumo/aberta/planos/demanda_longa/`, fora de
    `sumo/aberta/demanda/`, e o `.sumocfg` dela é DERIVADO do canônico (mesma
    receita do `feira/demanda/config_seed.py`), com os caminhos relativos
    recalculados para a nova pasta. O canônico não é tocado.

    Propriedade que torna as duas comparáveis (medida pelo A1): aumentar o
    horizonte só ACRESCENTA veículos no fim — a demanda de 5400 s é prefixo
    exato da de 8400 s, mesma seed, mesma taxa.
    """
    import xml.etree.ElementTree as ET
    from dataclasses import replace

    from feira.demanda import GeradorDemandaAberta
    from feira.demanda.config_seed import escreve_config_seed

    LONGA.mkdir(parents=True, exist_ok=True)
    canonico = Path(cen.sumocfg)
    base = LONGA / canonico.name
    texto = canonico.read_text(encoding="utf-8")
    # os caminhos do canônico são relativos a `config/`; aqui o cfg mora noutra
    # pasta, então cada um é reescrito relativo a ESTA. Sem isso o SUMO carregaria
    # `planos/demanda_longa/../network/...`, que não existe.
    for elem in ET.fromstring(texto).iter():
        v = elem.get("value")
        if elem.tag in ("net-file", "additional-files") and v:
            alvo = (canonico.parent / v).resolve()
            novo = os.path.relpath(alvo, LONGA).replace("\\", "/")
            texto = texto.replace('<%s value="%s"/>' % (elem.tag, v),
                                  '<%s value="%s"/>' % (elem.tag, novo))
    base.write_text(texto, encoding="utf-8", newline="\n")

    cen_longo = replace(cen, sumocfg=str(base),
                        rou_pattern=str(LONGA / "demanda_s{seed}.rou.xml"))
    ger = GeradorDemandaAberta(veh_por_hora=taxa, escreve_cfg=False,
                               horizonte_s=HORIZONTE_LONGO)
    mans = {}
    for s in seeds:
        man = ger.gera(cen_longo, s)
        escreve_config_seed(cen_longo, s, cen_longo.rou_file(s))
        mans[s] = man.sha256
    (LONGA / "MANIFESTO.json").write_text(
        json.dumps({"taxa_veh_h": taxa, "horizonte_s": HORIZONTE_LONGO,
                    "motivo": "janela de 7200 s não cabe na demanda canônica (5400 s)",
                    "sha256_por_seed": mans}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    return cen_longo


def confere_cfg_da_seed(cen, seed: int) -> None:
    """Falha ANTES de subir o SUMO se o `.sumocfg` desta seed não existir.

    Histórico, porque explica a guarda de `res.inseridos > 0` mais abaixo: até o
    conserto de 2026-09-07, `ArenaSumo.roda()` apontava `constants.SUMOCFG` para
    o arquivo da seed e logo depois chamava `self.topologia()`, que passava por
    `_aponta_constants` outra vez e devolvia o campo ao **canônico** — que não
    tem `<route-files>`, de propósito (`CALIBRACAO_ABERTA.md` §2.1.1). Resultado
    medido aqui, seed 42, janela de 900 s: **0 veículos inseridos**, `travou =
    True` nos três braços, e `ultimo_diagnostico["sumocfg"]` reportando o arquivo
    da seed — o diagnóstico afirmando o contrário do que a corrida fez.

    A varredura desviava disso entregando à Arena um `Cenario` cujo `sumocfg` já
    era o da seed. A Arena consertada resolve sozinha (e de forma idempotente,
    então o desvio continuaria funcionando), mas a guarda ficou: ela custa nada e
    é a única checagem que pega esta classe de falha DE FORA do laço.
    """
    base = Path(cen.sumocfg)
    if base.stem.endswith("_s%d" % int(seed)):
        return
    por_seed = base.with_name("%s_s%d%s" % (base.stem, int(seed), base.suffix))
    if not por_seed.exists():
        raise SystemExit(
            "falta %s — rode `python -m feira.demanda` antes da varredura." % por_seed)


def planos_da_familia(padrao: str) -> list[str]:
    if padrao == "familia":
        nomes = sorted(p.stem for p in PLANOS.glob("*.json"))
    elif padrao == "coordenados":
        nomes = sorted(p.stem for p in PLANOS.glob("coordenado_c*.json"))
    else:
        nomes = [x.strip() for x in padrao.split(",") if x.strip()]
    return nomes


def _ordena(nomes: list[str]) -> list[str]:
    """uniforme < webster < coordenado dentro de cada ciclo; ciclo crescente."""
    grau = {"uniforme": 0, "onda": 1, "webster": 2, "coordenado": 3}

    def chave(n: str):
        try:
            fam, c = n.rsplit("_c", 1)
            return (int(c), grau.get(fam, 9), n)
        except ValueError:
            return (10**6, 9, n)
    return sorted(nomes, key=chave)


def uma_corrida(arena, cen, seed, ctrl, janela, rotulo: str) -> dict:
    from feira.metricas import lacuna_sobrevivencia, sinais_de_travamento

    t0 = time.perf_counter()
    res = arena.roda(cen, seed, ctrl, janela)
    parede = time.perf_counter() - t0
    diag = dict(arena.ultimo_diagnostico)
    # GUARDA DA REDE VAZIA. O bug da §5.1 do docs/BASELINE_ABERTO.md faz a Arena
    # subir o `.sumocfg` canônico (sem `<route-files>`) e rodar sem UM carro,
    # reportando no diagnóstico o arquivo da seed — o diagnóstico mente, e um
    # plano "otimizado" contra tráfego zero é lixo com aparência de número. Vale
    # mesmo depois do conserto: custa nada e nunca mais deixa passar.
    if res.inseridos <= 0:
        raise SystemExit(
            "[%s] seed %d: ZERO veículos inseridos em %g s de janela. A Arena subiu "
            "a rede vazia — provavelmente o `.sumocfg` canônico no lugar do da seed "
            "(diag diz %r). NÃO use este número."
            % (rotulo, seed, janela.duracao, diag.get("sumocfg")))
    linha = {
        "plano": rotulo,
        "seed": int(seed),
        "controlador": res.controlador,
        "entregues": res.entregues,
        "tempo_medio_entregue": res.tempo_medio_entregue,
        "tempo_medio_no_sistema": res.tempo_medio_no_sistema,
        "fila_media": res.fila_media,
        "espera_media": res.espera_media,
        "inseridos": res.inseridos,
        "ativos_inicio": res.ativos_inicio,
        "ativos_fim": res.ativos_fim,
        "backlog_insercao": res.backlog_insercao,
        "perdidos": res.perdidos,
        "conservacao": res.conservacao,
        "travou": bool(res.travou),
        "lacuna_sobrevivencia": lacuna_sobrevivencia(res),
        "sinais": sinais_de_travamento(res),
        "sane": list(res.sane()),
        "sumocfg": diag.get("sumocfg"),
        "maior_seca_s": diag.get("maior_seca_s"),
        "teleportes": diag.get("teleportes"),
        "decisoes": diag.get("decisoes"),
        "fila_com_internas": (diag.get("fila_media_com_internas") or {}).get("total"),
        "parede_s": round(parede, 1),
        "resultado": dataclasses.asdict(res),
    }
    if hasattr(ctrl, "plano_executado"):
        exe = ctrl.plano_executado()
        linha["n_trocas"] = getattr(ctrl, "n_trocas", None)
        linha["verde_realizado_medio_s"] = {
            t: (round(v["verde_medio_s"], 2) if v.get("verde_medio_s") is not None else None)
            for t, v in exe.items()}
        linha["offset_estavel"] = all(v.get("offset_estavel") is not False
                                      for v in exe.values())
    return linha


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--planos", default="familia")
    p.add_argument("--seeds", default="42,43,44,45,46,47")
    p.add_argument("--t0", type=float, default=None, help="default = cenario.warmup_s")
    p.add_argument("--dur", type=float, default=7200.0)
    p.add_argument("--taxa", type=float, default=3500.0,
                   help="veh/h da demanda longa (só com --demanda-longa)")
    p.add_argument("--demanda-longa", action="store_true",
                   help="gera/usa demanda de horizonte 8400 s — OBRIGATÓRIO para --dur > 5000")
    p.add_argument("--sem-referencia", action="store_true",
                   help="não rodar o ControladorTimer(27) — só use se ele já foi medido")
    p.add_argument("--json", default=None)
    a = p.parse_args(argv)

    from feira.arena import ArenaSumo
    from feira.contratos import Janela
    from feira.contratos import cenario as resolve_cenario
    from feira.controladores import ControladorTimer
    from feira.controladores.coordenado import ControladorCoordenado, PlanoFixo

    cen = resolve_cenario("aberta.maquete")
    cen.aplicar()
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    t0 = a.t0 if a.t0 is not None else float(cen.warmup_s)
    janela = Janela(t0=t0, t1=t0 + float(a.dur))
    if janela.t1 > 5400.0 and not a.demanda_longa:
        raise SystemExit(
            "janela até t=%g s, mas a demanda canônica só tem depart até 5400 s: os "
            "últimos %g s seriam DRENAGEM e os dois braços entregariam todo mundo. "
            "Use --demanda-longa." % (janela.t1, janela.t1 - 5400.0))
    if a.demanda_longa:
        cen = prepara_demanda_longa(cen, seeds, taxa=a.taxa)
        print("demanda longa: %s (%g veh/h, horizonte %g s)"
              % (LONGA, a.taxa, HORIZONTE_LONGO), flush=True)
    nomes = _ordena(planos_da_familia(a.planos))

    saida = Path(a.json) if a.json else (SAIDA / ("varredura_%.0fs.json" % a.dur))
    saida.parent.mkdir(parents=True, exist_ok=True)

    print("janela %s · %d seeds · %d planos%s"
          % (janela, len(seeds), len(nomes), "" if a.sem_referencia else " + referência"),
          flush=True)

    linhas: list[dict] = []
    arena = ArenaSumo()

    def grava():
        # a cada corrida, não a cada seed: uma varredura longa tem que deixar
        # resultado parcial utilizável se for interrompida
        saida.write_text(json.dumps({"janela": [janela.t0, janela.t1], "seeds": seeds,
                                     "linhas": linhas}, indent=1, ensure_ascii=False,
                                    default=str),
                         encoding="utf-8", newline="\n")

    for seed in seeds:
        confere_cfg_da_seed(cen, seed)     # falha antes de subir o SUMO, não depois
        if not a.sem_referencia:
            print("[%s] seed %d ..." % (REFERENCIA, seed), flush=True)
            linhas.append(uma_corrida(arena, cen, seed, ControladorTimer(27), janela,
                                      REFERENCIA))
            grava()
            print("  -> %d entregues em %.0f s de parede"
                  % (linhas[-1]["entregues"], linhas[-1]["parede_s"]), flush=True)
        for nome in nomes:
            plano = PlanoFixo.carrega(PLANOS / ("%s.json" % nome))
            print("[%s] seed %d ..." % (nome, seed), flush=True)
            linhas.append(uma_corrida(arena, cen, seed,
                                      ControladorCoordenado(plano), janela, nome))
            grava()
            print("  -> %d entregues em %.0f s de parede"
                  % (linhas[-1]["entregues"], linhas[-1]["parede_s"]), flush=True)

    print("json -> %s" % saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
