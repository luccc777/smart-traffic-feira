"""A7 — o transporte da projeção: recebe o placar do motor e serve o front.

O motor (C8/`MotorDoJogo`) já publica o placar chamando `publicador(placar.json())`
e **engole a exceção de propósito** — projeção caída não derruba a rodada (risco 7
do plano). Este módulo é do outro lado desse gancho: um servidor FastAPI que

  * recebe `placar` (do motor) e `frame` (da Arena, via `ArenaPublicada`);
  * difunde os dois por WebSocket a todos os clientes;
  * serve `web/` (o front da projeção) e `GET /api/rede` (a geometria do
    `.net.xml`, PURE READ);
  * vigia a rodada e, se ela parar de publicar, **volta sozinho para `ocioso`**
    (o modo degradado do DoD (d)).

A PROPRIEDADE QUE MANDA EM TUDO AQUI
------------------------------------
A projeção é **observador passivo**. Nada no caminho do jogo pode bloquear
esperando cliente. Por isso:

  * `PublicadorProjecao.__call__` só faz `put_nowait` numa fila LIMITADA e um
    `call_soon_threadsafe` para acordar o laço — as duas operações são O(1) e não
    esperam ninguém. Fila cheia = **descarta o quadro mais velho** e conta;
  * o broadcast roda na asyncio loop, com `asyncio.wait_for(send, 1.0)` por
    cliente e em paralelo (um cliente lento não segura os outros, e é derrubado);
  * o servidor vive numa **thread daemon** com loop próprio. Se ele morrer, o
    motor não fica sabendo.

O QUE ESTE MÓDULO NÃO FAZ (e é de propósito)
---------------------------------------------
Não toca no motor, no contrato e na Arena. O frame ao vivo chega pela
`ArenaPublicada`, um decorador de `Arena` (C4) que encadeia o observador — o motor
recebe `arena=` no construtor, então isso não exige gancho novo em `motor.py`.

Origem: a arquitetura (thread de drenagem, broadcast paralelo, `_NoCacheStatic`,
`export_network`) é portada de `smart-traffic-maquete/dashboard/backend/{app,geometry}.py`
(commit `18ea6dd`), adaptada ao C7 e ao modo jogo.
"""
from __future__ import annotations

import asyncio
import contextlib
import math
import os
import queue
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..contratos.frame import (
    BRACOS,
    CONTAGEM,
    FASES,
    JOGANDO,
    OCIOSO,
    PREPARANDO,
    RESULTADO,
    frame_wire,
)

# O import do FastAPI é de MÓDULO, e tem que ser — não por gosto, por uma armadilha
# que custou meia hora aqui: com `from __future__ import annotations` toda anotação
# vira STRING, e o FastAPI resolve a anotação de uma rota com `get_type_hints`, que só
# enxerga `func.__globals__`. Com `from fastapi import WebSocket` DENTRO da função de
# fábrica, `WebSocket` é local: o FastAPI não resolve, deixa de reconhecer o parâmetro
# como a conexão, e o handshake do `/ws` passa a devolver **403** — sem erro, sem log,
# sem nada no handler (ele nunca é chamado). O guarda abaixo mantém o resto do módulo
# (`EstadoProjecao`, `PublicadorProjecao`, `ArenaPublicada`, `geometria`) importável
# numa máquina sem o extra `web` instalado.
try:                                                      # pragma: no cover - ambiente
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
except ImportError:                                       # pragma: no cover - ambiente
    FastAPI = None
    WebSocket = None
    WebSocketDisconnect = None
    JSONResponse = None
    StaticFiles = None

__all__ = [
    "ANEL", "LEASH_S", "EstadoProjecao", "PublicadorProjecao", "ArenaPublicada",
    "ServidorProjecao", "braco_do_controlador", "cria_app", "geometria", "raiz_web",
]

# Capacidade da fila entre o caminho do jogo e a asyncio loop. A 1 Hz e com o
# broadcast vivo ela nunca passa de 1-2; 512 é o que sobra para um engasgo de 8 min
# de servidor parado antes de começar a descartar. Descarte é do MAIS VELHO: o
# público quer o placar de agora, não a reprise do que perdeu.
ANEL = 512

