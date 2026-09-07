"""smart-traffic-feira — a rede aberta, a comparacao honesta e o modo jogo.

Este repo NAO reimplementa o ambiente de RL: ele consome o pacote `sim` do
`smart-traffic-maquete`, instalado em modo editavel (`pip install -e
../smart-traffic-maquete --no-deps`). Assim os resultados da rede fechada seguem
reproduzives no repo deles, e aqui nao ha copia para divergir.

O que e proprio daqui:
    feira/contratos/   C1..C8 -- congelados na Onda 0, antes de qualquer codigo
    feira/_fakes.py    implementacoes de referencia (alvo da suite de conformidade)
    sumo/aberta/       a rede de bordas abertas + a demanda por seed  (agente A1)
    web/               a projecao com o placar da rodada              (agente A7)
"""

__version__ = "0.1.0"
