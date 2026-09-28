"""O supervisor da TELA PADRÃO: os dois braços do ocioso, subindo e descendo com a fase.

O PROBLEMA QUE ESTE MÓDULO RESOLVE
----------------------------------
A tela padrão da feira é "a RL rodando ao vivo, o timer como régua" — duas simulações
ao vivo. `scripts/projecao_ocioso.py` já sabe rodar UMA delas e empurrar os quadros
para o `/ingest`; o que não existia era quem as coordenasse com a rodada do visitante.
Rodando na mão, em dois terminais, o operador tinha três problemas:

1. **Os dois braços brigavam com a rodada pela tela.** O feed não sabe que alguém
   apertou ESPAÇO: continua empurrando quadro, e a projeção alternava entre a malha do
   visitante e a da tela ociosa. (A outra metade desse conserto é o portão de fase em
   `EstadoProjecao.absorve_externo`.)
2. **Os dois braços saíam de sincronia.** Cada processo tem o seu rodízio de seeds e o
   seu vigia de população — que aborta uma volta quando a malha enche, e aborta ANTES
   no braço que congestiona mais. Um aborto e os dois passam a rodar horas de trânsito
   diferentes, comparando o incomparável. Aqui eles andam em TRAVA: mesma seed, sobem
   juntos, e a próxima volta só começa quando os DOIS terminaram.
3. **Três SUMOs concorrendo durante a rodada.** Os 120 s do visitante são o momento em
   que a projeção mais precisa de CPU. Os feeds descem quando a rodada começa e voltam
   quando a tela volta a ser a padrão.

POR QUE SUBPROCESSO, E NÃO THREAD
---------------------------------
`traci` é uma conexão de MÓDULO: duas Arenas no mesmo processo brigam pela sessão. É o
mesmo motivo pelo qual o prefetch dos fantasmas roda em subprocesso
(`Fantasmaria.agenda`). Dois braços ao vivo = dois processos, sem escolha.

COMO ELES MORREM
----------------
`terminate()` no Windows é `TerminateProcess`: o Python filho morre sem rodar `finally`
nenhum, e o SUMO que ele abriu fica ÓRFÃO — uma rodada por visitante, dois órfãos por
rodada, a feira inteira. Por isso o caminho normal é `CTRL_BREAK_EVENT` no grupo do
filho, que vira `KeyboardInterrupt` lá dentro: o `finally` da Arena roda, `env.close()`
fecha o SUMO, e o processo sai limpo. `terminate()` é só o plano B, depois do prazo.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..contratos.frame import OCIOSO

__all__ = ["SupervisorOcioso", "comando_ocioso"]

# Quanto esperar o filho sair pelo caminho limpo antes de apelar para o `terminate()`.
# O `finally` da Arena só precisa fechar o socket do traci e esperar o SUMO sair.
PRAZO_SAIDA_S = 8.0

# Período da ronda. O que ele custa em latência: é o atraso máximo entre a fase mudar
# e os feeds subirem/descerem. Um quarto de segundo é invisível na tela e barato.
TICK_S = 0.25

# Uma volta nova não começa antes disto, contado do fim da anterior. Sem a folga, uma
# seed que morre no aquecimento (SUMO não subiu, rede não construída) vira um laço de
# `spawn` a 4 Hz que ninguém vê acontecer — só a CPU sente.
FOLGA_VOLTA_S = 2.0


def comando_ocioso(braco: str, seed: int, *, cenario: str, duracao: float,
                   host: str, porta: int, ckpt: str | None = None,
                   verde_timer: float | None = None,
                   python: str | None = None) -> list[str]:
    """A linha de comando de UM braço do feed. Isolada para o teste poder lê-la."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "projecao_ocioso.py"
    cmd = [python or sys.executable, str(script),
           "--braco", str(braco), "--cenario", str(cenario),
           # UMA volta, UMA seed: quem escolhe a próxima é o supervisor, para os dois
           # braços nunca discordarem sobre qual hora de trânsito está na tela.
           "--seeds", str(int(seed)), "--voltas", "1",
           "--duracao", "%g" % float(duracao),
           "--host", str(host), "--porta", str(int(porta))]
    if ckpt:
        cmd += ["--ckpt", str(ckpt)]
    if verde_timer is not None:
        cmd += ["--verde-timer", "%g" % float(verde_timer)]
    return cmd


