"""A leitura da rede que o gerador de demanda precisa - e SO ela.

Fronteira de dominio (a mesma do `routing.py` do repo de pesquisa): aqui nao se
toca em TraCI. So `sumolib`, lendo o `.net.xml` em disco. A rede e read-only: se
um par OD nao tem caminho, a resposta e "esse par nao existe", nunca "conserta a
rede".

O QUE ESTE MODULO RESOLVE
-------------------------
1. **Quem e fonte e quem e sorvedouro.** Nao ha lista hardcodada: fonte = edge
   normal sem `getIncoming()`, sorvedouro = edge normal sem `getOutgoing()`. Se o
   gerador da rede mudar a geometria dos cotos, isto acompanha sozinho.
2. **O peso de OD por capacidade** (`faixas x v_max`), que e o regime medido na
   Vila Olimpia (`smart-traffic-rl/.../scenarios.py::_large`): expoente 1. Com
   expoente >= 1,5 a malha grande COLAPSOU (producao -50%), entao o expoente e
   parametro do cenario e nao constante escondida aqui.
3. **Rotas alternativas por par OD** (Yen, k caminhos sem repeticao de edge). Duas
   razoes:
   - a demanda vai em ARQUIVO, entao a rota inicial e escolhida na geracao; se
     todo carro do mesmo par OD levasse a mesma rota, a carga concentraria antes
     de o `device.rerouting` (60 s) ter chance de espalhar;
   - a contagem de caminhos distintos e o numero que responde ao risco 3 do plano
     ("mao unica com 9 fontes/9 sorvedouros pode limitar demais a escolha de
     rota"). Melhor medi-lo do que supor.

Tudo aqui e DETERMINISTICO: listas ordenadas por id, nenhuma iteracao sobre
`dict` sem `sorted`, nenhuma dependencia de ordem de leitura do sumolib. O
invariante "mesma seed -> mesmo .rou.xml byte a byte" morre a qualquer descuido
disso.
"""
from __future__ import annotations

import heapq
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

if "SUMO_HOME" in os.environ:                                    # sumolib vive la
    sys.path.append(str(Path(os.environ["SUMO_HOME"]) / "tools"))
import sumolib  # noqa: E402

INFINITO = float("inf")


@dataclass(frozen=True)
class Caminho:
    """Uma rota completa fonte->sorvedouro, com o custo de fluxo livre em segundos."""

    edges: tuple[str, ...]
    custo_s: float

    @property
    def n_edges(self) -> int:
        return len(self.edges)


