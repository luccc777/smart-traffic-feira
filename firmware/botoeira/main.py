"""Botoeira SmartTraffic -- firmware MicroPython para Raspberry Pi Pico (RP2040).

Copie ESTE arquivo e `protocolo.py` para a raiz do Pico. O MicroPython roda
`main.py` sozinho no boot; a partir dai o painel fala o protocolo do C6 pela USB
CDC (zero driver no Windows, zero adaptador serial).

ZERO LOGICA DE JOGO AQUI
------------------------
O Pico le bordas e acende o que mandarem. Ele nao sabe o que e verde minimo, nao
sabe se a troca foi aceita, nao decide nada. Toda a decisao mora no host, e e por
isso que trocar a politica do jogo nunca exige regravar firmware.

    dispositivo -> host          host -> dispositivo
    HELLO botoeira v1 n=12       LED <i> <off|armed|on|deny>
    BTN <i>                      LEDS <13 chars>
    START                        RESET
    PING (1 Hz)

SAIDA DE EMERGENCIA
-------------------
SEGURE O BOTAO START ENQUANTO PLUGA O USB: o firmware imprime um aviso e cai no
REPL sem armar o watchdog. E o unico jeito de recuperar a placa se o laco travar
-- sem isso, sobra apagar a flash (BOOTSEL + flash_nuke.uf2) e reinstalar tudo.

BANCADA
-------
No REPL (Thonny, mpremote, `screen`):

    >>> import main
    >>> main.bancada()        # periodo do laco, varredura dos 13 LEDs, botoes

Ver `docs/BOTOEIRA.md` para montagem, teste e diagnostico.
"""
import select
import sys
import time

import machine
import micropython
import protocolo as P

# ------------------------------------------------------------------- pinagem
# Os 12 semaforos ficam em GP2..GP13 -- contiguos e do MESMO lado da placa, para
# o chicote sair reto. Regra unica, sem tabela: **GPIO = indice + 2**.
#
# ATENCAO -- por que NAO comeca em GP0: GP0/GP1 sao a UART0. Ha build de
# MicroPython que sobe o REPL nela; ai a GP0 vira SAIDA em nivel alto e o botao,
# ao fechar contra o GND, curto-circuita a TX. Comecar em GP2 custa uma soma e
# ainda deixa a UART livre como console de socorro se a CDC der problema.
PINOS_BOTAO = list(range(2, 14))
PINO_START = 22                 # do outro lado da placa, longe dos 12: e outro botao

PINO_SPI_SCK = 18               # SPI0 SCK  -> 74HC595 SRCLK (pino 11)
PINO_SPI_MOSI = 19              # SPI0 TX   -> 74HC595 SER   (pino 14)
PINO_LATCH = 20                 # RCLK (pino 12) dos dois chips, em paralelo
PINO_OE = 21                    # /OE (pino 13); pull-up 10k externo = apagado no boot
PINO_LED_PLACA = 25             # LED onboard do Pico (nao existe no Pico W)

SPI_HZ = 1_000_000              # 2 bytes = ~16 us; sobra folga sobre fio longo
PERIODO_LED_MS = 10             # cadencia do shift-out (resolve 10 Hz do "deny")
LIMITE_CHARS_LACO = 64          # teto de leitura da CDC por laco: host nao starva o scan
WDT_MS = 2000                   # watchdog; o host desiste da botoeira em 2 s tambem


def _pinos_entrada():
    """Os 13 botoes, ativo-baixo com pull-up interno. Indice 12 = START."""
    pinos = [machine.Pin(g, machine.Pin.IN, machine.Pin.PULL_UP) for g in PINOS_BOTAO]
    pinos.append(machine.Pin(PINO_START, machine.Pin.IN, machine.Pin.PULL_UP))
    return pinos


def _le_nivel(pinos):
    """True = apertado. Ativo-baixo: o botao curta o GPIO ao GND."""
    return [p.value() == 0 for p in pinos]


class Painel:
    """Os dois 74HC595 em cascata: 3 fios do Pico, 16 saidas, 13 usadas."""

    def __init__(self):
        self.spi = machine.SPI(0, baudrate=SPI_HZ, polarity=0, phase=0,
                               sck=machine.Pin(PINO_SPI_SCK),
                               mosi=machine.Pin(PINO_SPI_MOSI))
        self.latch = machine.Pin(PINO_LATCH, machine.Pin.OUT, value=0)
        self.oe = machine.Pin(PINO_OE, machine.Pin.OUT, value=1)   # 1 = saidas Hi-Z
        self.escreve(bytes([0, 0]))
        self.oe.value(0)                                           # so agora habilita

    def escreve(self, palavra):
        self.spi.write(palavra)
        self.latch.value(1)
        self.latch.value(0)

    def apaga(self):
        self.escreve(bytes([0, 0]))


