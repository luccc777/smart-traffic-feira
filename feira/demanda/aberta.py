"""`GeradorDemandaAberta` - a demanda do cenario `aberta.maquete` (contrato C2).

Escreve um `.rou.xml` COMPLETO por seed: veiculo a veiculo, com a rota inteira
escrita no arquivo. Nada de `<flow>`, nada de `<trip>` sem rota.

POR QUE ROTA EXPLICITA, E NAO `<trip>`
-------------------------------------
Um `<trip from= to=>` faz o SUMO rotear NO INSTANTE DA INSERCAO, usando os tempos
de viagem correntes - que dependem do controlador de semaforo. A rota inicial
deixaria de ser propriedade da DEMANDA e passaria a ser propriedade do BRACO, e a
comparacao pareada perde exatamente a garantia que o contrato C2 existe para dar.
Com a rota escrita no arquivo, os tres bracos partem da MESMA rota; o
`device.rerouting` (60 s) adapta depois, e a adaptacao e o comportamento que se
quer medir.

O INVARIANTE (e o que ele custa)
--------------------------------
Mesma seed -> mesmo arquivo, byte a byte. Na pratica isso proibe:
  - iterar `dict`/`set` sem `sorted` (ordem de insercao vaza para o arquivo);
  - `random.choices`/`expovariate` sem saber quantos numeros consomem (aqui a
    exponencial e escrita na mao a partir de `random()`, um numero por sorteio);
  - `repr` de float (varia com a plataforma) - tudo sai por `%.2f`/`%.4f`;
  - semear o RNG com tupla ou objeto (Python usa `hash()`, que e ALEATORIZADO
    entre processos). Aqui o seed e int e so int.

DE ONDE VEM O REGIME (credito)
------------------------------
`depart_lane="best"`, `od_weight="capacity"` com expoente 1 e `reroute_period=60`
sao os parametros MEDIDOS na Vila Olimpia, em
`smart-traffic-rl/neural_network/environment/scenarios.py::_large`:
  - `departLane` default ("first") fazia todo carro nascer na faixa 0 - avenida de
    3 faixas escoando em fila unica; medido: producao +119%;
  - `od_weight=capacity` pow=1: producao +7%, parados -4 pp. **pow >= 1,5
    COLAPSA** (producao -50%), por isso o expoente e do cenario;
  - sem `reroute_period` a malha travava em 98% parados.
"""
from __future__ import annotations

import math
import random
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from ..contratos import (
    Cenario,
    ManifestoDemanda,
    caminho_manifesto,
    sha256_arquivo,
)
from .config_seed import (
    caminho_config_seed,
    confere_config_seed,
    escreve_config_seed,
)
from .malha import Malha

VERSAO = "aberta-1.1"

# --- o regime CALIBRADO (docs/CALIBRACAO_ABERTA.md) ----------------------------
# 3500 veh/h e a MAIOR taxa que a malha sustenta ESTAVEL nas 6 seeds (42-47) por
# 7200 s - o DOBRO da janela de avaliacao: 156-167 carros ativos, 38,2% parados,
# 19,9 km/h equivalentes da rede real, backlog de insercao <= 6, populacao sem
# deriva.
#
# Por que 7200 s e nao 3600 s: a 3800 veh/h as 6 seeds passam folgadas em 3600 s
# (190-212 ativos, backlog <= 6) e DUAS DELAS travam quando a run continua ate
# 7200 s (552 e 582 ativos, 70% parados, backlog 556 e 798). Perto da capacidade
# a malha e metaestavel: uma janela de 1 h nao ve a fila crescendo devagar. 3600
# ja quebra 1 das 3 seeds testadas em 7200 s; 3500 nao quebra nenhuma das 6.
#
# O numero NAO foi escolhido por dar um % parados bonito: os 38,2% que saem dele
# estao ABAIXO dos 45-55% que o plano pedia, e o motivo esta medido (o piso de
# fluxo livre desta rede ja e 38%: e o custo do proprio semaforo). Ver §3.5 e §7
# do documento de calibracao.
VEH_POR_HORA = 3500.0
# 5400 s = warm-up medido (300) + janela de avaliacao (3600) + 1500 s de folga.
# E parametro do MANIFESTO: mudar aqui muda o sha256 de toda demanda ja gerada.
# (Propriedade util: o horizonte so ACRESCENTA veiculos no fim - a demanda de
# horizonte menor e prefixo exato da de horizonte maior, mesma seed e mesma taxa.)
HORIZONTE_S = 5400.0      # s de demanda gerada; cobre warm-up + janela de 3600 s
MIN_EDGES = 4             # rota minima: os 2 cotos + 2 edges internos (>=2 cruzamentos)
K_ROTAS = 4               # alternativas por par OD (Yen)
GAMMA_ROTA = 4.0          # dispersao da escolha de rota: w_i = exp(-g*(c_i-c_0)/c_0)
DEPART_SPEED = "max"      # entra na velocidade segura mais alta; sem isso todo
                          # coto vira uma partida parada e a insercao estrangula
