"""C7 — o contrato de fio: o que trafega no WebSocket até a projeção.

Extensão do contrato que já existe no maquete (`dashboard/backend/snapshot.py`),
com o mínimo necessário para o modo jogo. As adições são ADITIVAS de propósito:
o front atual ignora campo desconhecido, então a projeção de hoje continua
funcionando enquanto a do jogo é construída.

O QUE MUDA EM RELAÇÃO AO CONTRATO DE HOJE
------------------------------------------
- `sim` vira `braco` e ganha um terceiro valor: "humano". O nome muda porque
  "sim" (de simulação) já não descreve o campo — ele identifica o BRAÇO da
  comparação.
- `janela` viaja junto do frame. Sem ela o cliente não tem como saber se dois
  braços estão na mesma condição, e foi exatamente isso que deixou a projeção
  comparar contadores de simulações derivadas.
- mensagem nova `placar`: o estado da rodada, com os três braços no MESMO `t`.

REGRA DO PLACAR: `entregues` é a manchete. NÃO tempo de viagem — a média só conta
quem chegou, então um jogador que trave a rede ganharia com a média dos poucos
sobreviventes. `entregues` colapsa sob travamento e por isso não é enganável do
mesmo jeito (é o mesmo motivo pelo qual a seleção de checkpoint deste projeto
passou a ser por vazão).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .resultado import Chave

BRACOS = ("timer", "rl", "humano")

# Fases da rodada. A projeção desenha uma tela por fase.
OCIOSO = "ocioso"            # exibição normal: a RL rodando, timer como régua
PREPARANDO = "preparando"    # calculando/carregando os fantasmas da próxima rodada
CONTAGEM = "contagem"        # 3-2-1
JOGANDO = "jogando"
RESULTADO = "resultado"
FASES = (OCIOSO, PREPARANDO, CONTAGEM, JOGANDO, RESULTADO)


@dataclass(frozen=True)
class LinhaPlacar:
    """Um braço no placar, no instante `t` da rodada."""

    braco: str               # "timer" | "rl" | "humano"
    rotulo: str              # "TIMER FIXO" | "REDE NEURAL" | "VOCÊ"
    entregues: int           # a MANCHETE
    fila: float              # secundária, menor é melhor
    tempo_medio: float       # secundária, menor é melhor
    fantasma: bool           # True = trajetória pré-computada; False = ao vivo


@dataclass(frozen=True)
class Placar:
    """Mensagem `placar` — os três braços no MESMO tempo simulado.

    `t` é único para os três de propósito: é a garantia estrutural de que o
    público não vê um braço comparado com outro em instantes diferentes.
    """

    tipo: str
    fase: str
    t: float
    t_restante: float
    chave: dict
    linhas: list[dict]
    vencedor: str | None = None    # só na fase RESULTADO
    # `vencedor=None` tem DOIS significados opostos, e sem estes dois campos a
    # projeção não consegue distingui-los: empate (resultado legítimo) e rodada
    # NÃO PAREADA (os braços partiram de estados diferentes em t0 — a comparação
    # não vale). O motor já sabia a diferença e escrevia um `motivo` detalhado em
    # `ResultadoRodada`; ele simplesmente não viajava no fio, então a tela mostrava
    # os dois casos idênticos. É a mesma família de falha que a janela viajar no
    # frame fecha do lado do braço: o cliente tem que poder DENUNCIAR, não adivinhar.
    motivo: str = ""               # por que a rodada terminou assim (livre, humano)
    pareado: bool = True           # os selos de t0 bateram? False => não compare
    # Dois campos ADITIVOS (Onda 3½, gamificação — docs/GAMIFICACAO.md §6.2), com
    # default para nenhum consumidor existente quebrar:
    #
    # `rodada`: o contador de rodadas do motor. É a IDENTIDADE da rodada no fio. Sem
    # ele, quem consome o placar (o quadro de recordes) só consegue distinguir duas
    # rodadas pela tupla de números — e duas pessoas que entregam o mesmo tanto na
    # mesma seed colidem legitimamente. 0 = "mensagem anterior ao campo".
    #
    # `sinais`: os sinais de saúde do braço humano (`feira/metricas.py::
    # sinais_de_travamento`, com o timer da mesma seed como referência). Vazio = são.
    # Não vazio = a rodada NÃO VALE como comparação — a malha travou neste braço — e
    # o vencedor fica em branco. É o terceiro significado de `vencedor=None` que o
    # fio precisava separar: sem este campo, "TRAVOU" chegaria à tela idêntico a
    # "EMPATE" (`pareado=true`, sem vencedor, com linha do humano), e distingui-los
    # exigiria parsear `motivo` — string livre como discriminador de estado, a
    # classe de erro que `pareado` foi criado para eliminar.
    rodada: int = 0
    sinais: tuple[str, ...] = ()

    @staticmethod
    def monta(fase: str, t: float, chave: Chave, linhas: list[LinhaPlacar],
              *, t_restante: float = 0.0, vencedor: str | None = None,
              motivo: str = "", pareado: bool = True,
              rodada: int = 0, sinais=()) -> "Placar":
        if fase not in FASES:
            raise ValueError("fase %r desconhecida (use %r)" % (fase, FASES))
        for ln in linhas:
            if ln.braco not in BRACOS:
                raise ValueError("braço %r desconhecido (use %r)" % (ln.braco, BRACOS))
        sinais = tuple(str(s) for s in (sinais or ()))
        if sinais and vencedor is not None:
            raise ValueError("rodada com sinais de travamento não pode ter vencedor")
        return Placar(
            tipo="placar",
            fase=fase,
            t=round(float(t), 1),
            t_restante=round(float(t_restante), 1),
            chave={"cenario": chave.cenario, "seed": chave.seed,
                   "janela": [chave.janela.t0, chave.janela.t1],
                   "demanda": chave.demanda_sha[:12]},
            linhas=[asdict(ln) for ln in linhas],
            vencedor=vencedor,
            motivo=str(motivo or ""),
            pareado=bool(pareado),
            rodada=int(rodada),
            sinais=sinais,
        )

    @property
    def valida(self) -> bool:
        """A rodada vale como comparação? Pareada E sem sinal de travamento."""
        return self.pareado and not self.sinais

    def json(self) -> dict:
        # `type` SAI JUNTO de `tipo`, de propósito. O frame usa `type` porque
        # espelha o `snapshot.frame` do maquete, e o front de lá despacha por esse
        # nome — renomear quebraria a projeção que já roda. O placar é mensagem
        # nova e nasceu em português. Resultado: um cliente teria que despachar por
        # `m.type || m.tipo`, e o dia em que alguém esquecer a segunda metade a
        # mensagem some sem erro. Duplicar 16 bytes fecha o buraco sem quebrar
        # nenhum dos dois lados (achado do agente A7).
        return {**asdict(self), "type": self.tipo, "sinais": list(self.sinais)}


def frame_wire(braco: str, t: float, *, decisao: int, substep: int, politica: str,
               tls: list[dict], veiculos: list[dict], heat: dict, stats: dict,
               janela: tuple[float, float] | None = None, status: str = "ok",
               seed: int | None = None) -> dict:
    """Um frame de simulação no formato do fio. Espelha o `snapshot.frame` do maquete.

    `seed` é ADITIVO (default `None` = "o produtor não disse"), pela mesma razão que a
    `janela` viaja aqui: a tela OCIOSA recebe dois braços de DOIS PROCESSOS diferentes
    (`scripts/projecao_ocioso.py`), cada um com o seu rodízio de seeds. Se um deles
    abortar uma volta antes do outro — o vigia de população faz isso, e faz de
    propósito — eles passam a rodar HORAS DE TRÂNSITO DIFERENTES. A janela sozinha não
    pega: ela é [warmup, warmup+duração] nos dois casos. Sem a seed no fio, o placar
    do ocioso compararia seed 100 com seed 101 e ninguém veria — o mesmo defeito que a
    janela foi criada para fechar, uma porta adiante.
    """
    if braco not in BRACOS:
        raise ValueError("braço %r desconhecido (use %r)" % (braco, BRACOS))
    return {
        "type": "frame",
        "braco": braco,
        "status": status,
        "t": round(float(t), 1),
        "janela": list(janela) if janela else None,
        "seed": None if seed is None else int(seed),
        "decision": decisao,
        "substep": substep,
        "policy": politica,
        "tls": tls,
        "vehicles": veiculos,
        "heat": heat,
        "stats": stats,
    }