class Botoeira:
    """O laco. Sem estado de jogo: bordas para fora, LEDs para dentro."""

    def __init__(self, com_watchdog=True):
        self.pinos = _pinos_entrada()
        self.painel = Painel()
        self.debounce = P.Debounce(len(self.pinos))
        self.debounce.sincroniza(_le_nivel(self.pinos))
        self.linhas = P.Linhas()
        self.estados = [P.OFF] * (P.N_BOTOES + 1)
        self.poll_stdin = select.poll()
        self.poll_stdin.register(sys.stdin, select.POLLIN)
        try:
            self.led_placa = machine.Pin(PINO_LED_PLACA, machine.Pin.OUT)
        except (ValueError, TypeError):                # Pico W: GP25 e do WiFi
            self.led_placa = None
        self.wdt = machine.WDT(timeout=WDT_MS) if com_watchdog else None
        self.ignoradas = 0

    # ------------------------------------------------------------- protocolo

    def diz(self, linha):
        """Uma linha para o host.

        RISCO CONHECIDO: `sys.stdout.write` na CDC BLOQUEIA se a porta estiver
        aberta e o host parar de ler (jogo travado, terminal esquecido aberto sem
        ninguem lendo). O buffer da CDC enche, o laco para e o watchdog reinicia o
        Pico. Isso e degradacao aceitavel, nao perda: ao voltar, o firmware manda
        `HELLO`, o host reconhece o HELLO fora de hora e REENVIA o quadro de LEDs
        (`SerialInput._confere_hello`), entao o painel volta ao estado certo.
        Com a porta FECHADA nao ha bloqueio: o TinyUSB descarta a escrita.
        Volume proposital: 5 bytes/s de `PING` mais uma linha por aperto.
        """
        sys.stdout.write(linha)
        sys.stdout.write("\n")

    def le_host(self):
        """Drena a CDC (ate LIMITE_CHARS_LACO) e aplica os comandos."""
        pedaco = ""
        n = 0
        while n < LIMITE_CHARS_LACO and self.poll_stdin.poll(0):
            c = sys.stdin.read(1)
            if not c:
                break
            pedaco += c
            n += 1
        for linha in self.linhas.alimenta(pedaco):
            tipo, dado = P.interpreta(linha)
            if tipo == "leds":
                self.estados = dado
            elif tipo == "led":
                i, estado = dado
                self.estados[i] = estado
            elif tipo == "reset":
                self.estados = [P.OFF] * (P.N_BOTOES + 1)
                self.diz(P.linha_hello())
            else:
                self.ignoradas += 1                    # ignorar, nunca morrer

    # ------------------------------------------------------------------ laco

    def roda(self):
        self.diz(P.linha_hello())
        t0 = time.ticks_ms()
        prox_ping = 0
        prox_led = 0
        while True:
            agora = time.ticks_diff(time.ticks_ms(), t0)

            for i in self.debounce.passo(agora, _le_nivel(self.pinos)):
                # O 13o pino e o START; os 12 primeiros sao os semaforos.
                self.diz(P.linha_btn(P.BOTAO_START if i == P.N_BOTOES else i))

            self.le_host()

            if agora >= prox_led:
                prox_led = agora + PERIODO_LED_MS
                bat = (agora // P.HEARTBEAT_MS) % 2 == 0
                self.painel.escreve(P.palavra_595(self.estados, agora, heartbeat=bat))
                if self.led_placa is not None:
                    self.led_placa.value(1 if bat else 0)

            if agora >= prox_ping:
                prox_ping = agora + P.PING_MS
                self.diz("PING")

            if self.wdt is not None:
                self.wdt.feed()
            time.sleep_ms(1)


def _start_apertado():
    """Le o START uma vez, cru, antes de qualquer coisa (saida de emergencia)."""
    return machine.Pin(PINO_START, machine.Pin.IN, machine.Pin.PULL_UP).value() == 0


def bancada():
    """Auto-teste de bancada. Roda do REPL, sem host e sem jogo.

    1. mede o periodo do laco (o termo do orcamento de latencia que so a placa
       real sabe -- em `docs/BOTOEIRA.md` ele esta ESTIMADO em 2 ms; este numero
       e o medido, e e ele que vale);
    2. acende os 13 LEDs um a um -- confere fiacao e ordem da cascata;
    3. imprime cada botao apertado por 20 s -- confere pinagem e debounce.
    """
    b = Botoeira(com_watchdog=False)
    print("--- 1. periodo do laco (2000 iteracoes, sem USB do host) ---")
    t0 = time.ticks_ms()
    for _ in range(2000):
        b.debounce.passo(time.ticks_diff(time.ticks_ms(), t0), _le_nivel(b.pinos))
        b.le_host()
        time.sleep_ms(1)
    dt = time.ticks_diff(time.ticks_ms(), t0)
    print("periodo medio: %.3f ms/laco  (orcamento assume <= 2 ms)" % (dt / 2000.0))

    print("--- 2. varredura dos 13 LEDs ---")
    for i in range(P.N_BOTOES + 1):
        nome = "START" if i == P.N_BOTOES else "botao %d" % i
        estados = [P.OFF] * (P.N_BOTOES + 1)
        estados[i] = P.ACEITO
        b.painel.escreve(P.palavra_595(estados, 0))
        print("  aceso: %s" % nome)
        time.sleep_ms(400)
    b.painel.apaga()

    print("--- 3. botoes (20 s) --- aperte cada um; nada impresso = fio solto")
    t0 = time.ticks_ms()
    vistos = set()
    while time.ticks_diff(time.ticks_ms(), t0) < 20000:
        agora = time.ticks_diff(time.ticks_ms(), t0)
        for i in b.debounce.passo(agora, _le_nivel(b.pinos)):
            nome = "START (GP%d)" % PINO_START if i == P.N_BOTOES \
                else "botao %d (GP%d)" % (i, PINOS_BOTAO[i])
            vistos.add(i)
            print("  %s  t=%d ms" % (nome, agora))
        time.sleep_ms(2)
    faltam = [i for i in range(P.N_BOTOES + 1) if i not in vistos]
    print("nao apertados/nao detectados: %s" % (faltam if faltam else "nenhum -- 13/13 OK"))


def principal():
    if _start_apertado():
        print("START segurado no boot: firmware NAO iniciado, REPL livre.")
        print("Para rodar mesmo assim:  import main; main.principal()")
        print("Auto-teste de bancada:   import main; main.bancada()")
        return
    micropython.kbd_intr(-1)          # 0x03 vindo do host nao pode virar Ctrl-C
    Botoeira().roda()


if __name__ == "__main__":
    principal()
