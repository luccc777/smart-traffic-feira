"""projecao_telas.py — uma foto de cada uma das cinco telas, sem projetor e sem SUMO.

Serve a dois donos:

  * ao AGENTE/desenvolvedor: conferir que as cinco fases da máquina de estados do C7
    (`ocioso`, `preparando`, `contagem`, `jogando`, `resultado`) desenham, e que nada
    estoura o retângulo quando o placar cresce;
  * ao DONO DO PROJETO: gerar as imagens da lista de conferência de bancada
    (docs/PROJECAO.md §2) para comparar com o que o projetor põe no chão.

Ele NÃO substitui a foto do projetor real. Legibilidade a 2 m depende do brilho, da
luz da sala e da distância — coisas que só existem na bancada. O que este script
entrega é a geometria e o layout, no mesmo tamanho de painel.

    python scripts/projecao_telas.py --saida C:\\tmp\\telas
    python scripts/projecao_telas.py --fase resultado --carros 250
    python scripts/projecao_telas.py --denuncia      # a tela de janela divergente
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.projecao_bench import acha_chrome  # noqa: E402

FASES = ("ocioso", "preparando", "contagem", "jogando", "resultado")
# Desfechos e camadas de servico que nao sao fase do C7, mas tem tela propria.
EXTRAS = ("nao_pareada", "empate", "sem_placar", "denuncia", "degradado")


def _foto(exe, url, destino: Path, porta: int, espera: float = 6.0) -> bool:
    """Um instantâneo. O `--virtual-time-budget` só termina quando a página para de
    pedir quadro — por isso a URL leva `quadros=N` (ver `projecao.js`)."""
    perfil = Path(os.environ.get("TEMP", ".")) / ("st-telas-%d" % porta)
    args = [exe, "--user-data-dir=%s" % perfil, "--no-first-run",
            "--no-default-browser-check", "--headless=new", "--disable-gpu",
            "--hide-scrollbars", "--window-size=1920,1080",
            "--screenshot=%s" % destino,
            "--virtual-time-budget=%d" % int(espera * 1000), url]
    r = subprocess.run(args, capture_output=True, timeout=180)
    shutil.rmtree(perfil, ignore_errors=True)
    return destino.exists() and destino.stat().st_size > 0 and r.returncode == 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--saida", default="telas")
    p.add_argument("--cenario", default="aberta.maquete")
    p.add_argument("--carros", type=int, default=180)
    p.add_argument("--porta", type=int, default=8410)
    p.add_argument("--quadros", type=int, default=40,
                   help="quantos quadros a página desenha antes de parar (ver `_foto`)")
    p.add_argument("--fase", choices=FASES + EXTRAS, default=None,
                   help="só uma tela (default: as cinco fases)")
    p.add_argument("--denuncia", action="store_true",
                   help="além das fases: rodada não pareada, empate, rodada não "
                        "concluída, janela divergente e modo degradado")
    a = p.parse_args(argv)

    exe = acha_chrome()
    if not exe:
        print("Chrome/Edge não encontrado", file=sys.stderr)
        return 2

    from feira.contratos import cenario as resolve
    from feira.jogo.web import EstadoProjecao, ServidorProjecao, geometria

    cen = resolve(a.cenario)
    est = EstadoProjecao(cenario=cen)
    rede = geometria(cen)
    est._rede = rede
    srv = ServidorProjecao(est, porta=a.porta)
    if not srv.sobe():
        print("o servidor não subiu", file=sys.stderr)
        return 2

    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    fases = [a.fase] if a.fase else list(FASES)
    if a.denuncia:
        # Os quatro desfechos que `vencedor: null` esconderia se o C7 não tivesse
        # `pareado` e `motivo`, mais as duas camadas de serviço.
        fases = fases + list(EXTRAS)
    feitas = []
    try:
        for fase in fases:
            # `?demo=` em vez de empurrar pelo WebSocket: o `--screenshot` do Chrome
            # dispara o instantâneo assim que o orçamento de tempo VIRTUAL acaba, e uma
            # conexão WS de verdade não cabe nessa janela — a foto sairia sempre na tela
            # de "conectando". O `demo` injeta pelo MESMO `recebe()` do fio.
            url = ("http://127.0.0.1:%d/?demo=%s&carros=%d&quadros=%d&diag=1"
                   % (a.porta, fase, a.carros, a.quadros))
            destino = saida / ("%s.png" % fase)
            ok = _foto(exe, url, destino, a.porta)
            feitas.append((fase, destino, ok))
            print("  %-11s %s" % (fase, destino if ok else "FALHOU"))
    finally:
        srv.desce()
    time.sleep(0.2)
    return 0 if all(ok for _, _, ok in feitas) else 1


if __name__ == "__main__":
    raise SystemExit(main())
