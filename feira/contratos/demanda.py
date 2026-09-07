"""C2 — `Demanda`: mesma seed, mesma sequência de veículos, sempre.

Requisito não negociável do projeto. A forma mais forte de garanti-lo é a demanda
NÃO ser código rodando junto da simulação, e sim um **arquivo de rotas gerado uma
vez a partir da seed**: mesmo arquivo -> mesmos veículos, mesmos instantes de
partida, mesmo OD, verificável por hash, e **provadamente** independente do
controlador — não "quase".

POR QUE NÃO INJEÇÃO IN-PROCESS (o modelo de hoje)
-------------------------------------------------
O `OpenDemandController` do repo de pesquisa sorteia as chegadas de um RNG semeado,
em ordem de tempo simulado, então o CRONOGRAMA é função só de (seed, índice). Isso
é quase suficiente. O "quase" é a contrapressão de inserção: sob congestionamento
o `vehicle.add` não insere na hora, e um controlador que trave a via de borda
atrasa (ou perde) inserções. O tráfego REALIZADO passa a depender do controlador,
que é exatamente o que a comparação pareada não pode admitir.

Com arquivo de rotas o cronograma continua idêntico entre braços, a contrapressão
vira observável (`backlog_insercao` em C5, `--duration-log.statistics` no SUMO) e
o braço que estrangula a borda é DENUNCIADO em vez de premiado.

E há a razão que amarra a Frente 3: com rotas em arquivo a demanda vive no estado
do SUMO, então o replay determinístico do warm-up (que é como a rodada do jogo
começa igual para os três braços) funciona. Com injeção in-process, não funciona.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .cenario import Cenario


def sha256_arquivo(caminho: Path) -> str:
    """SHA-256 do conteúdo. É a identidade da demanda em toda a `Chave` (C5)."""
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


@dataclass(frozen=True)
class ManifestoDemanda:
    """A prova de proveniência de um `.rou.xml`. Vai versionado; o `.rou.xml`, não.

    O arquivo de rotas é grande e regenerável; o manifesto é pequeno e é o que
    permite dizer "esta run usou ESTA demanda" seis meses depois. Se o gerador
    mudar de versão e o hash não bater, a run antiga não é mais reproduzível — e
    isso tem que aparecer, não passar batido.
    """

    cenario: str
    seed: int
    versao_gerador: str
    sha256: str
    n_veiculos: int
    t_primeiro: float
    t_ultimo: float
    parametros: dict

    def salva(self, caminho: Path) -> Path:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False,
                                      sort_keys=True) + "\n", encoding="utf-8")
        return caminho

    @staticmethod
    def carrega(caminho: Path) -> "ManifestoDemanda":
        return ManifestoDemanda(**json.loads(Path(caminho).read_text(encoding="utf-8")))

    def confere(self, rou: Path) -> None:
        """Levanta se o arquivo em disco não é o que o manifesto descreve."""
        real = sha256_arquivo(rou)
        if real != self.sha256:
            raise DemandaDivergente(
                "%s não bate com o manifesto (%s):\n  esperado %s\n  encontrado %s\n"
                "Regenere com a mesma seed e a mesma versão do gerador (%s)."
                % (rou.name, self.cenario, self.sha256[:16], real[:16], self.versao_gerador)
            )


class DemandaDivergente(RuntimeError):
    """O `.rou.xml` em disco não é o que o manifesto versionado descreve."""


@runtime_checkable
class GeradorDemanda(Protocol):
    """Gera (e regenera) a demanda de um cenário a partir de uma seed.

    INVARIANTE, e é o teste de conformidade: gerar duas vezes com a mesma seed
    produz arquivos com o MESMO sha256. Byte-idêntico, não "estatisticamente
    equivalente".
    """

    versao: str

    def gera(self, cenario: Cenario, seed: int, *, forcar: bool = False) -> ManifestoDemanda:
        """Escreve `cenario.rou_file(seed)` e devolve o manifesto. Idempotente:
        se o arquivo já existe e bate com o manifesto, não regera (a menos de
        `forcar`)."""
        ...

    def manifesto(self, cenario: Cenario, seed: int) -> ManifestoDemanda:
        """Lê o manifesto versionado. Levanta se não existir."""
        ...


def caminho_manifesto(cenario: Cenario, seed: int) -> Path:
    """`.../demanda_s42.rou.xml` -> `.../demanda_s42.manifesto.json`.

    Manipulação de string na unha em vez de `with_suffix`: o nome tem sufixo
    composto (`.rou.xml`) e `with_suffix` só troca o último.
    """
    rou = cenario.rou_file(seed)
    base = rou.name
    for sufixo in (".rou.xml", ".xml"):
        if base.endswith(sufixo):
            base = base[: -len(sufixo)]
            break
    return rou.with_name(base + ".manifesto.json")
