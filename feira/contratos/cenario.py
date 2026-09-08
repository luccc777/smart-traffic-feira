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

    @property
    def assinatura(self) -> str:
        """Assinatura compacta do espaço de ação, para carimbar a `Chave` (C5).

        Duas corridas com grades diferentes descrevem conjuntos de políticas
        diferentes (verde mínimo alcançável de 7 s contra 17 s, entre os dois
        regimes deste projeto) e não podem ser comparadas como se fossem a
        mesma condição.
        """
        return "di%d/vm%d/am%d/mr%g" % (self.decision_interval, self.min_green,
                                        self.yellow, self.max_red)

    def env(self) -> dict[str, str]:
        """As env vars que o pacote `sim` lê no import.

        `yellow` NÃO aparece aqui, e a ausência é o ponto: `sim.environment
        .constants.YELLOW_DUR` é literal 3, sem env var. Configurar `yellow != 3`
        aqui seria mentira silenciosa — por isso `Cenario.aplicar()` compara o
        valor congelado e levanta em vez de deixar passar.
        """
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

    def divergencias_congeladas(self) -> dict[str, tuple]:
        """O que `sim.environment.constants` REALMENTE tem vs o que este cenário quer.

        Devolve `{atributo: (congelado, desejado)}`; vazio quando bate, e vazio
        também quando `sim` ainda não foi importado (aí não há nada congelado).

        Compara o ESTADO DO MÓDULO, não a env var — e a diferença não é
        acadêmica: a versão anterior comparava `os.environ`, então bastava
        alguém importar `sim` com outra rede e depois devolver a env var ao lugar
        para a guarda passar. Aconteceu: a Arena chegou a medir 12 semáforos onde
        havia 10, sem erro (`docs/AUDITORIA_COMPARACAO.md` §12e).

        `YELLOW_DUR` entra porque ele é literal no `constants.py`, sem env var:
        é o único jeito de um `RestricoesFase.yellow != 3` falhar alto em vez de
        ser silenciosamente ignorado.
        """
        mod = sys.modules.get("sim.environment.constants")
        if mod is None:
            return {}
        alvo = {
            "NET_FILE": str(Path(self.net_file)),
            "SUMOCFG": str(Path(self.sumocfg)),
            "MIN_GREEN": self.restricoes.min_green,
            "DECISION_INTERVAL": self.restricoes.decision_interval,
            "MAX_RED": float(self.restricoes.max_red),
            "YELLOW_DUR": self.restricoes.yellow,
        }
        fora: dict[str, tuple] = {}
        for attr, quer in alvo.items():
            tem = getattr(mod, attr, None)
            if attr in ("NET_FILE", "SUMOCFG"):
                tem = str(Path(tem)) if tem else tem
            if tem != quer:
                fora[attr] = (tem, quer)
        return fora

    def aplicar(self, *, forcar: bool = False) -> None:
        """Escreve as env vars deste cenário no processo.

        DEVE rodar antes do primeiro `import sim.environment...`. Se `sim` já foi
        importado com outra configuração, levanta `CenarioJaImportado` — os
        escalares dele estão congelados desde o import, e mudar a env agora não
        muda nada, só mente.

        Quem PRECISA trocar de cenário no mesmo processo (a Arena, ao alternar
        entre a rede fechada e a aberta) não usa `forcar`: descarta os módulos
        derivados de `constants` de `sys.modules` e reimporta — ver
        `feira/arena/sumo.py::_amarra_sim`.
        """
        os.environ.update(self.env())
        if forcar:
            return
        fora = self.divergencias_congeladas()
        if fora:
            linhas = "\n".join("    %-18s congelado=%r  desejado=%r" % (k, a, b)
                               for k, (a, b) in sorted(fora.items()))
            raise CenarioJaImportado(
                "sim.environment.constants já importado com outra configuração — os "
                "escalares dele estão congelados desde o import e a env var acima já "
                "não os alcança:\n%s\nAplique o cenário no topo do processo, antes de "
                "qualquer import de `sim`, ou reimporte o pacote." % linhas
            )


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

    Rede e demanda gerados por `sumo/aberta/build_rede_aberta.py` e
    `feira.demanda.GeradorDemandaAberta`. 12 semáforos, 12 controláveis, 9 fontes
    e 9 sorvedouros.

    `warmup_s=300.0` é MEDIDO (docs/CALIBRACAO_ABERTA.md §4), não escolhido:
      - o transiente de enchimento fecha em ~240 s (a população ativa chega a 90%
        do regime no bloco 120-240 s e a velocidade da rede para de cair);
      - medir a partir de 120 s já não enviesa a média em mais de 5%, mas 120 s
        ainda pega a malha meio vazia — o que importaria para uma RODADA de 120 s
        do modo jogo, que começa exatamente no fim do warm-up;
      - o `device.rerouting` só tem estimativa de tempo de viagem depois de
        `adaptation-steps 18 x adaptation-interval 10 s` = 180 s;
      - 300 s = 5 ciclos inteiros do plano fixo de 60 s, o menor múltiplo do ciclo
        acima dos três critérios.
    É MUITO menor que os 1200 s da Vila Olímpia porque esta malha é ~60x menor:
    a viagem média é muito mais curta e a população de regime é 158 contra 850
    carros.

    `n_vehicles=0` continua 0 e é correto: a frota aqui não é fixa. A população
    ativa (~158 carros) é EMERGENTE da taxa de injeção calibrada
    (`feira.demanda.aberta.VEH_POR_HORA` = 3500 veh/h), e a taxa foi escolhida
    por ser a maior estável nas 6 seeds por 7200 s — o dobro de `janela_eval_s`.
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
        warmup_s=300.0,                # MEDIDO (ver docstring e CALIBRACAO_ABERTA.md §4)
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