# Rédea do vigia, por fase: quanto tempo sem publicação antes de declarar QUEDA.
#
# Só `contagem` e `jogando` têm cadência garantida (1 Hz: a contagem publica 3-2-1 e
# o laço publica um placar por sim-step). `preparando` pode ficar em silêncio por
# 9,1 s calculando o fantasma da RL sem cache (JOGO.md §2) e por mais alguns
# segundos subindo o SUMO e rodando os 300 s de aquecimento — armar 2 s ali produz
# "queda" falsa a cada rodada. `resultado` publica UMA vez e o motor dorme 8 s.
# `ocioso` não publica nada: nunca arma.
LEASH_S = {CONTAGEM: 2.0, JOGANDO: 2.0, PREPARANDO: 25.0, RESULTADO: 20.0, OCIOSO: None}

# Período do vigia. O pior caso de detecção é `leash + TICK_VIGIA`, e é isso que o
# teste do DoD (d) mede contra os 3 s.
TICK_VIGIA = 0.25


def raiz_web() -> Path:
    """A pasta do front (`web/` na raiz do repo)."""
    return Path(__file__).resolve().parents[2] / "web"


# ------------------------------------------------------------------ geometria
def _pontos(pts, nd: int = 2) -> list[list[float]]:
    return [[round(float(x), nd), round(float(y), nd)] for x, y in pts]


def _location(net_file: str) -> tuple[dict, list[float]]:
    loc = ET.parse(net_file).getroot().find("location")
    xmin, ymin, xmax, ymax = (float(v) for v in loc.get("convBoundary").split(","))
    ox, oy = (float(v) for v in loc.get("netOffset", "0,0").split(","))
    return {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}, [ox, oy]


def _vtype(add_file: str | None) -> dict:
    """O carro do cenário. `minGap` viaja junto — sem ele o front não sabe a PEGADA.

    A herança do maquete não exportava `minGap` e o `paint.js` chutava
    `1,7 x comprimento`. Aqui a pegada é o teto do sprite (ver docs/PROJECAO.md §3),
    então chutar não serve: sai do `.add.xml`.
    """
    veh = {"length": 5.0, "width": 1.8, "minGap": 2.5, "color": [1.0, 0.85, 0.0]}
    if not add_file or not os.path.exists(add_file):
        return veh
    escolhido = None
    for vt in ET.parse(add_file).getroot().iter("vType"):
        if escolhido is None or vt.get("id") == "DEFAULT_VEHTYPE":
            escolhido = vt
        if vt.get("id") == "DEFAULT_VEHTYPE":
            break
    if escolhido is not None:
        for k in ("length", "width", "minGap"):
            if escolhido.get(k) is not None:
                veh[k] = float(escolhido.get(k))
        cor = escolhido.get("color")
        if cor:
            veh["color"] = [float(v) for v in cor.split(",")][:3]
    return veh


def _links_por_tl(net_file: str, net) -> dict[str, list[dict]]:
    """Por farol, os links em ordem de `linkIndex`, com a linha de parada e o rumo.

    Casa 1:1 com o i-ésimo caractere de `getRedYellowGreenState` que viaja no frame.
    Portado de `dashboard/backend/geometry.py::_tls_links`.
    """
    por_tl: dict[str, list[dict]] = {}
    for c in ET.parse(net_file).getroot().iter("connection"):
        tl = c.get("tl")
        if tl is None:
            continue
        lane = "%s_%s" % (c.get("from"), c.get("fromLane"))
        try:
            shape = net.getLane(lane).getShape()
        except Exception:
            continue
        p1 = shape[-1]
        p0 = shape[-2] if len(shape) >= 2 else p1
        rumo = (math.degrees(math.atan2(p1[0] - p0[0], p1[1] - p0[1])) + 360.0) % 360.0
        por_tl.setdefault(tl, []).append({
            "linkIndex": int(c.get("linkIndex")),
            "dir": c.get("dir", ""),
            "inLane": lane,
            "stopLine": [round(float(p1[0]), 2), round(float(p1[1]), 2)],
            "heading": round(rumo, 1),
        })
    for links in por_tl.values():
        links.sort(key=lambda d: d["linkIndex"])
    return por_tl


