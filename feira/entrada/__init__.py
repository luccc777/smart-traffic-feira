"""Camada de entrada do modo jogo — as implementações do C6.

`TecladoInput` é a que sempre existe: stdlib pura, sem `pyserial` (que não está
instalado no venv compartilhado, e isso é de propósito). `ReplayInput` reproduz
uma rodada gravada e é o que torna o jogo testável — e é a fonte que o agente A8
usa para rodar adversários scriptados em massa. `FonteComReserva` é a queda
automática para o teclado quando a botoeira física some no meio da rodada.

Nada aqui importa `serial`: a implementação da botoeira é do agente A4
(`feira/entrada_serial.py`) e entra como `primaria` do `FonteComReserva`.
"""
from .replay import GravacaoRodada, ReplayInput, caminho_gravacao
from .reserva import FonteComReserva
from .teclado import MAPA_TECLAS, TECLA_START, LeitorRoteirizado, TecladoInput, linhas_do_mapa

__all__ = [
    "TecladoInput", "LeitorRoteirizado", "MAPA_TECLAS", "TECLA_START", "linhas_do_mapa",
    "ReplayInput", "GravacaoRodada", "caminho_gravacao",
    "FonteComReserva",
]
