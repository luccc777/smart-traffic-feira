"""`ArenaSumo` — a implementação do C4: UM laço, três braços.

Hoje, no maquete, o braço da rede neural (`dashboard/backend/nn_runner.py`) e o
braço do timer (`dashboard/backend/timer_runner.py`) são dois laços escritos à
mão, em dois processos, cada um com o seu controle de cadência. Aqui existe um
laço só, e a diferença entre os braços é o objeto `Controlador` que ele consulta.

O MOTOR É O DO MAQUETE, DE PROPÓSITO
------------------------------------
Esta Arena NÃO reimplementa o ambiente de RL: ela dirige o `TrafficEnv` do
`smart-traffic-maquete` (máquina de fases, estado de 26 dims, controlador de
demanda). Reescrever qualquer uma dessas peças criaria uma segunda verdade — foi
assim que este projeto acabou com dois baselines diferentes no mesmo repositório.
O que a Arena acrescenta, e o `TrafficEnv` não tem, é o que a comparação exige:

    aquecimento com plano comum · janela de medição · contabilidade de
    conservação · cadência única · observador por sim-step · `Chave`

Consequência direta: com `decision_interval=10` e o `ControladorRL`, esta Arena
reproduz `sim.evaluation.policy_sim.evaluate_policy`; com `decision_interval=1` e
o `ControladorTimer(27)`, reproduz `sim.baselines.fixed_timer_sim.FixedTimerSim`.
Os dois são medidos em `scripts/reproduz_evaluate.py` (DoD (a) do agente A2).

FRONTEIRA COM O MAQUETE
-----------------------
Leitura da máquina de fases (`_tls`, `_phases`, `_cur_green`, `_in_yellow`,
`_green_since`) é a MESMA superfície que o `dashboard/backend/snapshot.py` já
consome — é a fronteira estabelecida entre o lado do treino e o lado da
visualização. Escrita, nenhuma: quem aplica ação é o `TrafficEnv`.

A AMARRAÇÃO COM O PACOTE `sim`
------------------------------
`sim.environment.constants` lê env var no import e vira singleton de módulo;
`net_topology`, `demand_controller` e `traffic_env` derivam tudo a partir dele,
também no import. Duas consequências que a Arena precisa tratar, e trata em
`_amarra_sim`:

* a rede ABERTA mora neste repo, e o `scenarios.py` do maquete só conhece
  `real`/`maquete`/`maquete_sim` — sem reapontar `constants.NET_FILE`/`SUMOCFG`
  a Arena rodaria a rede fechada achando que roda a aberta;
* a guarda do C1 (`Cenario.aplicar`) compara ENV VAR, então ela passa quando
  alguém importou `sim` com outra rede e depois devolveu a env var ao lugar. A
  Arena confere o ESTADO CONGELADO e reimporta o pacote quando ele diverge.

A CADÊNCIA É DO LAÇO
--------------------
`Ritmo.recupera_atraso=True` (o default) ACUMULA o atraso em vez de reajustar o
relógio. O código do dashboard faz `deadline = time.perf_counter()` quando fica
para trás — o atraso some da vista e nunca volta, e é assim que os dois braços
derivam. Aqui o atraso é medido e devolvido em `ultimo_diagnostico`.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np

from ..contratos import (
    ArenaNaoConfigurada,
    Cenario,
    Chave,
    Frame,
    Janela,
    Observacao,
    Observador,
    RestricoesFase,
    Resultado,
    Ritmo,
    Topologia,
    TravamentoDetectado,
    janela_padrao,
)
from ..metricas import Contabilidade

__all__ = ["ArenaSumo", "sha_demanda"]


# ------------------------------------------------------------------ helpers
def sha_demanda(cenario: Cenario, seed: int) -> str:
    """Hash da demanda desta condição — o campo que fecha a `Chave`.

    Rede aberta: sha256 do `.rou.xml` da seed (o manifesto do agente A1).
    Frota persistente: não há arquivo — a demanda é gerada in-process pelo
    `PersistentDemandController`, e o que a determina é (cenário, seed, frota,
    modo determinístico). O hash é dessa tupla, com o prefixo `persistente:`
    para nunca ser confundido com o sha de um arquivo.
    """
    import hashlib

    if cenario.modelo_demanda == "arquivo":
        from ..contratos import sha256_arquivo

        return sha256_arquivo(cenario.rou_file(seed))
    crua = "persistente|%s|%d|%d|deterministico" % (cenario.chave, seed, cenario.n_vehicles)
    return "persistente:" + hashlib.sha256(crua.encode("utf-8")).hexdigest()[:52]



# ------------------------------------------------------- amarração com `sim`
# Os submódulos abaixo derivam TUDO no import (rede, fases, frota, normalizadores)
# a partir de `sim.environment.constants`, que por sua vez lê env var no import.
# Se o cenário mudar depois disso, eles ficam com a configuração antiga — em
# silêncio. `_amarra_sim` os descarta e reimporta quando isso acontece.
_DERIVADOS_DE_CONSTANTS = (
    "sim.evaluation.policy_sim",
    "sim.baselines.fixed_timer_sim",
    "sim.environment",
    "sim.environment.traffic_env",
    "sim.environment.demand_controller",
    "sim.environment.routing",
    "sim.environment.rewards",
    "sim.environment.net_topology",
)


def _mesmo_caminho(a, b) -> bool:
    if not a or not b:
        return a == b
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def _amarra_sim(cenario: Cenario, seed: int | None = None):
    """Aponta o pacote `sim` para ESTE cenário e devolve o módulo `constants`.

    `Cenario.aplicar()` (C1) protege contra o caso "importei `sim` antes de
    aplicar o cenário" comparando ENV VAR. Isso não cobre dois casos que
    acontecem de verdade:

    1. **A rede aberta não existe no `scenarios.py` do maquete.** Ele só conhece
       `real`/`maquete`/`maquete_sim`; `sumo/aberta/` mora neste repo. Sem
       reapontar `constants.NET_FILE`/`SUMOCFG`, a Arena rodaria a rede FECHADA
       achando que roda a aberta.
    2. **Alguém já importou `sim` com outro cenário e depois restaurou a env
       var.** A guarda do C1 compara `os.environ` com o alvo, então ela passa —
       e os escalares congelados continuam errados. Aconteceu de verdade na
       suíte: um teste da rede aberta importa `net_topology` apontado para
       outra rede, e a corrida seguinte media 12 semáforos onde há 10.

    Por isso a verificação aqui é sobre o ESTADO CONGELADO (o `NET_FILE` que o
    `net_topology` de fato usou), não sobre a env var — e, se ele estiver errado,
    o pacote inteiro é descartado de `sys.modules` e reimportado. É caro (relê o
    `.net.xml` com sumolib) e por isso só acontece quando há divergência de
    verdade: numa sessão de um cenário só, nunca dispara.
    """
    C = _aponta_constants(cenario, seed)
    nt = _importa_net_topology()
    if _sim_bate_com(C, nt, cenario):
        return C

    # os escalares (grade de decisão, verde mínimo, amarelo) NÃO são atributos que
    # dê para reapontar: eles já foram lidos por quem importou. Só reimportando.
    _purga_sim()
    C = _aponta_constants(cenario, seed)
    nt = _importa_net_topology()
    if not _sim_bate_com(C, nt, cenario):
        raise ArenaNaoConfigurada(
            "o pacote `sim` continua desalinhado do cenário %s depois de ser "
            "reimportado: net=%r (pedido %r), di=%s/%s min_green=%s/%s yellow=%s/%s. "
            "Alguma coisa está segurando os módulos antigos."
            % (cenario.chave, nt.NET_FILE, cenario.net_file,
               C.DECISION_INTERVAL, cenario.restricoes.decision_interval,
               C.MIN_GREEN, cenario.restricoes.min_green,
               C.YELLOW_DUR, cenario.restricoes.yellow))
    return C


def _sim_bate_com(C, nt, cenario: Cenario) -> bool:
    """O pacote `sim` congelado corresponde a ESTE cenário?

    Rede e restrições de fase juntas: um `net_topology` certo com um
    `DECISION_INTERVAL` de outro cenário mediria a rede certa no regime errado.
    """
    r = cenario.restricoes
    n_alvo = cenario.n_vehicles if cenario.modelo_demanda == "persistente" else 0
    return (_mesmo_caminho(getattr(nt, "NET_FILE", None), cenario.net_file)
            and int(C.DECISION_INTERVAL) == int(r.decision_interval)
            and int(C.MIN_GREEN) == int(r.min_green)
            and int(C.YELLOW_DUR) == int(r.yellow)
            and float(C.MAX_RED) == float(r.max_red)
            and int(C.N_VEHICLES) == int(n_alvo))


def _aponta_constants(cenario: Cenario, seed: int | None = None):
    """Importa `sim.environment.constants` e o aponta para os arquivos do cenário.

    A rede aberta mora NESTE repo e o `scenarios.py` do maquete não a conhece —
    sem reapontar, a Arena rodaria a rede fechada achando que roda a aberta.
    A frota persistente do `sim` também é zerada no modelo de demanda em ARQUIVO:
    senão ela injeta 30 carros por cima da demanda do `.rou.xml`.

    `seed` RESOLVE O `SUMOCFG`, e a costura importa: `roda()` apontava o cfg da
    seed e logo depois chamava `topologia()`, que passa por aqui de novo e
    devolvia o `SUMOCFG` ao canônico — que não tem `<route-files>`. Medido: a
    corrida inseria 0 veículos e o diagnóstico reportava o caminho da seed.
    Agora todo caminho que passa por aqui resolve o MESMO alvo; sem `seed`
    (o caso de `topologia()`, que só precisa do `.net.xml`) o `SUMOCFG` de
    demanda-em-arquivo é deixado como está, em vez de ser reescrito para um
    valor que esta função não tem como saber.
    """
    # `forcar=True`: a guarda do C1 compara ENV VAR, e aqui a verificação é sobre
    # o ESTADO CONGELADO (`_sim_bate_com`), que é estritamente mais forte — e é a
    # única que permite trocar de cenário no mesmo processo, reimportando.
    cenario.aplicar(forcar=True)
    from sim.environment import constants as C

    alvo = {"NET_FILE": cenario.net_file,
            "ADD_FILE": cenario.add_file, "VIEW_FILE": cenario.view_file}
    if cenario.modelo_demanda != "arquivo" or seed is not None:
        alvo["SUMOCFG"] = _sumocfg_da_seed(cenario, seed)
    for campo, valor in alvo.items():
        if valor is not None and not _mesmo_caminho(getattr(C, campo, None), valor):
            setattr(C, campo, str(valor))
    n_alvo = cenario.n_vehicles if cenario.modelo_demanda == "persistente" else 0
    if int(getattr(C, "N_VEHICLES", -1)) != int(n_alvo):
        C.N_VEHICLES = int(n_alvo)
    return C


def _importa_net_topology():
    """Reimporta `net_topology` se ele estiver desalinhado de `constants.NET_FILE`.

    Ele deriva TUDO no import (fases, aproximações, capacidade, adjacência), então
    trocar a rede exige descartá-lo — junto de quem o consumiu no import."""
    import sys

    from sim.environment import constants as C

    nt = sys.modules.get("sim.environment.net_topology")
    if nt is not None and _mesmo_caminho(getattr(nt, "NET_FILE", None), C.NET_FILE):
        return nt
    for mod in _DERIVADOS_DE_CONSTANTS:
        sys.modules.pop(mod, None)
    from sim.environment import net_topology as nt2

    return nt2


def _purga_sim() -> None:
    """Descarta o pacote `sim` inteiro de `sys.modules`.

    Último recurso quando `constants` foi congelado com outra configuração e
    reapontar os atributos não bastou (alguém importou um derivado no meio)."""
    import sys

    for nome in [m for m in list(sys.modules) if m == "sim" or m.startswith("sim.")]:
        sys.modules.pop(nome, None)


def _sumocfg_da_seed(cenario: Cenario, seed: int | None) -> str:
    """O `.sumocfg` que esta corrida deve subir.

    A frota persistente não tem arquivo de rotas: um `.sumocfg` serve a todas as
    seeds. A rede aberta tem um `.rou.xml` POR SEED, e quem escolhe o arquivo de
    rotas é o `.sumocfg` — mas quem monta a linha de comando do SUMO é o
    `TrafficEnv` do maquete, que não aceita `--route-files`. A convenção, então,
    é um `.sumocfg` por seed ao lado do canônico:

        maquete_aberta.sumocfg  ->  maquete_aberta_s42.sumocfg

    LEVANTA se o arquivo da seed não existir. A versão anterior caía no canônico,
    e o canônico não tem `<route-files>`: a corrida rodava a malha VAZIA e o
    `ultimo_diagnostico` ainda registrava o caminho da seed. É o mesmo silêncio
    que o agente A1 fechou do lado do gerador (`ConfigDaSeedAusente`) — cair no
    canônico é sempre erro, nunca degradação aceitável.
    """
    if cenario.modelo_demanda != "arquivo" or seed is None:
        return cenario.sumocfg
    base = Path(cenario.sumocfg)
    # IDEMPOTENTE: um `Cenario` cujo `sumocfg` JÁ é o da seed passa direto. Sem
    # isto sai `..._s100_s100.sumocfg` quando o chamador resolveu a seed antes de
    # entregar o cenário — que é o que o motor do jogo faz.
    if base.stem.endswith("_s%d" % int(seed)):
        por_seed = base
    else:
        por_seed = base.with_name("%s_s%d%s" % (base.stem, int(seed), base.suffix))
    if not por_seed.exists():
        raise ArenaNaoConfigurada(
            "cenário %s (demanda em arquivo) não tem `.sumocfg` para a seed %d:\n"
            "    %s\n"
            "Sem ele o SUMO sobe o canônico, que não tem <route-files>, e a malha "
            "roda VAZIA. Gere com `python -m feira.demanda --seed %d` (agente A1)."
            % (cenario.chave, int(seed), por_seed, int(seed)))
    return str(por_seed)


class _Contador:
    """Traduz o que o SUMO/o controlador de demanda fazem em eventos da C5.

    Existe uma subclasse por MODELO DE DEMANDA porque os dois contam coisas
    diferentes (ver o cabeçalho de `feira/metricas.py`). Ele roda desde o boot,
    inclusive durante o aquecimento; só passa a registrar quando recebe uma
    `Contabilidade` (isto é, dentro da janela)."""

    prefixo: str = ""

    def observa(self, t, completed, contab):  # pragma: no cover - interface
        raise NotImplementedError

    def vivos(self) -> set[str]:  # pragma: no cover - interface
        raise NotImplementedError

    def backlog(self) -> int:
        import traci

        try:
            pend = traci.simulation.getPendingVehicles()
        except Exception:
            return 0
        if self.prefixo:
            pend = [v for v in pend if v.startswith(self.prefixo)]
        return len(pend)

    def abertos(self) -> dict[str, float]:  # pragma: no cover - interface
        raise NotImplementedError


class _ContadorFechado(_Contador):
    """Frota persistente (`small.maquete`): a viagem fecha, o veículo continua.

    Uma chegada aqui NÃO tira o carro da rede — ela fecha uma viagem e abre
    outra no mesmo sim-step. Logo, entrega e ativação acontecem juntas, e o
    número de viagens ativas (= carros vivos) não muda. É o que faz a identidade
    de conservação continuar valendo sem tratar a frota fechada como caso
    especial.

    Um despawn de verdade é outra coisa: o `PersistentDemandController` o
    registra como "viagem concluída" (backstop) e re-injeta o carro. Contar isso
    como entrega infla a vazão com um carro que evaporou, então aqui ele vira
    `perdidos` — a diferença é o delta de `demand.backstop_count`.
    """

    def __init__(self, env, prefixo: str) -> None:
        self.env = env
        self.demand = env.demand
        self.prefixo = prefixo
        self._vivos: set[str] = set()
        self._depart: dict[str, float] = {}
        self._backstop = 0
        self._teleportando: set[str] = set()
        self.n_backstop_janela = 0
        self._sincroniza_depart()
        self._vivos = self.vivos()
        self._backstop = int(self.demand.backstop_count)

    # -- estado ------------------------------------------------------------
    def vivos(self) -> set[str]:
        import traci

        return {v for v in traci.vehicle.getIDList() if v.startswith(self.prefixo)}

    def _sincroniza_depart(self) -> None:
        """Reconstrói o instante em que a viagem em curso de cada carro começou.

        Só com API pública: a viagem em curso de um carro começou quando a
        anterior fechou (keep-alive no mesmo sim-step) ou, se não fechou
        nenhuma, no `reset` (t=0)."""
        for rec in self.demand.completed_trips:
            self._depart[rec.veh_id] = float(rec.arrive_time)

    def abertos(self) -> dict[str, float]:
        return {v: self._depart.get(v, 0.0) for v in self.vivos()}

    # -- passo -------------------------------------------------------------
    def observa(self, t: float, completed, contab: Contabilidade | None) -> None:
        import traci

        vivos = self.vivos()
        tele_ini = set(traci.simulation.getStartingTeleportIDList())
        tele_fim = set(traci.simulation.getEndingTeleportIDList())
        self._teleportando |= tele_ini
        self._teleportando -= tele_fim

        bs = int(self.demand.backstop_count)
        n_bs = bs - self._backstop
        self._backstop = bs
        completed = list(completed or ())
        # `demand.step` empilha primeiro as CHEGADAS e depois os backstops.
        corte = len(completed) - n_bs if n_bs else len(completed)
        chegadas, perdas = completed[:corte], completed[corte:]

        for rec in chegadas:
            if contab is not None:
                contab.chegou(rec.veh_id, t, t_abre=rec.depart_time)
                contab.ativou(rec.veh_id, t, fisica=False, t_abre=t)
            self._depart[rec.veh_id] = float(t)
        for rec in perdas:
            if contab is not None:
                contab.perdeu(rec.veh_id, t)
            self._depart[rec.veh_id] = float(t)
        if contab is not None:
            self.n_backstop_janela += n_bs

        entrou = vivos - self._vivos - tele_fim
        for vid in entrou:
            if contab is not None:
                contab.ativou(vid, t, fisica=True, t_abre=self._depart.get(vid, t))
        # despawn que o backstop ainda não viu (não deveria acontecer)
        vistos = {r.veh_id for r in perdas}
        saiu = self._vivos - vivos - tele_ini - vistos
        for vid in saiu:
            if contab is not None:
                contab.perdeu(vid, t)
        if contab is not None and tele_ini:
            contab.teleportou(len(tele_ini))
        self._vivos = vivos


class _ContadorAberto(_Contador):
    """Rede aberta (`.rou.xml` por seed): um veículo nasce, viaja e some.

    Aqui viagem e veículo são a mesma coisa, e as três quantidades saem dos
    contadores do próprio SUMO — `getDepartedIDList`, `getArrivedIDList` e a
    contagem de vivos. `perdidos` é o resíduo: quem sumiu da rede sem constar
    como chegada nem como teleporte."""

    def __init__(self, env, prefixo: str = "") -> None:
        self.env = env
        self.prefixo = prefixo
        self._vivos: set[str] = set()
        self._depart: dict[str, float] = {}
        self._vivos = self.vivos()
        import traci

        agora = float(traci.simulation.getTime())
        for vid in self._vivos:
            self._depart.setdefault(vid, agora)

    def vivos(self) -> set[str]:
        import traci

        return set(traci.vehicle.getIDList())

    def abertos(self) -> dict[str, float]:
        return {v: self._depart.get(v, 0.0) for v in self.vivos()}

    def observa(self, t: float, completed, contab: Contabilidade | None) -> None:
        import traci

        partiram = list(traci.simulation.getDepartedIDList())
        chegaram = list(traci.simulation.getArrivedIDList())
        tele_ini = set(traci.simulation.getStartingTeleportIDList())
        vivos = self.vivos()

        for vid in partiram:
            self._depart[vid] = float(t)
            if contab is not None:
                contab.ativou(vid, t, fisica=True, t_abre=t)
        for vid in chegaram:
            if contab is not None:
                contab.chegou(vid, t, t_abre=self._depart.get(vid))
            self._depart.pop(vid, None)
        saiu = self._vivos - vivos - set(chegaram) - tele_ini
        for vid in saiu:
            if contab is not None:
                contab.perdeu(vid, t)
            self._depart.pop(vid, None)
        if contab is not None and tele_ini:
            contab.teleportou(len(tele_ini))
        self._vivos = vivos


# -------------------------------------------------------------------- arena
class ArenaSumo:
    """Roda um braço numa condição e devolve o que ele mediu (C4).

    `seca_max_s`: quantos segundos SIMULADOS sem nenhuma chegada bastam para
    declarar travamento. É um critério model-free — não usa frota fixa nem
    demanda esperada —, e é o que a rede aberta permite. `abortar_travamento`
    controla se o laço para (levantando `TravamentoDetectado`) ou termina a
    janela marcando `Resultado.travou=True`; o default é TERMINAR, porque o
    número da corrida travada é o dado que a auditoria precisa reportar seed a
    seed.
    """

    def __init__(self, *, seca_max_s: float = 600.0, abortar_travamento: bool = False,
                 usar_subscriptions: bool = True, heat_com_internas: bool = True,
                 ao_esperar=None, fatia_espera_s: float = 0.02) -> None:
        self.seca_max_s = float(seca_max_s)
        self.abortar_travamento = bool(abortar_travamento)
        self.usar_subscriptions = bool(usar_subscriptions)
        self.heat_com_internas = bool(heat_com_internas)
        self.ultimo_diagnostico: dict = {}
        # A contabilidade crua da última corrida: séries por sim-step e instantes
        # de entrega. O `Resultado` (C5) é imutável e só carrega os agregados;
        # as séries ficam aqui porque a auditoria precisa delas (achados nº4/nº6)
        # e o contrato não deve crescer para acomodar diagnóstico.
        self.ultima_contabilidade: Contabilidade | None = None
        self.ultimo_leitor: "_LeitorDeFaixas | None" = None

        # Gancho de cadencia de entrada (pedido do agente A3, achado do A4). Em
        # tempo real o laco dorme ~1 s entre sim-steps; sem isto o `poll()` da
        # botoeira/teclado roda a 1 Hz e o botao parece quebrado. Publicos e
        # settables de proposito: o motor do jogo os liga sem tocar em contrato.
        self.ao_esperar = ao_esperar
        self.fatia_espera_s = float(fatia_espera_s)

    # ------------------------------------------------------------ topologia
    def topologia(self, cenario: Cenario) -> Topologia:
        """Deriva a topologia do `.net.xml` sem subir o SUMO.

        Sem `seed` de proposito: topologia sai do `.net.xml`, nao da demanda. Por
        isso `_aponta_constants` NAO reescreve o `SUMOCFG` quando a demanda vem de
        arquivo -- era esse reescrever que apagava a escolha da seed feita em
        `roda()`.
        """
        _amarra_sim(cenario)
        from sim.environment import net_topology as nt

        ids = tuple(nt.TLS_IDS)
        fases = [nt.TL_PHASES[t] for t in ids]
        return Topologia(
            tls_ids=ids,
            controlavel=tuple(bool(f.controllable) for f in fases),
            n_fases_verdes=tuple(len(f.green_phases) for f in fases),
            edge_index=np.asarray(nt.EDGE_INDEX, dtype=np.int64),
            approach_capacity=float(nt.APPROACH_CAPACITY),
        )

    # ----------------------------------------------------------------- roda
    def roda(self, cenario: Cenario, seed: int, controlador, janela: Janela | None = None,
             *, ritmo: Ritmo | None = None, observador: Observador | None = None,
             gui: bool = False) -> Resultado:
        if cenario.warmup_s is None:
            raise ArenaNaoConfigurada(
                "cenário %s sem warmup_s medido — a Arena recusa rodar. O número sai "
                "de docs/CALIBRACAO_ABERTA.md (agente A1), não de estimativa."
                % cenario.chave)
        if not cenario.disponivel():
            raise ArenaNaoConfigurada(
                "rede do cenário %s não existe em disco (%s)" % (cenario.chave, cenario.net_file))

        if cenario.modelo_demanda == "arquivo" and not cenario.rou_file(seed).exists():
            raise ArenaNaoConfigurada(
                "demanda da seed %d não existe (%s). O `.rou.xml` por seed é "
                "entregável do agente A1." % (seed, cenario.rou_file(seed)))

        janela = janela or janela_padrao(cenario)
        ritmo = ritmo or Ritmo()

        # A seed entra AQUI: e ela que resolve o `.sumocfg` com o <route-files>
        # certo, e `topologia()` mais abaixo passa por `_aponta_constants` de novo
        # -- antes desta correcao era esse segundo passe que devolvia o SUMOCFG ao
        # canonico e fazia a corrida rodar a malha vazia.
        C = _amarra_sim(cenario, seed)
        from sim.environment import net_topology as nt
        from sim.environment.traffic_env import TrafficEnv

        self._confere_constantes(C, cenario.restricoes)
        topo = self.topologia(cenario)
        lanes = _lanes_de_aproximacao(nt)
        # Chave.de carimba tambem a assinatura do espaco de acao (C5): duas
        # corridas com decision_interval/min_green diferentes deixam de ter
        # chaves iguais e nao se comparam mais em silencio.
        chave = Chave.de(cenario, int(seed), janela, sha_demanda(cenario, seed))

        env = TrafficEnv(gui=gui, seed=int(seed), deterministic_demand=True)
        try:
            return self._laco(env, C, cenario, topo, lanes, chave, controlador,
                              janela, ritmo, observador)
        finally:
            try:
                env.close()
            except Exception:
                pass

    # ------------------------------------------------------------- interno
    @staticmethod
    def _confere_constantes(C, r: RestricoesFase) -> None:
        """O pacote `sim` congela estes escalares no import. Se não bateram com o
        cenário, alguém importou `sim` antes de `Cenario.aplicar()` — e a corrida
        toda seria medida numa configuração que ninguém pediu."""
        divergentes = {
            k: (real, pedido)
            for k, real, pedido in (
                ("decision_interval", C.DECISION_INTERVAL, r.decision_interval),
                ("min_green", C.MIN_GREEN, r.min_green),
                ("yellow", C.YELLOW_DUR, r.yellow),
                ("max_red", float(C.MAX_RED), float(r.max_red)),
            )
            if real != pedido
        }
        if divergentes:
            raise ArenaNaoConfigurada(
                "sim.environment.constants está em outra configuração que a do "
                "cenário (real -> pedido): %r. Aplique o cenário ANTES do primeiro "
                "import de `sim` — os escalares foram congelados no import." % divergentes)

    def _laco(self, env, C, cenario, topo, lanes, chave, controlador, janela,
              ritmo, observador) -> Resultado:
        import traci

        passo = float(C.STEP_LENGTH)
        env.reset()
        t_boot = float(traci.simulation.getTime())

        contador = (_ContadorFechado(env, C.VEHICLE_PREFIX)
                    if cenario.modelo_demanda == "persistente"
                    else _ContadorAberto(env))
        leitor = _LeitorDeFaixas(lanes, usar_subscriptions=self.usar_subscriptions)
        leitor.le(acumula=False)   # prime: a 1ª Observacao já sai com fila por TL

        # ---- aquecimento: plano COMUM aos três braços -----------------------
        aquecedor = _plano_de_aquecimento(cenario)
        aquecedor.reset(topo, cenario.restricoes, t_boot)
        n_aquecimento = 0
        alvo = max(float(janela.t0), t_boot)
        while float(traci.simulation.getTime()) < alvo:
            n_aquecimento += self._bloco(env, C, topo, leitor, contador,
                                         aquecedor, None, None, None, None,
                                         "aquecimento", 0)

        # ---- janela de medição ---------------------------------------------
        t_ini = float(traci.simulation.getTime())
        contab = Contabilidade()
        contab.abre_janela(t_ini, ativos=len(contador.vivos()), abertos=contador.abertos())
        controlador.reset(topo, cenario.restricoes, t_ini)

        n_passos = int(round(janela.duracao / passo))
        feito = 0
        relogio = _Relogio(ritmo, passo, ao_esperar=self.ao_esperar,
                           fatia_s=self.fatia_espera_s)
        travou = False
        decisao = 0
        while feito < n_passos:
            decisao += 1
            feito += self._bloco(env, C, topo, leitor, contador, controlador,
                                 contab, observador, relogio, n_passos - feito,
                                 getattr(controlador, "nome", "braco"), decisao)
            agora = float(traci.simulation.getTime())
            if not travou and contab.seca_atual(agora) > self.seca_max_s:
                travou = True
                if self.abortar_travamento:
                    raise TravamentoDetectado(
                        "%s: %.0f s simulados sem nenhuma chegada (limite %.0f s)"
                        % (getattr(controlador, "nome", "braco"),
                           contab.seca_atual(agora), self.seca_max_s))

        t_fim = float(traci.simulation.getTime())
        contador.observa(t_fim, (), None)   # só sincroniza estado; nada a registrar
        contab.fecha_janela(t_fim, ativos=len(contador.vivos()), backlog=contador.backlog())
        res = contab.resultado(chave, getattr(controlador, "nome", "braco"), travou=travou)
        self.ultima_contabilidade = contab
        self.ultimo_leitor = leitor

        self.ultimo_diagnostico = {
            "cenario": cenario.chave,
            "seed": chave.seed,
            "net_file": cenario.net_file,
            "sumocfg": _sumocfg_da_seed(cenario, chave.seed),
            "sumocfg_por_seed": _mesmo_caminho(
                _sumocfg_da_seed(cenario, chave.seed), cenario.sumocfg) is False,
            "controlador": res.controlador,
            "t_boot": t_boot,
            "t_inicio_efetivo": t_ini,
            "t_fim_efetivo": t_fim,
            "passos_medidos": feito,
            "passos_aquecimento": n_aquecimento,
            "amostras_rede": contab.n_amostras,
            "decisoes": getattr(controlador, "n_decisoes", None),
            "maior_seca_s": contab.maior_seca_s,
            "teleportes": contab.teleportes,
            "ativacoes_fisicas": contab.ativacoes_fisicas,
            "reativacoes": contab.reativacoes,
            "backstop": getattr(contador, "n_backstop_janela", 0),
            "atraso_max_s": relogio.atraso_max,
            "atraso_final_s": relogio.atraso_final,
            "atrasos_acima_do_teto": relogio.estouros,
            "fila_media_com_internas": leitor.fila_media_total,
        }
        return res

    def _bloco(self, env, C, topo, leitor, contador, controlador, contab,
               observador, relogio, restantes, braco, decisao) -> int:
        """Um bloco de decisão: consulta o controlador UMA vez e avança
        `decision_interval` sim-steps. É o único lugar do repo que avança o
        relógio da simulação."""
        import traci

        agora = float(traci.simulation.getTime())
        obs = self._observacao(env, C, topo, leitor, agora)
        acoes = controlador.decide(obs)
        n = 0
        for sub, concluidas in env.step_substeps(acoes):
            t = float(traci.simulation.getTime())
            fila, espera = leitor.le(acumula=contab is not None)
            contador.observa(t, concluidas, contab)
            if contab is not None:
                contab.amostra_rede(fila, espera)
            if observador is not None:
                observador(self._frame(topo, braco, t, decisao, sub, leitor, contab))
            if relogio is not None:
                relogio.espera()
            n += 1
            if restantes is not None and n >= restantes:
                break
        return n

    # ----------------------------------------------------------- observação
    def _observacao(self, env, C, topo, leitor, agora: float) -> Observacao:
        estado = env.last_state
        if estado is None:
            estado = env._get_state()
        n = topo.n
        cur = np.asarray(env._cur_green, dtype=np.int64)
        fase = np.zeros(n, dtype=np.int64)
        for i in range(n):
            gp = env._phases[i].green_phases
            fase[i] = gp.index(int(cur[i])) if int(cur[i]) in gp else 0
        verde_desde = agora - np.asarray(env._green_since, dtype=np.float64)
        amarelo = np.asarray(env._in_yellow, dtype=bool)
        controlavel = np.asarray(topo.controlavel, dtype=bool)
        pode = controlavel & (~amarelo) & (verde_desde >= float(C.MIN_GREEN))
        return Observacao(
            t=agora,
            estado=np.asarray(estado, dtype=np.float32),
            fase_atual=fase,
            verde_desde=verde_desde,
            em_amarelo=amarelo,
            pode_trocar=pode,
            fila_por_tl=leitor.fila_por_tl(env),
        )

    def _frame(self, topo, braco, t, decisao, sub, leitor, contab) -> Frame:
        import traci

        veiculos = []
        for vid in traci.vehicle.getIDList():
            x, y = traci.vehicle.getPosition(vid)
            veiculos.append({"id": vid, "x": round(x, 2), "y": round(y, 2),
                             "angle": round(traci.vehicle.getAngle(vid), 1),
                             "speed": round(traci.vehicle.getSpeed(vid), 2)})
        tls = [{"id": tid, "state": traci.trafficlight.getRedYellowGreenState(tid)}
               for tid in topo.tls_ids]
        stats = {}
        if contab is not None:
            stats = {"entregues": contab.entregues, "ativos": len(traci.vehicle.getIDList()),
                     "tempo_medio_entregue": round(contab.tempo_medio_entregue, 1),
                     "fila_media": round(contab.fila_media, 2)}
        return Frame(braco=str(braco), t=t, decisao=int(decisao), substep=int(sub),
                     veiculos=veiculos, tls=tls,
                     heat=leitor.heat(incluir_internas=self.heat_com_internas),
                     stats=stats)


# ------------------------------------------------------------------ leitura
def _lanes_de_aproximacao(nt) -> list[str]:
    """As lanes de aproximação únicas da rede — a MESMA definição do
    `policy_sim._unique_approach_lanes` e do `FixedTimerSim._all_lanes`.

    Ter exatamente este conjunto é o que torna `fila_media`/`espera_media`
    comparáveis com os números publicados do maquete."""
    ordem = ("N", "S", "E", "W")
    vistas: set[str] = set()
    saida: list[str] = []
    for t in nt.TLS_IDS:
        for d in ordem:
            for lane_id in nt.APPROACH_LANES[t][d]:
                if lane_id not in vistas:
                    vistas.add(lane_id)
                    saida.append(lane_id)
    return saida


class _LeitorDeFaixas:
    """Fila e espera por sim-step, sobre o conjunto de lanes de aproximação.

    Usa subscriptions (1 round-trip por passo) em vez de 2×|lanes| chamadas: os
    valores são os mesmos que `getLastStepHaltingNumber`/`getWaitingTime`
    devolvem — verificado contra a implementação de referência em
    `scripts/reproduz_evaluate.py`.

    Também mede a fila com as faixas INTERNAS de junção incluídas. O
    `LaneStream` do dashboard as ignora (`id.startswith(':')`), então um carro
    parado DENTRO do cruzamento não conta no mapa de calor da projeção — é o
    achado nº5 da auditoria, e o número que o quantifica sai daqui."""

    def __init__(self, lanes: list[str], *, usar_subscriptions: bool = True) -> None:
        self.lanes = list(lanes)
        self._aproximacao = set(self.lanes)
        self.usar_subscriptions = usar_subscriptions
        self._sub = False
        self._todas: list[str] = []
        self._halting: dict[str, int] = {}
        self._soma_desenhavel = 0.0     # faixas normais (o que o heat da projeção conta)
        self._soma_internas = 0.0       # faixas ':' de junção (o que ele NÃO conta)
        self._n_total = 0
        # série por sim-step da fila DESENHÁVEL: é literalmente o que a projeção
        # soma do `heat` a cada frame, e a série sobre a qual o `tail()` dela
        # calcula a média das últimas 20 amostras (achado nº4).
        self.serie_desenhavel: list[float] = []
        self.serie_internas: list[float] = []

    def _assina(self) -> None:
        import traci
        import traci.constants as tc

        self._todas = list(traci.lane.getIDList())
        for lid in self._todas:
            traci.lane.subscribe(lid, (tc.LAST_STEP_VEHICLE_HALTING_NUMBER,
                                       tc.VAR_WAITING_TIME))
        self._sub = True

    def le(self, *, acumula: bool = True) -> tuple[float, float]:
        """Uma leitura por sim-step. `acumula=False` durante o AQUECIMENTO: as
        séries e as médias por tipo de faixa são da JANELA, não da corrida — se
        o aquecimento entrasse nelas, a fila reportada seria de um regime que a
        janela existe justamente para excluir."""
        import traci
        import traci.constants as tc

        fila = 0.0
        espera = 0.0
        internas = 0.0
        desenhaveis = 0.0
        self._halting = {}
        if self.usar_subscriptions:
            if not self._sub:
                self._assina()
            res = traci.lane.getAllSubscriptionResults()
            for lid in self._todas:
                d = res.get(lid) or {}
                h = int(d.get(tc.LAST_STEP_VEHICLE_HALTING_NUMBER, 0))
                if h:
                    self._halting[lid] = h
                if lid.startswith(":"):
                    internas += h
                else:
                    desenhaveis += h
                if lid in self._aproximacao:
                    fila += h
                    espera += d.get(tc.VAR_WAITING_TIME, 0.0)
        else:
            if not self._todas:
                self._todas = list(traci.lane.getIDList())
            for lid in self._todas:
                h = int(traci.lane.getLastStepHaltingNumber(lid))
                if h:
                    self._halting[lid] = h
                if lid.startswith(":"):
                    internas += h
                else:
                    desenhaveis += h
                if lid in self._aproximacao:
                    fila += h
                    espera += traci.lane.getWaitingTime(lid)
        if acumula:
            self._soma_internas += internas
            self._soma_desenhavel += desenhaveis
            self.serie_desenhavel.append(float(desenhaveis))
            self.serie_internas.append(float(internas))
            self._n_total += 1
        return float(fila), float(espera)

    @property
    def fila_media_total(self) -> dict[str, float]:
        """Fila média por sim-step separada em faixas DESENHÁVEIS e INTERNAS.

        O `LaneStream` do dashboard ignora as faixas `:` de junção, então um
        carro parado DENTRO do cruzamento não entra no mapa de calor nem na
        série de fila da projeção. A razão `internas / (internas+desenhaveis)`
        é o tamanho do achado nº5, medido."""
        n = self._n_total or 1
        des = self._soma_desenhavel / n
        ind = self._soma_internas / n
        total = des + ind
        return {"desenhaveis": des, "internas": ind, "total": total,
                "fracao_internas": (ind / total) if total else 0.0}

    def fila_por_tl(self, env) -> np.ndarray:
        """Parados por interseção, derivados da última leitura (sem novo TraCI)."""
        n = len(env._tls)
        out = np.zeros(n, dtype=np.float64)
        for i in range(n):
            for appr in env._appr_lanes[i]:
                for lid in appr:
                    out[i] += self._halting.get(lid, 0)
        return out

    def heat(self, *, incluir_internas: bool = True) -> dict[str, int]:
        """`{lane: parados}`, só as faixas com fila. Com `incluir_internas=False`
        reproduz o `LaneStream` do dashboard — o do achado nº5."""
        if incluir_internas:
            return dict(self._halting)
        return {k: v for k, v in self._halting.items() if not k.startswith(":")}


class _Relogio:
    """Cadência do laço — e a contabilidade honesta do atraso.

    O dashboard do maquete faz `deadline = time.perf_counter()` quando fica para
    trás: o atraso some da vista e nunca é recuperado, e é entre os dois braços
    que ele vira deriva de tempo simulado. Aqui, com `recupera_atraso=True`, o
    deadline NÃO é reajustado — o laço deixa de dormir até recuperar, e o atraso
    máximo visto vai no diagnóstico.

    `ao_esperar` é o gancho de CADÊNCIA DE ENTRADA. Em tempo real o laço dorme
    ~1 s entre sim-steps, e quem drena a `FonteEntrada` é o observador — ou seja,
    a 1 Hz. Medido pelo agente A4: latência botão→evento de até 1000 ms, contra
    um teto de 50 ms. O sono é fatiado em `fatia_s` e o gancho roda entre as
    fatias, levando o `poll()` a ~50 Hz sem mexer no relógio da simulação: o
    deadline continua sendo o mesmo, e o atraso continua sendo acumulado.

    O gancho PODE levantar — é assim que o botão ABORTAR interrompe a rodada — e
    a exceção sobe por `roda()`.
    """

    def __init__(self, ritmo: Ritmo, passo_sim: float, *,
                 ao_esperar=None, fatia_s: float = 0.02) -> None:
        self.ritmo = ritmo
        self.passo_sim = float(passo_sim)
        self.ao_esperar = ao_esperar
        self.fatia_s = max(1e-3, float(fatia_s))
        self.atraso_max = 0.0
        self.atraso_final = 0.0
        self.estouros = 0
        self._deadline = time.perf_counter()

    def _dorme(self, falta: float) -> None:
        """Dorme `falta` segundos, bombeando o gancho entre as fatias."""
        if self.ao_esperar is None:
            time.sleep(falta)
            return
        while True:
            resta = self._deadline - time.perf_counter()
            if resta <= 0:
                break
            time.sleep(min(self.fatia_s, resta))
            self.ao_esperar()

    def espera(self) -> None:
        if not self.ritmo.sim_por_parede:
            if self.ao_esperar is not None:
                self.ao_esperar()      # solto: ainda assim bombeia uma vez por passo
            return
        self._deadline += self.passo_sim / float(self.ritmo.sim_por_parede)
        atraso = time.perf_counter() - self._deadline
        if atraso < 0:
            self._dorme(-atraso)
            atraso = 0.0
        else:
            if atraso > self.ritmo.atraso_max_s:
                self.estouros += 1
            if not self.ritmo.recupera_atraso:
                self._deadline = time.perf_counter()   # o comportamento do dashboard
        self.atraso_max = max(self.atraso_max, atraso)
        self.atraso_final = atraso


def _plano_de_aquecimento(cenario: Cenario):
    """O controlador que roda o aquecimento — IGUAL nos três braços.

    É isto que torna a rodada pareada: os três partem do MESMO estado, e nenhum
    herda uma rede arrumada pelo concorrente.

    QUAL plano aquece não é neutro em janela CURTA, e isso está medido. O agente
    A8 mediu que numa rodada de 120 s o `coordenado_c60` fica ABAIXO do timer
    uniforme (109,2 contra 112,5) — invertendo o resultado da janela de 7200 s —
    porque, aquecido pelo timer uniforme, ele entra fora de fase e gasta um ciclo
    inteiro (60 s, metade da rodada) se prendendo ao relógio absoluto. Aquecer com
    o próprio plano coordenado tira esse transiente: os três braços continuam
    partindo do mesmo estado — o que o pareamento exige —, só que de um estado que
    não penaliza especificamente o plano travado no relógio.

    `"coordenado:<nome>"` carrega o plano em `sumo/aberta/planos/<nome>.json`.
    """
    if cenario.warmup_plano == "timer":
        from sim.environment import constants as C

        from ..controladores import ControladorTimer

        return ControladorTimer(float(C.BASELINE_GREEN), nome="aquecimento")

    if cenario.warmup_plano.startswith("coordenado:"):
        from ..controladores import ControladorCoordenado

        nome = cenario.warmup_plano.split(":", 1)[1]
        raiz = Path(__file__).resolve().parents[2]
        plano = raiz / "sumo" / "aberta" / "planos" / ("%s.json" % nome)
        if not plano.exists():
            raise ArenaNaoConfigurada("plano de aquecimento não existe: %s" % plano)
        return ControladorCoordenado(plano, nome="aquecimento")

    raise ArenaNaoConfigurada(
        "warmup_plano=%r não implementado (use 'timer' ou 'coordenado:<plano>')"
        % cenario.warmup_plano)