def geometria(cenario) -> dict:
    """A geometria estática da rede do cenário, em METROS do SUMO. PURE READ.

    Mesmas unidades de `traci.vehicle.getPosition` — todo o `mundo -> tela` é do
    front. Portado de `dashboard/backend/geometry.py::export_network`, com `minGap`
    e `escalaSimilitude` a mais.
    """
    if "SUMO_HOME" in os.environ:
        caminho = os.path.join(os.environ["SUMO_HOME"], "tools")
        if caminho not in sys.path:
            sys.path.append(caminho)
    import sumolib  # noqa: PLC0415  (import tardio: sumolib depende de SUMO_HOME)

    net = sumolib.net.readNet(cenario.net_file)
    bbox, offset = _location(cenario.net_file)

    faixas = []
    for e in net.getEdges():
        if e.getFunction() != "":
            continue
        rua = "|".join(sorted((e.getFromNode().getID(), e.getToNode().getID())))
        for ln in e.getLanes():
            faixas.append({
                "id": ln.getID(), "edge": e.getID(), "street": rua,
                "index": ln.getIndex(), "width": round(float(ln.getWidth()), 3),
                "type": e.getType(), "shape": _pontos(ln.getShape()),
            })

    juncoes = []
    for n in net.getNodes():
        if n.getType() == "internal":
            continue
        forma = n.getShape()
        if not forma:
            continue
        cx, cy = n.getCoord()
        juncoes.append({"id": n.getID(), "type": n.getType(),
                        "center": [round(float(cx), 2), round(float(cy), 2)],
                        "shape": _pontos(forma)})

    links = _links_por_tl(cenario.net_file, net)
    ids = sorted(tl.getID() for tl in net.getTrafficLights())

    # Velocidade de fluxo livre para o front normalizar a COR do carro. Sai da rede,
    # não de constante: o `paint.js` do maquete tinha 11,11 m/s chumbado (40 km/h) e
    # nesta rede, que está em SIMILITUDE K=6, o limite da secundária é 1,852 m/s — com
    # o valor herdado a frota inteira seria classificada como "parada" e a tela ficaria
    # de uma cor só. `vFree` é o limite da SECUNDÁRIA (a arterial satura, que é o que
    # se quer); `vMax` viaja junto para o cromo do operador.
    velocidades = sorted({round(float(ln.getSpeed()), 4)
                          for e in net.getEdges() if e.getFunction() == ""
                          for ln in e.getLanes() if ln.getSpeed() > 0})
    return {
        "cenario": cenario.chave,
        "bbox": bbox,
        "netOffset": offset,
        "defaultLaneWidth": round(float(faixas[0]["width"]), 3) if faixas else 3.2,
        "vehicle": _vtype(cenario.add_file),
        "vFree": velocidades[0] if velocidades else 11.11,
        "vMax": velocidades[-1] if velocidades else 13.89,
        "lanes": faixas,
        "junctions": juncoes,
        "tls": [{"id": t, "index": i, "links": links.get(t, [])} for i, t in enumerate(ids)],
    }


# -------------------------------------------------------------------- braços
def braco_do_controlador(nome: str | None) -> str | None:
    """`"timer:uniforme_27s"` -> `"timer"`. Devolve None para o que não é braço.

    Os controladores se nomeiam `familia:variante` (`humano:teclado`,
    `rl:v1_queue_di5`, e o coordenado também se chama `timer:...` porque é
    a régua de plano fixo). `frame_wire` recusa braço fora de `BRACOS` — e recusar
    no caminho do jogo seria exatamente o que este módulo não pode fazer, então a
    normalização mora aqui e o desconhecido vira descarte contado, não exceção.
    """
    if not nome:
        return None
    familia = str(nome).split(":", 1)[0].strip().lower()
    return familia if familia in BRACOS else None