class Malha:
    """O `.net.xml` da rede aberta, visto como grafo de EDGES.

    Grafo de edges (e nao de nos) porque e nele que as proibicoes de conversao
    vivem: `edge.getOutgoing()` ja respeita os `<delete>` do arquivo de conexoes.
    Rotear no grafo de nos daria caminhos que o carro nao consegue fazer.
    """

    def __init__(self, net_file: str | Path):
        self.net_file = str(net_file)
        self._net = sumolib.net.readNet(self.net_file)

        normais = [e for e in self._net.getEdges() if e.getFunction() == ""]
        self.edges: tuple[str, ...] = tuple(sorted(e.getID() for e in normais))
        self._por_id = {e.getID(): e for e in normais}

        self.fontes: tuple[str, ...] = tuple(
            sorted(e.getID() for e in normais if not e.getIncoming()))
        self.sorvedouros: tuple[str, ...] = tuple(
            sorted(e.getID() for e in normais if not e.getOutgoing()))

        # tempo de travessia em fluxo livre (s) e capacidade (faixas x v_max)
        self.tempo_s: dict[str, float] = {}
        self.capacidade: dict[str, float] = {}
        self.comprimento_m: dict[str, float] = {}
        for e in normais:
            eid = e.getID()
            v = float(e.getSpeed())
            ln = float(e.getLength())
            self.tempo_s[eid] = ln / v if v > 0 else INFINITO
            self.capacidade[eid] = float(e.getLaneNumber()) * v
            self.comprimento_m[eid] = ln

        # sucessores, sempre em ordem de id (determinismo)
        self.saidas: dict[str, tuple[str, ...]] = {}
        for e in normais:
            viz = sorted(d.getID() for d in e.getOutgoing()
                         if d.getFunction() == "")
            self.saidas[e.getID()] = tuple(viz)

    # ------------------------------------------------------------------ metrica
    def vagas_por_faixa(self, slot_m: float) -> float:
        """Quantos carros PARADOS cabem na rede inteira, dado o slot do vType."""
        total = sum(self.comprimento_m[e] * self._por_id[e].getLaneNumber()
                    for e in self.edges)
        return total / slot_m

    # ------------------------------------------------------------------ Dijkstra
    def _dijkstra(self, origem: str, destino: str, *,
                  banidos: frozenset[str] = frozenset(),
                  prefixo: tuple[str, ...] = ()) -> Caminho | None:
        """Caminho mais barato origem->destino evitando `banidos` (edges) - o
        primitivo do Yen. `prefixo` so entra no resultado (o Yen ja o percorreu).

        Desempate por id do edge: dois caminhos de custo identico sempre saem na
        mesma ordem, em qualquer maquina.
        """
        if origem in banidos:
            return None
        dist = {origem: 0.0}
        anterior: dict[str, str] = {}
        fila: list[tuple[float, str]] = [(0.0, origem)]
        visto: set[str] = set()
        while fila:
            d, u = heapq.heappop(fila)
            if u in visto:
                continue
            visto.add(u)
            if u == destino:
                break
            for v in self.saidas[u]:
                if v in banidos or v in visto:
                    continue
                nd = d + self.tempo_s[v]
                if nd < dist.get(v, INFINITO) - 1e-12:
                    dist[v] = nd
                    anterior[v] = u
                    heapq.heappush(fila, (nd, v))
        if destino not in dist:
            return None
        seq = [destino]
        while seq[-1] != origem:
            seq.append(anterior[seq[-1]])
        seq.reverse()
        edges = prefixo + tuple(seq)
        return Caminho(edges, sum(self.tempo_s[e] for e in edges))

    def caminho_mais_curto(self, origem: str, destino: str) -> Caminho | None:
        return self._dijkstra(origem, destino)

    @lru_cache(maxsize=None)
    def k_caminhos(self, origem: str, destino: str, k: int = 4) -> tuple[Caminho, ...]:
        """Ate `k` caminhos sem repeticao de edge, do mais barato ao mais caro (Yen).

        Sem repeticao de edge (e nao so sem repeticao de no): numa malha de mao
        unica um "caminho" que passa duas vezes pela mesma via e uma volta ao
        quarteirao, nao uma alternativa.
        """
        primeiro = self._dijkstra(origem, destino)
        if primeiro is None:
            return ()
        aceitos: list[Caminho] = [primeiro]
        candidatos: list[tuple[float, tuple[str, ...]]] = []
        vistos = {primeiro.edges}
        while len(aceitos) < k:
            anterior = aceitos[-1]
            for i in range(len(anterior.edges) - 1):
                raiz = anterior.edges[: i + 1]
                banidos = set(raiz[:-1])
                for c in aceitos:
                    if c.edges[: i + 1] == raiz and len(c.edges) > i + 1:
                        banidos.add(c.edges[i + 1])
                alt = self._dijkstra(raiz[-1], destino, banidos=frozenset(banidos),
                                     prefixo=raiz[:-1])
                if alt is not None and alt.edges not in vistos:
                    vistos.add(alt.edges)
                    heapq.heappush(candidatos, (alt.custo_s, alt.edges))
            if not candidatos:
                break
            custo, edges = heapq.heappop(candidatos)
            aceitos.append(Caminho(edges, custo))
        return tuple(aceitos)

    # ---------------------------------------------------------------- diagnostico
    def conta_caminhos_simples(self, origem: str, destino: str,
                               teto: int = 2000) -> int:
        """Quantos caminhos SIMPLES (sem repetir edge) existem origem->destino.

        Diagnostico do risco 3 do plano. Para de contar em `teto` (a contagem
        explode exponencialmente e o numero que interessa e "e degenerado ou
        nao?", nao a contagem exata).
        """
        total = 0
        pilha = [(origem, {origem})]
        while pilha:
            atual, visitados = pilha.pop()
            if atual == destino:
                total += 1
                if total >= teto:
                    return teto
                continue
            for v in self.saidas[atual]:
                if v not in visitados:
                    pilha.append((v, visitados | {v}))
        return total

    def pesos_od(self, edges: tuple[str, ...], modo: str, pot: float) -> tuple[float, ...]:
        """Pesos de sorteio de origem/destino. `uniform` ou `capacity ** pot`."""
        if modo == "uniform":
            return tuple(1.0 for _ in edges)
        if modo == "capacity":
            return tuple(max(self.capacidade[e], 1e-6) ** pot for e in edges)
        raise ValueError("od_weight=%r desconhecido (use uniform|capacity)." % modo)
