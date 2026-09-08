"""Implementações de referência dos contratos — o alvo da suíte de conformidade.

Não são mocks de teste descartáveis: são a definição executável do que "implementar
o contrato" significa. Quando o agente A6 entregar o `ControladorRL` de verdade, ele
entra na MESMA suíte parametrizada que estes fakes passam hoje (`tests/
test_conformidade.py`). Se o real não passa onde o fake passa, o real está errado.

Nada aqui toca SUMO, torch ou serial.
"""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from .contratos import (
    ACEITO,
    ARMADO,
    BOTAO_START,
    MANTER,
    NEGADO,
    OFF,
    TROCAR,
    Cenario,
    Chave,
    EventoBotao,
    Janela,
    ManifestoDemanda,
    Observacao,
    RestricoesFase,
    Resultado,
    Topologia,
    caminho_manifesto,
    sha256_arquivo,
    valida_acoes,
    valida_estados,
)

# ---------------------------------------------------------------------- fábricas


def topologia_fake(n: int = 12, n_controlaveis: int | None = None) -> Topologia:
    """Uma topologia em anel com `n` nós. Por padrão reproduz o que foi MEDIDO na
    rede fechada de hoje: 12 semáforos, 8 controláveis."""
    if n_controlaveis is None:
        n_controlaveis = min(8, n)
    controlavel = tuple(i < n_controlaveis for i in range(n))
    origem = list(range(n))
    destino = [(i + 1) % n for i in range(n)]
    edge_index = np.array([origem + destino, destino + origem], dtype=np.int64)
    return Topologia(
        tls_ids=tuple("TL%02d" % i for i in range(n)),
        controlavel=controlavel,
        n_fases_verdes=tuple(2 if c else 1 for c in controlavel),
        edge_index=edge_index,
        approach_capacity=64.457,
    )


def observacao_fake(topo: Topologia, t: float = 0.0, *, dim: int = 26,
                    verde_desde: float = 99.0, rng: random.Random | None = None) -> Observacao:
    n = topo.n
    r = rng or random.Random(0)
    estado = np.array([[r.random() for _ in range(dim)] for _ in range(n)], dtype=np.float32)
    vd = np.full(n, float(verde_desde), dtype=np.float64)
    amarelo = np.zeros(n, dtype=bool)
    pode = np.array(topo.controlavel, dtype=bool) & (vd >= 0) & ~amarelo
    return Observacao(
        t=float(t),
        estado=estado,
        fase_atual=np.zeros(n, dtype=np.int64),
        verde_desde=vd,
        em_amarelo=amarelo,
        pode_trocar=pode,
        fila_por_tl=np.zeros(n, dtype=np.float64),
    )


def chave_fake(seed: int = 42, *, cenario: str = "small.maquete",
               t0: float = 0.0, t1: float = 120.0, sha: str = "0" * 64,
               restricoes: str = "di10/vm10/am3/mr0") -> Chave:
    return Chave(cenario=cenario, seed=seed, janela=Janela(t0=t0, t1=t1),
                 demanda_sha=sha, restricoes=restricoes)


def resultado_fake(chave: Chave | None = None, *, controlador: str = "fake",
                   entregues: int = 300, **campos) -> Resultado:
    """Resultado SÃO por padrão: balanço fecha, sem backlog, sem travamento."""
    k = chave or chave_fake()
    base = dict(
        chave=k,
        controlador=controlador,
        entregues=entregues,
        tempo_medio_entregue=56.2,
        tempo_medio_no_sistema=61.0,
        fila_media=7.99,
        espera_media=12.4,
        inseridos=entregues,          # regime estacionário: entra tanto quanto sai
        ativos_fim=150,
        ativos_inicio=150,
        backlog_insercao=0,
        perdidos=0,
        travou=False,
    )
    base.update(campos)
    return Resultado(**base)


# ---------------------------------------------------------------------- C3


class ControladorFake:
    """Controlador determinístico com três modos — cobre os extremos do espaço de ação.

    `modo="nunca"`  : todo MANTER (o pior caso degenerado; equivale a farol travado)
    `modo="sempre"` : todo TROCAR (o humano que martela o botão)
    `modo="rng"`    : bernoulli semeado — o adversário "aleatório" da suíte do A8
    """

    def __init__(self, modo: str = "nunca", *, p: float = 0.5, seed: int = 0) -> None:
        if modo not in ("nunca", "sempre", "rng"):
            raise ValueError("modo %r" % modo)
        self.nome = "fake:%s" % modo
        self._modo = modo
        self._p = p
        self._seed = seed
        self._rng = random.Random(seed)
        self._topo: Topologia | None = None
        self._restricoes: RestricoesFase | None = None
        self.n_decisoes = 0

    def reset(self, topo: Topologia, restricoes: RestricoesFase, t0: float) -> None:
        self._topo = topo
        self._restricoes = restricoes
        self._rng = random.Random(self._seed)   # idempotente: mesmo reset, mesma sequência
        self.n_decisoes = 0

    def decide(self, obs: Observacao) -> np.ndarray:
        if self._topo is None:
            raise RuntimeError("decide() antes de reset()")
        self.n_decisoes += 1
        n = obs.n
        if self._modo == "nunca":
            a = np.full(n, MANTER, dtype=np.int8)
        elif self._modo == "sempre":
            a = np.full(n, TROCAR, dtype=np.int8)
        else:
            a = np.array([TROCAR if self._rng.random() < self._p else MANTER
                          for _ in range(n)], dtype=np.int8)
        return valida_acoes(a, n)


