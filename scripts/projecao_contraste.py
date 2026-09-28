"""projecao_contraste.py — audita a paleta da projeção da FEIRA contra o projetor.

PORTADO de `smart-traffic-maquete/scripts/projecao/contraste.py` (commit `18ea6dd`).
O modelo, os pisos (`BOM`/`LIMITE`) e as funções `lum`/`sobre`/`parede` são de lá,
sem alteração — este repo não escreve naquele, então a lógica veio junto em vez de
ser importada. O que é novo aqui:

  * o **ponto de operação é parâmetro**, não constante. A projeção da feira não é
    a mesa de 1,30 m do maquete: o projetor fica numa torre de 2 m e joga NO CHÃO,
    então a mesma lâmpada espalha o dobro de área e o branco cai pela metade. Com
    menos branco o ambiente pesa mais e TODO contraste percebido piora — auditar
    a paleta nova no ponto de operação errado seria auditar outra coisa;
  * os elementos do **placar** (C7): trilho, as três barras, a régua do timer, a
    faixa de denúncia e a tipografia. São os elementos novos do A7, e são o que a
    DoD (c) cobra.

Uso:
    python scripts/projecao_contraste.py                    # mesa 1,30 m e chão 1,82 m
    python scripts/projecao_contraste.py --montagem chao    # só o chão
    python scripts/projecao_contraste.py --amb 25 90 150    # ambientes a auditar
    python scripts/projecao_contraste.py --json             # saída para teste/CI

Sai 0 se todo par crítico fica >= LIMITE no ponto de operação escolhido; 1 se algum
cai abaixo. Os pares que a paleta ASSUME abaixo do piso estão marcados `assumido=` e
não derrubam a saída — mas continuam impressos, com o motivo.
"""
from __future__ import annotations

import argparse
import json
import sys

# --- modelo do projetor (PLANO_PROJECAO §3.2/§A.6 do maquete) ------------------
FLUXO_LM = 300.0        # HY320: ~300 ANSI lumens
CR_PAINEL = 150.0       # contraste ANSI do painel -> quanto ele vaza no preto
AMB_PADRAO = (25.0, 90.0)   # sala escura / sala com luz acesa

# Pisos de aceitação, em razão de ILUMINÂNCIA na parede. Não são WCAG: são o que
# sobrevive a alguns metros num painel fraco. Valores do maquete, não mexidos.
BOM, LIMITE = 1.60, 1.30

# --- montagens ----------------------------------------------------------------
# `mesa`: o ponto de projeto do maquete (W=1,30 m). Reproduzido aqui para provar
#   que o port bate com o original: dá 315,6 lux, contra os 316 de lá.
# `chao`: a montagem da FEIRA. Torre de 2,00 m, throw ratio 1,10 -> a imagem tem
#   W = 2,00/1,10 = 1,82 m. Área 1,86 m² contra 0,95 m² da mesa: o mesmo fluxo
#   espalhado em 1,96x a área.
MONTAGENS = {
    "mesa": {"largura_m": 1.30, "distancia_m": 1.43, "desc": "mesa do maquete (W=1,30 m)"},
    "chao": {"largura_m": 2.00 / 1.10, "distancia_m": 2.00,
             "desc": "feira: torre de 2,00 m, TR 1,10, imagem no chão"},
}


def ponto(montagem: str = "chao", fluxo_lm: float = FLUXO_LM,
          cr: float = CR_PAINEL) -> dict:
    """Branco e preto vazado (lux) da montagem. 16:9 assumido no painel."""
    m = MONTAGENS[montagem]
    w = float(m["largura_m"])
    h = w * 9.0 / 16.0
    area = w * h
    branco = fluxo_lm / area
    return {"montagem": montagem, "desc": m["desc"], "largura_m": w, "altura_m": h,
            "area_m2": area, "branco": branco, "preto": branco / cr,
            "distancia_m": float(m["distancia_m"])}


