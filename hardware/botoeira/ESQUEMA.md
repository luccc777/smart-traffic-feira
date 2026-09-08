# Botoeira SmartTraffic — esquema elétrico, pinagem e orçamento de energia

**13 botões arcade iluminados sobre Raspberry Pi Pico (RP2040), USB CDC nativo**
Iniciação Científica FIAP · Semáforos Inteligentes · agente A4 · rede aberta (12 TLs)

Companheiros deste arquivo: [`BOM.md`](BOM.md) (custo em R$), [`gabarito.py`](gabarito.py)
+ [`gabarito_painel.svg`](gabarito_painel.svg) (furação 1:1), `firmware/botoeira/`
(MicroPython) e [`docs/BOTOEIRA.md`](../../docs/BOTOEIRA.md) (montar, testar, diagnosticar).

Estilo e rigor herdados do [guia de eletrônica dos carrinhos](../../../smart-traffic-maquete/hardware/GUIA_ELETRONICA.md).
Onde uma conclusão contraria a intuição, está marcada ⚠️.

---

## 1. Sumário executivo

| Bloco | Escolha | Por quê |
|---|---|---|
| Microcontrolador | **Raspberry Pi Pico (RP2040)** | USB CDC nativo (zero driver no Windows), MicroPython, 26 GPIOs |
| Entrada | **13 GPIOs diretos**, pull-up interno, ativo-baixo | 13 fios contra 3 de um 74HC165 — mas dentro da caixa, e sem um segundo barramento para depurar |
| Saída de LED | **2× 74HC595** em cascata (3 pinos) + **2× ULN2803A** | 16 saídas para 13 LEDs; o ULN permite trilho de 5 V **ou 12 V** sem trocar nada do lado lógico |
| Protocolo | ASCII por linha sobre a CDC (C6 congelado) | depurável em qualquer terminal, falsificável por script |
| Alimentação | VBUS do USB, com **jumper para fonte externa** | 300 mA cabem nos 500 mA da porta — com 200 mA de margem e um "se" (§6) |

**Zero lógica de jogo no microcontrolador.** Ele reporta bordas e acende o que
mandarem. Verde mínimo, aceitação de troca, placar: tudo no host.

**Orçamento de pinos:** 13 (botões) + 4 (painel) = **17 de 26**. Sobram 9.

---

## 2. Por que Pico e não o ESP32-C3 do guia dos carrinhos

O C3 SuperMini expõe ~11 GPIOs úteis. **13 botões não cabem** — e nem com um
74HC165 valeria: seriam 3 pinos do 595 + 3 do 165 + as armadilhas de dois
barramentos seriais concorrentes no mesmo laço, para economizar uma placa de
R$ 45 num projeto de R$ 430. Some a isso que o CDC do C3 é o USB-Serial/JTAG
integrado, que no Windows já deu trabalho no projeto, contra o CDC do RP2040 que
enumera como porta COM e nunca pede driver.

| | ESP32-C3 SuperMini | **Pico (RP2040)** |
|---|---|---|
| GPIOs úteis | ~11 | **26** |
| 13 botões diretos | ✗ | ✓ |
| USB no Windows | USB-Serial/JTAG | **CDC, sem driver** |
| Gravação | esptool | **arrasta o .uf2** |
| Rádio | sim (não usamos) | não (não precisamos) |

---

## 3. Diagrama de blocos

```
   [ Jogo (host) ]  --USB CDC 115200--  [ Raspberry Pi Pico ]
    feira/entrada_serial.py                firmware/botoeira/
    SerialInput (C6)                       main.py + protocolo.py
                                                  |
                     +----------------------------+---------------------------+
                     |                                                        |
              13x GPIO IN (pull-up)                            SPI0 + latch + /OE
              GP2..GP13, GP22                                  GP18,19,20,21
                     |                                                        |
              [ 13 microswitches ]                        [ 74HC595 ] -> [ 74HC595 ]
              (contato -> GND)                                  |             |
                                                          [ ULN2803A ]  [ ULN2803A ]
                                                                |             |
                                                          13 catodos de LED -> GND
                                                          13 anodos <- +5 V (trilho)
```

