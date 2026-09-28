"""projecao_ocioso.py — o feed da tela OCIOSO: um braço rodando ao vivo, a 1:1.

A tela `ocioso` da projeção mostra "a RL rodando, o timer como régua" (JOGO.md §2).
Isso são DUAS simulações ao vivo, e cada uma precisa do seu processo: `traci` é uma
conexão de MÓDULO e duas Arenas no mesmo processo brigam pela sessão — o mesmo motivo
pelo qual o prefetch dos fantasmas roda em subprocesso (`Fantasmaria.agenda`).

    # terminal 1 — a projeção
    python scripts/projecao_servidor.py --so-servidor
    # terminais 2 e 3 — os dois braços do ocioso
    python scripts/projecao_ocioso.py --braco rl
    python scripts/projecao_ocioso.py --braco timer

Cada um se conecta em `ws://host:porta/ingest` e empurra um `frame` (C7) por sim-step.
A JANELA VIAJA JUNTO, e é a mesma para os dois: sem isso a projeção estaria comparando
contadores de simulações derivadas de novo — que é exatamente o defeito que a janela no
frame existe para pegar. Se você subir os dois braços com `--seed` ou `--janela`
diferentes, a tela vai DENUNCIAR em vez de desenhar. É o comportamento correto.

O envio é assíncrono, numa fila LIMITADA: se a projeção cair, a simulação continua e os
quadros são descartados. Um feed que trava a simulação por causa de socket é pior do
que um feed que perde quadro.
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FILA = 64


class Remetente:
    """Thread que empurra o que estiver na fila para o `/ingest`. Reconecta sozinha."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.fila: "queue.Queue[dict]" = queue.Queue(maxsize=FILA)
        self.parar = threading.Event()
        self.enviadas = 0
        self.descartadas = 0
        self.thread = threading.Thread(target=self._laco, name="ingest", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def __call__(self, msg: dict) -> None:
        try:
            self.fila.put_nowait(msg)
        except queue.Full:
            self.descartadas += 1

    def _laco(self) -> None:
        from websockets.sync.client import connect

        while not self.parar.is_set():
            try:
                with connect(self.url, open_timeout=5) as ws:
                    while not self.parar.is_set():
                        try:
                            msg = self.fila.get(timeout=0.5)
                        except queue.Empty:
                            continue
                        ws.send(json.dumps(msg))
                        self.enviadas += 1
            except Exception:
                time.sleep(1.0)

    def close(self) -> None:
        self.parar.set()
        self.thread.join(timeout=2.0)


class _Encheu(RuntimeError):
    """A volta encheu a malha e foi abortada pelo vigia."""


class _Vigia:
    """Vigia de população para a volta do feed ocioso.

    O relógio sozinho não protege: `--duracao` é uma aposta sobre quando a malha
    degrada, e a resposta depende do braço, da seed e do regime. Este vigia olha o
    sintoma em vez do calendário — população ativa acima do teto por
    `segundos` seguidos —, então uma volta que azede aos 400 s morre aos 460 e não
    fica 1400 s no projetor mostrando congestionamento que ninguém pediu.

    Exige persistência de propósito: um pico isolado é flutuação de inserção, não
    acúmulo.
    """

    def __init__(self, teto: int, segundos: float) -> None:
        self.teto = int(teto or 0)
        self.segundos = float(segundos)
        self.pico = 0
        self._desde: float | None = None

    def ve(self, quadro) -> None:
        n = len(getattr(quadro, "veiculos", ()) or ())
        self.pico = max(self.pico, n)
        if not self.teto:
            return
        t = float(getattr(quadro, "t", 0.0))
        if n <= self.teto:
            self._desde = None
            return
        if self._desde is None:
            self._desde = t
        elif t - self._desde >= self.segundos:
            raise _Encheu("abortada: %d ativos (teto %d) por %.0f s seguidos"
                          % (n, self.teto, t - self._desde))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="feed ao vivo da tela ociosa")
    p.add_argument("--cenario", default="aberta.maquete")
    p.add_argument("--braco", choices=("rl", "timer"), default="rl")
    # RODÍZIO DE SEEDS, não uma só. Uma seed fixa faz a feira inteira assistir à
    # MESMA hora de trânsito em laço; e, pior, se aquela seed for uma das ruins
    # para o braço exibido, ela é ruim em todas as voltas do dia.
    p.add_argument("--seeds", default=",".join(str(s) for s in range(100, 112)),
                   help="seeds em rodízio, uma por volta")
    p.add_argument("--duracao", type=float, default=1800.0,
                   help="segundos simulados por volta (depois recomeça)")
    # O TETO DE POPULAÇÃO — o vigia que o relógio sozinho não substitui.
    # O regime calibrado é 157 ativos (141-170 nas fatias de 600 s,
    # `docs/CALIBRACAO_ABERTA.md`). O dobro disso não é flutuação: é a malha
    # enchendo. Medido pelo A1 a 3800 veh/h, as seeds que travam vão a 552-582.
    # Exigir `--teto-segundos` seguidos acima do teto evita abortar num pico.
    p.add_argument("--teto-ativos", type=int, default=320,
                   help="aborta a volta se a população passar disto (0 = sem vigia)")
    p.add_argument("--teto-segundos", type=float, default=60.0,
                   help="por quantos segundos seguidos o teto tem de ser excedido")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--porta", type=int, default=8080)
    p.add_argument("--ckpt", default=None)
    p.add_argument("--verde-timer", type=float, default=27.0)
    p.add_argument("--voltas", type=int, default=0, help="0 = para sempre")
    a = p.parse_args(argv)

    from feira.contratos import cenario as resolve_cenario

    cen = resolve_cenario(a.cenario)
    cen.aplicar(forcar=True)

    from feira.arena import ArenaSumo
    from feira.contratos.arena import Ritmo
    from feira.contratos.resultado import Janela
    from feira.jogo.fantasmas import Fantasmaria
    from feira.jogo.web import PublicadorProjecao

    if cen.warmup_s is None:
        print("cenário sem warmup medido", file=sys.stderr)
        return 2
    janela = Janela(t0=float(cen.warmup_s), t1=float(cen.warmup_s) + float(a.duracao))

    fm = Fantasmaria(cen, verde_timer=a.verde_timer,
                     ckpt_rl=Path(a.ckpt) if a.ckpt else None)
    ctrl = fm.controlador(a.braco)

    rem = Remetente("ws://%s:%d/ingest" % (a.host, a.porta))
    rem.start()

    # O `PublicadorProjecao` também serve aqui — é o único lugar do repo que converte
    # `Frame` (C4) em mensagem de fio (C7). Aqui ele manda para o socket, não para um
    # estado local: é para isso que existe o parâmetro `envia`.
    pub = PublicadorProjecao(envia=rem)

    arena = ArenaSumo()
    jan = (janela.t0, janela.t1)
    seeds = [int(x) for x in str(a.seeds).split(",") if str(x).strip()]
    if not seeds:
        print("--seeds vazio", file=sys.stderr)
        return 2
    n = 0
    print("ocioso: braço=%s seeds=%s janela=[%g, %g] teto=%s -> %s"
          % (a.braco, ",".join(str(s) for s in seeds), jan[0], jan[1],
             a.teto_ativos or "sem vigia", rem.url))
    try:
        while a.voltas <= 0 or n < a.voltas:
            seed = seeds[n % len(seeds)]
            vigia = _Vigia(a.teto_ativos, a.teto_segundos)

            def observa(quadro, _v=vigia, _s=seed):
                _v.ve(quadro)
                pub.frame(quadro, braco=a.braco, janela=jan, seed=_s,
                          politica=getattr(ctrl, "nome", a.braco))

            motivo = "completou"
            try:
                res = arena.roda(cen, seed, ctrl, janela,
                                 ritmo=Ritmo(sim_por_parede=1.0), observador=observa)
                inseridos, entregues = res.inseridos, res.entregues
            except _Encheu as exc:
                # Não é falha da corrida: é o vigia fazendo o trabalho dele. A volta
                # morre, a próxima seed entra, e o público nunca vê a malha travada.
                motivo, inseridos, entregues = str(exc), -1, -1
            n += 1
            # A checagem barata que pega a classe de falha que já custou uma trilha:
            # corrida sem inserção nenhuma é malha vazia, não é resultado.
            print("volta %d seed %d: inseridos=%d entregues=%d pico=%d ativos | %s"
                  " (enviadas=%d descartadas=%d)"
                  % (n, seed, inseridos, entregues, vigia.pico, motivo,
                     rem.enviadas, rem.descartadas))
            if inseridos == 0:
                print("  ATENÇÃO: inseridos=0 — a malha rodou vazia", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nencerrado pelo operador")
    finally:
        rem.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