# --------------------------------------------------------------------- estado
@dataclass
class EstadoProjecao:
    """O que o servidor sabe. Vive na asyncio loop, exceto a fila (thread-safe)."""

    cenario: Any = None
    fila: "queue.Queue[dict]" = field(default_factory=lambda: queue.Queue(maxsize=ANEL))
    clientes: set = field(default_factory=set)
    ultimo_placar: dict | None = None
    ultimo_frame: dict = field(default_factory=dict)      # braco -> frame
    fase: str = OCIOSO
    degradado: bool = False
    motivo: str = ""
    visto_em: float = 0.0                                  # perf_counter da última publicação
    recebidas: int = 0
    descartadas: int = 0
    enviadas: int = 0
    clientes_caidos: int = 0
    bench: dict | None = None
    relogio: Callable[[], float] = time.perf_counter
    _rede: dict | None = None
    _loop: asyncio.AbstractEventLoop | None = None
    _bcast: "asyncio.Queue | None" = None

    # ---------------------------------------------------------------- ingestão
    def entrega(self, msg: dict) -> bool:
        """Aceita uma mensagem do caminho do jogo. NÃO BLOQUEIA. True = enfileirada.

        Fila cheia descarta o MAIS VELHO: numa projeção o quadro atrasado não vale
        nada, e crescer a fila trocaria "projeção lenta" por "memória do jogo".
        """
        try:
            self.fila.put_nowait(msg)
        except queue.Full:
            self.descartadas += 1
            with contextlib.suppress(queue.Empty):
                self.fila.get_nowait()
            try:
                self.fila.put_nowait(msg)
            except queue.Full:
                return False
        self.acorda()
        return True

    def acorda(self) -> None:
        """Cutuca a asyncio loop. Falha em silêncio: loop morto não é problema do jogo."""
        laco, bc = self._loop, self._bcast
        if laco is None or bc is None:
            return
        with contextlib.suppress(RuntimeError, AttributeError):
            laco.call_soon_threadsafe(self._drena)

    # -------------------------------------------------------- dentro do loop
    def _drena(self) -> None:
        while True:
            try:
                msg = self.fila.get_nowait()
            except queue.Empty:
                return
            self.absorve(msg)

    def absorve(self, msg: dict) -> None:
        """Atualiza o estado com uma mensagem e a põe na fila de difusão."""
        self.recebidas += 1
        tipo = msg.get("tipo") or msg.get("type")
        if tipo == "placar":
            self.ultimo_placar = msg
            fase = msg.get("fase")
            if fase in FASES:
                self.fase = fase
            self.visto_em = self.relogio()
            if self.degradado:
                self.degradado = False
                self.motivo = ""
                self._difunde(self.status("retomada"))
        elif tipo == "frame":
            braco = msg.get("braco")
            if braco in BRACOS:
                self.ultimo_frame[braco] = msg
            self.visto_em = self.relogio()
        self._difunde(msg)

    def _difunde(self, msg: dict) -> None:
        if self._bcast is None:
            return
        try:
            self._bcast.put_nowait(msg)
        except asyncio.QueueFull:
            self.descartadas += 1

    # ------------------------------------------------------------- divergência
    def divergencia(self) -> str:
        """A ARMADILHA (b) do C7: dois braços em janelas diferentes não se comparam.

        A `janela` viaja no frame justamente porque a projeção antiga comparava
        contadores de simulações derivadas. Se dois frames vivos chegarem com
        janelas diferentes — ou um frame discordar da janela do placar — a tela tem
        que DENUNCIAR, não desenhar. Aqui a denúncia é montada; quem a mostra é o
        front (`web/js/projecao.js`), que refaz a mesma conta por conta própria.
        """
        janelas: dict[str, tuple] = {}
        for braco, fr in self.ultimo_frame.items():
            j = fr.get("janela")
            if j:
                janelas[braco] = tuple(round(float(v), 3) for v in j)
        p = self.ultimo_placar
        if p and p.get("chave", {}).get("janela"):
            janelas["placar"] = tuple(round(float(v), 3)
                                      for v in p["chave"]["janela"])
        distintas = set(janelas.values())
        if len(distintas) > 1:
            return "janelas diferentes: " + " · ".join(
                "%s=[%g, %g]" % (k, v[0], v[1]) for k, v in sorted(janelas.items()))
        return ""

    # ------------------------------------------------------------------ vigia
    def vencida(self) -> float:
        """Segundos além da rédea da fase atual. <= 0 = dentro do prazo."""
        redea = LEASH_S.get(self.fase)
        if redea is None or self.visto_em <= 0.0:
            return 0.0
        return (self.relogio() - self.visto_em) - float(redea)

    def cai(self, motivo: str) -> dict:
        """Declara a queda e devolve o placar sintético de `ocioso`.

        Não inventa número: o placar degradado vem SEM linhas e com `origem`
        marcando que foi o servidor que o montou. Quem desenha barra de placar com
        número que ninguém mediu está mentindo na frente do público.
        """
        self.degradado = True
        self.motivo = motivo
        self.fase = OCIOSO
        return self.status("queda")

    def status(self, evento: str = "estado") -> dict:
        return {
            "tipo": "projecao", "evento": evento, "fase": self.fase,
            "degradado": self.degradado, "motivo": self.motivo,
            "divergencia": self.divergencia(),
            "bracos_vivos": sorted(self.ultimo_frame),
            "recebidas": self.recebidas, "descartadas": self.descartadas,
            "clientes": len(self.clientes),
            "t_servidor": round(time.time(), 3),
        }

    def rede(self) -> dict:
        if self._rede is None:
            if self.cenario is None:
                raise RuntimeError("servidor sem cenário: /api/rede não tem o que ler")
            self._rede = geometria(self.cenario)
        return self._rede

    def inicial(self) -> list[dict]:
        """O que um cliente novo recebe antes de entrar no broadcast."""
        saida: list[dict] = [self.status("bem-vindo")]
        for braco in BRACOS:
            if braco in self.ultimo_frame:
                saida.append(self.ultimo_frame[braco])
        if self.ultimo_placar is not None:
            saida.append(self.ultimo_placar)
        return saida


