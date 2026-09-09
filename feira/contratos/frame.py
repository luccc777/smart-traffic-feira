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

    @staticmethod
    def monta(fase: str, t: float, chave: Chave, linhas: list[LinhaPlacar],
              *, t_restante: float = 0.0, vencedor: str | None = None,
              motivo: str = "", pareado: bool = True) -> "Placar":
        if fase not in FASES:
            raise ValueError("fase %r desconhecida (use %r)" % (fase, FASES))
        for ln in linhas:
            if ln.braco not in BRACOS:
                raise ValueError("braço %r desconhecido (use %r)" % (ln.braco, BRACOS))
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
        )

    def json(self) -> dict:
        # `type` SAI JUNTO de `tipo`, de propósito. O frame usa `type` porque
        # espelha o `snapshot.frame` do maquete, e o front de lá despacha por esse
        # nome — renomear quebraria a projeção que já roda. O placar é mensagem
        # nova e nasceu em português. Resultado: um cliente teria que despachar por
        # `m.type || m.tipo`, e o dia em que alguém esquecer a segunda metade a
        # mensagem some sem erro. Duplicar 16 bytes fecha o buraco sem quebrar
        # nenhum dos dois lados (achado do agente A7).
        return {**asdict(self), "type": self.tipo}


def frame_wire(braco: str, t: float, *, decisao: int, substep: int, politica: str,
               tls: list[dict], veiculos: list[dict], heat: dict, stats: dict,
               janela: tuple[float, float] | None = None, status: str = "ok") -> dict:
    """Um frame de simulação no formato do fio. Espelha o `snapshot.frame` do maquete."""
    if braco not in BRACOS:
        raise ValueError("braço %r desconhecido (use %r)" % (braco, BRACOS))
    return {
        "type": "frame",
        "braco": braco,
        "status": status,
        "t": round(float(t), 1),
        "janela": list(janela) if janela else None,
        "decision": decisao,
        "substep": substep,
        "policy": politica,
        "tls": tls,
        "vehicles": veiculos,
        "heat": heat,
        "stats": stats,
    }
