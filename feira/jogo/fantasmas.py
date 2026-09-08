"""`Fantasmaria` — quem calcula, guarda e confere os fantasmas da rodada (C8).

Durante a rodada do público a RL e o timer NÃO rodam ao vivo: as trajetórias
deles naquela `(cenario, seed, janela)` são calculadas headless e reproduzidas
como série por segundo. Três coisas saem de graça (o cabeçalho do C8 as lista):
pareamento exato, sincronia em tempo simulado e **um SUMO só ao vivo** — o do
humano.

CUSTO MEDIDO, porque o plano manda pré-computar durante a rodada anterior e
alguém tem que provar que cabe: no `aberta.maquete`, um fantasma completo
(300 s de aquecimento + 120 s de janela) custa **~2,5 s de parede** com o timer.
A rodada dura 120 s. Cabe com três ordens de grandeza de folga, e por isso o
modo padrão é o SÍNCRONO (calcula na fase `preparando`, uma vez, com cache em
disco) — subprocesso só quando o operador pedir.

POR QUE SUBPROCESSO E NÃO THREAD, quando é em segundo plano: `traci` é uma
conexão de módulo, singleton no processo. Duas Arenas na mesma interpretação
brigam pela sessão. O fantasma em paralelo roda em `python -m feira.jogo
.fantasmas`, escreve o JSON do C8 no caminho canônico, e o motor só carrega.

O RISCO É FANTASMA VELHO — e a defesa já está no contrato: `Fantasma.confere()`
levanta `FantasmaIncompativel` quando a `Chave` (cenário, seed, janela, sha da
demanda, assinatura do espaço de ação) não bate. Aqui a defesa é usada em TODO
carregamento, inclusive no do cache: um `.json` de ontem, de outra `min_green`,
parece perfeitamente válido na tela.
"""
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..contratos import (
    Amostra,
    Cenario,
    Chave,
    Fantasma,
    FantasmaIncompativel,
    Janela,
    Resultado,
    caminho_fantasma,
    janela_padrao,
)
from .estado import ControladorSelado, cenario_da_seed

__all__ = ["Fantasmaria", "ColetorDeSerie", "TarefaFantasma", "RAIZ_PADRAO"]

_RAIZ_REPO = Path(__file__).resolve().parents[2]
RAIZ_PADRAO = _RAIZ_REPO / "results"

# O baseline único do projeto enquanto o plano coordenado do agente A5 não
# congela. Trocar isto muda o adversário exibido — não é detalhe de jogo.
VERDE_TIMER_PADRAO = 27.0
CKPT_PADRAO = _RAIZ_REPO.parent / "smart-traffic-maquete" / "results" / "maq30_ats_full_best.pt"


class ColetorDeSerie:
    """Observador (C4) que transforma frames em `Amostra` (C8), um por segundo.

    É o MESMO coletor usado no braço humano ao vivo — de propósito: se a fila do
    fantasma fosse contada de um jeito e a do humano de outro, o placar
    compararia grandezas diferentes com o mesmo rótulo, que é a família de erro
    que a auditoria do A2 catalogou.
    """

    def __init__(self) -> None:
        self.amostras: list[Amostra] = []
        self._ultimo_t: float | None = None

    def __call__(self, frame) -> None:
        t = float(frame.t)
        if self._ultimo_t is not None and t <= self._ultimo_t:
            return
        self._ultimo_t = t
        self.amostras.append(self.amostra_de(frame))

    @staticmethod
    def amostra_de(frame) -> Amostra:
        stats = frame.stats or {}
        return Amostra(
            t=round(float(frame.t), 1),
            entregues=int(stats.get("entregues", 0)),
            # `heat` é a contagem de parados POR FAIXA no instante — a fila
            # instantânea que o C8 pede. `stats["fila_media"]` é a média
            # corrente da janela e serve a outra pergunta.
            fila=float(sum(frame.heat.values())) if frame.heat else 0.0,
            tempo_medio=float(stats.get("tempo_medio_entregue", 0.0)),
        )

    def serie(self, janela: Janela | None = None) -> tuple[Amostra, ...]:
        """As amostras, opcionalmente recortadas à janela declarada na `Chave`.

        O recorte existe por um deslocamento de 1 s da Arena, e não por gosto:
        `TrafficEnv.reset()` já dá um `simulationStep`, então o aquecimento
        termina em `t0+1` e a janela MEDIDA é `[t0+1, t1+1]` — mesma duração,
        deslocada. Como o deslocamento é idêntico nos três braços, o pareamento
        continua exato; o que não pode é o `Fantasma` guardar amostra fora da
        janela que a própria `Chave` declara (o C8 recusa, e com razão).
        """
        if janela is None:
            return tuple(self.amostras)
        return tuple(a for a in self.amostras
                     if janela.t0 - 1e-6 <= a.t <= janela.t1 + 1e-6)