# ----------------------------------------------------------------- publicador
class PublicadorProjecao:
    """O gancho `publicador` do motor, e o espelho de frames da Arena.

    Chamável: `motor = MotorDoJogo(..., publicador=pub)`. O motor já engole
    exceção deste caminho, mas ele NÃO deve precisar disso: aqui dentro nada
    levanta e nada espera.
    """

    def __init__(self, estado: EstadoProjecao | None = None, *,
                 envia: Callable[[dict], Any] | None = None) -> None:
        if estado is None and envia is None:
            raise ValueError("o publicador precisa de um `estado` ou de um `envia`")
        self.estado = estado
        # `envia` existe para o feed do ocioso, que roda em OUTRO processo e manda a
        # mensagem pelo socket `/ingest` em vez de entregar a um estado local. A
        # conversão `Frame` (C4) -> mensagem de fio (C7) é a mesma nos dois casos, e é
        # o único lugar do repo onde ela mora.
        self._envia = envia if envia is not None else estado.entrega
        self.chamadas = 0
        self.pior_ms = 0.0        # o custo máximo que o jogo pagou por publicar
        self.pior_em = -1         # em qual chamada ele aconteceu
        # Amostras do custo, para o custo virar DISTRIBUIÇÃO e não anedota: um máximo
        # sozinho não distingue "a projeção é cara" de "o Windows escalonou noutra
        # hora". Deque limitado: uma feira inteira não pode virar vazamento.
        self.custos_ms: "deque[float]" = deque(maxlen=4096)

    def __call__(self, msg: dict) -> None:
        t0 = time.perf_counter()
        try:
            self.chamadas += 1
            self._envia(msg)
        except Exception:
            pass                  # o caminho do jogo nunca vê erro da projeção
        finally:
            self._anota((time.perf_counter() - t0) * 1e3)

    def _anota(self, ms: float) -> None:
        self.custos_ms.append(ms)
        if ms > self.pior_ms:
            self.pior_ms = ms
            self.pior_em = self.chamadas

    def percentis(self) -> dict:
        """p50/p95/max do custo de publicar, em ms. É o número que prova a passividade."""
        if not self.custos_ms:
            return {"n": 0}
        v = sorted(self.custos_ms)
        pega = lambda q: v[min(len(v) - 1, int(len(v) * q))]  # noqa: E731
        return {"n": len(v), "p50": round(pega(0.50), 4), "p95": round(pega(0.95), 4),
                "p99": round(pega(0.99), 4), "max": round(v[-1], 4),
                "max_na_chamada": self.pior_em}

    def frame(self, quadro, *, braco: str | None = None,
              janela: tuple[float, float] | None = None,
              politica: str = "", status: str = "ok") -> None:
        """Espelha um `Frame` (C4) como mensagem de fio (C7). Nunca levanta."""
        t0 = time.perf_counter()
        try:
            b = braco or braco_do_controlador(getattr(quadro, "braco", None))
            if b is None:
                if self.estado is not None:
                    self.estado.descartadas += 1
                return
            self.chamadas += 1
            self._envia(frame_wire(
                b, quadro.t, decisao=quadro.decisao, substep=quadro.substep,
                politica=politica or str(getattr(quadro, "braco", b)),
                tls=quadro.tls, veiculos=quadro.veiculos, heat=quadro.heat,
                stats=quadro.stats, janela=janela, status=status))
        except Exception:
            pass
        finally:
            self._anota((time.perf_counter() - t0) * 1e3)


