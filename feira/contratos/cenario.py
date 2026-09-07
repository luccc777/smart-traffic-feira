"""C1 — `Cenario`: qual rede, qual demanda, e as restrições de fase que valem para TODOS.

Este é o contrato mais a montante: tudo o mais (demanda, arena, controladores, jogo)
recebe um `Cenario` e nunca lê env var por conta própria.

A REGRA QUE ESTE MÓDULO EXISTE PARA IMPOR
-----------------------------------------
As restrições de fase — verde mínimo, amarelo, max-red, grade de decisão — são
**as mesmas para os três braços** (RL, timer, humano). Sem isso o humano alterna
fase a cada tick e a comparação não vale nada. Por isso elas moram num objeto
`RestricoesFase` congelado que o `Cenario` entrega pronto: um controlador RECEBE
as restrições, não as escolhe. Um controlador que lê `ST_MIN_GREEN` por conta
própria está errado por construção.

A ARMADILHA DO PACOTE `sim` (herdada, e por isso guardada aqui)
--------------------------------------------------------------
`sim.environment.constants` lê env vars **no import** e vira singleton de módulo.
Ou seja: quem importa `sim.environment` antes de o cenário estar aplicado fica com
a configuração errada, em silêncio, para sempre naquele processo. Foi exatamente
essa classe de bug que deixou o projeto com dois baselines diferentes no mesmo
repositório (20 s na avaliação, 30 s no dashboard).

`aplicar()` fecha a porta: escreve as env vars E verifica se `sim` já foi importado
com outra configuração — se foi, levanta. Barulho alto em vez de número errado.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]  # .../smart-traffic-feira
_MAQUETE = _RAIZ.parent / "smart-traffic-maquete"


class CenarioJaImportado(RuntimeError):
    """`sim.environment` já estava importado com OUTRA configuração neste processo.

    Não há conserto em tempo de execução: os escalares de `constants.py` foram
    congelados no import. O chamador precisa aplicar o cenário ANTES do primeiro
    `import sim.environment...` — na prática, no topo do processo/worker.
    """


@dataclass(frozen=True)
class RestricoesFase:
    """As regras de fase. Iguais para RL, timer e humano — é decisão fechada.

    `decision_interval` é a GRADE: um controlador só é consultado a cada
    `decision_interval` sim-steps. Vale para o humano também — o botão dele
    enfileira intenção e ela é consumida no próximo tick, exatamente como a
    ação da RL. Aplicar na hora daria ao humano uma grade mais fina que a da
    política, e a comparação deixaria de ser pareada.

    O verde mais curto ALCANÇÁVEL não é `min_green`: é ele arredondado para
    cima na grade de decisões (ver `verde_minimo_alcancavel`). É o número que
    descreve de verdade o espaço de políticas.
    """

    decision_interval: int   # sim-steps entre decisões
    min_green: int           # s de verde antes de um switch ser aceito
    yellow: int              # s de amarelo obrigatório
    max_red: float = 0.0     # s sem verde antes da troca ser FORÇADA; 0 = guarda desligada

    def __post_init__(self) -> None:
        if self.decision_interval < 1:
            raise ValueError("decision_interval deve ser >= 1 (veio %r)" % self.decision_interval)
        if self.min_green < 0 or self.yellow < 1:
            raise ValueError("min_green >= 0 e yellow >= 1 (veio %r/%r)" % (self.min_green, self.yellow))
        if self.max_red and self.max_red <= self.min_green + self.yellow:
            raise ValueError(
                "max_red (%r) <= min_green+yellow (%r): a guarda dispararia antes de o "
                "verde mínimo fechar, e toda decisão do agente viraria no-op."
                % (self.max_red, self.min_green + self.yellow)
            )

    @property
    def verde_minimo_alcancavel(self) -> int:
        """O verde mais curto que o espaço de ação realmente permite (s).

        `min_green` é o piso para ACEITAR o switch; o switch só é consultado na
        grade, então o verde efetivo sobe até o próximo múltiplo de
        `decision_interval` depois de `min_green + yellow`.
        """
        di = self.decision_interval
        resto = (self.min_green + self.yellow) % di
        return self.min_green + (di - resto if resto else 0)

    def env(self) -> dict[str, str]:
        return {
            "ST_DECISION_INTERVAL": str(self.decision_interval),
            "ST_MIN_GREEN": str(self.min_green),
            "ST_MAX_RED": str(self.max_red),
        }


@dataclass(frozen=True)
class Cenario:
    """Uma configuração completa e reproduzível: rede + demanda + restrições.

    `warmup_s` é `None` enquanto NÃO tiver sido medido. A `Arena` recusa rodar
    um cenário com warm-up não medido — de propósito: o warm-up de uma rede
    aberta não é chute, é o tempo que a malha leva para sair do transiente de
    enchimento, e um número inventado contamina toda métrica depois dele.
    """

    chave: str                       # "small.maquete" | "aberta.maquete" ...
    net_file: str
    sumocfg: str
    add_file: str | None
    view_file: str | None
    restricoes: RestricoesFase
    # --- demanda ---
    modelo_demanda: str              # "persistente" (frota fixa) | "arquivo" (.rou.xml por seed)
    rou_pattern: str | None = None   # só modelo_demanda="arquivo"; {seed} no nome
    n_vehicles: int = 0              # só modelo_demanda="persistente"
    # --- regime (medidos; ver docs/CALIBRACAO_ABERTA.md) ---
    warmup_s: float | None = None    # None = ainda não medido -> a Arena recusa
    warmup_plano: str = "timer"      # controlador do aquecimento, IGUAL nos três braços
    reroute_period: int = 0
    depart_lane: str = "first"
    od_weight: str = "uniform"
    od_weight_pow: float = 1.0
    # --- janelas padrão (o chamador pode sobrepor) ---
    janela_eval_s: float = 3600.0
    janela_rodada_s: float = 120.0
    # --- extras de env (o pacote `sim` lê tudo no import) ---
    env_extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.modelo_demanda not in ("persistente", "arquivo"):
            raise ValueError("modelo_demanda=%r (use 'persistente' ou 'arquivo')" % self.modelo_demanda)
        if self.modelo_demanda == "arquivo" and not self.rou_pattern:
            raise ValueError("modelo_demanda='arquivo' exige rou_pattern")
        if self.modelo_demanda == "persistente" and self.n_vehicles <= 0:
            raise ValueError("modelo_demanda='persistente' exige n_vehicles > 0")

    # ---------------------------------------------------------------- disponibilidade
    def disponivel(self) -> bool:
        """A rede deste cenário já existe em disco? (`aberta.*` só depois da Onda 1.)"""
        return Path(self.net_file).exists() and Path(self.sumocfg).exists()

    def rou_file(self, seed: int) -> Path:
        if self.modelo_demanda != "arquivo":
            raise ValueError("cenário %s não usa arquivo de rotas" % self.chave)
        assert self.rou_pattern is not None
        return Path(self.rou_pattern.format(seed=seed))

    # ---------------------------------------------------------------- env
    def env(self) -> dict[str, str]:
        """As env vars que reproduzem este cenário no pacote `sim`."""
        e = {"ST_SCENARIO": self.chave.split(".", 1)[-1]}
        e.update(self.restricoes.env())
        if self.modelo_demanda == "persistente":
            e["ST_N_VEHICLES"] = str(self.n_vehicles)
        e.update(self.env_extra)
        return e

    def aplicar(self, *, forcar: bool = False) -> None:
        """Escreve as env vars deste cenário no processo.

        DEVE rodar antes do primeiro `import sim.environment...`. Se `sim.environment
        .constants` já estiver em `sys.modules` com configuração diferente, levanta
        `CenarioJaImportado` — porque a configuração dele já foi congelada e mudar a
        env agora não muda nada, só mente.
        """
        alvo = self.env()
        ja = sys.modules.get("sim.environment.constants")
        if ja is not None and not forcar:
            divergentes = {k: (os.environ.get(k), v) for k, v in alvo.items()
                           if os.environ.get(k) != v}
            if divergentes:
                raise CenarioJaImportado(
                    "sim.environment.constants já importado com outra configuração; "
                    "os escalares dele estão congelados desde o import. Divergências "
                    "(env_atual -> desejado): %r. Aplique o cenário no topo do "
                    "processo, antes de qualquer import de `sim`." % divergentes
                )
        os.environ.update(alvo)


# ---------------------------------------------------------------------- registro
# As restrições PADRÃO do cenário aberto: 5/7/3.
#
# 10/10/3 (o histórico) dá verde mínimo alcançável de 17 s. Dois motivos para abrir:
#   (a) é "o experimento em aberto mais barato do projeto" segundo o README do
#       maquete — nunca testado na small, e foi o que virou o resultado na large;
#   (b) o TATO DO JOGO: com grade de 10 s o visitante espera até 10 s para o botão
#       fazer efeito, e conclui que quebrou.
# A/B contra 10/10/3 é escopo do agente A6; se 10/10/3 vencer, ESTE default muda e
# o jogo herda a grade mais grossa (a regra "mesmas restrições para os três" manda).
RESTRICOES_ABERTA = RestricoesFase(decision_interval=5, min_green=7, yellow=3, max_red=0.0)

# As restrições da rede FECHADA de hoje — congeladas, é o regime em que
# `results/maq30_ats_full_best.pt` foi treinada. Não mexer: o cenário `small.maquete`
# existe aqui só para o agente A3 (jogo) ter onde rodar antes de a rede aberta existir.
RESTRICOES_FECHADA = RestricoesFase(decision_interval=10, min_green=10, yellow=3, max_red=0.0)

_SUMO_MAQ = _MAQUETE / "sumo" / "small_network"
_SUMO_AB = _RAIZ / "sumo" / "aberta"


def _small_maquete() -> Cenario:
    """A rede de hoje: fechada, 1/6 comprimida, 10 semáforos, frota persistente de 30.

    Aqui só para o jogo e a Arena terem alvo de teste antes da Onda 1 entregar a rede
    aberta. NÃO é o cenário da feira e NÃO deve receber política nova.
    """
    return Cenario(
        chave="small.maquete",
        net_file=str(_SUMO_MAQ / "network" / "net_loop_maquete.net.xml"),
        sumocfg=str(_SUMO_MAQ / "config" / "loop_rl_maquete.sumocfg"),
        add_file=str(_SUMO_MAQ / "demand" / "maquete.add.xml"),
        view_file=str(_SUMO_MAQ / "config" / "maquete.view.xml"),
        restricoes=RESTRICOES_FECHADA,
        modelo_demanda="persistente",
        n_vehicles=30,
        warmup_s=0.0,          # frota persistente nasce cheia: não há transiente
        janela_eval_s=3600.0,
        janela_rodada_s=120.0,
    )


def _aberta_maquete() -> Cenario:
    """O cenário da feira: geometria da maquete em SIMILITUDE + bordas abertas.

    Os arquivos ainda não existem — são o entregável do agente A1 (Onda 1).
    `warmup_s=None` e `n_vehicles=0` de propósito: os dois números saem de MEDIÇÃO
    (docs/CALIBRACAO_ABERTA.md), e até lá a Arena recusa rodar este cenário.
    """
    return Cenario(
        chave="aberta.maquete",
        net_file=str(_SUMO_AB / "network" / "maquete_aberta.net.xml"),
        sumocfg=str(_SUMO_AB / "config" / "maquete_aberta.sumocfg"),
        add_file=str(_SUMO_AB / "demanda" / "maquete_aberta.add.xml"),
        view_file=str(_SUMO_AB / "config" / "maquete_aberta.view.xml"),
        restricoes=RESTRICOES_ABERTA,
        modelo_demanda="arquivo",
        rou_pattern=str(_SUMO_AB / "demanda" / "demanda_s{seed}.rou.xml"),
        warmup_s=None,                 # <- A1 preenche com o valor MEDIDO
        warmup_plano="timer",
        reroute_period=60,             # sem isto a malha trava e não volta (achado da large)
        depart_lane="best",
        od_weight="capacity",
        od_weight_pow=1.0,
        janela_eval_s=3600.0,
        janela_rodada_s=120.0,
    )


_REGISTRO = {
    "small.maquete": _small_maquete,
    "aberta.maquete": _aberta_maquete,
}


def cenario(chave: str) -> Cenario:
    """Resolve um cenário pela chave. Typo falha alto, em vez de cair num default."""
    if chave not in _REGISTRO:
        raise ValueError("cenário %r desconhecido (use %s)" % (chave, " | ".join(sorted(_REGISTRO))))
    return _REGISTRO[chave]()


def chaves() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRO))
