"""Significância — o teste PAREADO por seed, num lugar só.

`agrega_por_seed` (C5) devolve médias; médias não sustentam "p ≤ 1e-11". Este
módulo trabalha com as LISTAS pareadas, que é o que o teste exige: em cada seed
os dois braços enfrentam a MESMA demanda, então a variação entre seeds é ruído
comum aos dois e o pareamento a remove.

Três regras que este módulo impõe, e que existem por causa de erros já cometidos
neste projeto (docs/RESULTADOS_ATS.md §5.2):

1. **`comparar()` é o único lugar onde nasce uma porcentagem.** Aqui só entram
   listas de `Resultado` já casadas por `Chave`; qualquer par com chave
   diferente levanta antes de virar número.
2. **Nunca decidir com 2 seeds.** `teste_pareado` devolve `n_seeds` e o chamador
   é obrigado a olhar: o travamento que derrubou a variante C aparecia em ~2 de
   12 seeds e não aparecia na avaliação interna de 2.
3. **Travamento vai por seed, separado das médias.** `resumo_pareado` reporta
   `travamentos` e `nao_sa` em vez de diluí-los na média.

`scipy` é opcional: sem ele saem média/desvio e `p_valor=None` — nunca um
p-valor inventado.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .contratos import DIRECAO, Chave, ChavesIncompativeis, Resultado, comparar

__all__ = ["TestePareado", "teste_pareado", "resumo_pareado", "pareia_por_chave"]


@dataclass(frozen=True)
class TestePareado:
    """Resultado de um t-test pareado numa métrica. `melhor` = o sinal correto
    para a direção da métrica (positivo = `novo` melhor que `base`)."""

    campo: str
    n_seeds: int
    base_media: float
    base_desvio: float
    novo_media: float
    novo_desvio: float
    delta_pct: float
    vitorias: int              # em quantas seeds `novo` foi melhor
    t: float | None = None
    p: float | None = None
    nota: str = ""

    @property
    def significante_05(self) -> bool:
        return self.p is not None and self.p < 0.05

    def linha(self) -> str:
        p = ("p=%.3g" % self.p) if self.p is not None else "p=n/a"
        return ("%-24s base=%9.3f±%-7.3f  novo=%9.3f±%-7.3f  %+7.2f%%  "
                "vitórias %d/%d  %s"
                % (self.campo, self.base_media, self.base_desvio,
                   self.novo_media, self.novo_desvio, self.delta_pct,
                   self.vitorias, self.n_seeds, p))


def _media(v):
    return sum(v) / len(v) if v else float("nan")


def _desvio(v):
    if len(v) < 2:
        return 0.0
    m = _media(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def pareia_por_chave(base: list[Resultado], novo: list[Resultado]) -> list[tuple[Resultado, Resultado]]:
    """Casa as duas listas pela `Chave`. Levanta se sobra alguém sem par.

    O pareamento é por CHAVE e não por posição de propósito: uma lista fora de
    ordem produziria um t-test perfeitamente calculado sobre pares errados."""
    por_chave: dict[Chave, Resultado] = {}
    for r in novo:
        if r.chave in por_chave:
            raise ChavesIncompativeis("duas corridas de `novo` com a mesma chave: %s"
                                      % r.chave.descreve())
        por_chave[r.chave] = r
    pares = []
    for b in base:
        n = por_chave.pop(b.chave, None)
        if n is None:
            raise ChavesIncompativeis("sem par para %s" % b.chave.descreve())
        pares.append((b, n))
    if por_chave:
        sobra = next(iter(por_chave))
        raise ChavesIncompativeis("sem par para %s" % sobra.descreve())
    return pares


def teste_pareado(pares: list[tuple[Resultado, Resultado]], campo: str) -> TestePareado:
    """t-test pareado de `campo` entre os dois braços. `pares` vem de
    `pareia_por_chave` — cada par é (base, novo) na MESMA condição."""
    if not pares:
        raise ValueError("nenhum par a testar")
    maior_melhor = DIRECAO.get(campo, False)
    b = [float(getattr(x, campo)) for x, _ in pares]
    n = [float(getattr(_y, campo)) for _, _y in pares]
    delta = _media([comparar(x, y).deltas[campo] for x, y in pares]) if campo in DIRECAO else float("nan")
    vitorias = sum(1 for x, y in zip(b, n) if (y > x if maior_melhor else y < x))

    t = p = None
    nota = ""
    if len(pares) >= 2:
        try:
            from scipy import stats

            tt, pp = stats.ttest_rel(n, b)
            t, p = float(tt), float(pp)
        except Exception as e:
            nota = "scipy indisponível (%s) — sem p-valor" % type(e).__name__
    else:
        nota = "1 seed: sem teste (e sem decisão — ver §5.2 do RESULTADOS_ATS)"

    return TestePareado(campo=campo, n_seeds=len(pares),
                        base_media=_media(b), base_desvio=_desvio(b),
                        novo_media=_media(n), novo_desvio=_desvio(n),
                        delta_pct=delta, vitorias=vitorias, t=t, p=p, nota=nota)


def resumo_pareado(base: list[Resultado], novo: list[Resultado],
                   campos: tuple[str, ...] = ("tempo_medio_entregue",
                                              "tempo_medio_no_sistema",
                                              "fila_media", "entregues")) -> dict:
    """Comparação completa entre dois braços em várias seeds.

    Devolve os testes por métrica MAIS a contabilidade de saúde (travamentos e
    corridas não-sãs), que nunca deve ser diluída na média."""
    pares = pareia_por_chave(base, novo)
    testes = {c: teste_pareado(pares, c) for c in campos}
    def _saude(rs):
        fora = [(r.chave.seed, r.sane()[1]) for r in rs if not r.sane()[0]]
        return {"travamentos": sum(1 for r in rs if r.travou),
                "nao_sa": fora, "n": len(rs)}
    return {
        "n_seeds": len(pares),
        "seeds": [b.chave.seed for b, _ in pares],
        "base": pares[0][0].controlador,
        "novo": pares[0][1].controlador,
        "testes": testes,
        "saude_base": _saude([b for b, _ in pares]),
        "saude_novo": _saude([n for _, n in pares]),
    }


def imprime_resumo(res: dict) -> str:
    linhas = ["%s  vs  %s   (%d seeds: %s)"
              % (res["novo"], res["base"], res["n_seeds"], res["seeds"])]
    for t in res["testes"].values():
        linhas.append("  " + t.linha())
    for lado in ("base", "novo"):
        s = res["saude_%s" % lado]
        linhas.append("  saúde %-4s: travamentos=%d  não-sãs=%s"
                      % (lado, s["travamentos"], s["nao_sa"] or "nenhuma"))
    if res["n_seeds"] < 3:
        linhas.append("  AVISO: %d seed(s) — não decida nada com isto (RESULTADOS_ATS §5.2)"
                      % res["n_seeds"])
    return "\n".join(linhas)
