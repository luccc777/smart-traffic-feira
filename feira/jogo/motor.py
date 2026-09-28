"""`MotorDoJogo` — a máquina de estados da rodada e a montagem do placar (C7).

    ocioso ─START─> preparando ─fantasmas ok─> contagem ─3·2·1─> jogando ─t1─> resultado ─┐
       ^                  │ falhou tudo                            │ START = ABORTAR      │
       └──────────────────┴────────────────────────────────────────┴──────────────────────┘

O QUE CADA FASE FAZ, E POR QUÊ ELA EXISTE
-----------------------------------------
`preparando`  garante os dois fantasmas da seed da vez (cache em disco ou
              cálculo headless, ~2,5 s cada no `aberta.maquete`) e agenda os da
              PRÓXIMA seed, para a rodada seguinte começar instantânea.
`contagem`    3-2-1. Roda DENTRO do `reset()` do `ControladorHumano`, que é o
              instante exato em que a janela de medição abre. Contar antes de
              chamar a Arena deixaria um buraco de ~1,5 s entre o "JÁ!" e o
              primeiro carro andar, porque o aquecimento de 300 s roda solto
              (a Arena só aplica `Ritmo` dentro da janela) — e o `_Relogio` da
              rodada nasce depois do `reset`, então o tempo gasto aqui não vira
              atraso acumulado.
`jogando`     UMA chamada de `ArenaSumo.roda(...)` com `Ritmo(1.0)`: 120 s
              simulados em 120 s de parede. O observador por sim-step é quem
              publica o `Placar` — os três braços no MESMO `t`, que é a garantia
              estrutural do C7 contra o achado nº1 da auditoria.
`resultado`   manchete = **carros entregues**. Nunca tempo de viagem: a média só
              conta quem chegou, então um jogador que trave a rede ganharia com
              a média dos sobreviventes (a mesma razão pela qual a seleção de
              checkpoint deste projeto passou a ser por vazão).

O SELO DE t0
------------
O humano e os dois fantasmas têm que ter partido do MESMO estado em `t0` — o
achado do agente A1 sobre a quantização de 1 cm do `saveState` (ver
`feira/jogo/estado.py`). O motor compara os selos e, se divergirem, publica o
placar com `vencedor=None` e `motivo` preenchido em vez de coroar alguém com
base numa comparação que não é pareada.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from ..contratos import (
    ACEITO as ACEITO_START,
)
from ..contratos import (
    ARMADO as ARMADO_START,
)
from ..contratos import (
    CONTAGEM,
    JOGANDO,
    OCIOSO,
    PREPARANDO,
    RESULTADO,
    Cenario,
    Chave,
    Fantasma,
    Janela,
    LinhaPlacar,
    Placar,
    Resultado,
    Ritmo,
)
from ..contratos import (
    NEGADO as NEGADO_START,
)
from ..contratos import (
    OFF as OFF_START,
)
from ..controladores.humano import ControladorHumano
from ..entrada import GravacaoRodada, caminho_gravacao
from ..metricas import sinais_de_travamento
from .estado import ControladorSelado, cenario_da_seed
from .fantasmas import ColetorDeSerie, Fantasmaria

__all__ = ["MotorDoJogo", "ResultadoRodada", "ROTULOS", "RodadaAbortada", "Marcapasso",
           "ABORTA_START", "ABORTA_OPERADOR", "PREFIXO_TRAVOU"]

ROTULOS = {"timer": "TIMER FIXO", "rl": "REDE NEURAL", "humano": "VOCÊ"}

# Alvo de frequência de `poll()` na fonte de entrada. 50 Hz = 20 ms de fatia, um
# quarto do teto de 50 ms que o agente A4 mediu para a botoeira.
FATIA_S = 0.02

# Quem pode abortar a rodada no meio (docs/GAMIFICACAO.md §2.5).
#
# `start`    o comportamento original: qualquer START durante a rodada aborta.
# `operador` o START do visitante é IGNORADO durante `contagem`/`jogando` (o botão
#            grande, iluminado, no meio de 12 que ele está martelando, VAI ser
#            apertado — e perder 2 minutos de um visitante por isso é a pior
#            experiência possível em público). Abortar passa a ser `abortar()`,
#            chamado por quem opera (Esc no teclado, botão na página do operador).
ABORTA_START = "start"
ABORTA_OPERADOR = "operador"

# Prefixo do `motivo` quando o portão de saúde dispara. O discriminador de estado
# no fio é `Placar.sinais` (C7); o prefixo existe para o log e para a leitura humana.
PREFIXO_TRAVOU = "o trânsito travou"


class RodadaAbortada(RuntimeError):
    """O operador (ou o visitante) apertou START no meio da rodada."""


class Marcapasso:
    """Cadência 1:1 do lado do observador, com bombeamento de alta frequência.

    O PROBLEMA (medido pelo agente A4): a Arena chama o observador UMA vez por
    sim-step e, com `STEP_LENGTH=1.0` e `Ritmo(sim_por_parede=1.0)`, dorme o
    segundo inteiro logo depois. Quem drena a `FonteEntrada` durante a rodada é
    o observador — então a fonte é lida a **1 Hz**. Latência botão→evento de até
    1000 ms contra um teto de 50 ms, e, pior para o jogo, o LED de "armado"
    demora um segundo para acender: exatamente o efeito que o C6 existe para
    evitar ("sem retorno visual o visitante conclui que o botão quebrou").

    O CONSERTO CERTO é na Arena — fatiar a espera do `_Relogio` e chamar um
    gancho entre as fatias. `feira/arena/**` está fora da fronteira do agente
    A3, então a mudança foi PEDIDA ao dono do repo e, enquanto ela não chega, a
    rodada roda com `Ritmo` SOLTO e a cadência é imposta aqui: o observador
    dorme até o deadline do sim-step em fatias de `fatia_s` e bombeia a fonte
    entre elas. Quando a Arena expuser `ao_esperar`, o motor devolve a cadência
    para ela e este objeto sai de cena (ver `MotorDoJogo._cadencia`).

    A disciplina de atraso é a MESMA do `_Relogio`: o deadline não é reajustado
    quando o laço fica para trás — o atraso é acumulado e reportado. Reajustar o
    deadline em silêncio foi o que produziu a deriva entre os dois braços do
    dashboard (achado nº1 da auditoria).
    """

    def __init__(self, *, passo_sim: float = 1.0, sim_por_parede: float = 1.0,
                 fatia_s: float = FATIA_S, bomba: Callable[[], None] | None = None,
                 atraso_max_s: float = 2.0,
                 dorme: Callable[[float], None] = time.sleep,
                 agora: Callable[[], float] = time.perf_counter) -> None:
        self.passo_sim = float(passo_sim)
        self.sim_por_parede = float(sim_por_parede)
        self.fatia_s = float(fatia_s)
        self.bomba = bomba
        self.atraso_max_s = float(atraso_max_s)
        self._dorme = dorme
        self._agora = agora
        self.atraso_max = 0.0
        self.atraso_final = 0.0
        self.estouros = 0
        self.n_bombas = 0
        self._deadline = 0.0
        self._t_ini = 0.0

    def inicia(self) -> None:
        self._deadline = self._agora()
        self._t_ini = self._deadline
        self.atraso_max = self.atraso_final = 0.0
        self.estouros = 0
        self.n_bombas = 0

    def _bombeia(self) -> None:
        self.n_bombas += 1
        if self.bomba is not None:
            self.bomba()

    def passo(self) -> None:
        """Um sim-step passou: espera o que falta, bombeando a fonte."""
        self._deadline += self.passo_sim / self.sim_por_parede
        self._bombeia()                       # sempre ao menos uma vez por step
        while True:
            falta = self._deadline - self._agora()
            if falta <= 0:
                break
            self._dorme(min(self.fatia_s, falta))
            self._bombeia()
        atraso = self._agora() - self._deadline
        if atraso > self.atraso_max_s:
            self.estouros += 1
        self.atraso_max = max(self.atraso_max, atraso)
        self.atraso_final = atraso

    @property
    def hz(self) -> float:
        """Frequência MEDIDA de `poll()` na fonte durante a rodada."""
        dt = self._agora() - self._t_ini
        return self.n_bombas / dt if dt > 0 else 0.0


@dataclass
class ResultadoRodada:
    """O que uma rodada produziu. Dado, não estado — o motor já seguiu adiante."""

    chave: Chave
    seed: int
    humano: Resultado | None
    fantasmas: dict[str, Fantasma]
    placar: Placar | None
    vencedor: str | None
    gravacao: GravacaoRodada | None = None
    abortada: bool = False
    motivo: str = ""
    selo_humano: str | None = None
    selos: dict[str, str] = field(default_factory=dict)
    duracao_parede_s: float = 0.0
    hz_entrada: float = 0.0          # frequência MEDIDA de poll() na fonte
    atraso_max_s: float = 0.0        # o pior atraso da cadência 1:1, acumulado
    # Sinais de saúde do braço humano contra o timer da mesma seed (o portão de
    # rodada curta, docs/DIFICULDADE.md §7). Vazio = a rodada vale.
    sinais: tuple[str, ...] = ()
    # A rodada não aconteceu por falha NOSSA (SUMO caiu, TraCI fechou) e a mesma
    # seed vai ser repetida para o mesmo visitante — a "rodada grátis" (§5.4).
    repetir: bool = False

    @property
    def travou(self) -> bool:
        return bool(self.sinais)

    @property
    def selos_batem(self) -> bool:
        """Humano e fantasmas partiram do mesmo estado em t0?

        `True` também quando não há selo de fantasma com o que comparar (cache
        antigo sem o arquivo `.selo.json`) — a ausência de prova não é prova de
        divergência, e o `motivo` registra que a checagem não pôde ser feita."""
        if self.selo_humano is None:
            return True
        return all(s == self.selo_humano for s in self.selos.values())


class MotorDoJogo:
    """A rodada da feira, do START ao placar final."""

    def __init__(self, cenario: Cenario, *, fonte, fantasmaria: Fantasmaria | None = None,
                 arena=None, publicador: Callable[[dict], None] | None = None,
                 seeds: tuple[int, ...] = (100, 101, 102, 103, 104, 105),
                 bracos: tuple[str, ...] = ("timer", "rl"),
                 ao_vivo: bool = True, contagem_s: float = 3.0,
                 resultado_s: float = 7.0, prefetch: bool = True,
                 dorme: Callable[[float], None] | None = None,
                 grava_em=None, fatia_s: float = FATIA_S,
                 abortar_por: str = ABORTA_START, portao_saude: bool = True,
                 repete_falha: bool = False, ritmo: float = 1.0,
                 anuncia_ocioso: bool = False) -> None:
        if not seeds:
            raise ValueError("o motor precisa de pelo menos uma seed")
        if not (ritmo > 0):
            raise ValueError("ritmo deve ser > 0 (segundos simulados por segundo de parede)")
        if abortar_por not in (ABORTA_START, ABORTA_OPERADOR):
            raise ValueError("abortar_por deve ser %r ou %r" % (ABORTA_START, ABORTA_OPERADOR))
        self.cenario = cenario
        self.fonte = fonte
        self.abortar_por = abortar_por
        # RITMO (docs/GAMIFICACAO.md §2.7): segundos simulados por segundo de parede.
        # É APRESENTAÇÃO: a simulação, os fantasmas e o pareamento são indexados em
        # tempo simulado e não mudam. O que muda é o relógio da plateia — e o tempo
        # de parede que o visitante tem por tick, que fica `ritmo` vezes menor.
        self.ritmo = float(ritmo)
        # ANUNCIAR O OCIOSO (docs/GAMIFICACAO.md §3.6): o motor voltava a `ocioso`
        # em silêncio, e a tela só saía do RESULTADO quando o vigia do servidor
        # declarava QUEDA (20 s de rédea) — ou nunca, se o feed ocioso mantivesse
        # `visto_em` fresco. Com isto ligado, o fim da tela de resultado publica um
        # placar de `ocioso` sem linhas, e a projeção volta na hora. Opt-in para não
        # mudar o fio de quem não pediu.
        self.anuncia_ocioso = bool(anuncia_ocioso)
        self.portao_saude = bool(portao_saude)
        self.repete_falha = bool(repete_falha)
        self.starts_ignorados = 0
        self._rodada_id = 0
        self._pular = False
        # Fonte que saiba avisar "o operador pediu para abortar" (Esc no teclado, a
        # página do operador) liga direto no motor. É atributo, não contrato: o C6
        # não conhece abortar, e uma fonte sem ele simplesmente não aborta.
        if abortar_por == ABORTA_OPERADOR and hasattr(fonte, "ao_abortar"):
            try:
                fonte.ao_abortar = self.abortar
            except Exception:
                pass
        self.fantasmaria = fantasmaria or Fantasmaria(cenario)
        self.bracos = tuple(bracos)
        self.seeds = tuple(int(s) for s in seeds)
        self.ao_vivo = bool(ao_vivo)
        self.contagem_s = float(contagem_s)
        self.resultado_s = float(resultado_s)
        self.prefetch = bool(prefetch)
        self.publicador = publicador
        self.dorme = dorme or time.sleep
        self.grava_em = grava_em
        self.fatia_s = float(fatia_s)
        self.marcapasso: Marcapasso | None = None
        self._arena = arena
        self.fase = OCIOSO
        self.i_seed = 0
        self.n_rodadas = 0
        self.ultimo_placar: Placar | None = None
        self.ultima_rodada: ResultadoRodada | None = None
        self.motivo_degradado = ""
        self._tarefas = []
        self._humano: ControladorHumano | None = None
        self._fantasmas: dict[str, Fantasma] = {}
        self._selos: dict[str, str] = {}
        self._coletor: ColetorDeSerie | None = None
        self._t0: float = 0.0
        self._abortar = False

    # ------------------------------------------------------------ condição
    @property
    def seed(self) -> int:
        return self.seeds[self.i_seed % len(self.seeds)]

    @property
    def proxima_seed(self) -> int:
        return self.seeds[(self.i_seed + 1) % len(self.seeds)]

    def janela(self) -> Janela:
        return self.fantasmaria.janela()

    def chave(self, seed: int | None = None) -> Chave:
        return self.fantasmaria.chave(self.seed if seed is None else seed)

    def _arena_viva(self):
        if self._arena is None:
            from ..arena import ArenaSumo

            self._arena = ArenaSumo()
        return self._arena

    # -------------------------------------------------------------- laço
    def espera_start(self, timeout: float | None = None,
                     intervalo: float | None = None) -> bool:
        """Fica em `ocioso` até alguém apertar START. Não bloqueia o processo:
        devolve False no timeout, para o chamador poder publicar a tela ociosa."""
        self.fase = OCIOSO
        intervalo = self.fatia_s if intervalo is None else float(intervalo)
        fim = None if timeout is None else time.perf_counter() + float(timeout)
        while True:
            for ev in self.fonte.poll():
                if ev.e_start:
                    return True
            if fim is not None and time.perf_counter() >= fim:
                return False
            self.dorme(intervalo)

    def rodada(self) -> ResultadoRodada:
        """Uma rodada inteira: preparando -> contagem -> jogando -> resultado.

        BLOQUEIA por ~`janela.duracao` segundos de parede quando `ao_vivo=True`
        (é a rodada acontecendo). Quem quiser tela ociosa entre rodadas chama
        `espera_start()` antes."""
        t_ini = time.perf_counter()
        seed = self.seed
        chave = self.chave(seed)
        self._rodada_id = self.n_rodadas + 1
        self._pular = False
        self._fantasmas = self._prepara(seed)
        self._selos = {b: self.fantasmaria.selos.get((seed, b), "")
                       for b in self._fantasmas}
        self._selos = {b: s for b, s in self._selos.items() if s}

        humano = ControladorHumano(self.fonte, ao_abrir_janela=self._contagem)
        selado = ControladorSelado(humano)
        self._humano = humano
        self._coletor = ColetorDeSerie()
        self._abortar = False
        res: Resultado | None = None
        motivo = self.motivo_degradado
        abortada = False
        ritmo = self._cadencia()
        try:
            self.fase = CONTAGEM
            res = self._arena_viva().roda(
                cenario_da_seed(self.cenario, seed), seed, selado, self.janela(),
                ritmo=ritmo, observador=self._observa)
        except RodadaAbortada as exc:
            abortada = True
            motivo = str(exc) or "abortada pelo operador"
        except Exception as exc:                              # degradado, não fatal
            motivo = "%s: %s" % (type(exc).__name__, exc)

        gravacao = None
        if humano.gravacao:
            gravacao = GravacaoRodada.de(chave, n_botoes=self.fonte.n_botoes,
                                         fonte=getattr(self.fonte, "nome", "?"),
                                         ticks=humano.gravacao)
            if self.grava_em is not None:
                gravacao.salva(caminho_gravacao(self.grava_em, chave,
                                                "r%03d" % self.n_rodadas))

        rodada = ResultadoRodada(
            chave=chave, seed=seed, humano=res, fantasmas=dict(self._fantasmas),
            placar=None, vencedor=None, gravacao=gravacao, abortada=abortada,
            motivo=motivo, selo_humano=selado.selo, selos=dict(self._selos),
            duracao_parede_s=time.perf_counter() - t_ini,
            hz_entrada=self.marcapasso.hz if self.marcapasso else 0.0,
            atraso_max_s=self.marcapasso.atraso_max if self.marcapasso else 0.0)
        # Rodada grátis: falha NOSSA (não abortada, sem resultado) repete a seed para
        # o mesmo visitante em vez de passar a vez — os fantasmas já estão em cache.
        rodada.repetir = bool(self.repete_falha and res is None and not abortada)
        rodada.placar, rodada.vencedor = self._placar_final(rodada)
        self._publica(rodada.placar)
        self.fase = RESULTADO
        self.ultima_rodada = rodada
        self.n_rodadas += 1
        if not rodada.repetir:
            self.i_seed += 1
        if self.resultado_s > 0:
            self._espera_resultado(self.resultado_s)
        if self.prefetch:
            self.agenda_proxima()
        self.fase = OCIOSO
        if self.anuncia_ocioso:
            self._publica(Placar.monta(OCIOSO, self.janela().t1, self.chave(), [],
                                       t_restante=0.0, rodada=self._rodada_id))
        return rodada

    def _espera_resultado(self, segundos: float) -> None:
        """A tela de RESULTADO fica `segundos` no ar — a menos que o operador pule."""
        if not self.ao_vivo:
            self.dorme(segundos)
            return
        fim = time.perf_counter() + float(segundos)
        while not self._pular:
            falta = fim - time.perf_counter()
            if falta <= 0:
                break
            self.dorme(min(0.1, falta))

    # ------------------------------------------------------------ operador
    def abortar(self) -> None:
        """Pede o aborto da rodada em curso. Fora da rodada, não faz nada."""
        self._abortar = True

    def pula_resultado(self) -> None:
        """Encurta a tela de RESULTADO — a fila está grande."""
        self._pular = True

    def laco(self, n_rodadas: int | None = None, *, esperar_start: bool = True
             ) -> list[ResultadoRodada]:
        """O laço do operador. `n_rodadas=None` = até o fim da feira (Ctrl-C)."""
        saida: list[ResultadoRodada] = []
        while n_rodadas is None or len(saida) < n_rodadas:
            if esperar_start and not self.espera_start(timeout=None):
                break
            saida.append(self.rodada())
        return saida

    # ------------------------------------------------------------ cadência
    def _bomba(self) -> None:
        """Drena a fonte e atende o ABORTAR. Chamado a ~50 Hz durante a rodada."""
        if self._humano is None:
            return
        self._humano.bombeia()
        if self._abortar:
            raise RodadaAbortada("abortada pelo operador")
        starts = self._humano.consome_starts()
        if starts:
            if self.abortar_por == ABORTA_START:
                raise RodadaAbortada("START apertado durante a rodada")
            # `operador`: o START do visitante não aborta. O LED do botão grande
            # pisca (deny) para dizer "agora não" e volta ao estado da fase.
            self.starts_ignorados += len(starts)
            self._led_start_bruto(NEGADO_START)

    def _cadencia(self) -> Ritmo:
        """Escolhe QUEM impõe o 1:1 — a Arena (se ela tiver o gancho) ou o motor.

        A cadência é do laço, nunca do controlador (regra do C4). O gancho
        `ao_esperar` ainda não existe na `ArenaSumo`: enquanto não existir, o
        `Ritmo` vai solto e o `Marcapasso` impõe o 1:1 do lado do observador —
        senão a fonte de entrada é lida a 1 Hz (ver o cabeçalho do `Marcapasso`).
        """
        self.marcapasso = None
        if not self.ao_vivo:
            return Ritmo()
        arena = self._arena_viva()
        if hasattr(arena, "ao_esperar"):
            arena.ao_esperar = self._bomba
            return Ritmo(sim_por_parede=self.ritmo)
        self.marcapasso = Marcapasso(bomba=self._bomba, fatia_s=self.fatia_s,
                                     dorme=self.dorme, sim_por_parede=self.ritmo)
        self.marcapasso.inicia()
        return Ritmo()

    # -------------------------------------------------------------- fases
    def _prepara(self, seed: int) -> dict[str, Fantasma]:
        self.fase = PREPARANDO
        self.motivo_degradado = ""
        self._publica(self._placar(PREPARANDO, self.janela().t0, {}, None))
        for t in list(self._tarefas):
            if t.seed == seed and t.processo is not None:
                try:
                    t.espera(timeout=180)
                except Exception:
                    pass
        self._tarefas = [t for t in self._tarefas if t.seed != seed]
        fantasmas = self.fantasmaria.garante(seed, self.bracos)
        faltando = [b for b in self.bracos if b not in fantasmas]
        if faltando:
            self.motivo_degradado = ("modo degradado: sem fantasma de %s (%s)"
                                     % ("/".join(faltando),
                                        getattr(self.fantasmaria, "ultimo_erro", "?")))
        return fantasmas

    def _contagem(self, t0: float) -> None:
        """3-2-1, dentro do `reset()` do humano. Ver o cabeçalho do módulo.

        A fonte é drenada durante a contagem e o que vier é DESCARTADO: quem
        martela o botão no 3-2-1 não começa a rodada com 12 trocas de graça.
        Drenar também é o que mantém o buffer do teclado vazio em t0."""
        self._t0 = float(t0)
        self.fase = CONTAGEM
        n = int(self.contagem_s)
        for k in range(n, 0, -1):
            self._publica(self._placar(CONTAGEM, t0, {}, None, t_restante=float(k)))
            self._espera_contando(1.0 if k > 1 else 1.0 + (self.contagem_s - n))
        if self._humano is not None:
            self._humano.consome_starts()
            self._humano.descarta()
        if self.marcapasso is not None:
            self.marcapasso.inicia()          # o relógio da rodada nasce AQUI
        self.fase = JOGANDO

    def _espera_contando(self, segundos: float) -> None:
        """Dorme em fatias, drenando a fonte — a contagem não pode engasgar o LED."""
        if not self.ao_vivo:
            return
        fim = time.perf_counter() + float(segundos)
        while time.perf_counter() < fim:
            self.dorme(min(self.fatia_s, max(0.0, fim - time.perf_counter())))
            if self._humano is not None:
                self._humano.bombeia()

    def _observa(self, frame) -> None:
        """Observador da Arena: publica o placar, marca a cadência e atende o ABORTAR."""
        assert self._coletor is not None
        antes = len(self._coletor.amostras)
        self._coletor(frame)
        if len(self._coletor.amostras) > antes:
            self._publica(self._placar(JOGANDO, frame.t,
                                       self._fantasmas, self._coletor.amostras[-1]))
        if self.marcapasso is not None:
            self.marcapasso.passo()           # dorme até o deadline, bombeando
        else:
            self._bomba()

    # -------------------------------------------------------------- placar
    def _linhas(self, t: float, fantasmas: dict[str, Fantasma], humano) -> list[LinhaPlacar]:
        linhas: list[LinhaPlacar] = []
        for braco in ("timer", "rl"):
            f = fantasmas.get(braco)
            if f is None:
                continue
            a = f.em(t)
            linhas.append(LinhaPlacar(braco=braco, rotulo=ROTULOS[braco],
                                      entregues=int(a.entregues), fila=float(a.fila),
                                      tempo_medio=float(a.tempo_medio), fantasma=True))
        if humano is not None:
            linhas.append(LinhaPlacar(braco="humano", rotulo=ROTULOS["humano"],
                                      entregues=int(humano.entregues),
                                      fila=float(humano.fila),
                                      tempo_medio=float(humano.tempo_medio),
                                      fantasma=False))
        return linhas

    @staticmethod
    def _linha_final(braco: str, res: Resultado) -> LinhaPlacar:
        return LinhaPlacar(braco=braco, rotulo=ROTULOS[braco],
                           entregues=int(res.entregues), fila=float(res.fila_media),
                           tempo_medio=float(res.tempo_medio_entregue),
                           fantasma=braco != "humano")

    def _placar(self, fase: str, t: float, fantasmas: dict[str, Fantasma], humano,
                *, t_restante: float | None = None, vencedor: str | None = None) -> Placar:
        j = self.janela()
        if t_restante is None:
            t_restante = max(0.0, j.t1 - float(t))
        p = Placar.monta(fase, float(t), self.chave(), self._linhas(t, fantasmas, humano),
                         t_restante=float(t_restante), vencedor=vencedor,
                         motivo=self.motivo_degradado, rodada=self._rodada_id)
        self.ultimo_placar = p
        return p

    def _sinais(self, rodada: ResultadoRodada) -> tuple[str, ...]:
        """O portão de saúde da rodada curta (docs/DIFICULDADE.md §7, §10.1).

        `sane()` e os sinais sem referência são CEGOS em 120 s — medido em 4752
        rodadas, nem o farol congelado dispara. O sinal que funciona é PAREADO: o
        acúmulo excedente do humano sobre o timer da MESMA seed (+20 pp, zero falso
        positivo em 96 rodadas de referência, 528/528 rodadas congeladas pegas). O
        `Resultado` do timer já está em memória: é o `final` do fantasma.

        Sem fantasma do timer o portão fica DESLIGADO e o `motivo` diz isso — uma
        rodada degradada não pode ser recusada por um portão que não rodou.
        """
        if not self.portao_saude or rodada.humano is None or rodada.abortada:
            return ()
        timer = rodada.fantasmas.get("timer")
        if timer is None:
            rodada.motivo = (rodada.motivo + " | " if rodada.motivo else "") + \
                "sem portão de saúde nesta rodada (sem fantasma do timer)"
            return ()
        try:
            fora = sinais_de_travamento(rodada.humano, referencia=timer.final)
        except Exception as exc:                        # chave incompatível etc.
            rodada.motivo = (rodada.motivo + " | " if rodada.motivo else "") + \
                "portão de saúde não rodou: %s" % exc
            return ()
        return tuple(fora)

    def _placar_final(self, rodada: ResultadoRodada) -> tuple[Placar, str | None]:
        """Manchete = ENTREGUES. Ver o cabeçalho do C7 para o porquê.

        As três linhas saem do `Resultado` (C5), não da última amostra da série:
        é o número que o repo publica, é o mesmo objeto para os três braços, e
        evita comparar a contagem do humano num `t` e a do fantasma noutro — a
        família de erro que a auditoria do A2 catalogou."""
        t = self.janela().t1
        linhas = [self._linha_final(b, rodada.fantasmas[b].final)
                  for b in ("timer", "rl") if b in rodada.fantasmas]
        if rodada.humano is not None:
            linhas.append(self._linha_final("humano", rodada.humano))
        rodada.sinais = self._sinais(rodada)
        vencedor: str | None = None
        if (not rodada.abortada and rodada.humano is not None and rodada.selos_batem
                and not rodada.sinais):
            if linhas:
                melhor = max(ln.entregues for ln in linhas)
                campeoes = [ln.braco for ln in linhas if ln.entregues == melhor]
                vencedor = campeoes[0] if len(campeoes) == 1 else None
        if not rodada.selos_batem:
            rodada.motivo = (rodada.motivo + " | " if rodada.motivo else "") + (
                "selo de t0 divergente (humano=%s fantasmas=%s): a rodada não é "
                "pareada e o vencedor fica em branco"
                % (rodada.selo_humano, rodada.selos))
        if rodada.sinais:
            # Quantas trocas a pessoa pediu: quase sempre a resposta para "por que
            # travou" é "quase nenhuma" (a rodada do dono em 2026-09-14: 2 pedidos em
            # 24 ciclos), e a tela precisa dizer isso junto com o veredito.
            h = self._humano
            pedidos = ("" if h is None else " — você pediu %d trocas em %d ciclos, %d aceitas"
                       % (sum(len(t) for t in h.gravacao), len(h.gravacao), h.n_aceitos))
            rodada.motivo = (rodada.motivo + " | " if rodada.motivo else "") + (
                "%s: %s%s" % (PREFIXO_TRAVOU, "; ".join(rodada.sinais), pedidos))
        if rodada.repetir:
            rodada.motivo = (rodada.motivo + " | " if rodada.motivo else "") + \
                "falha nossa — a mesma seed vai de novo"
        p = Placar.monta(RESULTADO, t, rodada.chave, linhas, t_restante=0.0,
                         vencedor=vencedor, motivo=rodada.motivo,
                         pareado=rodada.selos_batem, rodada=self._rodada_id,
                         sinais=rodada.sinais)
        self.ultimo_placar = p
        return p, vencedor

    def _publica(self, placar: Placar | None) -> None:
        if placar is None:
            return
        self._led_start(placar.fase)
        if self.publicador is None:
            return
        try:
            self.publicador(placar.json())
        except Exception:
            pass          # projeção caída não derruba a rodada (risco 7)

    # O LED do botão grande, por fase da rodada. O C6 fechou o buraco que o
    # agente A4 reportou: `feedback(estados, start=...)` diz o estado do START
    # junto com o dos semáforos, num quadro só. O `feedback_start` continua
    # aceito para fontes que ainda não tenham o parâmetro.
    LED_START = {OCIOSO: ARMADO_START, PREPARANDO: NEGADO_START,
                 CONTAGEM: ACEITO_START, JOGANDO: ACEITO_START,
                 RESULTADO: ARMADO_START}

    def _led_start(self, fase: str) -> None:
        self._led_start_bruto(self.LED_START.get(fase, OFF_START))

    def _led_start_bruto(self, estado: str) -> None:
        try:
            self.fonte.feedback_start(estado)
        except Exception:
            pass          # LED que não acende não derruba a rodada

    # ----------------------------------------------------------- prefetch
    def agenda_proxima(self) -> list:
        """Pré-computa os fantasmas da PRÓXIMA seed, em subprocesso.

        Medido no `aberta.maquete`: ~2,5 s por fantasma contra 120 s de rodada.
        Cabe com folga; o subprocesso existe porque `traci` é uma conexão de
        módulo e duas Arenas no mesmo processo brigam pela sessão."""
        self._tarefas = self.fantasmaria.agenda(self.proxima_seed, self.bracos)
        return self._tarefas
