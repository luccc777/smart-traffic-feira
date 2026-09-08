"""A4 — `SerialInput`: a botoeira física falando o protocolo serial do C6.

Este módulo implementa `feira.contratos.FonteEntrada` (C6) sobre a botoeira de 13
botões descrita em `hardware/botoeira/` e `firmware/botoeira/main.py`. Ele NÃO
inventa protocolo: fala exatamente o que `feira/contratos/entrada.py` congelou
(`PROTO_VERSAO`, `PROTO_BAUD`, `PROTO_TIMEOUT_S`, `PROTO_CHAR`).

O IMPORT DE `serial` É TARDIO — E ISSO É O PONTO
------------------------------------------------
`pyserial` **não** está instalado no venv compartilhado (medido: `find_spec` devolve
`None`). O jogo tem que rodar de teclado sem ele. Por isso o `import serial` mora
dentro de `_abre_porta_real()` e de `lista_portas()`, e não no topo: importar este
módulo num ambiente sem `pyserial` funciona, e é o que a suíte prova.

O QUE FAZ ESTA CLASSE SER TESTÁVEL SEM A BOTOEIRA NA MESA
---------------------------------------------------------
`SerialInput` nunca fala com `pyserial` — fala com um objeto que satisfaz
`PortaSerial` (cinco membros: `in_waiting`, `read`, `write`, `close`, `is_open`).
`SerialFalso`, aqui embaixo, é um **modelo do Pico em software**: decodifica
`LED`/`LEDS`/`RESET` e mantém os 13 estados de LED, e emite `HELLO`/`BTN`/`START`/
`PING` como o firmware emitiria. Com ele a suíte inteira roda hoje, sem hardware.

REGRA DE OURO: NADA AQUI PODE DERRUBAR A RODADA
-----------------------------------------------
Cabo USB saindo no meio da rodada é o caso NORMAL, não o excepcional. `poll()`,
`feedback()` e `viva()` engolem qualquer exceção da porta, marcam a fonte como
morta e devolvem o de sempre (lista vazia / nada / `False`). Quem decide cair para
o teclado é o motor do jogo, olhando `viva()` — nunca um traceback subindo.

LATÊNCIA
--------
`poll()` faz UMA leitura instantânea do que já está no buffer do sistema
(`in_waiting` bytes) e volta. Não drena em laço, não dorme, não bloqueia: o
trabalho por chamada é limitado pelo que chegou desde a chamada anterior. O custo
próprio disso é de microssegundos (medido em `tests/test_a4_latencia.py`); o termo
que domina a latência botão→evento é o PERÍODO DE POLLING DO MOTOR DO JOGO.
Orçamento fechado em `docs/BOTOEIRA.md` §latência: **o motor precisa chamar
`poll()` a ≥ 30 Hz** para o total ficar sob os 50 ms do DoD.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from typing import Protocol, runtime_checkable

from feira.contratos import (
    ACEITO,
    BOTAO_START,
    ESTADOS,
    OFF,
    PROTO_BAUD,
    PROTO_CHAR,
    PROTO_TIMEOUT_S,
    PROTO_VERSAO,
    EventoBotao,
    valida_estados,
)

__all__ = [
    "SerialInput",
    "SerialFalso",
    "PortaSerial",
    "BotoeiraAusente",
    "BotoeiraIncompativel",
    "abre_botoeira",
    "porta_falsa",
    "lista_portas",
    "detecta_porta",
    "quadro_leds",
    "N_BOTOES_PADRAO",
    "VID_PICO",
    "PID_PICO_MICROPYTHON",
]

# --------------------------------------------------------------------- constantes

N_BOTOES_PADRAO = 12          # os 12 semáforos da rede aberta; o START não conta

# Raspberry Pi Pico rodando MicroPython, enumerado como USB CDC. Serve para achar
# a porta sozinho em vez de pedir "COM?" ao operador na hora da feira.
VID_PICO = 0x2E8A
PID_PICO_MICROPYTHON = 0x0005

# Teto do pedaço de linha ainda sem "\n" guardado entre dois `poll()`. Um
# dispositivo em pane pode cuspir bytes sem quebrar linha para sempre; acima disto
# o resto é descartado em vez de crescer sem limite.
LIMITE_RESTO_B = 4096

# Teto da fila de eventos ainda não colhidos. Se o motor do jogo travar e parar de
# chamar `poll()`, a fila para de crescer e os eventos MAIS ANTIGOS são descartados
# (o visitante quer que valha o último aperto, não o primeiro de um minuto atrás).
LIMITE_PENDENTES = 256

# Reverso do PROTO_CHAR, para o `SerialFalso` decodificar o quadro `LEDS`.
_CHAR_PARA_ESTADO = {c: e for e, c in PROTO_CHAR.items()}


class BotoeiraAusente(RuntimeError):
    """Não achou a porta, ou o `HELLO` não veio dentro do prazo."""


class BotoeiraIncompativel(RuntimeError):
    """O `HELLO` veio, mas com outra versão de protocolo ou outro número de botões."""


@runtime_checkable
class PortaSerial(Protocol):
    """O subconjunto de `serial.Serial` que esta classe usa — e só ele.

    Cinco membros. É o tamanho desta superfície que permite substituir a botoeira
    por software na suíte inteira; se `SerialInput` chamasse `readline()` (que
    bloqueia) ou `flush()`, o falso teria que simular bloqueio e o teste viraria
    ficção.
    """

    is_open: bool

    @property
    def in_waiting(self) -> int: ...

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


def quadro_leds(estados: Sequence[str], estado_start: str = OFF) -> str:
    """Os `n+1` caracteres do comando `LEDS`, na ordem do C6.

    Convenção adotada (o C6 não fixa a posição do START — ver `docs/BOTOEIRA.md`
    §defeitos do C6): **o START é o ÚLTIMO caractere**. Assim `quadro[BOTAO_START]`
    == `quadro[-1]` é literalmente o LED do botão grande, e o índice do contrato
    indexa o quadro sem tradução.
    """
    if estado_start not in ESTADOS:
        raise ValueError("estado do START desconhecido %r (use %r)" % (estado_start, ESTADOS))
    return "".join(PROTO_CHAR[e] for e in estados) + PROTO_CHAR[estado_start]


# ============================================================== a fonte de entrada


class SerialInput:
    """`FonteEntrada` (C6) sobre a botoeira física.

    Não abre porta nenhuma: recebe uma `PortaSerial` já aberta. Quem descobre a
    porta e instancia `serial.Serial` é `abre_botoeira()` — que é onde o import
    tardio de `pyserial` mora.
    """

    def __init__(
        self,
        porta: PortaSerial,
        *,
        n_botoes: int = N_BOTOES_PADRAO,
        timeout_s: float = PROTO_TIMEOUT_S,
        relogio: Callable[[], float] = time.monotonic,
        espera_hello: bool = True,
        prazo_hello_s: float = PROTO_TIMEOUT_S,
    ) -> None:
        self.n_botoes = int(n_botoes)
        self.nome = "botoeira"
        self._porta = porta
        self._timeout_s = float(timeout_s)
        self._relogio = relogio
        self._resto = b""
        self._pendentes: list[EventoBotao] = []
        self._fechada = False
        self._morta = False
        self.motivo_morte: str | None = None
        # Última coisa que sabemos ter recebido do dispositivo. Qualquer linha
        # não-vazia renova: o `PING` a 1 Hz é o PISO que garante renovação mesmo
        # com ninguém apertando nada, não a única fonte de vida.
        self._ultimo_sinal = relogio()
        # Espelho do que mandamos acender, para (a) não reenviar quadro igual a
        # cada tick e (b) restaurar depois de um `HELLO` fora de hora (= o Pico
        # reiniciou sozinho, provavelmente pelo watchdog).
        self._estados: list[str] = [OFF] * self.n_botoes
        self._estado_start = OFF
        self._ultimo_quadro: str | None = None
        self.linhas_ignoradas = 0
        self.hellos_recebidos = 0

        if espera_hello:
            self._aguarda_hello(prazo_hello_s)

    # ------------------------------------------------------------------ C6

    def poll(self) -> list[EventoBotao]:
        """Bordas desde a última chamada. Não bloqueia, não dorme, não drena em laço."""
        self._bombeia()
        if not self._pendentes:
            return []
        eventos, self._pendentes = self._pendentes, []
        return eventos

    def feedback(self, estados: list[str], start: str | None = None) -> None:
        """Acende os LEDs dos semáforos e, se `start` vier, o do botão grande.

        Um quadro só para os treze: o `LEDS` do protocolo já é `n+1`, e mandar
        dois quadros faria o START piscar de fora de fase com os semáforos."""
        self._estados = list(valida_estados(list(estados), self.n_botoes))
        if start is not None:
            self._estado_start = valida_estados([start], 1)[0]
        self._envia_quadro()

    def viva(self) -> bool:
        """`False` quando o `PING` falta por `PROTO_TIMEOUT_S`, ou a porta morreu.

        Bombeia a porta antes de responder — de propósito. Sem isso `viva()`
        mentiria para quem a chamasse antes do `poll()` do tick: reportaria morte
        por silêncio quando o `PING` já estava no buffer do sistema operacional,
        derrubando a botoeira por uma ordem de chamada. Os eventos lidos aqui vão
        para a fila e saem no `poll()` seguinte: nada se perde.
        """
        if self._fechada or self._morta:
            return False
        self._bombeia()
        if self._morta:
            return False
        return (self._relogio() - self._ultimo_sinal) <= self._timeout_s

    def close(self) -> None:
        self._fechada = True
        try:
            self._porta.close()
        except Exception:          # noqa: BLE001 - fechar não pode falhar para cima
            pass

    # ---------------------------------------------------- fora do Protocol C6

    def feedback_start(self, estado: str) -> None:
        """Acende o botão grande. **Não está no C6** — ver §defeitos em BOTOEIRA.md.

        `feedback()` recebe `n` estados e o quadro `LEDS` tem `n+1` caracteres: o
        contrato não tem por onde dizer o estado do START. Enquanto o C6 não abrir
        espaço, o motor do jogo chama isto (com `getattr`, para o teclado não
        precisar implementar).
        """
        if estado not in ESTADOS:
            raise ValueError("estado desconhecido %r (use %r)" % (estado, ESTADOS))
        self._estado_start = estado
        self._envia_quadro()

    def led(self, indice: int, estado: str) -> None:
        """Comando `LED <i> <estado>` — um LED só. Diagnóstico de bancada.

        `indice` aceita `0..n-1` e `BOTAO_START`. O jogo usa `feedback()`, que
        manda o quadro inteiro num write só; isto existe para o teste de conexão
        (`python -m feira.entrada_serial --chase`) e para conferir fiação.
        """
        if estado not in ESTADOS:
            raise ValueError("estado desconhecido %r (use %r)" % (estado, ESTADOS))
        if indice != BOTAO_START and not (0 <= indice < self.n_botoes):
            raise ValueError("índice de LED fora de faixa: %r" % (indice,))
        if indice == BOTAO_START:
            self._estado_start = estado
        else:
            self._estados[indice] = estado
        # Manda o comando de um LED só, mas atualiza o espelho: senão o próximo
        # `feedback()` acharia que o quadro não mudou e não reenviaria.
        self._ultimo_quadro = quadro_leds(self._estados, self._estado_start)
        self._escreve("LED %d %s\n" % (indice, estado))

    def reset(self) -> None:
        """Comando `RESET`: apaga tudo no dispositivo e pede um `HELLO` novo."""
        self._estados = [OFF] * self.n_botoes
        self._estado_start = OFF
        self._ultimo_quadro = None
        self._escreve("RESET\n")

    @property
    def estados_espelhados(self) -> tuple[str, ...]:
        """O que ACHAMOS que está aceso (12 semáforos + START). Só diagnóstico."""
        return (*self._estados, self._estado_start)

    # ------------------------------------------------------------- internals

    def _aguarda_hello(self, prazo_s: float) -> None:
        """Handshake: `RESET` e espera o `HELLO`. Prazo em tempo de PAREDE.

        O prazo NÃO usa `self._relogio` de propósito: um teste que congela o
        relógio para exercitar o timeout do `PING` não pode congelar junto o
        handshake e travar o processo.
        """
        self._escreve("RESET\n")
        if self._morta:
            raise BotoeiraAusente("porta morreu ao escrever RESET: %s" % self.motivo_morte)
        fim = time.monotonic() + max(0.0, prazo_s)
        while True:
            for linha in self._le_linhas():
                if not linha:
                    continue
                self._ultimo_sinal = self._relogio()
                self._interpreta(linha)
            if self.hellos_recebidos:
                return
            if self._morta:
                raise BotoeiraAusente("porta morreu no handshake: %s" % self.motivo_morte)
            if time.monotonic() >= fim:
                raise BotoeiraAusente(
                    "sem HELLO em %.1f s — dispositivo mudo, cabo de dados errado "
                    "(cabo só-carga é o erro clássico) ou firmware não rodando" % prazo_s
                )
            time.sleep(0.005)

    def _confere_hello(self, linha: str) -> None:
        """`HELLO botoeira v1 n=12` — versão e número de botões têm que bater."""
        corpo = linha[len("HELLO"):].strip()
        n_dito = None
        for pedaco in corpo.split():
            if pedaco.startswith("n="):
                try:
                    n_dito = int(pedaco[2:])
                except ValueError:
                    n_dito = None
        if not corpo.startswith(PROTO_VERSAO):
            raise BotoeiraIncompativel(
                "protocolo do dispositivo é %r, este host fala %r" % (corpo, PROTO_VERSAO)
            )
        if n_dito is None:
            raise BotoeiraIncompativel("HELLO sem n=: %r" % linha)
        if n_dito != self.n_botoes:
            raise BotoeiraIncompativel(
                "dispositivo diz n=%d, o cenário tem %d semáforos — painel errado "
                "ou firmware de outra rede" % (n_dito, self.n_botoes)
            )
        primeiro = self.hellos_recebidos == 0
        self.hellos_recebidos += 1
        if not primeiro:
            # HELLO fora de hora = o Pico reiniciou (watchdog, glitch de USB). Ele
            # acordou com os LEDs apagados; reenvia o quadro para o painel não
            # ficar mentindo para o visitante.
            self._ultimo_quadro = None
            self._envia_quadro()

    def _bombeia(self) -> None:
        """Uma leitura instantânea, parse e enfileira. O único caminho de entrada."""
        if self._fechada or self._morta:
            return
        for linha in self._le_linhas():
            if not linha:
                continue
            self._ultimo_sinal = self._relogio()
            try:
                self._interpreta(linha)
            except BotoeiraIncompativel as e:
                self._morre("dispositivo incompatível: %s" % e)
                return

    def _le_linhas(self) -> list[str]:
        try:
            n = self._porta.in_waiting
            bruto = self._porta.read(n) if n else b""
        except Exception as e:                       # noqa: BLE001 - cabo saiu
            self._morre("erro de leitura: %r" % (e,))
            return []
        if not bruto:
            return []
        dados = self._resto + bruto
        partes = dados.split(b"\n")
        self._resto = partes.pop()
        if len(self._resto) > LIMITE_RESTO_B:
            self._resto = b""
            self.linhas_ignoradas += 1
        return [p.decode("ascii", "replace").strip() for p in partes]

    def _interpreta(self, linha: str) -> None:
        if linha == "PING":
            return                                   # só liveness; já renovou
        if linha == "START":
            self._enfileira(BOTAO_START)
            return
        if linha.startswith("BTN "):
            try:
                i = int(linha[4:])
            except ValueError:
                self.linhas_ignoradas += 1
                return
            if 0 <= i < self.n_botoes:
                self._enfileira(i)
            else:
                self.linhas_ignoradas += 1
            return
        if linha.startswith("HELLO"):
            self._confere_hello(linha)
            return
        # Linha desconhecida é IGNORADA, nunca fatal: um firmware mais novo pode
        # falar mais coisas, e o eco de um terminal esquecido aberto na porta não
        # pode derrubar a rodada.
        self.linhas_ignoradas += 1

    def _enfileira(self, indice: int) -> None:
        if len(self._pendentes) >= LIMITE_PENDENTES:
            del self._pendentes[0]
        self._pendentes.append(EventoBotao(indice=indice, t_wall=self._relogio()))

    def _envia_quadro(self) -> None:
        quadro = quadro_leds(self._estados, self._estado_start)
        if quadro == self._ultimo_quadro:
            return                                   # nada mudou: não polui a CDC
        self._ultimo_quadro = quadro
        self._escreve("LEDS %s\n" % quadro)

    def _escreve(self, texto: str) -> None:
        if self._fechada or self._morta:
            return
        try:
            self._porta.write(texto.encode("ascii"))
        except Exception as e:                       # noqa: BLE001 - cabo saiu
            self._morre("erro de escrita: %r" % (e,))

    def _morre(self, motivo: str) -> None:
        if not self._morta:
            self._morta = True
            self.motivo_morte = motivo


# ============================================================== abertura da porta


def lista_portas() -> list[tuple[str, str, int | None, int | None]]:
    """`[(porta, descrição, vid, pid)]`. Import de `pyserial` TARDIO.

    Devolve `[]` (não levanta) quando `pyserial` não está instalado: quem chama é
    o diagnóstico e o auto-detect, e nenhum dos dois pode explodir num ambiente
    que só vai jogar de teclado.
    """
    try:
        from serial.tools import list_ports  # noqa: PLC0415 - tardio de propósito
    except ImportError:
        return []
    return [(p.device, p.description or "", p.vid, p.pid) for p in list_ports.comports()]


def detecta_porta() -> str | None:
    """A primeira porta com VID/PID de Pico em MicroPython, senão `None`."""
    for dispositivo, _desc, vid, pid in lista_portas():
        if vid == VID_PICO and pid == PID_PICO_MICROPYTHON:
            return dispositivo
    return None


def _abre_porta_real(porta: str, prazo_escrita_s: float = 0.5) -> PortaSerial:
    import serial  # noqa: PLC0415 - tardio de propósito

    # timeout=0 -> leitura NÃO BLOQUEANTE. É o que casa com o desenho de `poll()`:
    # ler exatamente `in_waiting` bytes e voltar. Com timeout>0 um `read` de um
    # buffer vazio dormiria e o jogo perderia frame.
    return serial.Serial(porta, PROTO_BAUD, timeout=0, write_timeout=prazo_escrita_s)


def abre_botoeira(
    porta: str | None = None,
    *,
    n_botoes: int = N_BOTOES_PADRAO,
    obrigatoria: bool = False,
    **kwargs,
) -> SerialInput | None:
    """Acha a botoeira, abre e faz o handshake. `None` se não houver (a menos de
    `obrigatoria=True`, que levanta `BotoeiraAusente`).

    Este é o caminho que o motor do jogo chama no boot: `fonte = abre_botoeira()
    or TecladoInput(12)`. Sem `pyserial`, sem cabo, ou com firmware velho, a
    resposta é a mesma — `None` — e o teclado assume.
    """
    try:
        alvo = porta or detecta_porta()
        if alvo is None:
            raise BotoeiraAusente(
                "nenhuma porta com VID:PID %04X:%04X (Pico/MicroPython). "
                "Portas vistas: %s" % (VID_PICO, PID_PICO_MICROPYTHON,
                                       [p[0] for p in lista_portas()] or "nenhuma "
                                       "(pyserial instalado?)")
            )
        p = _abre_porta_real(alvo)
        fonte = SerialInput(p, n_botoes=n_botoes, **kwargs)
    except (BotoeiraAusente, BotoeiraIncompativel, ImportError, OSError):
        if obrigatoria:
            raise
        return None
    return fonte


# ================================================================ o Pico em software


class SerialFalso:
    """Modelo do Pico em software. Fala os dois lados do protocolo do C6.

    É isto que dá DoD verificável hoje: a suíte inteira roda contra ele, sem a
    botoeira na mesa. Ele NÃO é um mock permissivo — decodifica `LED`/`LEDS`/
    `RESET` e mantém os 13 estados, então um `feedback()` errado do host aparece
    como LED errado aqui, não como "chamada registrada".

    Cadência dos eventos (`roteiro`): uma lista de LOTES. `SerialInput.poll()` faz
    UMA leitura instantânea por chamada, então "um lote por leitura de buffer
    vazio" reproduz exatamente a semântica de `FonteEntradaFake` da suíte de
    conformidade — `[[0, 3], [], [BOTAO_START]]` sai como `[0,3]`, `[]`,
    `[START]`, `[]`... e é por isso que `SerialInput(porta_falsa())` passa a mesma
    suíte que o teclado.
    """

    def __init__(
        self,
        roteiro: Iterable[Iterable[int]] | None = None,
        *,
        n_botoes: int = N_BOTOES_PADRAO,
        hello_no_boot: bool = True,
        versao: str = PROTO_VERSAO,
    ) -> None:
        self.n_botoes = int(n_botoes)
        self.versao = versao
        self.is_open = True
        self._rx = bytearray()                        # dispositivo -> host
        self._roteiro = [list(lote) for lote in (roteiro or [])]
        self._i_lote = 0
        self._desconectada = False
        self._erro: Exception = OSError(22, "dispositivo removido (cabo USB)")
        self.leds: list[str] = [OFF] * (self.n_botoes + 1)   # 12 + START (último)
        self.recebido: list[str] = []                 # linhas host -> dispositivo
        self.resets = 0
        self.bytes_escritos = 0
        if hello_no_boot:
            self.emite(self._hello())

    # -------------------------------------------- API que o SerialInput usa

    @property
    def in_waiting(self) -> int:
        self._checa_viva()
        if not self._rx:
            self._proximo_lote()
        return len(self._rx)

    def read(self, size: int = 1) -> bytes:
        self._checa_viva()
        if size <= 0:
            return b""
        pedaco = bytes(self._rx[:size])
        del self._rx[:size]
        return pedaco

    def write(self, data: bytes) -> int:
        self._checa_viva()
        self.bytes_escritos += len(data)
        for linha in data.decode("ascii", "replace").split("\n"):
            linha = linha.strip()
            if linha:
                self.recebido.append(linha)
                self._executa(linha)
        return len(data)

    def close(self) -> None:
        self.is_open = False

    # ------------------------------------------------ controle pelos testes

    def emite(self, linha: str) -> None:
        """Coloca uma linha no buffer do dispositivo -> host, agora."""
        self._rx.extend(("%s\n" % linha).encode("ascii"))

    def aperta(self, indice: int) -> None:
        """Uma borda de botão, agora. `BOTAO_START` vira a linha `START`."""
        if indice == BOTAO_START:
            self.emite("START")
        elif 0 <= indice < self.n_botoes:
            self.emite("BTN %d" % indice)
        else:
            raise ValueError("índice de botão fora de faixa: %r" % (indice,))

    def ping(self) -> None:
        """O heartbeat de 1 Hz do firmware."""
        self.emite("PING")

    def desconecta(self, erro: Exception | None = None) -> None:
        """O cabo USB saindo da tomada NO MEIO DA RODADA.

        Toda operação passa a levantar, como faz o driver do Windows quando o
        dispositivo CDC some (`OSError`/`SerialException` no `in_waiting`). É a
        prova do item (c) do DoD: `SerialInput` engole isso, `viva()` vira `False`
        e o motor cai para o teclado — sem traceback.
        """
        self._desconectada = True
        self._erro = erro or OSError(22, "dispositivo removido (cabo USB)")

    def reinicia(self) -> None:
        """O Pico voltando do watchdog no meio da rodada: LEDs apagados + HELLO."""
        self.leds = [OFF] * (self.n_botoes + 1)
        self.emite(self._hello())

    @property
    def led_start(self) -> str:
        return self.leds[BOTAO_START]

    # ------------------------------------------------------------ internals

    def _hello(self) -> str:
        return "HELLO %s n=%d" % (self.versao, self.n_botoes)

    def _checa_viva(self) -> None:
        if self._desconectada:
            raise self._erro
        if not self.is_open:
            raise OSError("porta fechada")

    def _proximo_lote(self) -> None:
        if self._i_lote >= len(self._roteiro):
            return
        lote = self._roteiro[self._i_lote]
        self._i_lote += 1
        for indice in lote:
            self.aperta(indice)

    def _executa(self, linha: str) -> None:
        """O firmware do lado de cá: aplica `LED`/`LEDS`/`RESET` nos 13 LEDs."""
        if linha == "RESET":
            self.resets += 1
            self.leds = [OFF] * (self.n_botoes + 1)
            self.emite(self._hello())
            return
        if linha.startswith("LEDS "):
            quadro = linha[5:].strip()
            if len(quadro) != self.n_botoes + 1:
                raise AssertionError(
                    "quadro LEDS com %d chars, esperado %d (12 semáforos + START)"
                    % (len(quadro), self.n_botoes + 1)
                )
            novos = []
            for c in quadro:
                if c not in _CHAR_PARA_ESTADO:
                    raise AssertionError("char de LED desconhecido %r em %r" % (c, quadro))
                novos.append(_CHAR_PARA_ESTADO[c])
            self.leds = novos
            return
        if linha.startswith("LED "):
            _, i_txt, estado = linha.split(maxsplit=2)
            i = int(i_txt)
            if estado not in ESTADOS:
                raise AssertionError("estado de LED desconhecido %r" % (estado,))
            # -1 (BOTAO_START) e n endereçam o MESMO LED físico: o botão grande.
            if i == BOTAO_START or i == self.n_botoes:
                self.leds[BOTAO_START] = estado
            elif 0 <= i < self.n_botoes:
                self.leds[i] = estado
            else:
                raise AssertionError("índice de LED fora de faixa: %d" % i)
            return
        raise AssertionError("comando desconhecido do host: %r" % (linha,))


def porta_falsa(
    roteiro: Iterable[Iterable[int]] | None = None,
    *,
    n_botoes: int = N_BOTOES_PADRAO,
    **kwargs,
) -> SerialFalso:
    """Uma botoeira de software pronta para `SerialInput(porta_falsa())`.

    O roteiro default é o MESMO da `FonteEntradaFake` da suíte de conformidade —
    `[[0, 3], [], [BOTAO_START]]` — para que a linha comentada em
    `tests/test_conformidade.py` (`SerialInput(porta_falsa())`) funcione literal,
    sem argumento nenhum, no dia em que ela for descomentada.
    """
    if roteiro is None:
        roteiro = [[0, 3], [], [BOTAO_START]]
    return SerialFalso(roteiro, n_botoes=n_botoes, **kwargs)


# ==================================================================== diagnóstico


def _cli(argv: Sequence[str] | None = None) -> int:
    """`python -m feira.entrada_serial` — bancada sem o jogo. Ver docs/BOTOEIRA.md."""
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(
        prog="python -m feira.entrada_serial",
        description="Bancada da botoeira: lista portas, lê botões, acende LEDs.",
    )
    ap.add_argument("--porta", help="COM7, /dev/ttyACM0... (default: auto-detect)")
    ap.add_argument("--lista", action="store_true", help="só lista as portas e sai")
    ap.add_argument("--chase", action="store_true",
                    help="acende os 13 LEDs em sequência e sai (confere fiação)")
    ap.add_argument("--segundos", type=float, default=30.0, help="duração da leitura")
    ap.add_argument("--falsa", action="store_true",
                    help="usa o Pico em software (sem hardware, sem pyserial)")
    a = ap.parse_args(argv)

    if a.lista:
        portas = lista_portas()
        if not portas:
            print("nenhuma porta (pyserial instalado? `pip install pyserial`)")
        for dispositivo, desc, vid, pid in portas:
            marca = "  <- BOTOEIRA?" if (vid, pid) == (VID_PICO, PID_PICO_MICROPYTHON) else ""
            print("%-12s %-40s %s:%s%s" % (
                dispositivo, desc,
                "%04X" % vid if vid else "----", "%04X" % pid if pid else "----", marca))
        return 0

    if a.falsa:
        fonte: SerialInput | None = SerialInput(porta_falsa())
        print("usando o Pico EM SOFTWARE (--falsa): nenhum hardware envolvido")
    else:
        fonte = abre_botoeira(a.porta)
        if fonte is None:
            print("botoeira não encontrada. `--lista` para ver as portas, "
                  "`--falsa` para exercitar sem hardware.")
            return 1
        print("botoeira aberta: %d botões + START" % fonte.n_botoes)

    try:
        if a.chase:
            for i in [*range(fonte.n_botoes), BOTAO_START]:
                fonte.led(i, ACEITO)
                print("LED %d aceso — confira o painel" % i)
                time.sleep(0.35)
                fonte.led(i, OFF)
            return 0
        fim = time.monotonic() + a.segundos
        print("apertando botões... (%.0f s)" % a.segundos)
        while time.monotonic() < fim:
            if not fonte.viva():
                print("botoeira MORREU: %s" % (fonte.motivo_morte or "sem PING"))
                return 2
            for e in fonte.poll():
                print("  %s  t=%.3f" % ("START" if e.e_start else "botão %2d" % e.indice,
                                        e.t_wall))
            time.sleep(0.02)                          # ~50 Hz, o piso do orçamento
    finally:
        fonte.close()
    return 0


if __name__ == "__main__":                            # pragma: no cover
    raise SystemExit(_cli())
