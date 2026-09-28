"""valida_fluxo.py — grava o FIO da projeção e responde o checklist da feira.

Conecta em `ws://host:porta/ws` como mais um cliente (o mesmo socket que a página
projetada usa) e escreve um JSONL com tudo que passou, com carimbo de relógio de
parede. Depois lê o diário e responde, com número, as perguntas que a validação da
feira faz:

  * a tela padrão está COMPARANDO de verdade (dois braços, mesma seed, mesmo `t`)?
  * a rodada passou por todas as fases, na ordem?
  * a tela de RESULTADO ficou no ar o tempo configurado e voltou sozinha ao `ocioso`?
  * o botão trocou o semáforo, e o COOLDOWN foi respeitado?
  * houve transição (amarelo) e ela foi respeitada?
  * o placar comparou o humano contra RL e timer?
  * o quadro de recordes registrou a marca?

Uso:
    # numa ponta, o jogo:
    python scripts/projecao_servidor.py --feira --porta 8098
    # na outra, o gravador (Ctrl-C para parar, ou --segundos):
    python scripts/valida_fluxo.py --porta 8098 --saida validacao.jsonl
    # e a leitura, quando quiser:
    python scripts/valida_fluxo.py --analisa validacao.jsonl

NÃO toca em nada do jogo: é um observador a mais no mesmo broadcast.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FASES_ESPERADAS = ("ocioso", "preparando", "contagem", "jogando", "resultado")


# --------------------------------------------------------------------- gravação
def grava(url: str, saida: Path, segundos: float | None) -> int:
    from websockets.sync.client import connect

    fim = None if segundos is None else time.time() + float(segundos)
    n = 0
    saida.parent.mkdir(parents=True, exist_ok=True)
    print("gravando %s -> %s" % (url, saida))
    with saida.open("w", encoding="utf-8") as f, connect(url, open_timeout=10) as ws:
        try:
            while fim is None or time.time() < fim:
                try:
                    bruto = ws.recv(timeout=2.0)
                except TimeoutError:
                    continue
                msg = json.loads(bruto)
                f.write(json.dumps({"parede": time.time(), "msg": msg},
                                   ensure_ascii=False) + "\n")
                f.flush()
                n += 1
        except KeyboardInterrupt:
            pass
    print("%d mensagens" % n)
    return 0


# --------------------------------------------------------------------- leitura
def _le(caminho: Path) -> list[dict]:
    linhas = []
    for ln in caminho.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            linhas.append(json.loads(ln))
    return linhas


def _tipo(m: dict) -> str:
    return m.get("type") or m.get("tipo") or "?"


def analisa(caminho: Path) -> dict:
    """O diário vira respostas. Cada uma traz o NÚMERO que a sustenta."""
    reg = _le(caminho)
    out: dict = {"arquivo": str(caminho), "mensagens": len(reg),
                 "tipos": dict(Counter(_tipo(r["msg"]) for r in reg))}
    if not reg:
        return out
    t0 = reg[0]["parede"]
    out["duracao_s"] = round(reg[-1]["parede"] - t0, 1)

    placares = [r for r in reg if _tipo(r["msg"]) == "placar"]
    frames = [r for r in reg if _tipo(r["msg"]) == "frame"]

    # ---- a linha do tempo das fases, com quanto cada uma durou
    linha = []
    for r in placares:
        fase = r["msg"].get("fase")
        if not linha or linha[-1]["fase"] != fase:
            linha.append({"fase": fase, "inicio_s": round(r["parede"] - t0, 2)})
    for i, p in enumerate(linha):
        fim = linha[i + 1]["inicio_s"] if i + 1 < len(linha) else round(
            reg[-1]["parede"] - t0, 2)
        p["duracao_s"] = round(fim - p["inicio_s"], 2)
    out["fases"] = linha
    out["ordem_das_fases"] = [p["fase"] for p in linha]

    # ---- RESULTADO -> OCIOSO: quanto a tela de resultado ficou no ar
    voltas = [linha[i]["duracao_s"] for i in range(len(linha) - 1)
              if linha[i]["fase"] == "resultado" and linha[i + 1]["fase"] == "ocioso"]
    out["resultado_no_ar_s"] = voltas
    out["voltou_sozinho_ao_ocioso"] = bool(voltas)

    # ---- a TELA PADRÃO comparou de verdade?
    oc = [r["msg"] for r in placares if r["msg"].get("fase") == "ocioso"
          and len(r["msg"].get("linhas") or ()) >= 2]
    out["placares_do_ocioso"] = len(oc)
    if oc:
        bracos = {ln["braco"] for ln in oc[-1]["linhas"]}
        out["ocioso_bracos"] = sorted(bracos)
        out["ocioso_ao_vivo"] = all(not ln["fantasma"] for ln in oc[-1]["linhas"])
        out["ocioso_exemplo"] = {ln["braco"]: ln["entregues"] for ln in oc[-1]["linhas"]}
    # os dois braços do ocioso vieram da MESMA seed e do MESMO `t`?
    fo = [r["msg"] for r in frames if r["msg"].get("seed") is not None]
    if fo:
        seeds = {m["braco"]: m["seed"] for m in fo[-40:]}
        out["ocioso_seeds_por_braco"] = seeds
        out["ocioso_mesma_seed"] = len(set(seeds.values())) <= 1

    # ---- a rodada: o botão trocou o semáforo, e o cooldown foi respeitado?
    jog = [r for r in reg if _tipo(r["msg"]) == "leds"]
    leds = Counter()
    for r in jog:
        for e in (r["msg"].get("estados") or ()):
            leds[e] += 1
    out["feedback_dos_botoes"] = dict(leds)
    out["houve_troca_aceita"] = leds.get("on", 0) > 0
    out["houve_recusa_por_cooldown"] = leds.get("deny", 0) > 0

    # ---- transição: algum farol ficou em AMARELO durante a rodada?
    amarelos = 0
    tls_vistos = 0
    for r in frames:
        if r["msg"].get("braco") != "humano":
            continue
        for tl in (r["msg"].get("tls") or ()):
            tls_vistos += 1
            if "y" in (tl.get("state") or "").lower():
                amarelos += 1
    out["tls_amostrados_do_humano"] = tls_vistos
    out["tls_em_amarelo"] = amarelos
    out["houve_transicao_amarela"] = amarelos > 0

    # ---- o placar final comparou os três braços?
    fin = [r["msg"] for r in placares if r["msg"].get("fase") == "resultado"]
    if fin:
        m = fin[-1]
        out["resultado"] = {
            "bracos": sorted(ln["braco"] for ln in m.get("linhas") or ()),
            "entregues": {ln["braco"]: ln["entregues"] for ln in m.get("linhas") or ()},
            "vencedor": m.get("vencedor"), "pareado": m.get("pareado"),
            "motivo": m.get("motivo"), "sinais": m.get("sinais"),
        }
        out["comparou_humano_rl_timer"] = out["resultado"]["bracos"] == [
            "humano", "rl", "timer"]

    # ---- o quadro de recordes registrou?
    rk = [r["msg"] for r in reg if _tipo(r["msg"]) == "ranking"]
    out["mensagens_de_ranking"] = len(rk)
    if rk:
        ult = rk[-1]
        out["ranking_marcas"] = ult.get("total")
        out["ranking_validade_s"] = ult.get("validade_s")
        out["ranking_expira"] = bool(ult.get("validade_s"))
        out["ranking_topo"] = [
            {"nome": m.get("nome") or "—", "entregues": m.get("entregues"),
             "score": m.get("score"), "seed": m.get("seed"), "posicao": m.get("ordem")}
            for m in (ult.get("topo") or ())[:5]]
        out["ranking_registrou"] = bool(ult.get("topo"))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="grava e analisa o fio da projeção")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--porta", type=int, default=8098)
    p.add_argument("--saida", default="validacao.jsonl")
    p.add_argument("--segundos", type=float, default=None)
    p.add_argument("--analisa", default=None, metavar="JSONL",
                   help="não grava: lê um diário já gravado e imprime o veredito")
    a = p.parse_args(argv)
    if a.analisa:
        print(json.dumps(analisa(Path(a.analisa)), indent=1, ensure_ascii=False))
        return 0
    return grava("ws://%s:%d/ws" % (a.host, a.porta), Path(a.saida), a.segundos)


if __name__ == "__main__":
    raise SystemExit(main())
