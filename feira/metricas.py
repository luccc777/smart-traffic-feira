"""Métricas de uma corrida — a contabilidade que preenche o `Resultado` (C5).

Puro Python + numpy: nada aqui importa `traci`. Quem tem a sessão TraCI aberta é a
`Arena` (`feira/arena/`); ela empurra EVENTOS para cá e no fim pede o `Resultado`.
Isso é de propósito: a contabilidade é a peça que precisa ser testável sem SUMO,
porque é ela que decide se um número publicado é honesto.

A UNIDADE É A VIAGEM ATIVA, NÃO O VEÍCULO
-----------------------------------------
Os dois modelos de demanda do projeto contam coisas diferentes:

* rede ABERTA (`.rou.xml` por seed): um veículo nasce, viaja e some. Viagem e
  veículo são a mesma coisa.
* rede FECHADA (frota persistente da maquete): o carro chega ao destino e ganha
  destino novo NO MESMO sim-step — a viagem fecha, o veículo continua.

A identidade de conservação do contrato

    ativos_inicio + inseridos − entregues − ativos_fim − perdidos == 0

só vale nos DOIS modelos se "ativo" significar VIAGEM ATIVA (viagem cujo veículo
está fisicamente na rede). Nos dois casos esse número é igual à contagem de
veículos vivos — porque todo veículo vivo tem exatamente uma viagem aberta — e é
por aí que a identidade vira um teste de verdade e não uma tautologia:

    `ativos_inicio`/`ativos_fim` vêm do SUMO (contagem de veículos vivos);
    `inseridos`/`entregues`/`perdidos` vêm do fluxo de eventos.

São DUAS escritas independentes. Se um carro evapora sem ninguém perceber
(teleporte, colisão, remoção), as duas param de fechar — que é exatamente o que
o `coherence_gap` fazia na frota fechada e não faz mais na aberta.

O SUBSTITUTO DO `coherence_gap`
-------------------------------
`sim.evaluation.metrics.coherence_gap` compara as viagens medidas com
`N × T / tempo_medio` — precisa de `N` (frota fixa), que a rede aberta não tem.
O substituto tem três pernas, e nenhuma delas usa `N`:

1. **conservação** (acima): denuncia veículo que sumiu da contabilidade;
2. **backlog de inserção**: denuncia o controlador que "vence" estrangulando a
   borda — a fila fica ótima porque o carro nem entrou;
3. **lacuna de sobrevivência** (`lacuna_sobrevivencia`): a distância entre
   `tempo_medio_no_sistema` (censurado em t1, conta quem ficou preso) e
   `tempo_medio_entregue` (só quem chegou). É o MESMO fenômeno que o
   `coherence_gap` detectava — congestionamento catastrófico melhora a média
   dos sobreviventes — medido sem supor frota fechada.

Ver `docs/AUDITORIA_COMPARACAO.md` §10 para os números medidos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .contratos import Chave, Resultado

__all__ = [
    "Contabilidade",
    "diagnostico",
    "lacuna_sobrevivencia",
    "sinais_de_travamento",
]


# ---------------------------------------------------------------------- livro
@dataclass
class Contabilidade:
    """Acumula os eventos de uma janela e fecha um `Resultado`.

    Ciclo de uso (a Arena chama nesta ordem):

        c = Contabilidade()
        c.abre_janela(t0, ativos=<vivos no SUMO>, abertos={vid: t_abre, ...})
        ...  por sim-step:  c.amostra_rede(fila, espera)
        ...  por evento  :  c.ativou / c.chegou / c.perdeu
        c.fecha_janela(t1, ativos=<vivos no SUMO>, backlog=<pendentes>)
        res = c.resultado(chave, "timer:27s")

    `abertos` é `{id_do_veiculo: instante em que a viagem em curso começou}` —
    inclusive viagens abertas ANTES de t0 (durante o aquecimento). O tempo de
    viagem delas é o tempo cheio, não o recortado pela janela: recortar
    inventaria viagens curtas que nunca existiram.
    """

    # --- produção ---
    entregues: int = 0
    inseridos: int = 0
    perdidos: int = 0
    ativos_inicio: int = 0
    ativos_fim: int = 0
    backlog_insercao: int = 0

    # --- diagnóstico (fora do contrato; a Arena publica em `ultimo_diagnostico`) ---
    teleportes: int = 0
    reativacoes: int = 0          # viagens que reabriram no mesmo instante (frota fechada)
    ativacoes_fisicas: int = 0    # veículo que de fato ENTROU na rede

    # --- estado interno ---
    _t0: float | None = field(default=None, repr=False)
    _t1: float | None = field(default=None, repr=False)
    _abertos: dict[str, float] = field(default_factory=dict, repr=False)
    _tt: list[float] = field(default_factory=list, repr=False)      # tempos de viagem entregues
    _fila: list[float] = field(default_factory=list, repr=False)
    _espera: list[float] = field(default_factory=list, repr=False)
    # detector de travamento: instante da última chegada
    _ultima_chegada: float = field(default=0.0, repr=False)
    _maior_seca_s: float = field(default=0.0, repr=False)
    _t_entregas: list[float] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------- janela
    def abre_janela(self, t0: float, *, ativos: int, abertos: dict[str, float]) -> None:
        self._t0 = float(t0)
        self._t1 = None
        self.ativos_inicio = int(ativos)
        self._abertos = {str(k): float(v) for k, v in abertos.items()}
        self._ultima_chegada = float(t0)

    def fecha_janela(self, t1: float, *, ativos: int, backlog: int) -> None:
        self._t1 = float(t1)
        self.ativos_fim = int(ativos)
        self.backlog_insercao = int(backlog)
        self._maior_seca_s = max(self._maior_seca_s, self._t1 - self._ultima_chegada)

    # ------------------------------------------------------------- eventos
    def ativou(self, vid: str, t: float, *, fisica: bool = True,
               t_abre: float | None = None) -> None:
        """Uma viagem passou a estar ATIVA (veículo presente na rede).

        `fisica=True`: o veículo entrou na rede agora (inserção). `fisica=False`:
        a viagem reabriu sobre um veículo que já estava dentro — o keep-alive da
        frota persistente. Os dois contam como `inseridos` porque os dois criam
        uma viagem ativa; a distinção fica no diagnóstico.

        `t_abre` sobrepõe o instante de início da viagem. Serve à frota
        persistente, onde a viagem de um carro que estava esperando inserção
        começou ANTES de ele entrar — é o `depart_time` do `TripRecord`.
        """
        self._abertos[str(vid)] = float(t if t_abre is None else t_abre)
        self.inseridos += 1
        if fisica:
            self.ativacoes_fisicas += 1
        else:
            self.reativacoes += 1

    def chegou(self, vid: str, t: float, t_abre: float | None = None) -> None:
        """Viagem concluída (o veículo alcançou o destino) dentro da janela."""
        vid = str(vid)
        ini = self._abertos.pop(vid, None) if t_abre is None else float(t_abre)
        if t_abre is not None:
            self._abertos.pop(vid, None)
        self.entregues += 1
        self._t_entregas.append(float(t))
        if ini is not None:
            self._tt.append(float(t) - float(ini))
        self._maior_seca_s = max(self._maior_seca_s, float(t) - self._ultima_chegada)
        self._ultima_chegada = float(t)

    def perdeu(self, vid: str, t: float) -> None:
        """Viagem que deixou de existir SEM concluir: teleporte, colisão, remoção.

        Deveria ser 0. Não entra em `entregues` de propósito — o backstop da frota
        persistente registra o despawn como "viagem concluída", e contá-lo como
        entrega infla a vazão com carros que evaporaram.
        """
        self._abertos.pop(str(vid), None)
        self.perdidos += 1

    def teleportou(self, n: int = 1) -> None:
        self.teleportes += int(n)

    # ------------------------------------------------------------- amostras
    def amostra_rede(self, fila: float, espera: float) -> None:
        """Uma amostra por sim-step: parados e espera acumulada somados na rede."""
        self._fila.append(float(fila))
        self._espera.append(float(espera))

    # ------------------------------------------------------------- fechamento
    @property
    def n_amostras(self) -> int:
        return len(self._fila)

    @property
    def fila_media(self) -> float:
        return (sum(self._fila) / len(self._fila)) if self._fila else 0.0

    @property
    def espera_media(self) -> float:
        return (sum(self._espera) / len(self._espera)) if self._espera else 0.0

    @property
    def tempo_medio_entregue(self) -> float:
        return (sum(self._tt) / len(self._tt)) if self._tt else 0.0

    @property
    def serie_fila(self) -> tuple[float, ...]:
        """A fila amostrada por sim-step, na ordem. É a série sobre a qual o
        `tail()` da projeção calcula a média das últimas 20 amostras — e é com
        ela que o achado nº4 é quantificado."""
        return tuple(self._fila)

    @property
    def serie_espera(self) -> tuple[float, ...]:
        return tuple(self._espera)

    @property
    def instantes_de_entrega(self) -> tuple[float, ...]:
        """Instante SIMULADO de cada entrega, na ordem. Serve ao achado nº6: o
        gate `AQUECIMENTO=8` da projeção é um contador de viagens, e o que ele
        significa em segundos depende do braço e do cenário."""
        return tuple(self._t_entregas)

    @property
    def maior_seca_s(self) -> float:
        """Maior intervalo simulado sem NENHUMA chegada. Sinal cru de travamento."""
        return self._maior_seca_s

    def seca_atual(self, t: float) -> float:
        """Há quanto tempo simulado nenhuma viagem é concluída.

        Tem que ser consultável DURANTE o laço: se só fosse atualizada no
        instante de uma chegada, uma malha que trava e nunca mais entrega
        passaria a corrida inteira sem disparar — foi o que aconteceu na
        primeira versão deste detector, com o farol congelado."""
        return max(0.0, float(t) - self._ultima_chegada)

    def tempo_medio_no_sistema(self, t1: float | None = None) -> float:
        """Média CENSURADA em t1: entregues + quem ainda está na rede.

        É a métrica que piora quando a malha trava, ao contrário do
        `tempo_medio_entregue`. Quem ficou preso entra com a idade que tem em t1.
        """
        fim = float(t1 if t1 is not None else (self._t1 if self._t1 is not None else 0.0))
        presos = [max(0.0, fim - ini) for ini in self._abertos.values()]
        todos = self._tt + presos
        return (sum(todos) / len(todos)) if todos else 0.0

    def resultado(self, chave: Chave, controlador: str, *, travou: bool = False) -> Resultado:
        if self._t1 is None:
            raise RuntimeError("fecha_janela() não foi chamado")
        return Resultado(
            chave=chave,
            controlador=controlador,
            entregues=self.entregues,
            tempo_medio_entregue=self.tempo_medio_entregue,
            tempo_medio_no_sistema=self.tempo_medio_no_sistema(self._t1),
            fila_media=self.fila_media,
            espera_media=self.espera_media,
            inseridos=self.inseridos,
            ativos_fim=self.ativos_fim,
            ativos_inicio=self.ativos_inicio,
            backlog_insercao=self.backlog_insercao,
            perdidos=self.perdidos,
            travou=travou,
        )


# ----------------------------------------------------------- detector novo
def lacuna_sobrevivencia(res: Resultado) -> float:
    """% por que o tempo CENSURADO excede o tempo dos ENTREGUES.

    Delega para `Resultado.lacuna_sobrevivencia` (C5). A medida MIGROU para o
    contrato depois desta auditoria: como ela e calculavel so dos campos do
    proprio `Resultado`, deixa-la aqui fora significava que `sane()` aprovava
    corrida com a malha parada sempre que o carimbo `travou` viesse `False` --
    e um `Resultado` desserializado vem assim.

    Continua exportada daqui porque e o nome que os scripts de medicao usam.
    """
    return res.lacuna_sobrevivencia


def sinais_de_travamento(res: Resultado, *, lacuna_max: float = 25.0,
                         backlog_max_frac: float = 0.10,
                         tol_conservacao: int = 0,
                         perdidos_max_frac: float = 0.005) -> list[str]:
    """Os quatro sinais do detector novo, avaliados. Lista vazia = corrida sã.

    `lacuna_max=25%` é o piso escolhido a partir dos números MEDIDOS na rede
    fechada (`docs/AUDITORIA_COMPARACAO.md` §10.1): política sã fica entre −1,4%
    e −0,2% em 1800-10800 s; o farol congelado passa de +5000%, e o timer de 27 s
    travado na seed 42 dá +173%. Não é um limiar que precise de calibração fina.

    `perdidos` passou a ser checado TAMBEM em `Resultado.sane()` (o contrato C5
    foi corrigido apos esta auditoria). A LACUNA ficou de fora do `sane()` de
    proposito: o limiar dela depende do regime -- os +5884% do farol congelado
    foram medidos em janelas de 1800-10800 s, e numa rodada de 120 s metade da
    populacao esta censurada por construcao. Aqui o limiar e declarado pelo
    chamador, que sabe em que regime esta; e a Arena quem consulta isto e carimba
    `Resultado.travou`.
    """
    fora: list[str] = []
    if abs(res.conservacao) > tol_conservacao:
        fora.append("conservação=%d (veículo evaporou da contabilidade)" % res.conservacao)
    total = res.ativos_inicio + res.inseridos
    if res.perdidos and (not total or res.perdidos / total > perdidos_max_frac):
        fora.append("perdidos=%d de %d viagens ativas (teleporte/colisão/remoção)"
                    % (res.perdidos, total))
    agendados = res.inseridos + res.backlog_insercao
    if agendados and (res.backlog_insercao / agendados) > backlog_max_frac:
        fora.append("backlog de inserção %.1f%% dos agendados (borda estrangulada)"
                    % (100.0 * res.backlog_insercao / agendados))
    lac = lacuna_sobrevivencia(res)
    if math.isinf(lac) or (not math.isnan(lac) and lac > lacuna_max):
        fora.append("lacuna de sobrevivência %s > %.0f%% (há população presa fora da média)"
                    % ("infinita" if math.isinf(lac) else "%.1f%%" % lac, lacuna_max))
    return fora


def diagnostico(res: Resultado, **kw) -> str:
    """Uma linha por sinal, pronta para o log da corrida."""
    fora = sinais_de_travamento(res, **kw)
    ok, motivo = res.sane()
    cab = "%s | %s" % (res.controlador, res.chave.descreve())
    linhas = [cab,
              "  entregues=%d  vazão=%.1f/min  tempo_entregue=%.1fs  tempo_sistema=%.1fs"
              % (res.entregues, res.vazao_por_min, res.tempo_medio_entregue,
                 res.tempo_medio_no_sistema),
              "  fila=%.2f  espera=%.1f  conservação=%d  backlog=%d  perdidos=%d"
              % (res.fila_media, res.espera_media, res.conservacao,
                 res.backlog_insercao, res.perdidos),
              "  lacuna de sobrevivência: %.1f%%" % lacuna_sobrevivencia(res)]
    linhas += ["  ALERTA: " + f for f in fora]
    if not ok:
        linhas.append("  NÃO-SÃ: " + motivo)
    return "\n".join(linhas)