@dataclass
class TarefaFantasma:
    """Um fantasma sendo calculado em segundo plano."""

    seed: int
    braco: str
    caminho: Path
    processo: subprocess.Popen | None
    inicio: float

    def pronta(self) -> bool:
        if self.processo is None:
            return self.caminho.exists()
        return self.processo.poll() is not None

    def espera(self, timeout: float | None = None) -> int:
        if self.processo is None:
            return 0
        return int(self.processo.wait(timeout=timeout))

    @property
    def custo_s(self) -> float:
        return time.perf_counter() - self.inicio


class Fantasmaria:
    """Calcula, guarda e confere os fantasmas de uma condição."""

    def __init__(self, cenario: Cenario, *, raiz: Path | None = None,
                 verde_timer: float = VERDE_TIMER_PADRAO,
                 ckpt_rl: Path | str | None = None,
                 arena=None) -> None:
        self.cenario = cenario
        self.raiz = Path(raiz) if raiz is not None else RAIZ_PADRAO
        self.verde_timer = float(verde_timer)
        self.ckpt_rl = Path(ckpt_rl) if ckpt_rl is not None else CKPT_PADRAO
        self._arena = arena
        # diagnóstico: quanto custou cada fantasma calculado nesta sessão.
        self.custos: list[tuple[int, str, float]] = []
        self.selos: dict[tuple[int, str], str] = {}
        # o `t` em que a janela de fato abriu para cada braço (a Arena desloca
        # em +1 s; ver `ColetorDeSerie.serie`). É o par do selo na checagem de
        # pareamento: mesmo estado, mesmo instante.
        self.t0s: dict[tuple[int, str], float] = {}
        self.ultimo_erro = ""

    # ------------------------------------------------------------ condição
    def janela(self) -> Janela:
        return janela_padrao(self.cenario, rodada=True)

    def chave(self, seed: int, janela: Janela | None = None) -> Chave:
        from ..arena.sumo import sha_demanda

        return Chave.de(self.cenario, int(seed), janela or self.janela(),
                        sha_demanda(self.cenario, int(seed)))

    def caminho(self, seed: int, braco: str, janela: Janela | None = None) -> Path:
        return caminho_fantasma(self.raiz, self.chave(seed, janela), braco)

    # --------------------------------------------------------- controladores
    def controlador(self, braco: str):
        """A fábrica do braço. `rl` importa torch tarde — e pode não existir."""
        if braco == "timer":
            from ..controladores import ControladorTimer

            return ControladorTimer(self.verde_timer)
        if braco == "rl":
            if not self.ckpt_rl.exists():
                raise FileNotFoundError("checkpoint da política não existe: %s" % self.ckpt_rl)
            from ..controladores import ControladorRL

            return ControladorRL(self.ckpt_rl)
        raise ValueError("braço %r desconhecido (use 'timer' | 'rl')" % braco)

    def _arena_viva(self):
        if self._arena is None:
            from ..arena import ArenaSumo

            self._arena = ArenaSumo()
        return self._arena

    # ------------------------------------------------------------- cálculo
    def calcula(self, seed: int, braco: str, *, salva: bool = True) -> Fantasma:
        """Roda o braço headless na janela da rodada e devolve o fantasma."""
        janela = self.janela()
        chave = self.chave(seed, janela)
        coletor = ColetorDeSerie()
        alvo = ControladorSelado(self.controlador(braco))
        arena = self._arena_viva()
        t_ini = time.perf_counter()
        res: Resultado = arena.roda(cenario_da_seed(self.cenario, seed), int(seed), alvo,
                                    janela, observador=coletor)
        custo = time.perf_counter() - t_ini
        self.custos.append((int(seed), braco, custo))
        if alvo.selo:
            self.selos[(int(seed), braco)] = alvo.selo
        if alvo.t0 is not None:
            self.t0s[(int(seed), braco)] = float(alvo.t0)
        serie = coletor.serie(janela)
        if not serie:                       # janela curta demais para amostrar
            serie = (Amostra(t=janela.t0, entregues=res.entregues,
                             fila=res.fila_media, tempo_medio=res.tempo_medio_entregue),)
        fant = Fantasma(chave=chave, controlador=res.controlador,
                        serie=serie, final=res)
        if salva:
            caminho = self.caminho(seed, braco, janela)
            fant.salva(caminho)
            if alvo.selo:
                _salva_selo(caminho, alvo.selo, res.controlador)
        return fant

    def carrega(self, seed: int, braco: str) -> Fantasma:
        """Do disco, CONFERINDO a chave. Fantasma velho parece válido na tela."""
        janela = self.janela()
        chave = self.chave(seed, janela)
        fant = Fantasma.carrega(self.caminho(seed, braco, janela))
        fant.confere(chave)
        selo = _le_selo(self.caminho(seed, braco, janela))
        if selo:
            self.selos[(int(seed), braco)] = selo
        return fant

    def garante(self, seed: int, bracos: tuple[str, ...] = ("timer", "rl"),
                *, recalcula: bool = False) -> dict[str, Fantasma]:
        """Os fantasmas desta seed, do cache quando servirem.

        Um braço que não puder ser calculado (checkpoint ausente, torch fora do
        ar) sai do dicionário em vez de derrubar a rodada — é o modo degradado:
        o placar perde uma barra, não a feira."""
        out: dict[str, Fantasma] = {}
        for braco in bracos:
            if not recalcula:
                try:
                    out[braco] = self.carrega(seed, braco)
                    continue
                except (FileNotFoundError, FantasmaIncompativel, ValueError, KeyError):
                    pass
            try:
                out[braco] = self.calcula(seed, braco)
            except Exception as exc:                     # degradado, não fatal
                self.custos.append((int(seed), braco + ":falhou", 0.0))
                self.ultimo_erro = "%s: %s" % (braco, exc)
        return out

    # ------------------------------------------------------- segundo plano
    def agenda(self, seed: int, bracos: tuple[str, ...] = ("timer", "rl"),
               ) -> list[TarefaFantasma]:
        """Dispara o cálculo em SUBPROCESSO (um por braço). Ver o cabeçalho."""
        tarefas: list[TarefaFantasma] = []
        for braco in bracos:
            caminho = self.caminho(seed, braco)
            if caminho.exists():
                try:
                    self.carrega(seed, braco)
                    tarefas.append(TarefaFantasma(int(seed), braco, caminho, None,
                                                  time.perf_counter()))
                    continue
                except Exception:
                    pass
            cmd = [sys.executable, "-m", "feira.jogo.fantasmas",
                   "--cenario", self.cenario.chave, "--seed", str(int(seed)),
                   "--braco", braco, "--raiz", str(self.raiz),
                   "--verde-timer", str(self.verde_timer)]
            proc = subprocess.Popen(cmd, cwd=str(_RAIZ_REPO),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            tarefas.append(TarefaFantasma(int(seed), braco, caminho, proc,
                                          time.perf_counter()))
        return tarefas


# ------------------------------------------------------------------- selo
def _caminho_selo(caminho: Path) -> Path:
    return Path(caminho).with_suffix(".selo.json")


def _salva_selo(caminho: Path, selo: str, controlador: str) -> Path:
    import json

    alvo = _caminho_selo(caminho)
    alvo.write_text(json.dumps({"selo_t0": selo, "controlador": controlador},
                               sort_keys=True) + "\n", encoding="utf-8")
    return alvo


def _le_selo(caminho: Path) -> str | None:
    import json

    alvo = _caminho_selo(caminho)
    if not alvo.exists():
        return None
    try:
        return str(json.loads(alvo.read_text(encoding="utf-8"))["selo_t0"])
    except Exception:
        return None


# -------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    """`python -m feira.jogo.fantasmas --cenario aberta.maquete --seed 100 --braco timer`."""
    import argparse

    from ..contratos import cenario as resolve_cenario

    p = argparse.ArgumentParser(description="calcula UM fantasma e escreve o JSON do C8")
    p.add_argument("--cenario", default="aberta.maquete")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--braco", default="timer", choices=("timer", "rl"))
    p.add_argument("--raiz", default=str(RAIZ_PADRAO))
    p.add_argument("--verde-timer", type=float, default=VERDE_TIMER_PADRAO)
    p.add_argument("--ckpt", default=None)
    a = p.parse_args(argv)

    cen = resolve_cenario(a.cenario)
    cen.aplicar(forcar=True)
    fm = Fantasmaria(cen, raiz=Path(a.raiz), verde_timer=a.verde_timer, ckpt_rl=a.ckpt)
    t0 = time.perf_counter()
    fant = fm.calcula(a.seed, a.braco)
    print("fantasma %s seed=%d: %d amostras, entregues=%d, %.2f s de parede -> %s"
          % (a.braco, a.seed, len(fant.serie), fant.final.entregues,
             time.perf_counter() - t0, fm.caminho(a.seed, a.braco)))
    return 0


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
