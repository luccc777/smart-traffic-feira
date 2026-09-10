"""Adversários roteirizados — as políticas "humanas" que o A8 roda em massa.

O pacote responde uma pergunta só: **qual a chance de um visitante vencer a RL
numa rodada de 120 s?** — e responde sem público, rodando jogadores scriptados
headless pelo MESMO protocolo da rodada.

Nada é importado ansiosamente aqui: `bancada` puxa `sim`/`traci` (e o
`Cenario.aplicar()` que tem de vir antes deles), então importar
`feira.adversarios` num teste sem SUMO continua barato.
"""
from .politicas import (
    CATALOGO,
    Aleatoria,
    Arterial,
    GulosaFase,
    GulosaFila,
    Leitura,
    Limite,
    Martelo,
    Parada,
    Periodica,
    Roteirista,
    Ruido,
    Sabotador,
    de_texto,
    leitura_de,
    verde_realizado_s,
)

__all__ = [
    "CATALOGO",
    "Aleatoria",
    "AdversarioHumano",
    "Arterial",
    "FonteRoteirizada",
    "GulosaFase",
    "GulosaFila",
    "Leitura",
    "Limite",
    "Martelo",
    "Parada",
    "Periodica",
    "Roteirista",
    "Ruido",
    "Sabotador",
    "de_texto",
    "leitura_de",
    "verde_realizado_s",
]


def __getattr__(nome):
    """`AdversarioHumano`/`FonteRoteirizada` sob demanda: eles puxam os controladores."""
    if nome in ("AdversarioHumano", "FonteRoteirizada"):
        from . import fonte

        return getattr(fonte, nome)
    raise AttributeError("module %r has no attribute %r" % (__name__, nome))