PREFIXO_VEIC = "car"      # = sim.environment.constants.VEHICLE_PREFIX
TIPO_VEIC = "DEFAULT_VEHTYPE"


def _amostra(cum: list[float], u: float) -> int:
    """Indice sorteado de uma distribuicao discreta dada a acumulada normalizada."""
    return min(bisect_right(cum, u), len(cum) - 1)


def _acumulada(pesos: list[float]) -> list[float]:
    total = math.fsum(pesos)
    acc, s = [], 0.0
    for p in pesos:
        s += p / total
        acc.append(s)
    return acc


@dataclass(frozen=True)
class ParOD:
    origem: str
    destino: str
    rotas: tuple[tuple[str, ...], ...]   # ate K_ROTAS, da mais barata p/ a mais cara
    pesos_rota: tuple[float, ...]        # acumulada normalizada da escolha de rota
    peso: float                          # peso do PAR (capacidade_o x capacidade_d)


class GeradorDemandaAberta:
    """Gera `.rou.xml` + manifesto para o cenario `aberta.maquete` (contrato C2).

    `veh_por_hora` e o unico numero que a calibracao move: e ele que fixa a
    POPULACAO ATIVA de regime (Lei de Little, L = lambda x W). O plano e explicito
    em nao calibrar por taxa fixa escolhida a dedo - foi o que prendeu a Vila
    Olimpia em fluxo livre - e sim por populacao ativa ALVO; este parametro e o
    que a busca da calibracao ajusta ate o alvo bater (ver
    `sumo/aberta/calibra.py` e `docs/CALIBRACAO_ABERTA.md`).

    `net_file=None` (o normal) significa "a rede do `Cenario` que chegar no
    `gera()`". O fallback para a rede canonica da rede aberta existe por um motivo
    concreto: a suite de conformidade da C2 exercita o contrato com um `Cenario`
    descartavel apontando para um `.net.xml` que nao existe (so quer provar o
    invariante do hash). Sem o fallback o gerador real nao poderia entrar naquela
    suite parametrizada.
    """

    versao = VERSAO

    def __init__(self, veh_por_hora: float = VEH_POR_HORA, *,
                 horizonte_s: float = HORIZONTE_S,
                 net_file: str | Path | None = None,
                 min_edges: int = MIN_EDGES,
                 k_rotas: int = K_ROTAS,
                 gamma_rota: float = GAMMA_ROTA,
                 depart_speed: str = DEPART_SPEED,
                 escreve_cfg: bool = True):
        if veh_por_hora <= 0:
            raise ValueError("veh_por_hora deve ser > 0 (veio %r)" % veh_por_hora)
        if horizonte_s <= 0:
            raise ValueError("horizonte_s deve ser > 0 (veio %r)" % horizonte_s)
        self.veh_por_hora = float(veh_por_hora)
        self.horizonte_s = float(horizonte_s)
        self.min_edges = int(min_edges)
        self.k_rotas = int(k_rotas)
        self.gamma_rota = float(gamma_rota)
        self.depart_speed = str(depart_speed)
        # `escreve_cfg=False` SO para a bancada de calibracao (sumo/aberta/calibra.py),
        # que gera demanda descartavel em varias taxas apontando para o MESMO
        # `Cenario` canonico e passa `-r` na linha de comando. Sem esta valvula ela
        # sobrescreveria `config/maquete_aberta_s42.sumocfg` para apontar para a
        # demanda de 3900 veh/h, e a proxima corrida da Arena mediria essa - em
        # silencio, que e o bug que o config_seed.py inteiro existe para matar. O
        # default e o seguro; ver tambem `confere_config_seed`, que denuncia se
        # alguem esquecer.
        self.escreve_cfg = bool(escreve_cfg)
        self._net_file = str(net_file) if net_file else None
        self._cache_od: dict[tuple[str, str, float], tuple[list[ParOD], list[float]]] = {}

    # ------------------------------------------------------------------ rede/OD
    def _rede(self, cenario: Cenario) -> str:
        if self._net_file:
            return self._net_file
        if Path(cenario.net_file).exists():
            return cenario.net_file
        from ..contratos import cenario as _resolve
        alvo = _resolve("aberta.maquete").net_file
        if not Path(alvo).exists():
            raise FileNotFoundError(
                "nem %s nem a rede canonica %s existem. Rode "
                "`sumo/aberta/build_rede_aberta.py` antes de gerar demanda."
                % (cenario.net_file, alvo))
        return alvo

    def _pares(self, cenario: Cenario) -> tuple[list[ParOD], list[float], Malha]:
        """Os pares OD validos, seus pesos e as rotas alternativas de cada um.

        Nao depende da seed: e propriedade da REDE + do regime de OD. Cacheado por
        (rede, od_weight, pow) para nao pagar Yen 81 vezes por seed.
        """
        net = self._rede(cenario)
        chave = (net, cenario.od_weight, cenario.od_weight_pow)
        malha = getattr(self, "_malha", None)
        if malha is None or malha.net_file != net:
            malha = Malha(net)
            self._malha = malha
        if chave in self._cache_od:
            pares, cum = self._cache_od[chave]
            return pares, cum, malha

        w_fonte = dict(zip(malha.fontes,
                           malha.pesos_od(malha.fontes, cenario.od_weight,
                                          cenario.od_weight_pow)))
        w_sorv = dict(zip(malha.sorvedouros,
                          malha.pesos_od(malha.sorvedouros, cenario.od_weight,
                                         cenario.od_weight_pow)))
        pares: list[ParOD] = []
        for o in malha.fontes:                       # ja ordenados por id
            for d in malha.sorvedouros:
                rotas = malha.k_caminhos(o, d, self.k_rotas)
                if not rotas or rotas[0].n_edges < self.min_edges:
                    continue                          # inalcancavel ou trivial
                c0 = rotas[0].custo_s
                pesos = [math.exp(-self.gamma_rota * (r.custo_s - c0) / c0)
                         for r in rotas]
                pares.append(ParOD(
                    origem=o, destino=d,
                    rotas=tuple(r.edges for r in rotas),
                    pesos_rota=tuple(_acumulada(pesos)),
                    peso=w_fonte[o] * w_sorv[d],
                ))
        if not pares:
            raise RuntimeError(
                "nenhum par OD valido em %s com min_edges=%d. A rede mudou?"
                % (net, self.min_edges))
        cum = _acumulada([p.peso for p in pares])
        self._cache_od[chave] = (pares, cum)
        return pares, cum, malha

    # ------------------------------------------------------------------ contrato
    def gera(self, cenario: Cenario, seed: int, *, forcar: bool = False) -> ManifestoDemanda:
        rou = cenario.rou_file(seed)
        man_path = caminho_manifesto(cenario, seed)
        if not forcar and rou.exists() and man_path.exists():
            man = ManifestoDemanda.carrega(man_path)
            try:
                man.confere(rou)
                # O cfg da seed nao vai versionado: pode faltar mesmo com o
                # `.rou.xml` intacto (clone novo, `git clean`). Recriar e barato e
                # deterministico; deixar faltando e o que fazia a Arena cair no
                # canonico e rodar OUTRA demanda.
                if self.escreve_cfg and not caminho_config_seed(cenario, seed).exists():
                    escreve_config_seed(cenario, seed, rou)
                return man
            except Exception:
                pass                                  # divergiu do manifesto: regera

        pares, cum, malha = self._pares(cenario)
        texto, n, t0, t1 = self._render(cenario, seed, pares, cum)
        rou.parent.mkdir(parents=True, exist_ok=True)
        rou.write_text(texto, encoding="utf-8", newline="\n")
        cfg = escreve_config_seed(cenario, seed, rou) if self.escreve_cfg else None

        man = ManifestoDemanda(
            cenario=cenario.chave,
            seed=int(seed),
            versao_gerador=self.versao,
            sha256=sha256_arquivo(rou),
            n_veiculos=n,
            t_primeiro=t0,
            t_ultimo=t1,
            parametros={
                "veh_por_hora": self.veh_por_hora,
                "horizonte_s": self.horizonte_s,
                "od_weight": cenario.od_weight,
                "od_weight_pow": cenario.od_weight_pow,
                "depart_lane": cenario.depart_lane,
                "depart_speed": self.depart_speed,
                "min_edges": self.min_edges,
                "k_rotas": self.k_rotas,
                "gamma_rota": self.gamma_rota,
                "n_pares_od": len(pares),
                "net_file": Path(malha.net_file).name,
                "net_sha256": sha256_arquivo(Path(malha.net_file)),
                # O cfg da seed e o que faz a demanda SEGUIR a seed (o TrafficEnv
                # nao aceita route-files). Carimbar o sha dele aqui e o que permite
                # `manifesto()` recusar um cfg trocado ou ausente.
                "sumocfg_seed": cfg.name if cfg else None,
                "sumocfg_seed_sha256": sha256_arquivo(cfg) if cfg else None,
            },
        )
        man.salva(man_path)
        return man

    def manifesto(self, cenario: Cenario, seed: int) -> ManifestoDemanda:
        """Le o manifesto versionado - e CONFERE o cfg da seed antes de devolver.

        E aqui que a checagem pega o chamador cedo: todo braco precisa do
        manifesto (a `Chave` da C5 carrega o `demanda_sha`), e nenhum deles sobe
        o SUMO sem passar por aqui. Se o cfg da seed sumiu ou aponta para outra
        demanda, o erro sai ANTES da corrida - nao como um numero errado depois.
        """
        man = ManifestoDemanda.carrega(caminho_manifesto(cenario, seed))
        confere_config_seed(cenario, seed, man.parametros.get("sumocfg_seed_sha256"))
        return man

    # ------------------------------------------------------------------- render
    def _render(self, cenario: Cenario, seed: int, pares: list[ParOD],
                cum: list[float]) -> tuple[str, int, float, float]:
        rng = random.Random(int(seed))
        lam = self.veh_por_hora / 3600.0
        saida = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!-- GERADO por feira.demanda.GeradorDemandaAberta (%s).' % self.versao,
            '     cenario=%s seed=%d veh_por_hora=%.1f horizonte=%.0fs'
            % (cenario.chave, seed, self.veh_por_hora, self.horizonte_s),
            '     od_weight=%s pow=%g | departLane=%s departSpeed=%s | min_edges=%d'
            % (cenario.od_weight, cenario.od_weight_pow, cenario.depart_lane,
               self.depart_speed, self.min_edges),
            '     Chegadas: processo de Poisson. Rota escrita por extenso: os tres',
            '     bracos leem literalmente este arquivo. NAO EDITAR A MAO (o',
            '     manifesto guarda o sha256 e denuncia). -->',
            '<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">',
        ]
        t = 0.0
        n = 0
        t0 = t1 = 0.0
        while True:
            # exponencial escrita na mao: UM random() por chegada, sempre.
            t += -math.log(1.0 - rng.random()) / lam
            if t > self.horizonte_s:
                break
            par = pares[_amostra(cum, rng.random())]
            rota = par.rotas[_amostra(list(par.pesos_rota), rng.random())]
            vid = "%s%05d" % (PREFIXO_VEIC, n)
            saida.append(
                '    <vehicle id="%s" type="%s" depart="%.2f" departLane="%s"'
                ' departSpeed="%s">' % (vid, TIPO_VEIC, t, cenario.depart_lane,
                                        self.depart_speed))
            saida.append('        <route edges="%s"/>' % " ".join(rota))
            saida.append('    </vehicle>')
            if n == 0:
                t0 = round(t, 2)
            t1 = round(t, 2)
            n += 1
        saida.append("</routes>")
        return "\n".join(saida) + "\n", n, t0, t1
