"""As políticas "humanas" roteirizadas — o que o visitante APERTA, tick a tick.

Uma política aqui NÃO é um `Controlador` (C3). Ela devolve **botões apertados**,
e quem transforma botão em ação é o `ControladorHumano`, pela camada de entrada
(C6) — exatamente o caminho do visitante de carne e osso. A separação existe
porque a alternativa (escrever o adversário direto como C3, emitindo o vetor de
ações) **pula a camada que define o jogo**: a intenção enfileirada, o consumo no
próximo tick da grade e a máscara de verde mínimo. Um adversário C3 mede outro
jogo, e o número dele não responde à pergunta do A8.

O QUE A POLÍTICA ENXERGA
------------------------
`Leitura` é o recorte do estado que o VISITANTE tem no projetor: fila por
cruzamento (o mapa de calor), fase corrente, tempo no verde e amarelo. As duas
colunas extras — `fila_servida` e `fila_parada` — são a mesma fila separada
entre "aproximações que estão no verde agora" e "as que estão no vermelho".
Elas exigem o mapa fase→aproximação da rede (`feira.adversarios.bancada
.mapa_de_fases`) e existem para o adversário ORÁCULO: um visitante real não lê
o vetor da política, mas lê o mapa de calor e sabe qual lado está parado. Quando
o mapa não é passado, as duas vêm `NaN` e as políticas que dependem delas
recusam rodar em vez de decidir no escuro.

O RUÍDO NÃO É ENFEITE
---------------------
Nenhum visitante aperta com regularidade de relógio. `Ruido` erra pressões
(`p_falha`) e aperta o que não queria (`p_extra`), e é o que torna duas rodadas
do MESMO adversário na MESMA seed dois eventos diferentes — sem isso, "200
rodadas por adversário" seriam 12 rodadas copiadas 17 vezes, e o intervalo de
confiança sairia estreito por construção. `Limite` é a mão: quantos botões cabem
num tick de 5 s.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

__all__ = [
    "Aleatoria",
    "Arterial",
    "CATALOGO",
    "GulosaFase",
    "GulosaFila",
    "Leitura",
    "Limite",
    "Martelo",
    "Parada",
    "Periodica",
    "Politica",
    "Roteirista",
    "Ruido",
    "Sabotador",
    "de_texto",
    "leitura_de",
]


@dataclass(frozen=True)
class Leitura:
    """O que o visitante enxerga do projetor num tick. Recorte da `Observacao` (C3).

    `fila_servida`/`fila_parada` são `NaN` quando o mapa fase→aproximação não foi
    passado: a política oráculo levanta em vez de decidir com lixo.
    """

    t: float
    fila_por_tl: np.ndarray
    fase_atual: np.ndarray
    verde_desde: np.ndarray
    em_amarelo: np.ndarray
    fila_servida: np.ndarray
    fila_parada: np.ndarray

    @property
    def n(self) -> int:
        return int(self.fila_por_tl.shape[0])

    @property
    def tem_aproximacoes(self) -> bool:
        return not bool(np.isnan(self.fila_servida).any())


# Colunas de `halting` no estado `ats` (N, 26): 4 aproximações x
# (halting, running, wait, speed), na ordem fixa N, S, E, W do `traffic_env`.
COL_HALTING = (0, 4, 8, 12)
DIRECOES = ("N", "S", "E", "W")


def leitura_de(obs, mapa=None) -> Leitura:
    """Monta a `Leitura` a partir de uma `Observacao` (C3) e do mapa de fases.

    `mapa` é `(N, G, 4)` booleano — aproximação servida por cada grupo de verde,
    na ordem N,S,E,W — mais a capacidade de aproximação usada para desnormalizar
    o `halting` do estado `ats`. Ver `feira.adversarios.bancada.mapa_de_fases`.
    """
    n = int(obs.n)
    fila = np.asarray(obs.fila_por_tl, dtype=np.float64)
    fase = np.asarray(obs.fase_atual, dtype=np.int64)
    servida = np.full(n, np.nan)
    parada = np.full(n, np.nan)
    if mapa is not None:
        serve, capacidade = mapa
        estado = np.asarray(obs.estado, dtype=np.float64)
        # (N, 4) de parados por aproximação. O estado vem normalizado e SATURADO
        # em 1 aproximação cheia — é o mesmo teto que a política enxerga, e o
        # visitante que olha o mapa de calor também não distingue "cheio" de
        # "muito cheio".
        halting = estado[:, list(COL_HALTING)] * float(capacidade)
        idx = np.clip(fase, 0, serve.shape[1] - 1)
        verde = serve[np.arange(n), idx]          # (N, 4) bool
        servida = (halting * verde).sum(axis=1)
        parada = (halting * (~verde)).sum(axis=1)
    return Leitura(t=float(obs.t), fila_por_tl=fila, fase_atual=fase,
                   verde_desde=np.asarray(obs.verde_desde, dtype=np.float64),
                   em_amarelo=np.asarray(obs.em_amarelo, dtype=bool),
                   fila_servida=servida, fila_parada=parada)


@runtime_checkable
class Politica(Protocol):
    """Devolve os botões apertados entre o tick anterior e este."""

    nome: str
    reativa: bool

    def reset(self, n_botoes: int) -> None:
        ...

    def aperta(self, tick: int, leitura: Leitura | None, rng: random.Random) -> tuple[int, ...]:
        ...


class _Base:
    reativa = False
    # `estocastica`: a política sorteia por conta própria? É o que decide se
    # repetir a mesma seed produz uma rodada NOVA ou uma cópia — e repetir cópia
    # estreita o intervalo de confiança sem acrescentar informação nenhuma.
    estocastica = False

    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.n_botoes = 0

    def reset(self, n_botoes: int) -> None:
        self.n_botoes = int(n_botoes)

    def _todos(self) -> tuple[int, ...]:
        return tuple(range(self.n_botoes))


class Parada(_Base):
    """Não aperta nada. O piso do placar, e o controle do experimento."""

    def __init__(self) -> None:
        super().__init__("parado")

    def aperta(self, tick, leitura, rng) -> tuple[int, ...]:
        return ()


class Martelo(_Base):
    """Aperta os 12 botões em TODO tick — o visitante que dá tapa no painel.

    Com `di=5`, `min_green=7` e amarelo 3, isso realiza verde de 7 s: a troca é
    aceita no primeiro tick em que `verde_desde >= 7`, e o painel 3x4 permite
    bater nos 12 com as duas palmas. É o adversário que o A3 mediu vencendo o
    timer uniforme de 27 s em 6 de 6 seeds.
    """

    def __init__(self) -> None:
        super().__init__("martelo")

    def aperta(self, tick, leitura, rng) -> tuple[int, ...]:
        return self._todos()


class Periodica(_Base):
    """Aperta os 12 a cada `periodo` ticks — o visitante com ritmo.

    Varre o comprimento de ciclo alcançável pelo botão: `periodo` ticks entre
    trocas dá verde de `periodo * decision_interval - amarelo` (7, 12, 17, 22...
    com di=5/am=3), respeitado o piso do verde mínimo.
    """

    def __init__(self, periodo: int = 2, fase: int = 0) -> None:
        if periodo < 1:
            raise ValueError("periodo deve ser >= 1 (veio %r)" % periodo)
        super().__init__("periodica_p%d" % periodo)
        self.periodo = int(periodo)
        self.fase = int(fase)

    def aperta(self, tick, leitura, rng) -> tuple[int, ...]:
        return self._todos() if (tick + self.fase) % self.periodo == 0 else ()


class Aleatoria(_Base):
    """Cada botão apertado com probabilidade `p` a cada tick. O visitante sem plano."""

    estocastica = True

    def __init__(self, p: float = 0.35) -> None:
        if not (0.0 <= p <= 1.0):
            raise ValueError("p deve estar em [0,1] (veio %r)" % p)
        super().__init__("aleatoria_p%g" % p)
        self.p = float(p)

    def aperta(self, tick, leitura, rng) -> tuple[int, ...]:
        return tuple(b for b in range(self.n_botoes) if rng.random() < self.p)


class Arterial(_Base):
    """Segura o verde na arterial: aperta o cruzamento cuja fase não é a dela.

    A estratégia que todo mundo propõe em voz alta ("deixa a avenida sempre
    verde") e que este experimento existe para medir em vez de supor.
    """

    reativa = True

    def __init__(self, grupo: np.ndarray | None = None) -> None:
        super().__init__("arterial")
        self.grupo = grupo

    def com_grupo(self, grupo) -> "Arterial":
        self.grupo = np.asarray(grupo, dtype=np.int64)
        return self

    def aperta(self, tick, leitura, rng) -> tuple[int, ...]:
        if leitura is None:
            return ()
        if self.grupo is None:
            raise ValueError("política 'arterial' sem o grupo de verde da arterial: "
                             "passe o mapa de fases (bancada.mapa_de_fases)")
        alvo = self.grupo[: leitura.n]
        return tuple(int(i) for i in np.nonzero(leitura.fase_atual[: len(alvo)] != alvo)[0]
                     if i < self.n_botoes)


class GulosaFila(_Base):
    """Aperta os `k` cruzamentos de maior fila total (acima de `limiar`).

    É o que o visitante de fato faz na frente do projetor: olha o mapa de calor,
    acha o vermelho mais gordo e bate naquele botão. Não sabe para qual fase vai
    trocar — só que aquele cruzamento está parado.
    """

    reativa = True

    def __init__(self, k: int = 4, limiar: float = 1.0) -> None:
        super().__init__("gulosa_fila_k%d" % k)
        self.k = int(k)
        self.limiar = float(limiar)

    def aperta(self, tick, leitura, rng) -> tuple[int, ...]:
        if leitura is None:
            return ()
        fila = leitura.fila_por_tl[: self.n_botoes]
        candidatos = [i for i in np.argsort(-fila) if fila[i] >= self.limiar]
        return tuple(int(i) for i in candidatos[: self.k])


class GulosaFase(_Base):
    """ORÁCULO: troca quando o lado no VERMELHO tem mais fila que o lado no verde.

    Precisa do mapa fase→aproximação — é a política que enxerga o que o mapa de
    calor mostra separado por aproximação. Serve de teto: é o melhor "humano
    plausível" deste catálogo, e é dele que sai a manchete de P(vitória).
    """

    reativa = True

    def __init__(self, fator: float = 1.0, margem: float = 0.0) -> None:
        super().__init__("gulosa_fase_f%g" % fator)
        self.fator = float(fator)
        self.margem = float(margem)

    def aperta(self, tick, leitura, rng) -> tuple[int, ...]:
        if leitura is None:
            return ()
        if not leitura.tem_aproximacoes:
            raise ValueError("política %r exige o mapa fase→aproximação "
                             "(bancada.mapa_de_fases)" % self.nome)
        n = min(self.n_botoes, leitura.n)
        parada = leitura.fila_parada[:n]
        servida = leitura.fila_servida[:n]
        quer = parada > (self.fator * servida + self.margem)
        return tuple(int(i) for i in np.nonzero(quer)[0])


class Sabotador(_Base):
    """O contrário da gulosa: serve sempre o lado VAZIO. Existe para pegar bug de métrica.

    Um adversário que trava a rede MELHORA `tempo_medio_entregue` — os presos
    saem da média e sobram as viagens curtas (a armadilha nº3 do A8, e o motivo
    pelo qual a manchete do jogo é `entregues`). Ele entra na campanha para que
    esse artefato apareça medido, com número, em vez de ficar como advertência.
    """

    reativa = True

    def __init__(self, fator: float = 1.0) -> None:
        super().__init__("sabotador")
        self.fator = float(fator)

    def aperta(self, tick, leitura, rng) -> tuple[int, ...]:
        if leitura is None:
            return ()
        if not leitura.tem_aproximacoes:
            raise ValueError("política 'sabotador' exige o mapa fase→aproximação")
        n = min(self.n_botoes, leitura.n)
        parada = leitura.fila_parada[:n]
        servida = leitura.fila_servida[:n]
        quer = servida > (self.fator * parada)
        return tuple(int(i) for i in np.nonzero(quer)[0])


# ------------------------------------------------------------------ modificadores
@dataclass(frozen=True)
class Ruido:
    """A mão errando: `p_falha` derruba a pressão pretendida, `p_extra` inventa uma."""

    p_falha: float = 0.0
    p_extra: float = 0.0

    def aplica(self, botoes: tuple[int, ...], n: int, rng: random.Random) -> tuple[int, ...]:
        if self.p_falha <= 0.0 and self.p_extra <= 0.0:
            return botoes
        saida = {b for b in botoes if rng.random() >= self.p_falha}
        if self.p_extra > 0.0:
            for b in range(n):
                if b not in saida and rng.random() < self.p_extra:
                    saida.add(b)
        return tuple(sorted(saida))

    @property
    def ativo(self) -> bool:
        return self.p_falha > 0.0 or self.p_extra > 0.0


@dataclass(frozen=True)
class Limite:
    """Quantos botões cabem num tick. `0` = sem limite (as duas palmas no painel)."""

    max_por_tick: int = 0

    def aplica(self, botoes: tuple[int, ...], rng: random.Random) -> tuple[int, ...]:
        if self.max_por_tick <= 0 or len(botoes) <= self.max_por_tick:
            return botoes
        # A ordem que chega é a de PRIORIDADE da política (a gulosa entrega os
        # maiores primeiro); truncar preserva a intenção melhor que sortear.
        return tuple(botoes[: self.max_por_tick])


@dataclass
class Roteirista:
    """Política + ruído + limite. É o objeto que a bancada roda.

    `semente` fecha a reprodutibilidade: (adversário, seed da demanda, repetição)
    determina a sequência inteira de botões — a mesma rodada roda igual duas
    vezes, que é o que permite auditar um resultado depois.
    """

    politica: Politica
    ruido: Ruido = field(default_factory=Ruido)
    limite: Limite = field(default_factory=Limite)
    lag_ticks: int = 0
    semente: int = 0

    def __post_init__(self) -> None:
        if self.lag_ticks < 0:
            raise ValueError("lag_ticks >= 0 (veio %r)" % self.lag_ticks)
        self.n_botoes = 0
        self._rng = random.Random(self.semente)

    @property
    def nome(self) -> str:
        partes = [self.politica.nome]
        if self.lag_ticks:
            partes.append("lag%d" % self.lag_ticks)
        if self.ruido.p_falha:
            partes.append("falha%g" % self.ruido.p_falha)
        if self.ruido.p_extra:
            partes.append("extra%g" % self.ruido.p_extra)
        if self.limite.max_por_tick:
            partes.append("mao%d" % self.limite.max_por_tick)
        return "+".join(partes)

    @property
    def reativa(self) -> bool:
        return bool(getattr(self.politica, "reativa", False))

    @property
    def deterministica(self) -> bool:
        """Duas repetições na mesma seed dão a MESMA rodada? (então repetir é copiar)"""
        return not (self.ruido.ativo or bool(getattr(self.politica, "estocastica", False)))

    def reset(self, n_botoes: int) -> None:
        self.politica.reset(int(n_botoes))
        self._rng = random.Random(self.semente)
        self.n_botoes = int(n_botoes)

    def aperta(self, tick: int, leitura: Leitura | None) -> tuple[int, ...]:
        botoes = tuple(self.politica.aperta(int(tick), leitura, self._rng))
        botoes = self.limite.aplica(botoes, self._rng)
        return self.ruido.aplica(botoes, self.n_botoes, self._rng)


# ------------------------------------------------------------------------ catálogo
CATALOGO = {
    "parado": lambda **kw: Parada(),
    "martelo": lambda **kw: Martelo(),
    "periodica": lambda p=2, fase=0, **kw: Periodica(int(p), int(fase)),
    "aleatoria": lambda p=0.35, **kw: Aleatoria(float(p)),
    "arterial": lambda **kw: Arterial(),
    "gulosa_fila": lambda k=4, limiar=1.0, **kw: GulosaFila(int(k), float(limiar)),
    "gulosa_fase": lambda f=1.0, margem=0.0, **kw: GulosaFase(float(f), float(margem)),
    "sabotador": lambda f=1.0, **kw: Sabotador(float(f)),
}


def _valor(txt: str):
    try:
        v = float(txt)
    except ValueError:
        return txt
    return int(v) if v.is_integer() and "." not in txt else v


def de_texto(spec: str, *, semente: int = 0) -> Roteirista:
    """Constrói um `Roteirista` de uma linha de comando.

        martelo
        periodica:p=3
        aleatoria:p=0.35@falha=0.05
        gulosa_fase:f=1.2@lag=1@falha=0.05@mao=6

    Antes do `@` vai a política e os parâmetros dela; depois, os modificadores
    (`lag`, `falha`, `extra`, `mao`). Nome desconhecido falha alto — um typo que
    caísse num default silencioso mediria outro adversário.
    """
    corpo, _, resto = str(spec).strip().partition("@")
    nome, _, args = corpo.partition(":")
    nome = nome.strip()
    if nome not in CATALOGO:
        raise ValueError("adversário %r desconhecido (use %s)"
                         % (nome, " | ".join(sorted(CATALOGO))))
    kw = {}
    for pedaco in args.split(","):
        if not pedaco.strip():
            continue
        k, _, v = pedaco.partition("=")
        kw[k.strip()] = _valor(v.strip())
    mods = {}
    for pedaco in resto.split("@"):
        if not pedaco.strip():
            continue
        k, _, v = pedaco.partition("=")
        mods[k.strip()] = _valor(v.strip()) if v.strip() else True
    pol = CATALOGO[nome](**kw)
    desconhecidos = sorted(set(mods) - {"lag", "falha", "extra", "mao"})
    if desconhecidos:
        raise ValueError("modificador(es) %r desconhecido(s) (use lag|falha|extra|mao)"
                         % desconhecidos)
    return Roteirista(
        politica=pol,
        ruido=Ruido(p_falha=float(mods.get("falha", 0.0)),
                    p_extra=float(mods.get("extra", 0.0))),
        limite=Limite(max_por_tick=int(mods.get("mao", 0))),
        lag_ticks=int(mods.get("lag", 0)),
        semente=int(semente),
    )


def verde_realizado_s(periodo_ticks: int, decision_interval: int, min_green: int,
                      yellow: int) -> float:
    """O verde que `periodo_ticks` entre pressões REALIZA na grade da Arena.

    Não é `periodo * di`: a troca só é aceita quando `verde_desde >= min_green`,
    e o amarelo consome parte do bloco. Serve para rotular a varredura da
    `Periodica` em segundos em vez de em ticks.
    """
    di = float(decision_interval)
    piso = math.ceil((float(min_green) + float(yellow)) / di) * di
    return max(piso, float(periodo_ticks) * di) - float(yellow)