# ---------------------------------------------------------------------- C6


class FonteEntradaFake:
    """Fonte de entrada roteirizada. É também o `ReplayInput` dos testes do jogo.

    `roteiro`: lista de listas — os eventos que cada `poll()` devolve, em ordem.
    Esgotado o roteiro, devolve vazio para sempre.
    """

    def __init__(self, n_botoes: int = 12, roteiro: list[list[int]] | None = None) -> None:
        self.n_botoes = n_botoes
        self.nome = "fake"
        self._roteiro = list(roteiro or [])
        self._i = 0
        self._viva = True
        self.feedbacks: list[list[str]] = []

    def poll(self) -> list[EventoBotao]:
        if self._i >= len(self._roteiro):
            return []
        indices = self._roteiro[self._i]
        self._i += 1
        return [EventoBotao(indice=i, t_wall=float(self._i)) for i in indices]

    def feedback(self, estados: list[str]) -> None:
        self.feedbacks.append(list(valida_estados(estados, self.n_botoes)))

    def viva(self) -> bool:
        return self._viva

    def desconecta(self) -> None:
        """Simula o cabo USB saindo no meio da rodada."""
        self._viva = False

    def close(self) -> None:
        self._viva = False


def roteiro_start(n_polls: int = 1) -> list[list[int]]:
    """Roteiro que aperta START e depois nada."""
    return [[BOTAO_START]] + [[] for _ in range(max(0, n_polls - 1))]


# ---------------------------------------------------------------------- C2


class GeradorDemandaFake:
    """Gerador de `.rou.xml` mínimo, determinístico por seed.

    Existe para a suíte de conformidade da C2 poder provar o invariante
    "mesma seed -> mesmo sha256" SEM depender do gerador real (que precisa de
    SUMO e da rede aberta, entregáveis do agente A1).
    """

    versao = "fake-1"

    def gera(self, cenario: Cenario, seed: int, *, forcar: bool = False) -> ManifestoDemanda:
        rou = cenario.rou_file(seed)
        man_path = caminho_manifesto(cenario, seed)
        if rou.exists() and man_path.exists() and not forcar:
            man = ManifestoDemanda.carrega(man_path)
            try:
                man.confere(rou)
                return man
            except Exception:
                pass    # em disco divergente do manifesto: regera

        rng = random.Random(seed)
        n = 20
        linhas = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>"]
        t = 0.0
        for i in range(n):
            t += rng.expovariate(1.0 / 5.0)
            linhas.append('  <trip id="v%04d" depart="%.2f" from="E_in" to="E_out"/>' % (i, t))
        linhas.append("</routes>")
        rou.parent.mkdir(parents=True, exist_ok=True)
        rou.write_text("\n".join(linhas) + "\n", encoding="utf-8")

        man = ManifestoDemanda(
            cenario=cenario.chave, seed=seed, versao_gerador=self.versao,
            sha256=sha256_arquivo(rou), n_veiculos=n, t_primeiro=0.0, t_ultimo=round(t, 2),
            parametros={"modelo": "fake", "lam": 0.2},
        )
        man.salva(man_path)
        return man

    def manifesto(self, cenario: Cenario, seed: int) -> ManifestoDemanda:
        return ManifestoDemanda.carrega(caminho_manifesto(cenario, seed))


# Seeds canônicas do projeto: 42-47 (varredura) e 100-111 (held-out).
SEEDS_CANONICAS = tuple(range(42, 48)) + tuple(range(100, 112))


def cenario_fake_arquivo(tmp: Path, *, seeds=SEEDS_CANONICAS) -> Cenario:
    """Cenário de demanda-em-arquivo apontando para um diretório temporário.

    Escreve TAMBÉM um `.sumocfg` por seed, ao lado do canônico. Não é enfeite: um
    cenário de demanda em arquivo tem um `.sumocfg` por seed **por construção** —
    quem escolhe o `.rou.xml` é o `.sumocfg`, e o `TrafficEnv` do maquete não
    aceita `--route-files`. Uma fake sem eles é estruturalmente irreal, e
    esconderia justamente a falha que custou caro: a Arena caía no canônico (que
    não tem `<route-files>`), rodava a malha VAZIA, e o diagnóstico ainda
    reportava o caminho da seed.
    """
    canon = tmp / "n.sumocfg"
    canon.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<configuration>\n'
        '  <input><net-file value="n.net.xml"/></input>\n</configuration>\n',
        encoding="utf-8")
    for s in seeds:
        (tmp / ("n_s%d.sumocfg" % s)).write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<configuration>\n'
            '  <input><net-file value="n.net.xml"/>\n'
            '         <route-files value="demanda_s%d.rou.xml"/></input>\n'
            '</configuration>\n' % s, encoding="utf-8")
    return Cenario(
        chave="fake.arquivo",
        net_file=str(tmp / "n.net.xml"),
        sumocfg=str(tmp / "n.sumocfg"),
        add_file=None,
        view_file=None,
        restricoes=RestricoesFase(decision_interval=5, min_green=7, yellow=3),
        modelo_demanda="arquivo",
        rou_pattern=str(tmp / "demanda_s{seed}.rou.xml"),
        warmup_s=0.0,
    )


__all__ = [
    "topologia_fake", "observacao_fake", "chave_fake", "resultado_fake",
    "ControladorFake", "FonteEntradaFake", "roteiro_start",
    "GeradorDemandaFake", "cenario_fake_arquivo",
    "ACEITO", "ARMADO", "NEGADO", "OFF",
]