class SupervisorOcioso:
    """Sobe/derruba os dois braços da tela ociosa conforme `estado.fase`.

    Uso:
        sup = SupervisorOcioso(estado, cenario="aberta.maquete", seeds=(100, 101))
        sup.start()
        ...
        sup.close()
    """

    def __init__(self, estado, *, cenario: str, seeds=(100,), duracao: float = 1800.0,
                 host: str = "127.0.0.1", porta: int = 8080,
                 ckpt: str | None = None, verde_timer: float | None = None,
                 bracos=("rl", "timer"), python: str | None = None,
                 log=None) -> None:
        self.estado = estado
        self.cenario = str(cenario)
        self.seeds = tuple(int(s) for s in seeds) or (100,)
        self.duracao = float(duracao)
        self.host, self.porta = str(host), int(porta)
        self.ckpt, self.verde_timer = ckpt, verde_timer
        self.bracos = tuple(bracos)
        self.python = python
        self.log = log or (lambda _m: None)
        self.i_seed = 0
        self.voltas = 0
        self._procs: dict[str, subprocess.Popen] = {}
        self._parar = threading.Event()
        self._proxima_em = 0.0
        self._thread = threading.Thread(target=self._laco, name="ocioso", daemon=True)

    # ------------------------------------------------------------------ ciclo
    @property
    def rodando(self) -> bool:
        return bool(self._procs)

    @property
    def seed_atual(self) -> int:
        return self.seeds[self.i_seed % len(self.seeds)]

    def start(self) -> None:
        self._thread.start()

    def close(self, timeout: float = PRAZO_SAIDA_S) -> None:
        self._parar.set()
        self.derruba(timeout=timeout)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _laco(self) -> None:
        while not self._parar.is_set():
            try:
                self.ronda()
            except Exception as exc:                       # nunca derruba a projeção
                self.log("ocioso: ronda falhou: %s: %s" % (type(exc).__name__, exc))
            time.sleep(TICK_S)

    def ronda(self) -> None:
        """Um passo da máquina. Pública para o teste chamar sem thread nem sleep."""
        if self.estado.fase != OCIOSO:
            if self.rodando:
                self.log("ocioso: fase %s — descendo os feeds" % self.estado.fase)
                self.derruba()
            return
        if not self.rodando:
            if time.monotonic() >= self._proxima_em:
                self.sobe()
            return
        # Volta terminada = os DOIS braços saíram. Enquanto um continua, o outro que
        # já acabou fica quieto: não se puxa a próxima seed com meia tela viva.
        if all(p.poll() is not None for p in self._procs.values()):
            codigos = {b: p.returncode for b, p in self._procs.items()}
            self.voltas += 1
            self.log("ocioso: volta %d (seed %d) terminada: %s"
                     % (self.voltas, self.seed_atual, codigos))
            self._procs.clear()
            self.i_seed += 1
            self._proxima_em = time.monotonic() + FOLGA_VOLTA_S

    # ----------------------------------------------------------- subprocessos
    def sobe(self) -> None:
        """Lança os dois braços na MESMA seed. Falha de um derruba o outro."""
        seed = self.seed_atual
        criacao = 0
        if os.name == "nt":                # grupo próprio: o CTRL_BREAK não volta em nós
            criacao = subprocess.CREATE_NEW_PROCESS_GROUP
        elif hasattr(os, "setsid"):
            criacao = 0
        try:
            for braco in self.bracos:
                cmd = comando_ocioso(braco, seed, cenario=self.cenario,
                                     duracao=self.duracao, host=self.host,
                                     porta=self.porta, ckpt=self.ckpt,
                                     verde_timer=self.verde_timer, python=self.python)
                kw = {"creationflags": criacao} if os.name == "nt" else {
                    "start_new_session": True}
                self._procs[braco] = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
            self.log("ocioso: seed %d — %s no ar" % (seed, "+".join(self.bracos)))
        except Exception as exc:
            self.log("ocioso: não subiu (%s: %s)" % (type(exc).__name__, exc))
            self.derruba()
            self._proxima_em = time.monotonic() + FOLGA_VOLTA_S

    def derruba(self, timeout: float = PRAZO_SAIDA_S) -> None:
        """Pede saída limpa (o SUMO do filho precisa do `finally`), depois insiste."""
        procs = list(self._procs.values())
        self._procs.clear()
        for p in procs:
            if p.poll() is not None:
                continue
            try:
                if os.name == "nt":
                    p.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    p.send_signal(signal.SIGINT)
            except Exception:
                with _silencio():
                    p.terminate()
        fim = time.monotonic() + float(timeout)
        for p in procs:
            with _silencio():
                p.wait(timeout=max(0.0, fim - time.monotonic()))
        for p in procs:                                    # plano B: o SUMO pode vazar
            if p.poll() is None:
                with _silencio():
                    p.kill()
                with _silencio():
                    p.wait(timeout=2.0)


class _silencio:
    """`with _silencio(): ...` — engole qualquer erro de encerramento de processo."""

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return True