---

## 4. Esquema elétrico

### 4.1 Cadeia de LED (o único trecho com corrente)

```
  +5V TRILHO DE LED  (JP1: VBUS do USB  |  VEXT da fonte externa - ver §6)
  o----+-------------+-------------+---------------------------- ... (13x)
       |             |             |
      LED           LED           LED      <- dentro do botao arcade
      (anodo)       (anodo)       (anodo)      (com resistor embutido, 5V)
       |             |             |
       v             v             v
     catodo        catodo        catodo
       |             |             |
    [1C]          [2C]          [3C]         ULN2803A  (saidas, coletor aberto)
    pino18        pino17        pino16
   +--------------------------------------------------+
   |  U3 / U4   ULN2803A  (par Darlington, dreno p/ GND)|
   |  IN 1B..8B (pinos 1..8)  <- saidas do 74HC595      |
   |  E (pino 9) -> GND comum                           |
   |  COM (pino 10) -> +5V do trilho (inofensivo com    |
   |                   LED; obrigatorio se entrar rele) |
   +----^-----^-----^----------------------------------+
        |     |     |
      QA    QB    QC   ...            74HC595  (U1: botoes 0..7 / U2: 8..11+START)
   +--------------------------------------------------+
   |  VCC(16) -> 3V3 do Pico       GND(8) -> GND       |
   |  SER(14) <- GP19 (SPI0 TX)    [U2.SER <- U1.QH'(9)]|
   |  SRCLK(11) <- GP18 (SPI0 SCK)  (os dois em paralelo)|
   |  RCLK(12)  <- GP20             (os dois em paralelo)|
   |  /OE(13)   <- GP21 + pull-up 10k para 3V3          |
   |  /SRCLR(10) -> 3V3 (limpeza e por shift de zeros)  |
   |  100 nF entre VCC e GND, colado no chip            |
   +--------------------------------------------------+
```

### 4.2 Botões (contato)

```
   GP<n>  o------[ microswitch NO do botao ]------o  GND (barramento comum)
             pull-up INTERNO do RP2040 (~50k)
             apertado = 0   (ativo-baixo)
```

Sem resistor externo e sem capacitor de debounce: o debounce é de firmware
(15 ms, borda na primeira detecção — ver §7). Um capacitor de 100 nF em paralelo
com o contato só é necessário se o chicote passar de ~1,5 m ou correr colado ao
cabo do projetor; nesse caso ele **atrasa** a borda e entra no orçamento de
latência.

### 4.3 Cascata dos dois 595 — o erro de montagem mais caro

```
   GP19 (SER) --> U1.SER(14)      U1.QH'(9) --> U2.SER(14)
   GP18 (SCK) --> U1.SRCLK(11) e U2.SRCLK(11)   (paralelo)
   GP20 (RCLK)--> U1.RCLK(12)  e U2.RCLK(12)    (paralelo)
   GP21 (/OE) --> U1./OE(13)   e U2./OE(13)     (paralelo)
```

⚠️ **O primeiro byte que sai do SPI atravessa o U1 e para no U2.** Por isso o
firmware escreve `bytes([byte_U2, byte_U1])` e não o contrário
(`protocolo.palavra_595`). Trocar os dois chips de lugar não queima nada — só
faz o painel acender o cruzamento errado, e é o tipo de erro que passa
despercebido até alguém jogar. `tests/test_a4_firmware.py::test_ordem_da_cascata_e_u2_primeiro`
trava o lado do software; do lado do fio, quem confere é `main.bancada()`.

---

## 5. Mapa de pinos

### 5.1 Botões (entrada, pull-up interno, ativo-baixo)

