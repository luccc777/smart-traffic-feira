"""C4 — `Arena`: UM laço de simulação, três braços.

O contrato mais importante do repo. Hoje, no maquete, o braço da rede neural e o
braço do timer são dois laços escritos à mão, em dois processos, cada um com seu
controle de cadência — e é entre eles que mora a deriva que a auditoria achou.
Aqui existe um laço só: ele sobe o SUMO, roda o aquecimento, entrega o controle ao
`Controlador` na grade certa, mede, e devolve um `Resultado` (C5) carimbado com a
`Chave` da condição.

CICLO DE VIDA (o mesmo para RL, timer e humano)
-----------------------------------------------
    1. cenario.aplicar()                    env antes de qualquer import de `sim`
    2. sobe SUMO com --seed e o .rou.xml da seed
    3. AQUECIMENTO até `cenario.warmup_s` com `cenario.warmup_plano`
       -> os três braços partem do MESMO estado; é isto que torna a rodada pareada
    4. controlador.reset(topo, restricoes, t0)
    5. laço até t1:  a cada `decision_interval` steps -> controlador.decide(obs)
                     todo step               -> aplica fases, mede, chama o observador
    6. devolve Resultado(chave=Chave(cenario, seed, janela, demanda_sha), ...)

MODO AO VIVO
------------
O mesmo laço serve a avaliação headless e a projeção: o que muda é o `Observador`
(que recebe um frame por sim-step) e o `ritmo` (headless = solto; ao vivo = 1 s
simulado por 1 s de parede). A cadência é do laço, nunca do controlador — é o que
impede o braço lento de "andar menos" e ainda assim ser comparado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from .cenario import Cenario
from .controlador import Controlador, Topologia
from .resultado import Janela, Resultado


class ArenaNaoConfigurada(RuntimeError):
    """Cenário sem os números MEDIDOS que a corrida exige (ex.: `warmup_s is None`).

    Recusa deliberada: warm-up chutado contamina toda métrica medida depois dele.
    O número sai de `docs/CALIBRACAO_ABERTA.md`, não de estimativa.
    """


class TravamentoDetectado(RuntimeError):
    """A malha travou e a corrida foi abortada. Vira `Resultado.travou=True`.

    Não é falha de software: é resultado, e vai reportado seed a seed, separado
    das médias (regra que saiu do artefato de sobrevivência da variante C).
    """


@dataclass(frozen=True)
class Ritmo:
    """Cadência do laço.

    `sim_por_parede`: quantos segundos simulados por segundo de parede. `None` =
    solto (headless, o mais rápido possível). 1.0 = tempo real, o da projeção.

    `recupera_atraso`: quando o laço fica para trás, tenta recuperar em vez de
    reajustar o relógio em silêncio. O código atual do dashboard faz
    `deadline = perf_counter()` ao atrasar — o atraso some da vista e nunca volta,
    e é assim que os dois braços derivam. Aqui o atraso é ACUMULADO e reportado.
    """

    sim_por_parede: float | None = None
    recupera_atraso: bool = True
    atraso_max_s: float = 2.0     # acima disto o laço avisa o observador


@dataclass(frozen=True)
class Frame:
    """Um instante da simulação, para o observador. Leitura pura — ver C7."""

    braco: str
    t: float
    decisao: int
    substep: int
    veiculos: list[dict]
    tls: list[dict]
    heat: dict[str, int]
    stats: dict


Observador = Callable[[Frame], None]
"""Callback por sim-step. Ao vivo é o publisher do WebSocket; headless é `None`."""


@runtime_checkable
class Arena(Protocol):
    """Roda um braço numa condição e devolve o que ele mediu."""

    def topologia(self, cenario: Cenario) -> Topologia:
        """Deriva a topologia do `.net.xml` sem subir o SUMO."""
        ...

    def roda(
        self,
        cenario: Cenario,
        seed: int,
        controlador: Controlador,
        janela: Janela | None = None,
        *,
        ritmo: Ritmo | None = None,
        observador: Observador | None = None,
        gui: bool = False,
    ) -> Resultado:
        """Uma corrida completa. `janela=None` usa `cenario.janela_eval_s` a partir
        do fim do aquecimento."""
        ...


def janela_padrao(cenario: Cenario, *, rodada: bool = False) -> Janela:
    """A janela de medição que começa no fim do aquecimento.

    Levanta se o warm-up do cenário ainda não foi medido — o mesmo motivo do
    `ArenaNaoConfigurada`, só que na hora de montar a janela.
    """
    if cenario.warmup_s is None:
        raise ArenaNaoConfigurada(
            "cenário %s sem warmup_s medido. O aquecimento de uma rede aberta é o "
            "tempo até a malha sair do transiente de enchimento; medir é entregável "
            "do agente A1 (docs/CALIBRACAO_ABERTA.md)." % cenario.chave
        )
    t0 = float(cenario.warmup_s)
    dur = cenario.janela_rodada_s if rodada else cenario.janela_eval_s
    return Janela(t0=t0, t1=t0 + float(dur))
