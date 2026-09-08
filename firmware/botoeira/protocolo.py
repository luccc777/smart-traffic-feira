"""Botoeira — a LOGICA do firmware, sem uma linha de hardware.

Este modulo roda igual no MicroPython do Pico e no CPython do notebook. E de
proposito: debounce, parser de comando, padrao de piscada e mapeamento dos
74HC595 sao exatamente as partes do firmware que erram calado, e sao as unicas
que dava para provar sem a botoeira na mesa. `tests/test_a4_firmware.py` exercita
ESTE arquivo -- o mesmo que sobe para o Pico, nao uma reimplementacao.

Restricoes de MicroPython respeitadas aqui: sem `__future__`, sem `typing`, sem
`dataclasses`, sem f-string com `=`, sem anotacao de tipo. So `%` e classes.

DIVERGENCIA DE CONSTANTE E O RISCO DESTE ARQUIVO
------------------------------------------------
O Pico nao consegue importar `feira.contratos.entrada`, entao VERSAO/CHAR/ESTADOS
estao repetidos aqui. Duas listas divergem -- ja divergiram neste projeto. A
mitigacao e um teste que compara constante a constante com o C6
(`test_a4_firmware.py::test_constantes_do_firmware_batem_com_o_contrato`): a
divergencia vira teste vermelho, nao bug no dia da feira.
"""

# ----------------------------------------------------------------- protocolo C6
VERSAO = "botoeira v1"
N_BOTOES = 12                  # semaforos; o START nao conta
BOTAO_START = -1

OFF = "off"
ARMADO = "armed"
ACEITO = "on"
NEGADO = "deny"
ESTADOS = (OFF, ARMADO, ACEITO, NEGADO)
CHAR = {OFF: "o", ARMADO: "a", ACEITO: "n", NEGADO: "d"}
CHAR_INV = {"o": OFF, "a": ARMADO, "n": ACEITO, "d": NEGADO}

# ------------------------------------------------------------------ cadencias
DEBOUNCE_MS = 15               # trava do contato; NAO entra na latencia (ver abaixo)
PING_MS = 1000                 # heartbeat de liveness (o host desiste em 2 s)
PISCA_ARMADO_MS = 125          # meio periodo -> 4 Hz
PISCA_NEGADO_MS = 50           # meio periodo -> 10 Hz
HEARTBEAT_MS = 500             # LED de "firmware vivo" (canal QF do U2)

# Posicao do LED do START no vetor de 13. O C6 nao fixa isso; a convencao do
# projeto e "o START e o ULTIMO", porque BOTAO_START == -1 e vetor[-1] e o ultimo.
I_START = N_BOTOES


def linha_hello(n=N_BOTOES):
    return "HELLO %s n=%d" % (VERSAO, n)


def linha_btn(indice):
    """A linha que o dispositivo manda quando o botao desce."""
    if indice == BOTAO_START:
        return "START"
    return "BTN %d" % indice


class Linhas:
    """Acumulador de caracteres -> linhas completas.

    A CDC entrega o que quiser, quando quiser: meia linha agora, o resto no
    proximo laco. Sem isto o parser cortaria comando no meio e o painel piscaria
    errado no meio da rodada.
    """

    def __init__(self, limite=256):
        self.limite = limite
        self._buf = ""
        self.descartadas = 0

    def alimenta(self, texto):
        """Devolve a lista de linhas COMPLETAS que fecharam com este pedaco."""
        if not texto:
            return []
        self._buf += texto
        if "\n" not in self._buf:
            if len(self._buf) > self.limite:     # host mudo cuspindo lixo
                self._buf = ""
                self.descartadas += 1
            return []
        partes = self._buf.split("\n")
        self._buf = partes.pop()
        saida = []
        for p in partes:
            p = p.strip()
            if p:
                saida.append(p)
        return saida


def interpreta(linha, n=N_BOTOES):
    """Comando do host -> `(tipo, dado)`.

    `("leds", [13 estados])` | `("led", (i, estado))` | `("reset", None)` |
    `(None, linha)` para qualquer outra coisa -- que e IGNORADA, nunca fatal: um
    terminal esquecido aberto na porta nao pode derrubar o painel.
    """
    if linha == "RESET":
        return ("reset", None)
    if linha.startswith("LEDS "):
        quadro = linha[5:].strip()
        if len(quadro) != n + 1:
            return (None, linha)
        estados = []
        for c in quadro:
            if c not in CHAR_INV:
                return (None, linha)
            estados.append(CHAR_INV[c])
        return ("leds", estados)
    if linha.startswith("LED "):
        pedacos = linha.split()
        if len(pedacos) != 3:
            return (None, linha)
        try:
            i = int(pedacos[1])
        except ValueError:
            return (None, linha)
        estado = pedacos[2]
        if estado not in ESTADOS:
            return (None, linha)
        # -1 (o indice do contrato) e n (a posicao no quadro) endereçam o MESMO
        # LED fisico: o botao grande. Aceitar os dois evita um bug de off-by-one
        # entre quem le o C6 e quem le o quadro `LEDS`.
        if i == BOTAO_START or i == n:
            return ("led", (n, estado))
        if 0 <= i < n:
            return ("led", (i, estado))
        return (None, linha)
    return (None, linha)