**Regra única: GPIO = índice + 2.** Sem tabela de tradução para errar.

| Botão | Semáforo | GPIO | pino físico | posição no painel |
|------:|----------|------|------------:|-------------------|
| 0 | H1V1 | GP2 | 4 | linha de cima, 1ª coluna |
| 1 | H1V2 | GP3 | 5 | linha de cima, 2ª |
| 2 | H1V3 | GP4 | 6 | linha de cima, 3ª |
| 3 | H1V4 | GP5 | 7 | linha de cima, 4ª |
| 4 | H2V1 | GP6 | 9 | **arterial**, 1ª |
| 5 | H2V2 | GP7 | 10 | **arterial**, 2ª |
| 6 | H2V3 | GP8 | 11 | **arterial**, 3ª |
| 7 | H2V4 | GP9 | 12 | **arterial**, 4ª |
| 8 | H3V1 | GP10 | 14 | linha de baixo, 1ª |
| 9 | H3V2 | GP11 | 15 | linha de baixo, 2ª |
| 10 | H3V3 | GP12 | 16 | linha de baixo, 3ª |
| 11 | H3V4 | GP13 | 17 | linha de baixo, 4ª |
| **START** | — | **GP22** | 29 | separado, embaixo, centrado |

⚠️ **Por que não começa em GP0.** GP0/GP1 são a UART0. Há build de MicroPython que
sobe o REPL nela; aí a GP0 é **saída em nível alto**, e o botão, ao fechar contra o
GND, curto-circuita a TX. Começar em GP2 custa uma soma no firmware e ainda deixa a
UART livre como console de socorro se a CDC der problema.

### 5.2 Painel de LED e reservados

| Sinal | GPIO | pino | vai para |
|---|---|---:|---|
| SPI0 SCK | GP18 | 24 | SRCLK (pino 11) dos **dois** 595 |
| SPI0 TX | GP19 | 25 | SER (pino 14) do **U1** |
| Latch (RCLK) | GP20 | 26 | RCLK (pino 12) dos **dois** 595 |
| /OE | GP21 | 27 | /OE (pino 13) dos dois + **pull-up 10 k para 3V3** |
| 3V3 OUT | — | 36 | VCC dos dois 595 |
| GND | — | 3, 8, 13, 18, 23, 28, 38 | barramento comum (botões, 595, ULN, trilho de LED) |
| VBUS | — | 40 | trilho de LED **se** JP1 = USB (§6) |

**Livres para o que vier:** GP0, GP1, GP14–GP17, GP26–GP28. **Nunca usar:** GP23
(SMPS), GP24 (VBUS sense), GP25 (LED da placa), GP29 (VSYS sense).

⚠️ **/OE precisa de pull-up externo, não de pull-down.** Entre ligar o USB e o
firmware rodar, a GP21 é entrada flutuante. Com pull-up de 10 k para 3V3 o /OE
fica ALTO = saídas em Hi-Z = **painel apagado no boot**. O firmware então escreve
zeros, dá o latch e só depois baixa o /OE. Sem esse resistor o painel acende um
padrão aleatório por ~1 s toda vez que alguém pluga o cabo.

### 5.3 Alocação das 16 saídas dos 595

| Chip | Saída | Uso |
|---|---|---|
| U1 | QA…QH | botões **0…7** (H1V1…H2V4) |
| U2 | QA…QD | botões **8…11** (H3V1…H3V4) |
| U2 | QE | **START** |
| U2 | QF | **heartbeat do firmware** — pisca a 1 Hz sozinho, sem host. Um LED de 5 mm na caixa: se ele bate, o Pico está vivo e o problema é o cabo ou o jogo |
| U2 | QG, QH | reserva (2 saídas) |

---

## 6. Orçamento de energia — e quando a fonte externa deixa de ser opcional

### 6.1 A conta

