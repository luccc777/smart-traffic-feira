"""A4 — latência botão→evento. Item (d) do DoD: **< 50 ms**.

O QUE ESTÁ MEDIDO E O QUE ESTÁ CONTADO — a distinção importa
-------------------------------------------------------------
O número medido aqui é o **termo do host**: do byte estar no buffer da porta até
o `EventoBotao` sair de `poll()`. É a única parcela que dá para medir hoje, e ela
é medida de verdade, com relógio, contra o Pico em software.

As outras três parcelas são **contadas**, não medidas, e cada uma diz de onde vem:

| parcela                          | ms   | origem |
|----------------------------------|------|--------|
| varredura do firmware            | 2,0  | `sleep_ms(1)` + 13 leituras de GPIO. **estimativa** — `main.bancada()` mede na placa |
| debounce                         | 0,0  | de propósito: a borda sai na PRIMEIRA detecção (ver `test_a4_firmware.py`) |
| transporte USB CDC (full-speed)  | 3,0  | 1 quadro de 1 ms + folga do driver. **estimativa** |
| período de polling do motor      | 33,3 | 1/30 Hz, PIOR CASO — é o termo que domina |
| host (`poll()`)                  | ~0   | **MEDIDO aqui** |

Total de pior caso a 30 Hz: **≈ 38 ms**, com 12 ms de folga sobre o teto de 50.
A 20 Hz o orçamento ESTOURA (55 ms). Daí o requisito sobre o agente A3, que é o
verdadeiro achado deste arquivo: **o motor precisa chamar `poll()` a ≥ 30 Hz**,
independentemente de a grade de decisão ser de 5 s.

Nada disto vira número de bancada até a placa existir. `docs/BOTOEIRA.md`
§"o que só se prova com hardware" lista o que falta.
"""
from __future__ import annotations

import statistics
import time

from feira.contratos import ARMADO, BOTAO_START, OFF
from feira.entrada_serial import SerialFalso, SerialInput

# As parcelas do orçamento, em ms. Ficam aqui (e não só no .md) para que o teste
# do teto de 50 ms falhe se alguém mexer numa delas sem refazer a conta.
MS_VARREDURA_FIRMWARE = 2.0
MS_DEBOUNCE = 0.0
MS_USB_CDC = 3.0
HZ_POLL_MINIMO = 30.0
TETO_DOD_MS = 50.0

N_AMOSTRAS = 2000


def _mede(n=N_AMOSTRAS):
    """Byte no buffer -> `EventoBotao` na mão do motor. Em milissegundos."""
    dev = SerialFalso([])
    host = SerialInput(dev)
    amostras = []
    for i in range(n):
        alvo = i % 12
        t0 = time.perf_counter()
        dev.aperta(alvo)                          # o firmware acabou de escrever
        eventos = host.poll()                     # o motor colhe
        t1 = time.perf_counter()
        assert [e.indice for e in eventos] == [alvo]
        amostras.append((t1 - t0) * 1000.0)
    return sorted(amostras)


def test_latencia_do_host_e_desprezivel_no_orcamento(capsys):
    amostras = _mede()
    p50 = statistics.median(amostras)
    p99 = amostras[int(0.99 * len(amostras))]
    pior = amostras[-1]
    with capsys.disabled():
        print("\n  latência do host (byte no buffer -> EventoBotao), %d amostras:"
              % len(amostras))
        print("    p50 = %.4f ms   p99 = %.4f ms   máx = %.4f ms" % (p50, p99, pior))

    # A folga é enorme de propósito: o número precisa continuar desprezível num
    # notebook de feira com o SUMO e a projeção rodando junto.
    assert p99 < 1.0, "p99 do host em %.3f ms — algo passou a alocar por evento" % p99
    assert pior < 10.0, "outlier de %.3f ms — GC? o pior caso entra no orçamento" % pior


def test_rajada_de_13_botoes_num_poll_so(capsys):
    """Uma criança apertando tudo ao mesmo tempo: 13 linhas numa leitura."""
    dev = SerialFalso([])
    host = SerialInput(dev)
    piores = []
    for _ in range(200):
        t0 = time.perf_counter()
        for i in [*range(12), BOTAO_START]:
            dev.aperta(i)
        eventos = host.poll()
        piores.append((time.perf_counter() - t0) * 1000.0)
        assert len(eventos) == 13
    with capsys.disabled():
        print("    rajada de 13: p50 = %.4f ms   máx = %.4f ms"
              % (statistics.median(piores), max(piores)))
    assert max(piores) < 10.0


def test_feedback_nao_pesa_no_tick(capsys):
    """`feedback()` roda no mesmo tick que a decisão; 13 LEDs não podem custar frame."""
    dev = SerialFalso([])
    host = SerialInput(dev)
    amostras = []
    for i in range(1000):
        estados = [ARMADO if j == i % 12 else OFF for j in range(12)]
        t0 = time.perf_counter()
        host.feedback(estados)                    # muda sempre: nunca cai no dedupe
        amostras.append((time.perf_counter() - t0) * 1000.0)
    with capsys.disabled():
        print("    feedback(12 LEDs): p50 = %.4f ms   máx = %.4f ms"
              % (statistics.median(amostras), max(amostras)))
    assert statistics.median(amostras) < 1.0


def test_orcamento_de_pior_caso_fecha_sob_o_teto_do_dod(capsys):
    """A conta inteira, com o termo do host medido e o resto contado.

    Se alguém baixar `HZ_POLL_MINIMO` para 20 Hz, este teste fica vermelho — que é
    o ponto: o requisito de cadência do motor não pode se perder num .md.
    """
    host_ms = _mede(200)[-1]                      # pior caso medido
    periodo_poll_ms = 1000.0 / HZ_POLL_MINIMO
    total = (MS_VARREDURA_FIRMWARE + MS_DEBOUNCE + MS_USB_CDC
             + periodo_poll_ms + host_ms)
    with capsys.disabled():
        print("\n  orçamento botão->evento (pior caso, poll a %.0f Hz):" % HZ_POLL_MINIMO)
        print("    firmware %.1f + debounce %.1f + USB %.1f + poll %.1f + host %.3f"
              % (MS_VARREDURA_FIRMWARE, MS_DEBOUNCE, MS_USB_CDC, periodo_poll_ms, host_ms))
        print("    = %.1f ms   (teto do DoD: %.0f ms; folga %.1f ms)"
              % (total, TETO_DOD_MS, TETO_DOD_MS - total))
    assert total < TETO_DOD_MS

    # E a prova de que 30 Hz não é folclore: a 20 Hz o orçamento estoura.
    a_20hz = MS_VARREDURA_FIRMWARE + MS_DEBOUNCE + MS_USB_CDC + 50.0 + host_ms
    assert a_20hz > TETO_DOD_MS