class Debounce:
    """Borda de descida com trava, reportando na PRIMEIRA deteccao.

    POR QUE "PRIMEIRA DETECCAO" E NAO "ESTAVEL POR 15 ms"
    -----------------------------------------------------
    O debounce classico so aceita o aperto depois de 15 ms estaveis -- e ai os
    15 ms entram inteiros na latencia botao->evento, que o DoD limita a 50 ms.
    Aqui a borda sai no primeiro laco em que o contato desce (contribuicao ~0 ms)
    e a trava de 15 ms serve para o RETORNO: enquanto ela nao vencer, nem um
    repique nem um novo aperto contam. O trecho do teclado mecanico que ricocheteia
    e sempre DEPOIS do primeiro contato, entao o primeiro contato ja e verdadeiro.

    Efeito colateral desejado: quem SEGURA o botao gera UMA borda, nunca uma por
    laco -- que e exatamente o que o C6 exige de `poll()` ("borda, nunca nivel").
    """

    def __init__(self, n, debounce_ms=DEBOUNCE_MS):
        self.n = n
        self.debounce_ms = debounce_ms
        self._preso = [False] * n
        self._t = [-1000000] * n

    def sincroniza(self, nivel):
        """Adota o nivel atual como repouso, sem gerar borda.

        Chamado uma vez no boot: um botao emperrado (ou um dedo em cima na hora de
        plugar) nao pode virar um aperto fantasma antes de o jogo comecar.
        """
        for i in range(self.n):
            self._preso[i] = bool(nivel[i])

    def passo(self, agora_ms, nivel):
        """`nivel[i]` True = apertado. Devolve os indices que ACABARAM de descer."""
        bordas = []
        for i in range(self.n):
            dt = agora_ms - self._t[i]
            apertado = bool(nivel[i])
            if apertado and not self._preso[i]:
                if dt >= self.debounce_ms:
                    self._preso[i] = True
                    self._t[i] = agora_ms
                    bordas.append(i)
            elif (not apertado) and self._preso[i]:
                if dt >= self.debounce_ms:
                    self._preso[i] = False
                    self._t[i] = agora_ms
        return bordas


def aceso(estado, fase_ms):
    """O LED esta aceso NESTE instante? Os 4 estados num LED de uma cor so.

    Um 74HC595 liga ou desliga -- nao tem meio-brilho. Entao a diferenca entre os
    quatro estados do C6 e TEMPORAL, e as duas piscadas foram escolhidas para
    serem distinguiveis de relance por um visitante a um metro:

        off    apagado
        armed  4 Hz  (pisca calmo)  "ouvi, esta na fila do proximo tick"
        on     aceso fixo           "trocou agora"
        deny   10 Hz (gagueja)      "ainda nao: verde minimo"
    """
    if estado == ACEITO:
        return True
    if estado == ARMADO:
        return (fase_ms // PISCA_ARMADO_MS) % 2 == 0
    if estado == NEGADO:
        return (fase_ms // PISCA_NEGADO_MS) % 2 == 0
    return False


def palavra_595(estados, fase_ms, heartbeat=False):
    """Os 2 bytes do shift-out, na ordem em que saem pelo SPI.

    Cascata: MCU -> U1.SER(14); U1.QH'(9) -> U2.SER(14). O primeiro byte que sai
    atravessa o U1 e PARA NO U2 -- por isso a saida e `(byte_U2, byte_U1)`.
    Dentro do byte, MSB primeiro: o primeiro bit acaba em QH, o ultimo em QA.

        U1  QA..QH  = botoes 0..7
        U2  QA..QD  = botoes 8..11
            QE      = START
            QF      = heartbeat do firmware (pisca sozinho, sem host)
            QG,QH   = reserva (3 saidas sobrando de 16)
    """
    u1 = 0
    for i in range(8):
        if aceso(estados[i], fase_ms):
            u1 |= 1 << i
    u2 = 0
    for i in range(8, N_BOTOES):
        if aceso(estados[i], fase_ms):
            u2 |= 1 << (i - 8)
    if aceso(estados[I_START], fase_ms):
        u2 |= 1 << 4
    if heartbeat:
        u2 |= 1 << 5
    return bytes([u2, u1])