| Bloco | Corrente | Nota |
|---|---:|---|
| 13 LEDs de botão a 20 mA (**todos acesos**) | **260 mA** | pior caso real: `--chase`, ou 12 cruzamentos em `on` |
| Pico + MicroPython + CDC | ~30 mA | RP2040 a 125 MHz + regulador |
| LED da placa (GP25) | ~4 mA | heartbeat |
| 2× 74HC595 (3,3 V) fornecendo as entradas do ULN | ~12 mA | 13 × ~0,7 mA + dinâmica do shift |
| 2× ULN2803A | ~0 | não tem pino de alimentação; só dissipa |
| **Total no VBUS (5 V)** | **≈ 300 mA** | |

**Porta USB 2.0 tipo A: 500 mA** garantidos após a enumeração. 300 mA são **60 %**
do orçamento, com 200 mA de folga. ✅ **Cabe no USB — nas condições da linha de cima.**

### 6.2 A regra de corte (o número que decide)

Reservando 20 % de margem sobre os 500 mA e descontando os ~35 mA da lógica:

```
    I_por_LED_maxima = (500 x 0,80 - 35) / 13 = 28,1 mA
```

> **Se o LED do botão puxar mais de ~28 mA, ou se o botão for de 12 V, o trilho de
> LED sai do USB e vai para fonte externa.** Meça um botão com multímetro **antes**
> de comprar os 13 — a variação entre fornecedores é enorme e a etiqueta mente.

### 6.3 Por que o jumper JP1 existe mesmo cabendo no USB

Três motivos, nenhum teórico:

1. **Botão de 12 V é o mais comum no mercado brasileiro de arcade.** Se for o que
   chegar, o trilho vira 12 V e o VBUS não serve. O ULN2803A já aguenta (50 V,
   500 mA/canal); só a lógica é que continua em 3,3 V. **Trocar de 5 V para 12 V é
   trocar o jumper e nada mais** — é para isso que o ULN está no projeto em vez de
   se acender direto do 595.
2. **Hub USB passivo** compartilhado com o adaptador do projetor e o mouse divide
   os 500 mA. Brownout no Pico = watchdog = painel apagado por ~1 s no meio da
   rodada, e é a falha que ninguém depura numa feira.
3. Se o painel crescer (LED de aviso, segundo START), a conta refaz sozinha.

```
    JP1:  [VBUS pino 40] o--o [trilho +5V] o--o [VEXT jack P4]
                            (jumper em UM dos dois — NUNCA nos dois)
```

⚠️ **Com fonte externa, o GND dela vai no MESMO barramento do Pico.** O ULN2803A
drena os catodos para o GND comum: sem referência comum ele não conduz, e o
sintoma é "os LEDs simplesmente não acendem" — que parece defeito de firmware.

### 6.4 Desacoplamento (não é enfeite)

| Componente | Onde | Por quê |
|---|---|---|
| 100 nF cerâmico | VCC–GND de cada 74HC595, colado no chip | ruído de chaveamento do shift |
| **470 µF eletrolítico** | trilho +5 V, perto dos ULN | 13 LEDs comutando a 10 Hz (piscada do `deny`) é um degrau de 260 mA no cabo USB. Sem o bulk, o degrau afunda o VBUS e derruba o Pico |
| 10 kΩ | GP21 (/OE) → 3V3 | painel apagado no boot (§5.2) |

### 6.5 Dissipação do ULN2803A

V_CE(sat) do Darlington a 20 mA ≈ 0,9 V → 18 mW por canal. O pior chip (U3, 8
canais) dissipa **144 mW**; DIP-18 com θ_JA ≈ 65 °C/W → **ΔT ≈ 9 °C**. Sem
dissipador, sem preocupação.

### 6.6 ULN2803A acionado por lógica de 3,3 V — verificação, não fé

O ULN2803**A** tem rede de entrada de 2,7 kΩ em série + 7,2 kΩ de shunt,
dimensionada para TTL de 5 V. Com 3,3 V:

```
    I_base = (3,3 - 1,4) / 2,7k  -  (1,4 / 7,2k)  =  0,70 mA - 0,19 mA = 0,51 mA
    h_FE do par Darlington >= 1000 (baixa corrente)  ->  I_C disponivel ~ 500 mA
    I_C necessaria = 20 mA por canal
```

Margem de **25×**. ✅ Funciona a 3,3 V. (A ressalva do datasheet sobre "5 V TTL" é
sobre garantir margem com I_C alta, não sobre um piso de tensão.)

### 6.7 A alternativa que não escolhemos: TPIC6B595

O **TPIC6B595** é registrador de deslocamento **com** saídas de dreno aberto de
150 mA — faz sozinho o que aqui são 595 + ULN. Menos peças, menos solda, entradas
já compatíveis com 3,3 V.

**Não foi escolhido** por dois motivos: o plano congelou 595 + ULN2803A, e o custo
no Brasil é ~R$ 18/chip contra R$ 2,50 + R$ 4,50 do par (≈ **3×**), sem ganho
funcional na nossa corrente (20 mA contra os 150 mA que ele oferece). Fica
registrado como o caminho a tomar **se** aparecer carga acima de 500 mA/canal ou
se a montagem manual virar o gargalo.

---

## 7. Firmware — o que o esquema assume dele

Detalhe em `firmware/botoeira/` e em `docs/BOTOEIRA.md`. O que o hardware depende:

- **Debounce de 15 ms com borda na PRIMEIRA detecção.** O debounce clássico
  ("estável por 15 ms") jogaria 15 ms inteiros dentro do teto de 50 ms do DoD.
  Aqui a borda sai no laço em que o contato desce e a trava de 15 ms vale para o
  **retorno** — o repique do micro-switch é sempre *depois* do primeiro contato.
- **Sincronização no boot:** o firmware adota o nível encontrado como repouso. Um
  botão emperrado (ou um dedo em cima na hora de plugar) não vira aperto fantasma.
- **/OE alto até o primeiro latch.** Ver §5.2.
- **Watchdog de 2 s.** Se o laço travar, o Pico reinicia, manda `HELLO` de novo, e
  o host **reenvia o quadro de LEDs** (senão o painel fica mentindo).
- **Saída de emergência:** START segurado no boot ⇒ firmware não inicia, REPL
  livre, watchdog não armado. É o único jeito de recuperar a placa sem apagar a
  flash.

---

## 8. Chicote e montagem

| Item | Contagem |
|---|---|
| Fios de sinal do micro-switch (GPIO) | 13 |
| Barramento GND dos micro-switches (encadeado) | 1 |
| Fios de catodo de LED (para os ULN) | 13 |
| Barramento +5 V dos anodos (encadeado) | 1 |
| **Terminais faston 2,8 mm fêmea** (4 por botão) | **52** |

Encadeie os dois barramentos de botão em botão (guirlanda) em vez de puxar 13
fios de cada até a placa: são 26 fios longos a menos e uma caixa que fecha.

**Cores sugeridas (e usadas no `docs/BOTOEIRA.md`):** preto = GND, vermelho =
+5 V do trilho, amarelo = sinal do micro-switch, verde = catodo de LED.

---

## 9. O que este documento **não** prova

Nada aqui foi medido em bancada — **não há hardware montado**. São contas de
datasheet e de folha de dados de catálogo. O que precisa da placa na mesa:

- corrente real dos LEDs comprados (o número que manda em §6.2);
- período real do laço do firmware (estimado em 2 ms; `main.bancada()` mede);
- ruído do micro-switch com o chicote de verdade;
- diâmetro do furo (28 mm é o nominal do botão "30 mm"; **fure uma sobra antes**);
- e o único item do DoD do A4 que continua aberto: *"13 botões e 13 LEDs
  verificados na bancada"* — em software está coberto (`tests/test_a4_protocolo.py`,
  159 casos), no fio não.
