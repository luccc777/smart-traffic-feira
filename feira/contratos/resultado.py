"""C5 — `Resultado`: o que uma corrida mediu, e o que precisa bater para comparar.

Duas coisas estruturais moram aqui, e as duas vêm da auditoria do sistema atual
(docs/AUDITORIA_COMPARACAO.md, agente A2):

1. **`Chave` — comparar exige a MESMA condição.** Hoje a projeção compara o
   `completed` acumulado dos dois braços sem olhar o `t` de cada um; os dois
   rodam em processos separados, cada um com seu deadline de parede, e quando
   um atrasa ele reajusta o próprio relógio em silêncio. Qualquer deriva entra
   direto na vantagem de vazão. Aqui `comparar()` LEVANTA se as chaves diferem:
   cenário, seed, janela e hash da demanda têm que ser idênticos. O bug não é
   corrigido — ele fica impossível de reintroduzir.

2. **`conservacao` no lugar de `coherence_gap`.** O detector de artefato de
   sobrevivência do projeto (`sim.evaluation.metrics.coherence_gap`) assume
   FROTA FECHADA — `esperado ≈ N × T / tempo_medio`. Numa rede aberta não há N.
   O substituto é uma identidade de balanço que vale sempre:

       inseridos = entregues + ativos_no_fim        (+ perdidos)

   Se não fecha, veículo sumiu (teleporte, colisão, remoção) e as médias estão
   contando uma população que não é a que entrou. E o backlog de inserção entra
   como métrica de primeira classe pelo mesmo motivo que o `coherence_gap`
   existia: **um controlador que trava a borda "vence" por não deixar carro
   entrar** — a fila fica ótima e o tempo médio dos sobreviventes também.

`tempo_medio_no_sistema` também é resposta ao artefato: `tempo_medio_entregue`
só conta quem CHEGOU, então congestionamento catastrófico melhora a métrica.
O tempo no sistema inclui quem ficou preso (censurado no fim da janela), e por
isso piora quando a rede trava — que é o comportamento que se quer de uma
métrica.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace


class ChavesIncompativeis(ValueError):
    """Tentativa de comparar dois `Resultado` medidos em condições diferentes.

    Não há conserto: comparar cenários/seeds/janelas diferentes é comparar coisas
    diferentes. Rode de novo com a mesma `Chave`.
    """


@dataclass(frozen=True, order=True)
class Janela:
    """Intervalo de tempo SIMULADO em que as métricas contam. Fora dela, nada conta.

    O warm-up fica FORA por definição: `t0` é o instante em que o braço assume o
    controle, e antes disso todos os braços rodaram o mesmo plano de aquecimento.
    """

    t0: float
    t1: float

    def __post_init__(self) -> None:
        if not (self.t1 > self.t0):
            raise ValueError("janela vazia ou invertida: t0=%r t1=%r" % (self.t0, self.t1))

    @property
    def duracao(self) -> float:
        return self.t1 - self.t0

    def contem(self, t: float) -> bool:
        return self.t0 <= t < self.t1


@dataclass(frozen=True)
class Chave:
    """A condição experimental. Dois resultados só são comparáveis se ela bater.

    `demanda_sha` fecha a porta do tráfego: cenário e seed iguais com um gerador
    de demanda diferente produzem trânsito diferente, e sem o hash isso passaria
    despercebido.

    `restricoes` fecha a porta do ESPAÇO DE AÇÃO, e essa porta estava aberta.
    Duas corridas com `decision_interval` ou `min_green` diferentes descrevem
    conjuntos de políticas diferentes — o verde mínimo alcançável vai de 7 s a
    17 s entre os dois regimes deste projeto. Sem este campo elas tinham chaves
    idênticas e `comparar()` passava, que é exatamente o que a comparação
    publicada faz quando alguém troca `ST_MIN_GREEN` entre um braço e outro.
    Use `Chave.de(...)`, que a preenche a partir do `Cenario`.
    """

    cenario: str
    seed: int
    janela: Janela
    demanda_sha: str
    restricoes: str          # assinatura compacta: "di10/vm10/am3/mr0"

    @staticmethod
    def de(cenario, seed: int, janela: Janela, demanda_sha: str) -> "Chave":
        """Constrói a chave a partir de um `Cenario` (C1) — a forma abençoada.

        Montar `Chave` na mão continua possível, mas quem faz isso assume a
        responsabilidade de preencher `restricoes` com a assinatura certa.
        """
        return Chave(cenario=cenario.chave, seed=int(seed), janela=janela,
                     demanda_sha=demanda_sha,
                     restricoes=cenario.restricoes.assinatura)

    def compativel(self, outra: "Chave") -> bool:
        return self == outra

    def descreve(self) -> str:
        return "%s seed=%d janela=[%g,%g) demanda=%s acao=%s" % (
            self.cenario, self.seed, self.janela.t0, self.janela.t1,
            self.demanda_sha[:12], self.restricoes)


@dataclass(frozen=True)
class Resultado:
    """O que um braço mediu numa janela. Imutável — é dado, não é estado."""

    chave: Chave
    controlador: str            # "rl:aberta_v3" | "timer:coordenado_c70" | "humano:anon"

    # --- produção (MAIOR é melhor) ---
    entregues: int              # viagens concluídas DENTRO da janela

    # --- tempo (MENOR é melhor) ---
    tempo_medio_entregue: float   # média só de quem chegou -> sofre viés de sobrevivência
    tempo_medio_no_sistema: float # inclui quem ficou preso (censurado em t1) -> não sofre

    # --- congestionamento (MENOR é melhor) ---
    fila_media: float           # média por sim-step do total de parados na rede
    espera_media: float

    # --- balanço de veículos: o detector de artefato ---
    inseridos: int              # entraram na rede dentro da janela
    ativos_fim: int             # ainda rodando em t1
    ativos_inicio: int          # já rodando em t0 (a rede não começa vazia após warm-up)
    backlog_insercao: int       # agendados para partir e ainda NÃO inseridos em t1
    perdidos: int = 0           # teleporte/colisão/remoção — deveria ser 0

    travou: bool = False        # o braço declarou travamento (critério da Arena)

    # -------------------------------------------------------------- balanço
    @property
    def conservacao(self) -> int:
        """`(ativos_inicio + inseridos) - entregues - ativos_fim - perdidos`.

        Zero = todo carro que estava ou entrou ou saiu pela porta ou continua lá.
        Diferente de zero = veículo evaporou, e as médias estão mentindo.
        """
        return (self.ativos_inicio + self.inseridos) - self.entregues - self.ativos_fim - self.perdidos

    @property
    def vazao_por_min(self) -> float:
        return self.entregues / (self.chave.janela.duracao / 60.0)

    @property
    def lacuna_sobrevivencia(self) -> float:
        """% por que o tempo CENSURADO excede o tempo dos ENTREGUES.

        O detector que de fato funciona, e a correção de um erro de desenho meu:
        o balanço de conservação + backlog que este contrato propunha é **cego na
        rede fechada** — conservação fecha em zero e o backlog é zero mesmo com a
        malha parada, porque o carro não some, ele só nunca chega. Medido
        (`docs/AUDITORIA_COMPARACAO.md` §10.1): −1,4% a −1,1% em política sã,
        **+5884% a +7528%** com o farol congelado.

        Model-free de propósito: não usa `N`, não supõe frota fechada nem regime
        estacionário — por isso vale nos dois cenários, ao contrário do
        `coherence_gap`, que errar `N` em 27% move 35 pontos percentuais.

        `inf` quando nada foi entregue e ainda há gente presa; `nan` quando não
        há o que medir.
        """
        if self.entregues <= 0:
            return math.inf if self.ativos_fim > 0 else math.nan
        if self.tempo_medio_entregue <= 0.0:
            return math.nan
        return ((self.tempo_medio_no_sistema - self.tempo_medio_entregue)
                / self.tempo_medio_entregue * 100.0)

    def sane(self, *, tol_conservacao: int = 0, backlog_max_frac: float = 0.10,
             perdidos_max_frac: float = 0.005) -> tuple[bool, str]:
        """Checagem ESTRUTURAL. Devolve `(ok, motivo)` — motivo vazio quando ok.

        Só o que vale em qualquer regime: o balanço de veículos fecha, ninguém
        evaporou, a borda não foi estrangulada, e a Arena não declarou travamento.

        POR QUE A LACUNA DE SOBREVIVÊNCIA NÃO ESTÁ AQUI, embora seja o detector
        que de fato pega gridlock: o limiar dela é **dependente do regime**. Os
        +5884% do farol congelado e os −1,1% da política sã foram medidos em
        janelas de 1800–10800 s; numa janela de 120 s (a rodada do jogo) metade
        da população está censurada por construção, e a mesma conta acusa uma
        corrida perfeitamente sã. Um limiar fixo aqui produziria falso positivo
        silencioso — o oposto do que este contrato existe para fazer.

        Ela mora, com limiar declarado pelo chamador, em
        `feira.metricas.sinais_de_travamento`; a Arena a consulta e é ela quem
        carimba `travou`. `Resultado.lacuna_sobrevivencia` fica exposta aqui como
        GRANDEZA (isso é regime-independente), só não vira veredito.

        `backlog_max_frac`: fração do agendado que pode ficar sem entrar. Acima
        disso o braço está estrangulando a borda, e o resultado não é comparável
        com um que deixou o tráfego entrar — a versão de rede aberta do artefato
        de sobrevivência.

        `perdidos_max_frac`: veículo perdido (teleporte, colisão, remoção) fecha
        a conservação em zero quando é CONTABILIZADO, então passava despercebido.
        Perder veículo continua sendo corrida inválida.
        """
        if self.travou:
            return False, "travamento declarado pela Arena"
        if abs(self.conservacao) > tol_conservacao:
            return False, ("balanço de veículos não fecha: conservacao=%d "
                           "(ativos_inicio=%d + inseridos=%d - entregues=%d - ativos_fim=%d "
                           "- perdidos=%d)" % (self.conservacao, self.ativos_inicio,
                                               self.inseridos, self.entregues,
                                               self.ativos_fim, self.perdidos))
        agendados = self.inseridos + self.backlog_insercao
        if agendados and (self.backlog_insercao / agendados) > backlog_max_frac:
            return False, ("backlog de inserção %d/%d = %.1f%% > %.1f%%: a borda está "
                           "estrangulada e a métrica premia isso"
                           % (self.backlog_insercao, agendados,
                              100.0 * self.backlog_insercao / agendados,
                              100.0 * backlog_max_frac))
        vistos = self.ativos_inicio + self.inseridos
        if vistos and (self.perdidos / vistos) > perdidos_max_frac:
            return False, ("perdidos %d de %d = %.2f%% > %.2f%%: veículo sumiu da rede "
                           "(teleporte/colisão/remoção) e o balanço fecha assim mesmo, "
                           "porque ele foi CONTABILIZADO"
                           % (self.perdidos, vistos, 100.0 * self.perdidos / vistos,
                              100.0 * perdidos_max_frac))
        if self.entregues == 0:
            return False, "nenhuma viagem concluída na janela"
        return True, ""

    def com(self, **campos) -> "Resultado":
        """Cópia com campos trocados (os testes usam; produção raramente)."""
        return replace(self, **campos)


# -------------------------------------------------------------------- comparação
def _reducao(base: float, novo: float) -> float:
    """% de redução de `novo` vs `base` — positivo = novo MENOR = melhor."""
    return ((base - novo) / base * 100.0) if base else 0.0


def _ganho(base: float, novo: float) -> float:
    """% de ganho de `novo` vs `base` — positivo = novo MAIOR = melhor."""
    return ((novo - base) / base * 100.0) if base else 0.0


# Direção de cada métrica: True = maior é melhor. Ter isto num lugar só é o que
# impede o slide "+20,8% de fila" (que existiu neste projeto e queria dizer o
# contrário do que parecia).
DIRECAO = {
    "entregues": True,
    "vazao_por_min": True,
    "tempo_medio_entregue": False,
    "tempo_medio_no_sistema": False,
    "fila_media": False,
    "espera_media": False,
}


@dataclass(frozen=True)
class Comparacao:
    """Deltas de `novo` contra `base`. Cada campo é POSITIVO quando `novo` é melhor."""

    chave: Chave
    base: str
    novo: str
    deltas: dict[str, float]
    base_sane: bool
    novo_sane: bool
    aviso: str = ""

    @property
    def novo_vence_em_tudo(self) -> bool:
        return bool(self.deltas) and all(v > 0 for v in self.deltas.values())

    def resumo(self) -> str:
        partes = ["%s %+.1f%%" % (k, v) for k, v in sorted(self.deltas.items())]
        return "%s vs %s | %s" % (self.novo, self.base, " · ".join(partes))


def comparar(base: Resultado, novo: Resultado) -> Comparacao:
    """Compara dois braços NA MESMA CONDIÇÃO. Levanta se as chaves diferem.

    Esta função é o ponto único onde uma vantagem percentual nasce neste projeto.
    Se aparecer um `(a - b) / b * 100` em qualquer outro lugar, é bug.
    """
    if not base.chave.compativel(novo.chave):
        raise ChavesIncompativeis(
            "condições diferentes — nada a comparar.\n  base: %s\n  novo: %s"
            % (base.chave.descreve(), novo.chave.descreve())
        )
    deltas: dict[str, float] = {}
    for campo, maior_melhor in DIRECAO.items():
        b = float(getattr(base, campo))
        n = float(getattr(novo, campo))
        if math.isnan(b) or math.isnan(n):
            continue
        deltas[campo] = _ganho(b, n) if maior_melhor else _reducao(b, n)

    ok_b, motivo_b = base.sane()
    ok_n, motivo_n = novo.sane()
    aviso = " | ".join(m for m in ("base: " + motivo_b if motivo_b else "",
                                   "novo: " + motivo_n if motivo_n else "") if m)
    return Comparacao(chave=base.chave, base=base.controlador, novo=novo.controlador,
                      deltas=deltas, base_sane=ok_b, novo_sane=ok_n, aviso=aviso)


def agrega_por_seed(resultados: list[Resultado]) -> dict[str, float]:
    """Média entre seeds das métricas numéricas. Só campos numéricos; `travou` vira contagem.

    Não faz t-test: significância é do agente A2 (`feira/estatistica.py`), que precisa
    das listas pareadas, não das médias.
    """
    if not resultados:
        return {}
    out: dict[str, float] = {}
    for campo in DIRECAO:
        vals = [float(getattr(r, campo)) for r in resultados]
        out[campo] = sum(vals) / len(vals)
    out["travamentos"] = float(sum(1 for r in resultados if r.travou))
    out["n_seeds"] = float(len(resultados))
    return out