# ==============================================================================
# PALETA — espelha `web/css/projecao.css` e `web/js/paint.js`. Mudou lá, muda aqui,
# e o teste `tests/test_a7_contraste.py` reprova se divergirem.
# ==============================================================================
# Mapa (herdado do maquete, sem mexer: já foi auditado lá e continua válido).
VIA = "#4b5869"
# JUNÇÃO REAJUSTADA PELO A7: o `#637183` do maquete media 1,37 contra a via na mesa
# de 1,30 m; na imagem de 1,82 m do chão o mesmo par cai para 1,26 — abaixo do piso,
# só por causa do ponto de operação. Re-resolvido para 1,45 no chão, preservando o
# matiz e a intenção original (a junção é a via um passo mais clara).
JUNCAO = "#708095"
FAIXA = "#9cbcdf"
RAMPA = [("#e0891a", 0.34), ("#ff7a1a", 0.50), ("#ff5424", 0.66), ("#ff2f3a", 0.80)]
NUCLEO, NUCLEO_A = "#ffdcac", 0.46
CARRO_LIVRE, CARRO_LENTO, CARRO_PARADO = "#f4fbff", "#e6eef7", "#ffe2b8"
FAROL_V, FAROL_A, FAROL_R = "#2bea88", "#ffd23d", "#ff5245"

# --- ELEMENTOS NOVOS DO A7 (o placar) -----------------------------------------
# O placar mora numa tarja PRETA no rodapé: todo par aqui é contra #000, contra o
# trilho ou contra outra barra.
#
# A REGRA QUE DECIDIU ESTA PALETA. No chão, a 25 lux de ambiente, a dinâmica INTEIRA
# disponível na imagem é E(branco)/E(preto) = 7,19. Cabem quatro degraus de 1,64 — e
# é exatamente o que o placar precisa: preto < trilho < TIMER < REDE < VOCÊ. Então a
# paleta não foi escolhida por gosto e depois auditada: ela foi RESOLVIDA a partir da
# dinâmica (degrau geométrico), e só depois recebeu matiz. Sobra zero folga, e é por
# isso que qualquer barra "mais bonita" que se aproxime de outra reprova aqui.
FUNDO = "#000000"
TRILHO = "#4e5c6c"          # trilho vazio da barra    L=0,104   (degrau 1,64 sobre o preto)
BAR_TIMER = "#cb7a18"       # TIMER FIXO  — âmbar      L=0,267   (degrau 1,62)
BAR_RL = "#7fcbfa"          # REDE NEURAL — azul       L=0,541   (degrau 1,64)
BAR_HUMANO = "#fafcff"      # VOCÊ        — gelo       L=0,972   (degrau 1,61)

# SOBREPOSTOS: tudo que cruza por cima de fundo VARIÁVEL é desenhado ESCURO.
# Um projetor não consegue ir abaixo do próprio preto, então o preto é o único valor
# garantidamente mais baixo que qualquer coisa embaixo dele — um tick claro que
# funciona sobre o trilho some sobre a barra VOCÊ, e um tick com a luminância certa
# para separar do trilho vira, ele mesmo, uma barra.
GRADE = "#060a10"           # ticks de 10 carros, cortados no trilho E nas barras
REGUA_FLANCO = "#060a10"    # flanco escuro da régua do timer
REGUA_NUCLEO = "#ffd98a"    # núcleo âmbar da régua (só precisa vencer o flanco)
MOLDURA_VENC = "#060a10"    # a moldura do vencedor, por cima da barra dele

TEXTO = "#ffffff"           # o número do placar
TEXTO_2 = "#bdd1e7"         # rótulos secundários (fila, tempo médio)
TEXTO_3 = "#8297b0"         # cromo do operador (chave, seed) — NÃO é para a plateia
VENCEDOR = "#6ef5b2"        # o texto "VENCEU" (sobre preto, nunca sobre barra)
ALERTA = "#ff4433"          # a faixa de denúncia (janela divergente)
ALERTA_NUC = "#ffffff"      # o núcleo branco dela — o vermelho sozinho some