class ArenaPublicada:
    """Decora uma `Arena` (C4) para espelhar os frames na projeção.

    Existe porque o `MotorDoJogo` consome o `observador` da Arena para si (é ali
    que ele mede a cadência e atende o ABORTAR) e só publica `Placar` — sem isto a
    projeção não teria os carros do braço HUMANO durante a rodada. O motor aceita
    `arena=` no construtor, então encadear o observador aqui não exige gancho novo
    em `motor.py` (o buraco está reportado no relatório do A7).

    ORDEM: publica ANTES de chamar o observador de dentro. O `_observa` do motor
    dorme até o deadline do `Marcapasso` (~1 s); publicar depois dele entregaria o
    quadro um segundo velho.
    """

    def __init__(self, arena, publicador: PublicadorProjecao, *,
                 braco: str | None = None) -> None:
        self._arena = arena
        self._pub = publicador
        self._braco = braco

    # `ao_esperar` é lido E escrito pelo motor (`_cadencia`): tem que ir para dentro.
    @property
    def ao_esperar(self):
        return getattr(self._arena, "ao_esperar", None)

    @ao_esperar.setter
    def ao_esperar(self, valor) -> None:
        self._arena.ao_esperar = valor

    def __getattr__(self, nome: str):
        return getattr(self._arena, nome)

    def topologia(self, cenario):
        return self._arena.topologia(cenario)

    def roda(self, cenario, seed, controlador, janela=None, *,
             ritmo=None, observador=None, gui=False):
        j = None if janela is None else (float(janela.t0), float(janela.t1))
        braco = self._braco or braco_do_controlador(getattr(controlador, "nome", None))
        pol = str(getattr(controlador, "nome", "") or "")

        def espelha(quadro):
            self._pub.frame(quadro, braco=braco, janela=j, politica=pol)
            if observador is not None:
                observador(quadro)

        return self._arena.roda(cenario, seed, controlador, janela,
                                ritmo=ritmo, observador=espelha, gui=gui)


