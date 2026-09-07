"""C8 — `Fantasma`: a trajetória pré-computada de um braço, para o placar do jogo.

Durante a rodada do público, a RL e o timer **não rodam ao vivo**. As trajetórias
deles naquela `(cenario, seed, janela)` são calculadas headless — de preferência
durante a rodada ANTERIOR, para o início ser instantâneo — e reproduzidas como
série por segundo.

Três coisas saem de graça dessa escolha:

- **pareamento exato**: os três braços viram a mesma demanda a partir do mesmo
  estado, por construção;
- **sincronia em tempo simulado**: o placar avança os três pela mesma linha do
  tempo `t`, então o achado nº1 da auditoria (comparar contadores acumulados de
  simulações que derivaram) deixa de ser possível AQUI também;
- **um SUMO só ao vivo** — o do humano.

O RISCO É FANTASMA VELHO. Um fantasma de outra seed, outra janela ou outra
demanda parece perfeitamente válido na tela e produz um placar mentiroso na
frente do público. Por isso ele carrega a `Chave` (C5) inteira e `confere()`
levanta em vez de deixar passar.
"""
from __future__ import annotations

import bisect
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .resultado import Chave, Janela, Resultado


class FantasmaIncompativel(RuntimeError):
    """Fantasma gravado em condição diferente da rodada que está para começar."""


@dataclass(frozen=True)
class Amostra:
    """Um segundo simulado da trajetória de um braço."""

    t: float
    entregues: int            # acumulado DENTRO da janela
    fila: float               # parados na rede naquele instante
    tempo_medio: float        # média corrente das viagens concluídas na janela


@dataclass(frozen=True)
class Fantasma:
    """A trajetória completa de um braço numa condição, mais o resultado final."""

    chave: Chave
    controlador: str
    serie: tuple[Amostra, ...]
    final: Resultado

    def __post_init__(self) -> None:
        if not self.serie:
            raise ValueError("fantasma sem amostras")
        ts = [a.t for a in self.serie]
        if ts != sorted(ts):
            raise ValueError("amostras fora de ordem temporal")
        j = self.chave.janela
        if ts[0] < j.t0 - 1e-6 or ts[-1] > j.t1 + 1e-6:
            raise ValueError("amostras (%g..%g) fora da janela [%g,%g)"
                             % (ts[0], ts[-1], j.t0, j.t1))

    # ---------------------------------------------------------------- leitura
    def em(self, t: float) -> Amostra:
        """A amostra vigente em `t` (a última com `amostra.t <= t`).

        Degrau, não interpolação: `entregues` é contagem, e interpolar contagem
        inventa meia viagem no placar.
        """
        ts = [a.t for a in self.serie]
        i = bisect.bisect_right(ts, t) - 1
        return self.serie[max(0, i)]

    def confere(self, chave: Chave) -> None:
        """Levanta se este fantasma não é desta rodada."""
        if not self.chave.compativel(chave):
            raise FantasmaIncompativel(
                "fantasma de %s não serve para %s — o placar mostraria a rodada "
                "errada." % (self.chave.descreve(), chave.descreve())
            )

    # ---------------------------------------------------------------- disco
    def salva(self, caminho: Path) -> Path:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "chave": {**asdict(self.chave), "janela": asdict(self.chave.janela)},
            "controlador": self.controlador,
            "serie": [asdict(a) for a in self.serie],
            "final": {**asdict(self.final),
                      "chave": {**asdict(self.final.chave),
                                "janela": asdict(self.final.chave.janela)}},
        }
        caminho.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
        return caminho

    @staticmethod
    def carrega(caminho: Path) -> "Fantasma":
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
        chave = _chave_de(d["chave"])
        final = dict(d["final"])
        final["chave"] = _chave_de(final["chave"])
        return Fantasma(
            chave=chave,
            controlador=d["controlador"],
            serie=tuple(Amostra(**a) for a in d["serie"]),
            final=Resultado(**final),
        )


def _chave_de(d: dict) -> Chave:
    d = dict(d)
    d["janela"] = Janela(**d["janela"])
    return Chave(**d)


def caminho_fantasma(raiz: Path, chave: Chave, controlador: str) -> Path:
    """`results/fantasmas/<cenario>/s<seed>_<t0>-<t1>_<controlador>.json`."""
    seguro = controlador.replace(":", "-").replace("/", "-")
    nome = "s%d_%g-%g_%s.json" % (chave.seed, chave.janela.t0, chave.janela.t1, seguro)
    return raiz / "fantasmas" / chave.cenario / nome
