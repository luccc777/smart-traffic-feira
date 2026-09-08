"""`ControladorCoordenado` — o baseline HONESTO: ciclo, split por interseção e offset.

O adversário que o projeto usa hoje é o `ControladorTimer(27)`: verde de 27 s
IGUAL em toda interseção, sem offset e sem split. É um plano que nenhum
engenheiro de tráfego instalaria numa arterial de 3 faixas, e enquanto ele for o
adversário, parte do ganho publicado da RL é da fraqueza dele
(`docs/PLANO.md` §1, ressalva 1). Este módulo fecha essa ressalva.

O QUE ISTO É, E O QUE NÃO É
---------------------------
É um plano de **tempo fixo** — a mesma classe de controlador do timer. Não olha
fila, não olha estado, não aprende: dado `t`, o plano diz qual fase deveria estar
verde. O que ele tem a mais que o timer uniforme são as três coisas que definem
um plano de tempo fixo de verdade:

    ciclo   — um só para a malha inteira (pré-requisito de coordenação)
    split   — verde por FASE e por INTERSEÇÃO, proporcional ao fluxo crítico
    offset  — quando o ciclo de cada interseção começa (a onda verde)

Os três saem de ferramenta externa (`$SUMO_HOME/tools/tlsCycleAdaptation.py` para
ciclo/split por Webster, `tlsCoordinator.py` para os offsets) alimentada pela
demanda de PROJETO, e ficam congelados em `sumo/aberta/planos/*.json`. O
controlador só executa; ele não calcula nada de Webster em tempo de corrida.

A REGRA DE DECISÃO — RELÓGIO ABSOLUTO, NÃO CRONÔMETRO
-----------------------------------------------------
O timer uniforme guarda "há quanto tempo estou no verde" e troca quando vence.
Aqui isso NÃO serve: um cronômetro por interseção deriva, e offset que deriva
deixa de ser onda verde depois de alguns ciclos (min_green negado uma vez, e a
interseção fica atrasada para sempre).

A regra é outra: a cada tick, o plano diz qual fase DEVERIA estar verde no
instante `t` absoluto; se a fase corrente é outra, TROCAR. Consequências:

* o plano é **auto-sincronizante** — uma troca negada pelo `min_green` é
  recuperada no tick seguinte, e o offset volta ao lugar sozinho;
* o aquecimento (que roda o timer uniforme, igual para os três braços) não
  precisa conhecer o plano: o controlador converge para ele em ~1 ciclo;
* o plano realizado é **periódico e determinístico** — mesma seed, mesmo plano,
  mesmo `Resultado`.

A GRADE DE DECISÃO COBRA UM PEDÁGIO, E ELE ESTÁ MEDIDO
------------------------------------------------------
A Arena só consulta o controlador a cada `decision_interval` sim-steps, e a troca
só pode ser comandada num tick. Logo:

* o verde REALIZADO é `k·decision_interval − yellow` (com di=5 e amarelo=3:
  7, 12, 17, 22, 27... segundos) — nenhum outro valor é alcançável;
* o offset realizado é múltiplo de `decision_interval`;
* o ciclo tem que ser múltiplo de `decision_interval`, senão o plano não fecha
  na grade e escorrega de ciclo em ciclo.

`PlanoFixo.realizado()` devolve o plano que a grade de fato executa, e
`ControladorCoordenado.trocas` registra os instantes de troca — os dois existem
para o número publicado ser o do plano REALIZADO, não o do plano no papel.

Nada aqui lê env var: as restrições chegam no `reset()`, como manda o C3.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..contratos import (
    MANTER,
    TROCAR,
    Observacao,
    RestricoesFase,
    Topologia,
    valida_acoes,
)

__all__ = ["PlanoFixo", "ControladorCoordenado", "PlanoIncompativel"]


class PlanoIncompativel(ValueError):
    """O plano não descreve a rede que chegou no `reset()`.

    Falha alto de propósito: um plano com um semáforo a menos, ou com o número
    de fases errado, produziria uma corrida silenciosamente inválida — e corrida
    inválida vira número publicado.
    """


@dataclass(frozen=True)
class PlanoFixo:
    """Um plano de tempo fixo congelado: ciclo + splits + offsets.

    `verdes[tls]` é a duração de verde de cada fase verde, **na ordem de
    `TLPhaseInfo.green_phases`** — a mesma ordem em que o `TrafficEnv` avança
    ciclicamente quando aceita um TROCAR. É por isso que o índice do plano casa
    com `Observacao.fase_atual` sem tradução.

    `offsets[tls]` é o instante ABSOLUTO (mod ciclo) em que a fase verde de
    índice 0 começa. É a mesma convenção do `startOffset` do `tlsCoordinator.py`
    ("o instante em que o ciclo começa"), então a saída da ferramenta entra aqui
    sem conversão de sinal.

    Invariante: `sum(verdes[tls]) + n_fases·amarelo == ciclo` para todo TL com
    2+ fases. Um TL de uma fase só (nenhum na rede aberta, 6 de 10 na fechada)
    entra com verde igual ao ciclo e nunca troca.
    """

    nome: str
    cenario: str
    ciclo_s: float
    amarelo_s: float
    verdes: dict[str, tuple[float, ...]]
    offsets: dict[str, float]
    proveniencia: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ciclo_s <= 0:
            raise ValueError("ciclo_s deve ser > 0 (veio %r)" % self.ciclo_s)
        if self.amarelo_s <= 0:
            raise ValueError("amarelo_s deve ser > 0 (veio %r)" % self.amarelo_s)
        if set(self.verdes) != set(self.offsets):
            raise ValueError("verdes e offsets descrevem semáforos diferentes: %r"
                             % (set(self.verdes) ^ set(self.offsets)))
        for tls, g in self.verdes.items():
            if not g:
                raise ValueError("semáforo %s sem nenhuma fase verde" % tls)
            if min(g) <= 0:
                raise ValueError("semáforo %s com verde <= 0: %r" % (tls, g))
            if len(g) >= 2:
                total = sum(g) + len(g) * self.amarelo_s
                if abs(total - self.ciclo_s) > 1e-6:
                    raise ValueError(
                        "semáforo %s não fecha o ciclo: %r + %d×%g = %g, ciclo = %g"
                        % (tls, g, len(g), self.amarelo_s, total, self.ciclo_s))

    # ------------------------------------------------------------------ plano
    @property
    def tls_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.verdes))

    def fase_alvo(self, tls: str, t: float) -> int:
        """Qual fase verde o plano quer no instante `t` (absoluto, simulado).

        Dentro do amarelo que drena a fase `k` a resposta é `k+1`: o amarelo é
        transição, e o alvo de uma transição é para onde ela vai. É essa
        convenção que faz o TROCAR ser comandado no primeiro tick em que o verde
        corrente já deveria ter acabado — sem lookahead e sem cronômetro.
        """
        g = self.verdes[tls]
        n = len(g)
        if n < 2:
            return 0
        p = (float(t) - self.offsets[tls]) % self.ciclo_s
        acc = 0.0
        for k in range(n):
            acc += g[k]
            if p < acc:
                return k
            acc += self.amarelo_s
            if p < acc:
                return (k + 1) % n
        return 0   # inalcançável: o invariante do __post_init__ fecha o ciclo

    def realizado(self, decision_interval: int, *, origem: float = 0.0,
                  passo_s: float = 1.0) -> "PlanoFixo":
        """O plano que a GRADE de decisão de fato executa.

        A Arena só pergunta a cada `decision_interval` sim-steps, então a troca
        só acontece no primeiro tick em que `fase_alvo` já mudou. O verde
        realizado é sempre `k·di·passo − amarelo`; o offset realizado é sempre
        múltiplo de `di·passo`. Este método aplica exatamente essa regra ao plano
        no papel e devolve o plano REALIZADO — que é o que deve ser publicado.

        `origem` é o instante de um tick qualquer da grade (a fase da grade, não
        o instante inicial da corrida): a Arena começa a contar em `t_boot`, que
        não é necessariamente 0.
        """
        di = float(decision_interval) * float(passo_s)
        if di <= 0:
            raise ValueError("decision_interval·passo deve ser > 0")
        if abs(self.ciclo_s / di - round(self.ciclo_s / di)) > 1e-9:
            raise PlanoIncompativel(
                "ciclo %g não é múltiplo da grade de decisão %g s: o plano "
                "escorregaria de ciclo em ciclo e o offset deixaria de valer."
                % (self.ciclo_s, di))
        n_ticks = int(round(self.ciclo_s / di))
        verdes: dict[str, tuple[float, ...]] = {}
        offsets: dict[str, float] = {}
        for tls, g in self.verdes.items():
            if len(g) < 2:
                verdes[tls] = tuple(g)
                offsets[tls] = float(self.offsets[tls])
                continue
            # varre um ciclo de ticks e anota em qual deles o alvo muda
            ticks = [origem + j * di for j in range(n_ticks)]
            alvo = [self.fase_alvo(tls, t) for t in ticks]
            trocas: dict[int, float] = {}
            for j, t in enumerate(ticks):
                if alvo[j] != alvo[j - 1]:            # j-1 = -1 fecha o ciclo
                    trocas[alvo[j]] = t
            if len(trocas) != len(g):
                raise PlanoIncompativel(
                    "plano %s: na grade de %g s o semáforo %s só alcança %d de %d "
                    "fases — algum verde é curto demais para a grade."
                    % (self.nome, di, tls, len(trocas), len(g)))
            # verde realizado de k = (instante da troca para k+1) − (troca p/ k) − amarelo
            reais = []
            for k in range(len(g)):
                t_k = trocas[k]
                t_next = trocas[(k + 1) % len(g)]
                dur = (t_next - t_k) % self.ciclo_s
                reais.append(dur - self.amarelo_s)
            verdes[tls] = tuple(reais)
            # o ciclo realizado começa quando o verde 0 começa: troca p/ 0 + amarelo
            offsets[tls] = (trocas[0] + self.amarelo_s) % self.ciclo_s
        prov = dict(self.proveniencia)
        prov["realizado_em_grade_s"] = di
        prov["realizado_origem_s"] = float(origem)
        prov["plano_no_papel"] = self.nome
        return PlanoFixo(nome=self.nome + "@grade%g" % di, cenario=self.cenario,
                         ciclo_s=self.ciclo_s, amarelo_s=self.amarelo_s,
                         verdes=verdes, offsets=offsets, proveniencia=prov)

    # ------------------------------------------------------------------- i/o
    def como_dict(self) -> dict:
        return {
            "nome": self.nome,
            "cenario": self.cenario,
            "ciclo_s": self.ciclo_s,
            "amarelo_s": self.amarelo_s,
            "tls": {t: {"verdes_s": list(self.verdes[t]),
                        "offset_s": self.offsets[t]}
                    for t in self.tls_ids},
            "proveniencia": self.proveniencia,
        }

    def salva(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.como_dict(), indent=2, ensure_ascii=False,
                                sort_keys=False) + "\n",
                     encoding="utf-8", newline="\n")
        return p

    @classmethod
    def de_dict(cls, d: dict) -> "PlanoFixo":
        return cls(
            nome=str(d["nome"]),
            cenario=str(d.get("cenario", "")),
            ciclo_s=float(d["ciclo_s"]),
            amarelo_s=float(d["amarelo_s"]),
            verdes={t: tuple(float(x) for x in v["verdes_s"]) for t, v in d["tls"].items()},
            offsets={t: float(v["offset_s"]) for t, v in d["tls"].items()},
            proveniencia=dict(d.get("proveniencia", {})),
        )

    @classmethod
    def carrega(cls, path: str | Path) -> "PlanoFixo":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                "plano %s não existe. Os planos congelados vivem em "
                "sumo/aberta/planos/ e são gerados por "
                "`python scripts/tune_baseline_plano.py`." % p)
        return cls.de_dict(json.loads(p.read_text(encoding="utf-8")))

    # --------------------------------------------------------------- fábrica
    @classmethod
    def uniforme(cls, tls_ids, n_fases, verde_s: float, amarelo_s: float,
                 *, nome: str = "uniforme", cenario: str = "") -> "PlanoFixo":
        """O timer uniforme escrito como plano — split igual, offset zero.

        Serve a dois propósitos e a nenhum terceiro: (a) provar em teste que o
        `ControladorCoordenado` com este plano reproduz o `ControladorTimer`
        (mesmo braço, duas implementações), e (b) ser o degrau 0 da varredura de
        sensibilidade, para o efeito de ciclo, split e offset ficar separado.
        """
        verdes = {}
        offsets = {}
        for tls, k in zip(tls_ids, n_fases):
            k = max(int(k), 1)
            verdes[tls] = tuple([float(verde_s)] * k)
            offsets[tls] = 0.0
        ciclo = float(verde_s + amarelo_s) * max(int(max(n_fases)), 1)
        return cls(nome=nome, cenario=cenario, ciclo_s=ciclo, amarelo_s=float(amarelo_s),
                   verdes=verdes, offsets=offsets,
                   proveniencia={"origem": "PlanoFixo.uniforme", "verde_s": float(verde_s)})


class ControladorCoordenado:
    """Executa um `PlanoFixo`. Implementa o C3 e nada além dele."""

    def __init__(self, plano: PlanoFixo | str | Path, *, nome: str | None = None,
                 registra_trocas: bool = True) -> None:
        self.plano = plano if isinstance(plano, PlanoFixo) else PlanoFixo.carrega(plano)
        self.nome = nome or "timer:%s" % self.plano.nome
        self.registra_trocas = bool(registra_trocas)
        self._topo: Topologia | None = None
        self._controlavel: np.ndarray | None = None
        self._restricoes: RestricoesFase | None = None
        self._tls: tuple[str, ...] = ()
        self._t0 = 0.0
        self.n_decisoes = 0
        self.n_trocas = 0
        self.trocas: list[tuple[float, int, int]] = []   # (t, índice do TL, fase alvo)

    # ---------------------------------------------------------------- ciclo
    def reset(self, topo: Topologia, restricoes: RestricoesFase, t0: float) -> None:
        faltando = [t for t in topo.tls_ids if t not in self.plano.verdes]
        if faltando:
            raise PlanoIncompativel(
                "plano %s não cobre %d semáforo(s) desta rede: %s"
                % (self.plano.nome, len(faltando), ", ".join(faltando)))
        for i, tls in enumerate(topo.tls_ids):
            n_plano = len(self.plano.verdes[tls])
            n_rede = int(topo.n_fases_verdes[i])
            if n_plano != n_rede:
                raise PlanoIncompativel(
                    "plano %s dá %d fase(s) verde(s) a %s, a rede tem %d — o índice "
                    "do plano deixaria de casar com Observacao.fase_atual."
                    % (self.plano.nome, n_plano, tls, n_rede))
        # o ciclo tem que fechar na grade, senão o offset escorrega
        di = float(restricoes.decision_interval)
        if abs(self.plano.ciclo_s / di - round(self.plano.ciclo_s / di)) > 1e-9:
            raise PlanoIncompativel(
                "ciclo %g s não é múltiplo da grade de decisão (%g sim-steps): o "
                "plano escorregaria de ciclo em ciclo e o offset deixaria de valer."
                % (self.plano.ciclo_s, di))
        if abs(self.plano.amarelo_s - restricoes.yellow) > 1e-9:
            raise PlanoIncompativel(
                "plano com amarelo de %g s contra %g s do cenário — os dois braços "
                "estariam medindo restrições de fase diferentes."
                % (self.plano.amarelo_s, restricoes.yellow))
        self._topo = topo
        self._tls = tuple(topo.tls_ids)
        self._controlavel = np.asarray(topo.controlavel, dtype=bool)
        self._restricoes = restricoes
        self._t0 = float(t0)
        self.n_decisoes = 0
        self.n_trocas = 0
        self.trocas = []

    def decide(self, obs: Observacao) -> np.ndarray:
        if self._topo is None or self._controlavel is None:
            raise RuntimeError("decide() antes de reset()")
        self.n_decisoes += 1
        n = obs.n
        acoes = np.full(n, MANTER, dtype=np.int8)
        for i in range(min(n, len(self._tls))):
            if not self._controlavel[i] or bool(obs.em_amarelo[i]):
                continue
            alvo = self.plano.fase_alvo(self._tls[i], obs.t)
            if alvo != int(obs.fase_atual[i]):
                acoes[i] = TROCAR
                self.n_trocas += 1
                if self.registra_trocas:
                    self.trocas.append((float(obs.t), i, int(alvo)))
        return valida_acoes(acoes, n)

    # ---------------------------------------------------------- diagnóstico
    def plano_executado(self, *, ciclos_de_transiente: int = 2) -> dict[str, dict]:
        """O que o plano REALIZOU nesta corrida, semáforo a semáforo.

        Sai dos instantes de troca de verdade, não da aritmética do papel: é o
        único jeito honesto de reportar o verde e o offset que a grade entregou.

        `ciclos_de_transiente` descarta o começo: a corrida herda do aquecimento
        (que roda o timer uniforme, igual para os três braços) uma configuração
        de fases que não é a do plano, e o plano leva ~1 ciclo para se prender ao
        relógio absoluto. Medido: a partir daí o offset realizado é CONSTANTE, e
        é por isso que ele é reportado — se variasse, a onda verde não existiria.
        """
        corte = self._t0 + ciclos_de_transiente * self.plano.ciclo_s
        por_tl: dict[str, list[tuple[float, int]]] = {t: [] for t in self._tls}
        for t, i, alvo in self.trocas:
            if t >= corte:
                por_tl[self._tls[i]].append((t, alvo))
        saida = {}
        C = self.plano.ciclo_s
        for tls, ev in por_tl.items():
            if len(ev) < 2:
                saida[tls] = {"n_trocas": len(ev), "verde_medio_s": None,
                              "offset_realizado_s": None}
                continue
            ts = [t for t, _ in ev]
            intervalos = [b - a for a, b in zip(ts, ts[1:])]
            # o offset realizado é a fase do ciclo em que o verde 0 de fato começa.
            # Preso ao relógio absoluto, isto é constante; se variar, o plano está
            # derivando e a onda verde já não existe.
            inicios0 = [(t + self.plano.amarelo_s) % C for t, alvo in ev if alvo == 0]
            saida[tls] = {
                "n_trocas": len(ev),
                "verde_medio_s": sum(intervalos) / len(intervalos) - self.plano.amarelo_s,
                "verde_min_s": min(intervalos) - self.plano.amarelo_s,
                "verde_max_s": max(intervalos) - self.plano.amarelo_s,
                "offset_realizado_s": inicios0[-1] if inicios0 else None,
                "offset_estavel": (len(set(round(x, 6) for x in inicios0)) <= 1
                                   if inicios0 else None),
            }
        return saida