# ------------------------------------------------------------------ do maquete
def _srgb_lin(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(hexs: str) -> float:
    """Luminância relativa sRGB (0 = preto, 1 = branco)."""
    h = hexs.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _srgb_lin(r) + 0.7152 * _srgb_lin(g) + 0.0722 * _srgb_lin(b)


def sobre(fg: str, alpha: float, fundo_L: float) -> float:
    """Luminância composta de `fg` com `alpha` sobre um fundo de luminância `fundo_L`."""
    return alpha * lum(fg) + (1 - alpha) * fundo_L


def parede(La: float, Lb: float, amb: float = 25.0, *,
           branco: float | None = None, preto: float | None = None) -> float:
    """Contraste PERCEBIDO na parede entre duas luminâncias relativas.

    O projetor SOMA luz e nunca subtrai: E(cor) = ambiente + preto_vazado + L·branco.
    O ambiente entra igual nos dois lados e achata tudo — por isso o contraste na
    parede é sempre muito pior que o do monitor.
    """
    p = ponto("mesa")
    b = p["branco"] if branco is None else branco
    k = p["preto"] if preto is None else preto
    ea, eb = amb + k + La * b, amb + k + Lb * b
    return max(ea, eb) / min(ea, eb)


def _sinal(c: float) -> str:
    return "  " if c >= BOM else " !" if c >= LIMITE else " X"


# ------------------------------------------------------------------- auditoria
def pares(pt: dict) -> list[tuple[str, float, float, str]]:
    """Os pares críticos. `assumido` != "" marca um limite aceito, com o motivo."""
    lv = lum(VIA)
    banda = [sobre(c, a, lv) for c, a in RAMPA]
    nucleo = sobre(NUCLEO, NUCLEO_A, banda[-1])
    tr = lum(TRILHO)
    return [
        # --- placar (NOVO, é o que a DoD (c) cobra) --------------------------
        ("placar: trilho vazio sobre o preto", tr, 0.0, ""),
        ("placar: barra TIMER sobre o trilho", lum(BAR_TIMER), tr, ""),
        ("placar: barra REDE sobre a barra TIMER", lum(BAR_RL), lum(BAR_TIMER), ""),
        ("placar: barra VOCÊ sobre a barra REDE", lum(BAR_HUMANO), lum(BAR_RL), ""),
        ("placar: barra REDE sobre o trilho", lum(BAR_RL), tr, ""),
        ("placar: barra VOCÊ sobre o trilho", lum(BAR_HUMANO), tr, ""),
        ("placar: barra VOCÊ sobre a barra TIMER", lum(BAR_HUMANO), lum(BAR_TIMER), ""),
        ("placar: tick escuro sobre o trilho", lum(GRADE), tr, ""),
        ("placar: tick escuro sobre a barra TIMER", lum(GRADE), lum(BAR_TIMER), ""),
        ("placar: tick escuro sobre a barra VOCÊ", lum(GRADE), lum(BAR_HUMANO), ""),
        ("régua: flanco escuro sobre o trilho", lum(REGUA_FLANCO), tr, ""),
        ("régua: flanco escuro sobre a barra VOCÊ", lum(REGUA_FLANCO), lum(BAR_HUMANO), ""),
        ("régua: núcleo âmbar sobre o flanco", lum(REGUA_NUCLEO), lum(REGUA_FLANCO), ""),
        ("vencedor: moldura escura sobre a barra VOCÊ", lum(MOLDURA_VENC),
         lum(BAR_HUMANO), ""),
        ("vencedor: texto VENCEU sobre o preto", lum(VENCEDOR), 0.0, ""),
        # O veredito tem QUATRO desfechos e três cores. A cor não é decoração: verde é
        # coroa, e coroar um empate ou uma rodada que não terminou seria dizer que
        # alguém ganhou. Ver docs/PROJECAO.md §6.4.
        ("veredito: EMPATE sobre o preto", lum(TEXTO_2), 0.0, ""),
        ("veredito: RODADA NÃO CONCLUÍDA sobre o preto", lum(ALERTA), 0.0, ""),
        ("veredito: o motivo do motor, sob o veredito", lum(TEXTO_2), 0.0, ""),
        ("denúncia: o motivo do motor sobre o preto", lum(TEXTO), 0.0, ""),
        ("texto: número do placar sobre o preto", lum(TEXTO), 0.0, ""),
        ("texto: rótulo secundário sobre o preto", lum(TEXTO_2), 0.0, ""),
        ("texto: cromo do operador sobre o preto", lum(TEXTO_3), 0.0, ""),
        ("denúncia: faixa de alerta sobre o preto", lum(ALERTA), 0.0, ""),
        ("denúncia: núcleo branco sobre o alerta", lum(ALERTA_NUC), lum(ALERTA), ""),
        # --- mapa (herdado; entra porque o A7 continua desenhando ele) --------
        ("mapa: via sobre o fundo preto", lv, 0.0, ""),
        ("mapa: faixa (tracejado) sobre a via", lum(FAIXA), lv, ""),
        ("mapa: junção sobre a via", lum(JUNCAO), lv, ""),
        ("mapa: carro andando sobre a via", lum(CARRO_LIVRE), lv, ""),
        ("mapa: carro andando sobre o núcleo", lum(CARRO_LIVRE), nucleo, ""),
        ("mapa: carro parado sobre o núcleo", lum(CARRO_PARADO), nucleo, ""),
        ("mapa: carro andando vs carro parado", lum(CARRO_LIVRE), lum(CARRO_PARADO),
         "medido no maquete e ASSUMIDO lá: os dois precisam ser claros; 'parado' se "
         "lê pela banda quente EMBAIXO dele e por não se mexer"),
        ("mapa: farol verde sobre a via", lum(FAROL_V), lv, ""),
        ("mapa: farol amarelo sobre a via", lum(FAROL_A), lv, ""),
        ("mapa: farol vermelho sobre a via", lum(FAROL_R), lv, ""),
        ("mapa: farol vermelho sobre a banda", lum(FAROL_R), banda[-1],
         "assumido NA ORIGEM: o vermelho é a cor de menor luminância possível e some "
         "sobre uma fila acesa; quem entrega a leitura é o miolo branco do farol, "
         "logo abaixo (2,97)"),
        ("mapa: miolo branco do farol sobre a banda", 1.0, banda[-1], ""),
        ("mapa: farol verde vs farol vermelho", lum(FAROL_V), lum(FAROL_R), ""),
    ]


def teto_ambiente(pt: dict, *, so_novos: bool = True, piso: float = LIMITE,
                  maximo: float = 400.0) -> float:
    """O ambiente MÁXIMO (lux) em que todo par ainda fica acima de `piso`.

    É o número operacional do documento: acima dele a projeção não é questão de
    paleta, é questão de apagar a luz ou encolher a imagem. `so_novos=True` mede só
    os elementos do A7 — os limites herdados do mapa não são desta entrega.
    """
    def ok(amb: float) -> bool:
        for rot, a, b, assumido in pares(pt):
            if assumido:
                continue
            if so_novos and rot.startswith("mapa: "):
                continue
            if parede(a, b, amb, branco=pt["branco"], preto=pt["preto"]) < piso:
                return False
        return True

    if not ok(0.0):
        return 0.0
    lo, hi = 0.0, maximo
    if ok(hi):
        return hi
    for _ in range(40):
        meio = (lo + hi) / 2.0
        if ok(meio):
            lo = meio
        else:
            hi = meio
    return lo


def auditar(pt: dict, ambs, *, amb_aceite: float = 25.0,
            mostrar: bool = True) -> tuple[int, list[dict]]:
    """Audita a paleta. REPROVA no ambiente de ACEITE, não no pior da tabela.

    Os outros ambientes são informativos: 90 lux (sala com luz acesa) derruba até a
    paleta HERDADA, que já foi aceita no maquete — usar o pior da tabela como
    critério transformaria "a sala está clara demais" em "a cor está errada".
    """
    linhas = []
    piores = 0
    if mostrar:
        print("MONTAGEM %s — %s" % (pt["montagem"], pt["desc"]))
        print("  imagem %.2f x %.2f m (%.3f m²) · branco %.0f lux · preto vazado %.2f lux"
              % (pt["largura_m"], pt["altura_m"], pt["area_m2"], pt["branco"], pt["preto"]))
        print("  dinâmica total da imagem a %.0f lux: %.2f  ·  aceite em %.0f lux"
              % (amb_aceite,
                 parede(1.0, 0.0, amb_aceite, branco=pt["branco"], preto=pt["preto"]),
                 amb_aceite))
        print()
        print("PAR CRÍTICO".ljust(48) + "".join(("amb %.0f" % a).rjust(12) for a in ambs))
        print("-" * (48 + 12 * len(ambs)))
    for rot, a, b, assumido in pares(pt):
        cs = [parede(a, b, amb, branco=pt["branco"], preto=pt["preto"]) for amb in ambs]
        aceite = parede(a, b, amb_aceite, branco=pt["branco"], preto=pt["preto"])
        reprova = aceite < LIMITE and not assumido
        piores += 1 if reprova else 0
        linhas.append({"par": rot, "contrastes": [round(c, 3) for c in cs],
                       "aceite": round(aceite, 3), "assumido": assumido,
                       "reprova": reprova, "novo": not rot.startswith("mapa: ")})
        if mostrar:
            out = rot.ljust(48)
            for c in cs:
                out += ("%.2f%s" % (c, _sinal(c))).rjust(12)
            print(out)
            if assumido:
                print("      assumido: %s" % assumido)
    if mostrar:
        teto_n = teto_ambiente(pt, so_novos=True)
        teto_t = teto_ambiente(pt, so_novos=False)
        print()
        print("  X < %.2f indistinguível na parede | ! até %.2f com esforço | limpo = lê de longe"
              % (LIMITE, BOM))
        print("  reprovados em %.0f lux (fora os assumidos): %d" % (amb_aceite, piores))
        print("  TETO DE AMBIENTE: elementos do A7 aguentam até %.0f lux; com o mapa "
              "herdado junto, %.0f lux." % (teto_n, teto_t))
        print()
    return piores, linhas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--montagem", choices=sorted(MONTAGENS) + ["todas"], default="todas")
    ap.add_argument("--amb", type=float, nargs="+", default=list(AMB_PADRAO),
                    help="lux de ambiente (default: 25 sala escura e 90 com luz)")
    ap.add_argument("--fluxo", type=float, default=FLUXO_LM, help="lumens do projetor")
    ap.add_argument("--amb-aceite", type=float, default=25.0,
                    help="ambiente (lux) em que a paleta TEM que passar (default: 25)")
    ap.add_argument("--json", action="store_true", help="saída legível por máquina")
    a = ap.parse_args(argv)

    nomes = sorted(MONTAGENS) if a.montagem == "todas" else [a.montagem]
    total = 0
    saida = []
    for nome in nomes:
        pt = ponto(nome, fluxo_lm=a.fluxo)
        piores, linhas = auditar(pt, a.amb, amb_aceite=a.amb_aceite, mostrar=not a.json)
        total += piores
        saida.append({"ponto": pt, "reprovados": piores, "pares": linhas,
                      "teto_ambiente_a7": round(teto_ambiente(pt, so_novos=True), 1),
                      "teto_ambiente_tudo": round(teto_ambiente(pt, so_novos=False), 1)})
    if a.json:
        json.dump({"piso": {"bom": BOM, "limite": LIMITE},
                   "ambientes": a.amb, "amb_aceite": a.amb_aceite,
                   "montagens": saida, "reprovados": total},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