# ------------------------------------------------------------------- servidor
def cria_app(estado: EstadoProjecao, *, raiz: Path | None = None):
    """A aplicação FastAPI que serve o front e difunde o placar."""
    if FastAPI is None:
        raise RuntimeError(
            "a projeção precisa do extra `web`: pip install fastapi uvicorn websockets")

    async def _envia(ws, msg: dict) -> None:
        try:
            await asyncio.wait_for(ws.send_json(msg), timeout=1.0)
        except Exception:
            estado.clientes.discard(ws)     # cliente lento/morto sai do broadcast
            estado.clientes_caidos += 1

    async def _difusor() -> None:
        assert estado._bcast is not None
        while True:
            msg = await estado._bcast.get()
            alvos = list(estado.clientes)
            if not alvos:
                continue
            estado.enviadas += 1
            await asyncio.gather(*(_envia(w, msg) for w in alvos))

    async def _vigia() -> None:
        """DoD (d): jogo parou de publicar -> a projeção volta para `ocioso` sozinha."""
        while True:
            await asyncio.sleep(TICK_VIGIA)
            if estado.degradado:
                continue
            atraso = estado.vencida()
            if atraso > 0.0:
                redea = LEASH_S.get(estado.fase) or 0.0
                msg = estado.cai("sem publicação há %.1f s na fase %s (rédea %.1f s)"
                                 % (redea + atraso, estado.fase, redea))
                estado._difunde(msg)

    @contextlib.asynccontextmanager
    async def ciclo(app):
        estado._loop = asyncio.get_running_loop()
        estado._bcast = asyncio.Queue(maxsize=ANEL)
        estado._drena()                      # o que chegou antes do loop subir
        tarefas = [asyncio.create_task(_difusor()), asyncio.create_task(_vigia())]
        try:
            yield
        finally:
            for t in tarefas:
                t.cancel()
            for t in tarefas:
                with contextlib.suppress(asyncio.CancelledError):
                    await t
            estado._loop = None
            estado._bcast = None

    app = FastAPI(lifespan=ciclo, title="SmartTraffic — Projeção da feira")

    @app.get("/api/rede")
    async def api_rede():
        return JSONResponse(estado.rede())

    @app.get("/api/estado")
    async def api_estado():
        return JSONResponse(estado.status())

    @app.get("/api/bench")
    async def api_bench_get():
        """A última medição de render que o front publicou (DoD (b)).

        O número que a DoD cobra — 180+ carros a 1 Hz sem perder quadro NO NOTEBOOK DA
        FEIRA — só existe no navegador do notebook certo. `web/?bench=250` mede lá e
        manda para cá, para o número ser lido/gravado sem ninguém transcrever à mão.
        """
        return JSONResponse(estado.bench or {"vazio": True})

    @app.post("/api/bench")
    async def api_bench_post(payload: dict):
        estado.bench = dict(payload)
        estado.bench["recebido_em"] = time.time()
        return JSONResponse({"ok": True})

    @app.websocket("/ingest")
    async def ingest(websocket: WebSocket):
        """Entrada de PRODUTOR: um processo externo empurra `frame`/`placar` aqui.

        Existe porque `traci` é uma conexão de MÓDULO: duas Arenas no mesmo processo
        brigam pela sessão (é o motivo pelo qual o prefetch dos fantasmas roda em
        subprocesso). O feed da tela `ocioso` — a RL rodando ao vivo com o timer de
        régua — é outro processo, e entra por aqui.

        Só escuta em `127.0.0.1` por padrão (ver `ServidorProjecao`). Mensagem que
        chega aqui passa pelo MESMO caminho limitado das outras: fila cheia descarta,
        nada bloqueia.
        """
        await websocket.accept()
        try:
            while True:
                msg = await websocket.receive_json()
                if isinstance(msg, dict):
                    estado.absorve(msg)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        try:
            # Replay do estado ANTES de entrar no set: assim o difusor nunca faz
            # `send_json` concorrente nesta mesma conexão.
            for msg in estado.inicial():
                await websocket.send_json(msg)
            estado.clientes.add(websocket)
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            estado.clientes.discard(websocket)

    class _SemCache(StaticFiles):
        """Obriga o navegador a revalidar.

        Sem `Cache-Control` o Chrome aplica cache heurístico e abre a versão de dez
        minutos atrás — em silêncio, com o projetor já montado. Aconteceu no maquete.
        """

        def file_response(self, *args, **kwargs):
            resp = super().file_response(*args, **kwargs)
            resp.headers["Cache-Control"] = "no-cache"
            return resp

    pasta = raiz or raiz_web()
    if pasta.exists():
        app.mount("/", _SemCache(directory=str(pasta), html=True), name="projecao")
    return app


class ServidorProjecao:
    """Uvicorn numa thread daemon. Subir e descer não bloqueia o jogo."""

    def __init__(self, estado: EstadoProjecao, *, host: str = "127.0.0.1",
                 porta: int = 8080, raiz: Path | None = None,
                 log_level: str = "warning") -> None:
        import uvicorn

        self.estado = estado
        self.host = host
        self.porta = porta
        self.app = cria_app(estado, raiz=raiz)
        # `websockets-sansio` em vez do `auto`: o `auto` do uvicorn 0.49 ainda escolhe
        # a implementação LEGADA do `websockets`, que já avisa que vai sair. Fixar a
        # nova evita que a projeção quebre numa atualização de dependência no dia da
        # feira — e cala o DeprecationWarning que sujava a suíte.
        self._cfg = uvicorn.Config(self.app, host=host, port=porta,
                                   log_level=log_level, access_log=False,
                                   ws="websockets-sansio",
                                   ws_ping_interval=20.0, ws_ping_timeout=20.0)
        self._srv = uvicorn.Server(self._cfg)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return "http://%s:%d/" % (self.host, self.porta)

    def sobe(self, timeout: float = 15.0) -> bool:
        self._thread = threading.Thread(target=self._srv.run, name="projecao",
                                        daemon=True)
        self._thread.start()
        fim = time.perf_counter() + timeout
        while time.perf_counter() < fim:
            if getattr(self._srv, "started", False):
                return True
            time.sleep(0.02)
        return False

    def desce(self, timeout: float = 6.0) -> None:
        self._srv.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def __enter__(self) -> "ServidorProjecao":
        self.sobe()
        return self

    def __exit__(self, *exc) -> None:
        self.desce()
