"""`ReplayInput` — a rodada gravada, reproduzida bit a bit.

É o que torna o modo jogo TESTÁVEL (uma rodada tem 120 s de parede e um humano
dentro; nenhuma dessas duas coisas cabe numa suíte) e é a fonte que o agente A8
vai usar para rodar adversários scriptados em massa.

POR QUE A GRAVAÇÃO É POR TICK, E NÃO POR TEMPO DE PAREDE
--------------------------------------------------------
O `EventoBotao` carrega `t_wall` porque a botoeira reporta borda em tempo de
parede. Guardar isso na gravação seria guardar o jitter: reproduzir a rodada
num notebook mais lento entregaria a mesma tecla em outro tick e o `Resultado`
mudaria. O que determina a ação é só uma coisa — **quais botões estavam armados
quando o tick da grade chegou** — e é exatamente isso que fica gravado. Por
construção, `ReplayInput(gravacao)` reproduz o mesmo vetor de ações e portanto
o mesmo `Resultado`.

`passo_por_tick = True` avisa o `ControladorHumano` de que esta fonte entrega um
slot por tick e não pode ser drenada fora dele: o `bombeia()` (que existe para o
LED responder no ato) vira no-op, e o `poll()` acontece uma vez só por decisão.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..contratos import BOTAO_START, Chave, EventoBotao, valida_estados

__all__ = ["ReplayInput", "GravacaoRodada", "caminho_gravacao"]


@dataclass(frozen=True)
class GravacaoRodada:
    """Uma rodada jogada, no único formato que a reproduz.

    A `Chave` inteira viaja junto pelo mesmo motivo do C8: uma gravação de
    outra seed/janela/espaço de ação reproduz perfeitamente e mede outra coisa.
    """

    cenario: str
    seed: int
    t0: float
    t1: float
    demanda_sha: str
    restricoes: str
    n_botoes: int
    fonte: str
    ticks: tuple[tuple[int, ...], ...]

    @staticmethod
    def de(chave: Chave, *, n_botoes: int, fonte: str,
           ticks: list[tuple[int, ...]]) -> "GravacaoRodada":
        return GravacaoRodada(
            cenario=chave.cenario, seed=chave.seed, t0=chave.janela.t0,
            t1=chave.janela.t1, demanda_sha=chave.demanda_sha,
            restricoes=chave.restricoes, n_botoes=int(n_botoes), fonte=str(fonte),
            ticks=tuple(tuple(int(b) for b in t) for t in ticks),
        )

    def confere(self, chave: Chave) -> None:
        """Levanta se esta gravação não é desta condição."""
        meu = (self.cenario, self.seed, self.t0, self.t1, self.demanda_sha, self.restricoes)
        dela = (chave.cenario, chave.seed, chave.janela.t0, chave.janela.t1,
                chave.demanda_sha, chave.restricoes)
        if meu != dela:
            raise ValueError(
                "gravação de %s seed=%d janela=[%g,%g) demanda=%s acao=%s não serve "
                "para %s" % (self.cenario, self.seed, self.t0, self.t1,
                             self.demanda_sha[:12], self.restricoes, chave.descreve()))

    @property
    def n_pressoes(self) -> int:
        return sum(len(t) for t in self.ticks)

    def fonte_de_replay(self) -> "ReplayInput":
        return ReplayInput(self.n_botoes, [list(t) for t in self.ticks],
                           nome="replay:%s" % self.fonte)

    # ---------------------------------------------------------------- disco
    def salva(self, caminho: Path) -> Path:
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(self)
        d["ticks"] = [list(t) for t in self.ticks]
        caminho.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return caminho

    @staticmethod
    def carrega(caminho: Path) -> "GravacaoRodada":
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
        d["ticks"] = tuple(tuple(int(b) for b in t) for t in d["ticks"])
        return GravacaoRodada(**d)


def caminho_gravacao(raiz: Path, chave: Chave, rotulo: str) -> Path:
    """`results/rodadas/<cenario>/s<seed>_<t0>-<t1>_<rotulo>.json`."""
    seguro = str(rotulo).replace(":", "-").replace("/", "-").replace(" ", "_")
    nome = "s%d_%g-%g_%s.json" % (chave.seed, chave.janela.t0, chave.janela.t1, seguro)
    return Path(raiz) / "rodadas" / chave.cenario / nome


class ReplayInput:
    """`FonteEntrada` (C6) que reproduz um roteiro de botões, um slot por poll."""

    passo_por_tick = True

    def __init__(self, n_botoes: int = 12, roteiro: list[list[int]] | None = None,
                 *, nome: str = "replay") -> None:
        self.n_botoes = int(n_botoes)
        self.nome = nome
        self._roteiro = [list(s) for s in (roteiro or [])]
        self._i = 0
        self._viva = True
        # O que o motor mandou acender, tick a tick. É o que permite comparar o
        # feedback de duas execuções da mesma gravação.
        self.feedbacks: list[list[str]] = []

    # -------------------------------------------------------------- C6
    def poll(self) -> list[EventoBotao]:
        if self._i >= len(self._roteiro):
            return []
        slot = self._roteiro[self._i]
        self._i += 1
        return [EventoBotao(indice=int(b), t_wall=float(self._i)) for b in slot]

    def feedback(self, estados: list[str], start: str | None = None) -> None:
        self.feedbacks.append(list(valida_estados(estados, self.n_botoes)))
        if start is not None:
            self.start = valida_estados([start], 1)[0]

    def feedback_start(self, estado: str) -> None:
        """O LED do botao grande (C6). Aqui e so estado guardado."""
        self.start = valida_estados([estado], 1)[0]

    def viva(self) -> bool:
        return self._viva

    def close(self) -> None:
        self._viva = False

    # ------------------------------------------------------------- extras
    def rebobina(self) -> None:
        """Volta ao início. É o que faz `ControladorHumano.reset()` ser
        idempotente — exigência da suíte de conformidade e do fantasma."""
        self._i = 0
        self.feedbacks = []

    def avanca_tick(self) -> None:
        """No-op: `poll()` já anda um slot por chamada, e com
        `passo_por_tick=True` o `ControladorHumano` chama `poll()` uma vez por
        tick. O gancho existe para a fonte que precisar do sinal."""

    @property
    def esgotado(self) -> bool:
        return self._i >= len(self._roteiro)

    @property
    def starts(self) -> int:
        return sum(1 for s in self._roteiro for b in s if int(b) == BOTAO_START)
