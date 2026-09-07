"""Os contratos do repo — a superfície que os agentes combinam antes de escrever código.

| # | módulo | o que congela |
|---|---|---|
| C1 | `cenario`    | rede + demanda + **as restrições de fase, iguais para os três braços** |
| C2 | `demanda`    | mesma seed -> mesmo `.rou.xml`, provado por hash |
| C3 | `controlador`| a única superfície de RL, timer e humano |
| C4 | `arena`      | **um laço só** roda os três; a cadência é do laço |
| C5 | `resultado`  | o que se mediu, e a `Chave` sem a qual não se compara |
| C6 | `entrada`    | teclado / botoeira / replay, plugáveis |
| C7 | `frame`      | o que trafega até a projeção, e o placar |
| C8 | `fantasma`   | trajetória pré-computada, carimbada com a `Chave` |

Nada aqui importa `sim`, `traci` ou `torch`: os contratos e seus testes rodam sem
SUMO. Quem toca SUMO são as implementações (`feira/arena/`, `feira/demanda/`, ...).
"""
from .arena import (
    Arena,
    ArenaNaoConfigurada,
    Frame,
    Observador,
    Ritmo,
    TravamentoDetectado,
    janela_padrao,
)
from .cenario import (
    RESTRICOES_ABERTA,
    RESTRICOES_FECHADA,
    Cenario,
    CenarioJaImportado,
    RestricoesFase,
    cenario,
    chaves,
)
from .controlador import (
    MANTER,
    TROCAR,
    Controlador,
    Observacao,
    Topologia,
    valida_acoes,
)
from .demanda import (
    DemandaDivergente,
    GeradorDemanda,
    ManifestoDemanda,
    caminho_manifesto,
    sha256_arquivo,
)
from .entrada import (
    ACEITO,
    ARMADO,
    BOTAO_START,
    ESTADOS,
    NEGADO,
    OFF,
    PROTO_BAUD,
    PROTO_CHAR,
    PROTO_TIMEOUT_S,
    PROTO_VERSAO,
    EventoBotao,
    FonteEntrada,
    valida_estados,
)
from .fantasma import (
    Amostra,
    Fantasma,
    FantasmaIncompativel,
    caminho_fantasma,
)
from .frame import (
    BRACOS,
    CONTAGEM,
    FASES,
    JOGANDO,
    OCIOSO,
    PREPARANDO,
    RESULTADO,
    LinhaPlacar,
    Placar,
    frame_wire,
)
from .resultado import (
    DIRECAO,
    Chave,
    ChavesIncompativeis,
    Comparacao,
    Janela,
    Resultado,
    agrega_por_seed,
    comparar,
)

__all__ = [
    # C1
    "Cenario", "RestricoesFase", "CenarioJaImportado", "cenario", "chaves",
    "RESTRICOES_ABERTA", "RESTRICOES_FECHADA",
    # C2
    "GeradorDemanda", "ManifestoDemanda", "DemandaDivergente", "sha256_arquivo",
    "caminho_manifesto",
    # C3
    "Controlador", "Observacao", "Topologia", "MANTER", "TROCAR", "valida_acoes",
    # C4
    "Arena", "Ritmo", "Frame", "Observador", "ArenaNaoConfigurada",
    "TravamentoDetectado", "janela_padrao",
    # C5
    "Janela", "Chave", "Resultado", "Comparacao", "comparar", "agrega_por_seed",
    "ChavesIncompativeis", "DIRECAO",
    # C6
    "FonteEntrada", "EventoBotao", "BOTAO_START", "ESTADOS", "OFF", "ARMADO",
    "ACEITO", "NEGADO", "valida_estados", "PROTO_VERSAO", "PROTO_BAUD",
    "PROTO_TIMEOUT_S", "PROTO_CHAR",
    # C7
    "Placar", "LinhaPlacar", "frame_wire", "BRACOS", "FASES", "OCIOSO",
    "PREPARANDO", "CONTAGEM", "JOGANDO", "RESULTADO",
    # C8
    "Fantasma", "Amostra", "FantasmaIncompativel", "caminho_fantasma",
]
