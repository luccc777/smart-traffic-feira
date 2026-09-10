"""A bancada do A8: uma rodada de 120 s por processo, milhares delas.

TRÊS COISAS QUE ESTE MÓDULO EXISTE PARA GARANTIR
------------------------------------------------
1. **O adversário passa pela camada do visitante.** Quem roda é o
   `AdversarioHumano` (ver `fonte.py`), nunca um `Controlador` escrito à mão.
2. **Todo braço é conferido.** `res.inseridos > 0` (a falha que já custou uma
   trilha inteira a este projeto: a Arena rodando a malha VAZIA e o diagnóstico
   reportando o caminho certo), `res.sane()` e `feira.metricas
   .sinais_de_travamento` saem em TODA rodada, adversário por adversário.
3. **Um processo por corrida-a-corrida, nunca uma thread.**
   `sim.environment.constants` lê env var no import e congela; `net_topology`,
   `demand_controller` e `traffic_env` derivam dele. Duas configurações no mesmo
   processo é número errado em silêncio — e `traci` ainda é uma conexão de
   módulo, singleton, que duas Arenas na mesma interpretação disputam. O
   paralelismo aqui é `ProcessPoolExecutor`, e cada processo roda SEMPRE o mesmo
   cenário.

O ADVERSÁRIO DA VEZ
-------------------
Os dois oponentes do placar são determinísticos dada a seed: `rl:v1_queue_di5`
(a política do A6, a mesma que `feira.jogo.fantasmas.CKPT_PADRAO` aponta) e
`timer:coordenado_c60` (o baseline do A5). Por isso eles são medidos UMA vez por
(seed, duração) e reusados por todas as rodadas de todos os adversários — é o
mesmo desenho dos fantasmas pré-computados do modo jogo.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..contratos import Cenario, Janela, Resultado
from ..contratos import cenario as resolve_cenario
from ..jogo.estado import cenario_da_seed
from ..jogo.fantasmas import CKPT_PADRAO, VERDE_TIMER_PADRAO
from ..metricas import sinais_de_travamento
from ..treino.ambiente import PLANO_BASELINE
from ..treino.avalia import janela_de, roda_um
from .fonte import AdversarioHumano
from .politicas import DIRECOES, de_texto

__all__ = [
    "CENARIO_PADRAO",
    "MapaFases",
    "OPONENTES",
    "MapaIndisponivel",
    "cria_adversario",
    "linha_de",
    "mapa_de_fases",
    "roda_adversario",
    "roda_oponente",
    "semente_de",
]

CENARIO_PADRAO = "aberta.maquete"

# Os braços contra os quais o humano é medido. `rl` é a política do A6 — a mesma
# que o projetor mostra —, `coordenado_c60` é o baseline do A5, e `timer27` fica
# só por continuidade com os números que o A3 publicou em `JOGO.md` §6.2.
OPONENTES = ("rl", "coordenado_c60", "timer27")


class MapaIndisponivel(RuntimeError):
    """A rede não expõe o mapa fase→aproximação de que a política oráculo precisa."""


@dataclass(frozen=True)
class MapaFases:
    """Que aproximação cada grupo de verde SERVE, por cruzamento.

    `serve` é `(N, G, 4)` booleano na ordem N,S,E,W — a mesma do estado `ats` do
    `TrafficEnv`, e é isso que torna a decodificação do `Observacao.estado`
    legítima em vez de chute. Sai do `.net.xml` (conexões com `linkIndex` +
    string de fase) cruzado com `net_topology.APPROACH_LANES`.

    `grupo_arterial` é, por cruzamento, o grupo de verde que serve as
    aproximações da arterial (E/W = as vias `H*` da maquete).
    """

    tls_ids: tuple[str, ...]
    serve: np.ndarray
    capacidade: float
    grupo_arterial: np.ndarray
    direcoes_arteriais: tuple[str, ...]

    def como_par(self) -> tuple[np.ndarray, float]:
        return self.serve, float(self.capacidade)

    def resumo(self) -> str:
        linhas = []
        for i, t in enumerate(self.tls_ids):
            desc = " | ".join(
                "g%d=%s" % (g, "".join(d for k, d in enumerate(DIRECOES) if self.serve[i, g, k])
                            or "-")
                for g in range(self.serve.shape[1]))
            linhas.append("  %-6s %s   arterial=g%d" % (t, desc, self.grupo_arterial[i]))
        return "\n".join(linhas)


def mapa_de_fases(cenario: Cenario, *, arteriais: tuple[str, ...] = ("E", "W"),
                  arena=None) -> MapaFases:
    """Deriva o mapa fase→aproximação desta rede.

    A chamada a `Arena.topologia(cenario)` no começo NÃO é decorativa: ela é o
    caminho público que amarra `sim.environment` a ESTE cenário. Sem ela,
    `net_topology` já importado responde pela rede que estiver congelada no
    processo — medido aqui: o mapa saiu com 10 semáforos e quase todo vazio,
    porque `ST_SCENARIO` vale "maquete" para `small.maquete` e `aberta.maquete`
    igualmente, e é o reapontamento de `NET_FILE` que separa as duas.
    """
    if arena is None:
        from ..arena import ArenaSumo

        arena = ArenaSumo()
    topo = arena.topologia(cenario)
    from sim.environment import net_topology as nt

    raiz = ET.parse(cenario.net_file).getroot()
    # linkIndex -> lane de origem, por semáforo
    origem: dict[str, dict[int, str]] = {}
    for c in raiz.findall("connection"):
        tid = c.get("tl")
        if tid is None:
            continue
        idx = c.get("linkIndex")
        if idx is None:
            continue
        origem.setdefault(tid, {})[int(idx)] = "%s_%s" % (c.get("from"), c.get("fromLane"))

    ids = tuple(nt.TLS_IDS)
    n_grupos = max(len(nt.TL_PHASES[t].green_phases) for t in ids)
    serve = np.zeros((len(ids), n_grupos, len(DIRECOES)), dtype=bool)
    for i, tid in enumerate(ids):
        info = nt.TL_PHASES[tid]
        por_lane = {}
        for k, d in enumerate(DIRECOES):
            for lane in nt.APPROACH_LANES[tid][d]:
                por_lane[lane] = k
        if tid not in origem:
            raise MapaIndisponivel("nenhuma conexão com linkIndex para %s em %s"
                                   % (tid, cenario.net_file))
        for g, fase in enumerate(info.green_phases):
            estado = info.states[fase]
            for link, lane in origem[tid].items():
                if link >= len(estado) or estado[link] not in "Gg":
                    continue
                k = por_lane.get(lane)
                if k is not None:
                    serve[i, g, k] = True
    if tuple(topo.tls_ids) != ids:
        raise MapaIndisponivel("topologia e net_topology discordam dos semáforos: %r vs %r"
                               % (topo.tls_ids, ids))
    # Um grupo de verde que não serve NENHUMA aproximação é mapa quebrado, não
    # cruzamento sem entrada: foi assim que a primeira versão deste código saiu
    # (rede errada congelada no processo) e o erro passaria como "fila zero".
    vazios = [(ids[i], g) for i in range(len(ids)) for g in range(n_grupos)
              if g < len(nt.TL_PHASES[ids[i]].green_phases) and not serve[i, g].any()]
    if vazios:
        raise MapaIndisponivel(
            "grupo(s) de verde sem aproximação servida em %s: %s — o mapa "
            "fase→aproximação não descreve esta rede" % (cenario.chave, vazios[:6]))
    quais = tuple(DIRECOES.index(d) for d in arteriais)
    peso = serve[:, :, quais].sum(axis=2)          # (N, G) aproximações arteriais servidas
    grupo = np.argmax(peso, axis=1).astype(np.int64)
    return MapaFases(tls_ids=ids, serve=serve, capacidade=float(nt.APPROACH_CAPACITY),
                     grupo_arterial=grupo, direcoes_arteriais=tuple(arteriais))


# --------------------------------------------------------------------- semente
def semente_de(spec: str, seed: int, rep: int) -> int:
    """Semente estável de (adversário, seed, repetição).

    `hash()` do Python é aleatorizado por processo — usá-lo aqui daria uma
    rodada irreprodutível entre execuções, e rodada irreprodutível não é dado.
    """
    return int(zlib.crc32(("%s|%d|%d" % (spec, int(seed), int(rep))).encode("utf-8")))


def cria_adversario(spec: str, *, seed: int, rep: int = 0, mapa=None) -> AdversarioHumano:
    """O `AdversarioHumano` desta (spec, seed, repetição)."""
    roteirista = de_texto(spec, semente=semente_de(spec, seed, rep))
    return AdversarioHumano(roteirista, mapa_fases=mapa)


# ------------------------------------------------------------------- corridas
def _controlador_oponente(qual: str):
    if qual == "rl":
        from ..controladores import ControladorRL

        if not Path(CKPT_PADRAO).exists():
            raise FileNotFoundError("checkpoint da política não existe: %s" % CKPT_PADRAO)
        return ControladorRL(CKPT_PADRAO)
    if qual == "coordenado_c60":
        from ..controladores import ControladorCoordenado

        return ControladorCoordenado(PLANO_BASELINE, nome="timer:coordenado_c60")
    if qual == "timer27":
        from ..controladores import ControladorTimer

        return ControladorTimer(VERDE_TIMER_PADRAO)
    raise ValueError("oponente %r desconhecido (use %s)" % (qual, " | ".join(OPONENTES)))


def linha_de(res: Resultado, *, lacuna_max: float = 25.0, extra: dict | None = None) -> dict:
    """Uma rodada, em JSON puro, com a saúde JUNTO — nunca separada da métrica.

    `sinais_de_travamento` sai com o limiar de lacuna DECLARADO pelo chamador: o
    limiar é dependente de regime, e numa janela de 120 s metade da população
    está censurada por construção (a nota do C5). Quem publica o número escolhe
    o limiar e diz qual foi.
    """
    ok, motivo = res.sane()
    linha = {
        "controlador": res.controlador,
        "seed": res.chave.seed,
        "t0": res.chave.janela.t0,
        "t1": res.chave.janela.t1,
        "entregues": int(res.entregues),
        "tempo_medio_entregue": float(res.tempo_medio_entregue),
        "tempo_medio_no_sistema": float(res.tempo_medio_no_sistema),
        "fila_media": float(res.fila_media),
        "espera_media": float(res.espera_media),
        "inseridos": int(res.inseridos),
        "ativos_inicio": int(res.ativos_inicio),
        "ativos_fim": int(res.ativos_fim),
        "backlog_insercao": int(res.backlog_insercao),
        "perdidos": int(res.perdidos),
        "conservacao": int(res.conservacao),
        "lacuna": _num(res.lacuna_sobrevivencia),
        "travou": bool(res.travou),
        "sane": bool(ok),
        "sane_motivo": motivo,
        "sinais": sinais_de_travamento(res, lacuna_max=lacuna_max),
    }
    if extra:
        linha.update(extra)
    return linha


def _num(x):
    import math

    if x is None or (isinstance(x, float) and (math.isinf(x) or math.isnan(x))):
        return None
    return round(float(x), 4)


def roda_oponente(qual: str, seed: int, *, duracao_s: float = 120.0,
                  cenario: str = CENARIO_PADRAO, arena=None) -> dict:
    """Um braço de referência numa seed. Determinístico — mede uma vez, reusa sempre."""
    cen = resolve_cenario(cenario)
    cen.aplicar(forcar=True)
    janela = janela_de(cen, duracao_s)
    res = roda_um(cenario_da_seed(cen, int(seed)), int(seed), _controlador_oponente(qual),
                  janela, arena=arena)
    return linha_de(res, extra={"braco": qual, "duracao_s": float(duracao_s)})


def roda_adversario(spec: str, seed: int, *, rep: int = 0, duracao_s: float = 120.0,
                    cenario: str = CENARIO_PADRAO, arena=None, mapa=None,
                    guarda_gravacao: bool = False) -> dict:
    """UMA rodada de um adversário. É a unidade da campanha."""
    cen = resolve_cenario(cenario)
    cen.aplicar(forcar=True)
    if mapa is None:
        mapa = mapa_de_fases(cen)
    janela = janela_de(cen, duracao_s)
    adv = cria_adversario(spec, seed=seed, rep=rep, mapa=mapa)
    res = roda_um(cenario_da_seed(cen, int(seed)), int(seed), adv, janela, arena=arena)
    extra = {"braco": "humano", "spec": spec, "rep": int(rep),
             "duracao_s": float(duracao_s)}
    extra.update(adv.diagnostico())
    if guarda_gravacao:
        extra["gravacao"] = [list(t) for t in adv.gravacao]
    return linha_de(res, extra=extra)


# ------------------------------------------------------- estado por processo
_ARENA = None
_MAPA: dict[str, MapaFases] = {}


def arena_do_processo():
    """Uma `ArenaSumo` por processo — ela é reusável entre corridas e o boot custa."""
    global _ARENA
    if _ARENA is None:
        from ..arena import ArenaSumo

        _ARENA = ArenaSumo()
    return _ARENA


def mapa_do_processo(cenario: str = CENARIO_PADRAO) -> MapaFases:
    if cenario not in _MAPA:
        cen = resolve_cenario(cenario)
        cen.aplicar(forcar=True)
        _MAPA[cenario] = mapa_de_fases(cen)
    return _MAPA[cenario]


def tarefa(args: dict) -> dict:
    """Entrada do processo filho: uma rodada (humano ou oponente)."""
    cenario = args.get("cenario", CENARIO_PADRAO)
    if args.get("braco") in OPONENTES:
        return roda_oponente(args["braco"], int(args["seed"]),
                             duracao_s=float(args["duracao_s"]), cenario=cenario,
                             arena=arena_do_processo())
    return roda_adversario(args["spec"], int(args["seed"]), rep=int(args.get("rep", 0)),
                           duracao_s=float(args["duracao_s"]), cenario=cenario,
                           arena=arena_do_processo(), mapa=mapa_do_processo(cenario),
                           guarda_gravacao=bool(args.get("guarda_gravacao", False)))


def _reseta_processo() -> None:
    """Descarta a Arena e a sessão TraCI deste processo depois de uma falha.

    `traci` é conexão de MÓDULO: uma corrida que morre no meio (o
    `struct.error: unpack requires a buffer of 3 bytes` do TraCI, a mesma falha
    transitória que o `JOGO.md` §7 registrou) deixa a conexão pela metade, e a
    corrida seguinte NESTE processo herdaria o estropício. Aqui a conexão é
    fechada à força e a Arena é recriada na próxima tarefa.
    """
    global _ARENA
    _ARENA = None
    try:
        import traci

        traci.close(False)
    except Exception:
        pass


def tarefa_segura(args: dict) -> dict:
    """`tarefa()` que NÃO derruba a campanha.

    Sem isto, uma falha transitória do TraCI em 1 rodada de 4128 aborta o
    `ProcessPoolExecutor` inteiro e joga fora horas de corrida — aconteceu duas
    vezes nesta trilha antes de o laço ganhar retentativa. O erro volta como
    dado (`{"erro": ...}`), o processo se limpa, e quem chama decide se
    reexecuta.
    """
    try:
        return tarefa(args)
    except BaseException as exc:                  # inclusive KeyboardInterrupt do filho
        _reseta_processo()
        return {"erro": "%s: %s" % (type(exc).__name__, exc), "tarefa": dict(args)}


def chave_tarefa(args: dict) -> str:
    """Identidade da rodada — é o que permite retomar uma campanha interrompida."""
    return "%s|%s|%s|%s|%g" % (args.get("braco"), args.get("spec", ""),
                               args.get("seed"), args.get("rep", ""),
                               float(args.get("duracao_s", 0.0)))


def chave_linha(linha: dict) -> str:
    """A mesma identidade, lida de uma linha já calculada."""
    braco = linha.get("braco")
    return "%s|%s|%s|%s|%g" % (braco, linha.get("spec", "") if braco == "humano" else "",
                               linha.get("seed"),
                               linha.get("rep", "") if braco == "humano" else "",
                               float(linha.get("duracao_s", 0.0)))


def janela_da_rodada(cenario: str = CENARIO_PADRAO, duracao_s: float = 120.0) -> Janela:
    return janela_de(resolve_cenario(cenario), duracao_s)
