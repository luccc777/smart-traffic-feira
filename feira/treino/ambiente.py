"""A amarração do treino com o cenário aberto — seeds, variantes e plano adversário.

Este módulo é o único lugar do pacote `feira.treino` que sabe QUAIS seeds servem
para quê. Ele existe porque a separação treino/validação/held-out é a diferença
entre um número que vale e um número que não vale, e ela não pode ficar espalhada
em `argparse` de três scripts.

AS TRÊS FAIXAS DE SEED — DISJUNTAS POR CONSTRUÇÃO
------------------------------------------------
    42-47     varredura/calibração — já entraram em ESCOLHA (o plano congelado
              saiu delas). Treinar aqui contamina a seleção do baseline.
    100-111   HELD-OUT. Só a validação final passa por elas, uma vez.
    200-223   TREINO (novas, geradas por `python -m feira.demanda`).
    230-233   VALIDAÇÃO durante o treino — é ela que escolhe o checkpoint, então
              ela é "gasta" por construção e não pode ser held-out.

`checa_disjuncao()` transforma isso em erro alto: um `--seeds` de treino que
encoste em 100-111 aborta em vez de produzir um resultado bonito e inválido.

O ADVERSÁRIO É O `coordenado_c60`, NÃO O TIMER DE 27 s
-----------------------------------------------------
`docs/BASELINE_ABERTO.md` §4.5 congelou o plano; o timer uniforme é o adversário
fraco que o projeto se comprometeu a aposentar. Toda avaliação daqui passa pelo
`ControladorCoordenado` carregando `sumo/aberta/planos/coordenado_c60.json`.

VARIANTE DE ESPAÇO DE AÇÃO — O QUE PODE E O QUE NÃO PODE
--------------------------------------------------------
`cenario_variante()` devolve uma CÓPIA do `Cenario` com outra `RestricoesFase`.
Isso é para o A/B do agente A6 (5/7 contra 10/10, `max_red`), e a cópia é local:
`RESTRICOES_ABERTA` continua sendo o default do C1. Se 10/10 vencer, quem muda o
contrato é o coordenador — o experimento só reporta o número.

E a comparação continua honesta porque a `Chave` (C5) carimba a assinatura do
espaço de ação: uma política medida em 10/10 só pareia com um baseline medido em
10/10. Rodar o `coordenado_c60` sob a grade da variante é obrigatório, e é o que
`feira.treino.avalia` faz.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..contratos import Cenario, RestricoesFase, cenario

__all__ = [
    "PLANO_BASELINE",
    "RAIZ",
    "SEEDS_HELD_OUT",
    "SEEDS_SELECAO",
    "SEEDS_TREINO",
    "SEEDS_VALIDACAO",
    "SeedContaminada",
    "cenario_variante",
    "checa_disjuncao",
    "seeds_de_texto",
]

RAIZ = Path(__file__).resolve().parents[2]

# As 12 held-out do projeto. NUNCA entram em treino nem em seleção.
SEEDS_HELD_OUT = tuple(range(100, 112))
# As 6 de varredura/calibração: o plano coordenado foi escolhido com elas.
SEEDS_SELECAO = tuple(range(42, 48))
# As novas, geradas para o A6.
SEEDS_TREINO = tuple(range(200, 224))
SEEDS_VALIDACAO = (230, 231, 232, 233)

PLANO_BASELINE = str(RAIZ / "sumo" / "aberta" / "planos" / "coordenado_c60.json")


class SeedContaminada(ValueError):
    """Uma seed de treino/validação encostou nas held-out (ou nas de seleção).

    Não há conserto em tempo de execução: um treino que viu a seed 103 não pode
    ser validado na seed 103, e o número que sairia daí não mede generalização.
    """


def checa_disjuncao(seeds_treino, seeds_validacao=()) -> None:
    """Levanta se treino/validação tocarem as held-out, as de seleção, ou uma à outra."""
    treino = set(int(s) for s in seeds_treino)
    validacao = set(int(s) for s in seeds_validacao)
    proibidas = set(SEEDS_HELD_OUT) | set(SEEDS_SELECAO)
    for nome, conjunto in (("treino", treino), ("validação", validacao)):
        invasoras = sorted(conjunto & proibidas)
        if invasoras:
            raise SeedContaminada(
                "seed(s) de %s dentro das reservadas: %s. 100-111 são held-out "
                "(validação final) e 42-47 escolheram o plano congelado — treinar "
                "em qualquer uma delas invalida o critério de aceite."
                % (nome, invasoras))
    comuns = sorted(treino & validacao)
    if comuns:
        raise SeedContaminada(
            "seed(s) em treino E validação ao mesmo tempo: %s. A validação escolhe o "
            "checkpoint; se ela for uma seed de treino, escolhe pelo que foi decorado."
            % comuns)


def seeds_de_texto(txt: str) -> tuple[int, ...]:
    """`"200-223"` ou `"200,201,205"` (ou os dois misturados) -> tupla de int."""
    saida: list[int] = []
    for pedaco in str(txt).split(","):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        if "-" in pedaco[1:]:
            a, b = pedaco.split("-", 1)
            saida.extend(range(int(a), int(b) + 1))
        else:
            saida.append(int(pedaco))
    return tuple(saida)


def cenario_variante(*, decision_interval: int | None = None, min_green: int | None = None,
                     max_red: float | None = None) -> Cenario:
    """Uma cópia do `aberta.maquete` com outro espaço de ação. `None` = o default do C1.

    O amarelo NÃO é parametrizável de propósito: `sim.environment.constants
    .YELLOW_DUR` é literal 3, sem env var, e `Cenario.divergencias_congeladas()`
    levanta se o cenário pedir outra coisa. Um `yellow` configurável aqui seria
    mentira silenciosa.
    """
    base = cenario("aberta.maquete")
    r = base.restricoes
    nova = RestricoesFase(
        decision_interval=int(decision_interval if decision_interval is not None
                              else r.decision_interval),
        min_green=int(min_green if min_green is not None else r.min_green),
        yellow=r.yellow,
        max_red=float(max_red if max_red is not None else r.max_red),
    )
    if nova == r:
        return base
    return replace(base, restricoes=nova)
