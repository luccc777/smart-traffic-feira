#!/usr/bin/env python3
"""A previsão do agente A1, testada: coordenar sobe a capacidade desta malha?

> "Se o plano coordenado subir a capacidade os 10-20% típicos de coordenação de
> arterial, **4000-4200 veh/h viram estáveis e caem exatamente na faixa de
> 45-55% parados**. Se subir a capacidade e a faixa não vier junto, a explicação
> está errada — e isso vale tanto quanto o resultado positivo."
> (`docs/CALIBRACAO_ABERTA.md` §7.1)

São DUAS afirmações independentes, e este script mede as duas separadamente:

  (a) **capacidade** — a maior taxa estável em 7200 s, plano a plano. O critério
      de estabilidade é o do `sumo/aberta/analisa.py` (agente A1), reproduzido
      aqui: a população ativa não pode estar crescendo (|deriva entre o terço do
      meio e o último| < 15% da população) E o backlog de inserção máximo tem
      que ficar abaixo de 20.
  (b) **regime** — % de veículos parados e velocidade equivalente na taxa em que
      a malha ficou estável, com o limiar de parado da SIMILITUDE (0,1/6 m/s,
      não os 0,1 m/s fixos do `getLastStepHaltingNumber`).

AS DUAS MEDIDAS SAEM DO MESMO LAÇO DA COMPARAÇÃO
------------------------------------------------
`ArenaComRegime` é a `ArenaSumo` com `_frame` trocado por uma amostragem barata
de velocidade — a MESMA grade de decisão, o mesmo aquecimento, o mesmo plano de
fases. Reimplementar o laço aqui criaria uma segunda verdade sobre o que o
baseline faz, que é exatamente o erro que a Arena existe para não repetir.

Uso (BACKGROUND):
    python scripts/tune_baseline_capacidade.py --taxas 3500,3800,4000,4200 \
        --planos coordenado_c40 --seeds 42,43,44 --dur 7200
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

PLANOS = _RAIZ / "sumo" / "aberta" / "planos"
CAP = PLANOS / "capacidade"
SAIDA = _RAIZ / "results" / "a5"

K_SIMILITUDE = 6.0
LIMIAR_PARADO = 0.1 / K_SIMILITUDE      # imagem de 0,1 m/s sob similitude (A1 §3.1)
AMOSTRA_S = 10.0


def _arena_com_regime():
    """A `ArenaSumo` com amostragem de regime no lugar do `Frame` caro.

    O `Frame` do C7 lê posição, ângulo e velocidade de CADA veículo a CADA
    sim-step — 1,4 milhão de chamadas TraCI numa run de 7200 s, o que dominaria
    o tempo de parede. Aqui o `_frame` é substituído por uma amostra a cada
    `AMOSTRA_S` (via subscription, como o `calibra.py` do A1) e devolve um
    `Frame` vazio, que o observador ignora. Nada mais da Arena muda: mesma
    grade, mesmo aquecimento, mesma máquina de fases.
    """
    import traci
    import traci.constants as tc

    from feira.arena import ArenaSumo
    from feira.contratos import Frame

    class ArenaComRegime(ArenaSumo):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.serie: list[dict] = []
            self._assinados: set[str] = set()
            self._t0_janela = None

        def _frame(self, topo, braco, t, decisao, sub, leitor, contab):
            if contab is not None and self._t0_janela is None:
                self._t0_janela = t
            novos = [v for v in traci.vehicle.getIDList() if v not in self._assinados]
            for vid in novos:
                traci.vehicle.subscribe(vid, (tc.VAR_SPEED, tc.VAR_ROAD_ID))
                self._assinados.add(vid)
            if contab is not None and abs(t % AMOSTRA_S) < 1e-9:
                res = traci.vehicle.getAllSubscriptionResults()
                itens = [(d[tc.VAR_SPEED], d[tc.VAR_ROAD_ID]) for d in res.values()]
                # veículo EM teleporte devolve o INVALID_DOUBLE (-1e9) do TraCI;
                # um só arrasta a média para -13 mil m/s. Filtrar E contar (A1).
                invalidos = sum(1 for v, _ in itens if v < -1e6)
                itens = [x for x in itens if x[0] > -1e6]
                n = len(itens)
                v = [x for x, _ in itens]
                self.serie.append({
                    "t": t, "ativos": n,
                    "n_coto": sum(1 for _, e in itens if "_B_" in e),
                    "frac_parados": (sum(1 for x in v if x < LIMIAR_PARADO) / n) if n else 0.0,
                    "frac_parados_01": (sum(1 for x in v if x < 0.1) / n) if n else 0.0,
                    "vel_media": (math.fsum(v) / n) if n else 0.0,
                    "em_teleporte": invalidos,
                })
            return Frame(braco=str(braco), t=t, decisao=int(decisao), substep=int(sub),
                         veiculos=[], tls=[], heat={}, stats={})

    return ArenaComRegime


def _media(xs):
    return math.fsum(xs) / len(xs) if xs else float("nan")


def veredito(serie: list[dict], backlog_max: int) -> dict:
    """O critério de estabilidade do agente A1 (`sumo/aberta/analisa.py`).

    Deriva = média da população ativa no ÚLTIMO terço menos a do terço do MEIO.
    O primeiro terço fica de fora porque nele a malha ainda pode estar enchendo
    mesmo depois do warm-up nominal.
    """
    if len(serie) < 6:
        return {"estavel": False, "motivo": "série curta demais"}
    n = len(serie)
    meio = [s["ativos"] for s in serie[n // 3: 2 * n // 3]]
    fim = [s["ativos"] for s in serie[2 * n // 3:]]
    pop = _media(fim) or 1.0
    deriva = _media(fim) - _media(meio)
    ok_deriva = abs(deriva) < 0.15 * pop
    ok_backlog = backlog_max < 20
    motivos = []
    if not ok_deriva:
        motivos.append("deriva %+.0f carros (%.0f%% da população)" % (deriva, 100 * deriva / pop))
    if not ok_backlog:
        motivos.append("backlog %d" % backlog_max)
    return {"estavel": ok_deriva and ok_backlog, "deriva": deriva,
            "motivo": "; ".join(motivos) or "estável"}


def demanda_da_taxa(cen, taxa: float, seeds: list[int], horizonte: float):
    """Demanda própria desta taxa, com horizonte suficiente para a janela.

    Vive em `sumo/aberta/planos/capacidade/taxaNNNN_hNNNN/`, nunca em
    `sumo/aberta/demanda/`: aqui a demanda é descartável e de OUTRA taxa, e
    sobrescrever o `.sumocfg` oficial de uma seed é a armadilha que o
    `feira/demanda/config_seed.py` inteiro existe para matar
    (`docs/CALIBRACAO_ABERTA.md` §2.1.1).

    **O horizonte entra no nome da pasta**, e isso não é estética. O
    `GeradorDemandaAberta.gera` é idempotente por `(pasta, seed)`: com o arquivo
    e o manifesto em disco ele DEVOLVE o que achou, sem olhar se o horizonte
    pedido bate. Custou uma varredura: uma corrida de teste de 600 s deixou em
    `taxa3500/` uma demanda de horizonte 2100 s, e a corrida seguinte de 7200 s
    reaproveitou aquele arquivo — a malha esvaziou aos ~2000 s e o resultado saiu
    `travou=True`, `ativos_fim=0`, vazão 916/h em vez de ~3400/h. A verificação
    de `t_ultimo` abaixo é a segunda trava, para o caso de alguém mexer na pasta.
    """
    import xml.etree.ElementTree as ET

    from feira.demanda import GeradorDemandaAberta
    from feira.demanda.config_seed import escreve_config_seed

    pasta = CAP / ("taxa%04d_h%04d" % (round(taxa), round(horizonte)))
    pasta.mkdir(parents=True, exist_ok=True)
    canonico = Path(cen.sumocfg)
    texto = canonico.read_text(encoding="utf-8")
    for elem in ET.fromstring(texto).iter():
        v = elem.get("value")
        if elem.tag in ("net-file", "additional-files") and v:
            novo = os.path.relpath((canonico.parent / v).resolve(), pasta).replace("\\", "/")
            texto = texto.replace('<%s value="%s"/>' % (elem.tag, v),
                                  '<%s value="%s"/>' % (elem.tag, novo))
    (pasta / canonico.name).write_text(texto, encoding="utf-8", newline="\n")
    cen_taxa = replace(cen, sumocfg=str(pasta / canonico.name),
                       rou_pattern=str(pasta / "demanda_s{seed}.rou.xml"))
    ger = GeradorDemandaAberta(veh_por_hora=taxa, escreve_cfg=False,
                               horizonte_s=horizonte)
    shas = {}
    for s in seeds:
        man = ger.gera(cen_taxa, s)
        if man.t_ultimo < horizonte - 60.0 or man.parametros["horizonte_s"] != horizonte:
            raise SystemExit(
                "demanda em %s tem horizonte %g s (último depart %.0f s), pedido %g s. "
                "Uma janela maior que o arquivo mede DRENAGEM, não regime. Apague a "
                "pasta e rode de novo."
                % (pasta, man.parametros["horizonte_s"], man.t_ultimo, horizonte))
        shas[s] = man.sha256
        escreve_config_seed(cen_taxa, s, cen_taxa.rou_file(s))
    return cen_taxa, shas


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--taxas", default="3500,3800,4000,4200,4400")
    p.add_argument("--planos", default="coordenado_c40",
                   help="além do timer27 de referência, que sempre roda")
    p.add_argument("--seeds", default="42,43,44")
    p.add_argument("--dur", type=float, default=7200.0)
    p.add_argument("--json", default=None)
    a = p.parse_args(argv)

    from feira.contratos import Janela
    from feira.contratos import cenario as resolve_cenario
    from feira.controladores import ControladorTimer
    from feira.controladores.coordenado import ControladorCoordenado, PlanoFixo

    cen0 = resolve_cenario("aberta.maquete")
    cen0.aplicar()
    ArenaComRegime = _arena_com_regime()

    taxas = [float(x) for x in a.taxas.split(",") if x.strip()]
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
    nomes = [x.strip() for x in a.planos.split(",") if x.strip()]
    t0 = float(cen0.warmup_s)
    janela = Janela(t0=t0, t1=t0 + a.dur)
    horizonte = janela.t1 + 1200.0

    saida = Path(a.json) if a.json else (SAIDA / "capacidade_%.0fs.json" % a.dur)
    saida.parent.mkdir(parents=True, exist_ok=True)
    linhas: list[dict] = []

    for taxa in taxas:
        cen_taxa, shas = demanda_da_taxa(cen0, taxa, seeds, horizonte)
        for seed in seeds:
            base = Path(cen_taxa.sumocfg)
            cen_s = replace(cen_taxa,
                            sumocfg=str(base.with_name("%s_s%d%s" % (base.stem, seed,
                                                                     base.suffix))))
            bracos = [("timer27", ControladorTimer(27))]
            for nome in nomes:
                bracos.append((nome, ControladorCoordenado(
                    PlanoFixo.carrega(PLANOS / ("%s.json" % nome)))))
            for rotulo, ctrl in bracos:
                print("[%s] %g veh/h seed %d ..." % (rotulo, taxa, seed), flush=True)
                arena = ArenaComRegime()
                t_ini = time.perf_counter()
                res = arena.roda(cen_taxa and cen_s, seed, ctrl, janela,
                                 observador=lambda f: None)
                parede = time.perf_counter() - t_ini
                # guarda da rede vazia — ver docs/BASELINE_ABERTO.md §5.1
                if res.inseridos <= 0:
                    raise SystemExit(
                        "[%s] %g veh/h seed %d: ZERO veículos inseridos. A Arena "
                        "subiu a rede vazia (sumocfg %r). NÃO use este número."
                        % (rotulo, taxa, seed,
                           arena.ultimo_diagnostico.get("sumocfg")))
                serie = arena.serie
                ver = veredito(serie, res.backlog_insercao)
                v = _media([s["vel_media"] for s in serie])
                linha = {
                    "taxa_veh_h": taxa, "seed": seed, "plano": rotulo,
                    "demanda_sha": shas[seed],
                    "ativos": _media([s["ativos"] for s in serie]),
                    "ativos_coto": _media([s["n_coto"] for s in serie]),
                    "pct_parados": 100 * _media([s["frac_parados"] for s in serie]),
                    "pct_parados_01": 100 * _media([s["frac_parados_01"] for s in serie]),
                    "vel_media_ms": v,
                    "kmh_equivalente": v * K_SIMILITUDE * 3.6,
                    "entregues": res.entregues,
                    "vazao_h": res.entregues / (janela.duracao / 3600.0),
                    "tempo_medio_no_sistema": res.tempo_medio_no_sistema,
                    "fila_media": res.fila_media,
                    "backlog_final": res.backlog_insercao,
                    "ativos_fim": res.ativos_fim,
                    "travou": bool(res.travou),
                    "sane": list(res.sane()),
                    "teleportes": arena.ultimo_diagnostico.get("teleportes"),
                    "estavel": ver["estavel"], "motivo": ver["motivo"],
                    "deriva_ativos": ver.get("deriva"),
                    "parede_s": round(parede, 1),
                }
                linhas.append(linha)
                saida.write_text(json.dumps({"janela": [janela.t0, janela.t1],
                                             "linhas": linhas}, indent=1,
                                            ensure_ascii=False, default=str),
                                 encoding="utf-8", newline="\n")
                print("  -> %s · %.0f ativos · %.1f%% parados · %.1f km/h eq · "
                      "vazão %.0f/h · %s"
                      % (rotulo, linha["ativos"], linha["pct_parados"],
                         linha["kmh_equivalente"], linha["vazao_h"],
                         "ESTÁVEL" if linha["estavel"] else "INSTÁVEL (%s)" % linha["motivo"]),
                      flush=True)

    print("json -> %s" % saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
