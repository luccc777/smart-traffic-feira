# Botoeira física — montar, testar sem o jogo, diagnosticar

**Agente A4** · 13 botões arcade iluminados sobre Raspberry Pi Pico · protocolo C6

| Onde está o quê | |
|---|---|
| Contrato congelado | [`feira/contratos/entrada.py`](../feira/contratos/entrada.py) (C6) — **não editar** |
| Host | [`feira/entrada_serial.py`](../feira/entrada_serial.py) — `SerialInput`, `SerialFalso`, `abre_botoeira()` |
| Firmware | [`firmware/botoeira/`](../firmware/botoeira/) — `main.py` (Pico) + `protocolo.py` (lógica pura) |
| Elétrica | [`hardware/botoeira/ESQUEMA.md`](../hardware/botoeira/ESQUEMA.md) |
| Custo | [`hardware/botoeira/BOM.md`](../hardware/botoeira/BOM.md) — **R$ 432** (R$ 477 com fonte externa) |
| Furação | [`hardware/botoeira/gabarito_painel.svg`](../hardware/botoeira/gabarito_painel.svg) (1:1) |
| Testes | `tests/test_a4_*.py` — **179 casos, todos sem hardware** |

> **A botoeira nunca é obrigatória.** O caminho canônico do motor é
> `FonteComReserva(abre_botoeira() or teclado, teclado)`: sem cabo, sem
> `pyserial`, sem firmware, o jogo roda de teclado exatamente igual. A trilha da
> botoeira é a única do plano que pode atrasar sem afetar a feira.

---

## 1. O painel é um mapa, não um teclado

```
        V1        V2        V3        V4
      +-------------------------------------+
 H1   |  (0)      (1)      (2)      (3)     |   <- corredor norte
      |                                     |
 H2   |  (4)      (5)      (6)        (7)   |   <- A ARTERIAL (3 faixas)
      |                                     |
 H3   |  (8)      (9)      (10)       (11)  |   <- corredor sul
      |                                     |
      |               ( START )             |   <- maior, separado
      +-------------------------------------+
```

A posição do botão **é** a posição do cruzamento no chão: as 13 coordenadas saem
de uma projeção afim sobre `sumo/aberta/build/nodes_aberta.nod.xml`
(`hardware/botoeira/gabarito.py`), e `tests/test_a4_painel.py` refaz a conta
contra o `.nod.xml` de verdade. Consequências que parecem defeito e não são:

- **o passo horizontal (71,25 mm) é maior que o vertical (45 mm)** — a razão
  1,583 é a da rede (31,667 / 20). Painel de passo uniforme mentiria;
- **a coluna V4 é torta**: `H1V4` está 11,25 mm à esquerda de `H2V4`/`H3V4`,
  porque na rede aberta a V4 dá um degrau. **Não é erro de furação.**

Índice do botão = índice do semáforo, sem tabela: `TLS_IDS` é `sorted(...)`, e a
ordem alfabética (`H1V1`…`H3V4`) percorre o painel da esquerda para a direita, de
cima para baixo — coincidência **verificada**, não suposta
(`test_a_ordem_alfabetica_e_a_ordem_de_leitura_do_painel`).

⚠️ **Oriente o painel como a projeção.** H1 (norte) em cima. Se a projeção
espelhar, quem remapeia é o motor do jogo — nunca a fiação, e nunca este gabarito.

---

## 2. Montagem

### 2.1 Painel

1. `python hardware/botoeira/gabarito.py` → regenera `gabarito_painel.svg`.
2. Imprima em **A3 paisagem, escala 1:1** (opção "tamanho real" / 100 %; **nunca**
   "ajustar à página"). **Meça a régua de 100 mm impressa no rodapé** — se ela não
   der 100 mm, o gabarito inteiro está errado e os 13 furos saem errados juntos.
3. Cole no MDF de 3 mm, fure: **Ø28 mm** nos 12, **Ø44 mm** no START.
   ⚠️ Antes de furar os 13, fure **um** numa sobra e encaixe o botão: "30 mm" é
   nome comercial, não medida, e a variação entre fornecedores chega a ±2 mm.
4. Monte a moldura de pinus por trás. A placa de 3 mm flexiona sob o dedo; a
   moldura é o que faz o botão travar em vez de o painel afundar.

### 2.2 Fiação

Cores usadas em todo este documento: **preto** = GND · **vermelho** = +5 V do
trilho · **amarelo** = sinal do micro-switch · **verde** = catodo de LED.

1. **Encadeie** (guirlanda) o GND dos micro-switches botão a botão, e o +5 V dos
   anodos idem. São 26 fios longos a menos e uma caixa que fecha.
2. Um fio amarelo por botão até o GPIO: **GPIO = índice + 2** (botão 0 → GP2 …
   botão 11 → GP13). START → **GP22**.
3. Um fio verde por LED até a saída do ULN2803A, na ordem da §5.3 do `ESQUEMA.md`.
4. Pull-up de 10 kΩ entre GP21 (/OE) e 3V3. **Não pule**: sem ele o painel acende
   um padrão aleatório por ~1 s toda vez que alguém pluga o cabo.
5. 100 nF em cada 74HC595 e **470 µF no trilho de +5 V**, perto dos ULN.

### 2.3 Firmware

1. Segure BOOTSEL, pluge o USB → aparece o disco `RPI-RP2`.
2. Arraste o `.uf2` do **MicroPython para Raspberry Pi Pico** (o oficial).
3. Copie `firmware/botoeira/main.py` e `firmware/botoeira/protocolo.py` para a
   **raiz** do Pico (Thonny, `mpremote cp`, ou o que preferir). Os dois arquivos,
   na raiz — `main.py` importa `protocolo`.
4. Despluge e pluge. O LED de heartbeat (U2·QF) deve piscar a 1 Hz.

### 2.4 `pyserial` (só do lado do host)

```powershell
..\smart-traffic\.venv\Scripts\python.exe -m pip install pyserial
```

O jogo **não** precisa disso. O import é tardio, dentro de `_abre_porta_real()`, e
`tests/test_a4_conformidade.py::test_a4_o_modulo_importa_sem_pyserial` existe para
travar isso: sem `pyserial`, `abre_botoeira()` devolve `None` e o teclado assume.

---

## 3. Testar **sem** o jogo

Quatro níveis, do que roda hoje ao que precisa da placa na mesa.

### 3.1 Sem hardware nenhum — a suíte (é o que tem DoD verificável hoje)

```powershell
.\run_testes.ps1                      # 179 casos de A4 entre os do repo
..\smart-traffic\.venv\Scripts\python.exe -m pytest -q tests/test_a4_latencia.py -s
```

| arquivo | o que prova |
|---|---|
| `test_a4_conformidade.py` | `SerialInput` passa **a mesma suíte do C6** que o teclado — os testes são *importados* de `tests/test_conformidade.py`, não copiados |
| `test_a4_protocolo.py` | 13 botões e 13 LEDs, ida e volta, contra o modelo do Pico em software |
| `test_a4_resiliencia.py` | cabo fora, `PING` mudo, rodada de 60 ticks com a queda no meio |
| `test_a4_integracao.py` | a mesma queda dentro do `FonteComReserva` **de verdade** (agente A3) |
| `test_a4_firmware.py` | debounce, parser e mapeamento dos 595 — **o mesmo arquivo que sobe para o Pico** |
| `test_a4_painel.py` | as 13 coordenadas contra o `.nod.xml` da rede aberta |
| `test_a4_latencia.py` | o termo do host, medido; e o orçamento inteiro |

### 3.2 Sem hardware, na mão — o Pico em software

```powershell
..\smart-traffic\.venv\Scripts\python.exe -m feira.entrada_serial --falsa
```

Roda a bancada contra `SerialFalso`. Serve para exercitar o caminho de código do
jogo (e para escrever o A7) sem cabo, sem placa e sem `pyserial`.

### 3.3 Com a placa, sem o painel — o REPL

Ligue só o Pico (sem botões nem LEDs). No Thonny / `mpremote repl`:

```python
>>> import main
>>> main.bancada()
```

Faz três coisas, nessa ordem:

1. **mede o período do laço** — é o único termo do orçamento de latência que
   depende da placa. Aqui ele está **estimado em 2 ms**; o número que vale é o que
   sair daqui;
2. **acende os 13 LEDs um a um**, dizendo qual é — confere fiação e, sobretudo, a
   **ordem da cascata** (U1 antes ou depois do U2);
3. **imprime cada botão apertado por 20 s** e, no fim, lista os que nunca
   apareceram: `nao apertados/nao detectados: [7, 11]` é fio solto em GP9 e GP13.

Se o firmware travar e o REPL não voltar: **segure o START enquanto pluga o USB**.
O firmware imprime um aviso, não inicia o laço e não arma o watchdog.

### 3.4 Com a placa e o painel — o host

```powershell
..\smart-traffic\.venv\Scripts\python.exe -m feira.entrada_serial --lista
..\smart-traffic\.venv\Scripts\python.exe -m feira.entrada_serial --chase
..\smart-traffic\.venv\Scripts\python.exe -m feira.entrada_serial --segundos 60
```

- `--lista` mostra as portas e marca a que tem VID:PID `2E8A:0005` (Pico/MicroPython);
- `--chase` acende os 13 em sequência pelo comando `LED` — o teste de fiação
  visto do lado do jogo;
- sem flag, imprime cada borda por 30 s com o carimbo de tempo.

A porta também abre em qualquer terminal (PuTTY, `screen`, monitor do Arduino) a
115200: o protocolo é ASCII por linha de propósito. Digitar `LEDS ooooooooooon` e
ver o START acender é um teste válido.

---

## 4. Diagnóstico

| Sintoma | Causa mais provável | O que fazer |
|---|---|---|
| `BotoeiraAusente: sem HELLO em 2.0 s` | **cabo só-carga** (o erro clássico), ou `main.py` não está na raiz do Pico | troque o cabo por um de dados; `--lista` mostra se a porta sequer existe |
| `--lista` não mostra porta nenhuma | `pyserial` não instalado | `pip install pyserial` — mas repare que **o jogo não precisa**: sem ele o teclado assume |
| Porta existe, `HELLO` não vem, heartbeat **não** pisca | firmware não está rodando | segure START e pluge → REPL; veja o erro do `main.py` |
| Porta existe, `HELLO` não vem, heartbeat **pisca** | outro programa segurando a COM (Thonny aberto!) | feche o Thonny/monitor serial. A COM é exclusiva no Windows |
| `BotoeiraIncompativel: protocolo do dispositivo é 'botoeira v0'` | firmware velho na placa | recopie `protocolo.py` **e** `main.py` |
| `BotoeiraIncompativel: dispositivo diz n=6` | firmware de outra rede / painel do "modo corredor" | acerte `N_BOTOES` no firmware, ou passe `n_botoes=` no host |
| Um botão nunca responde | fio amarelo solto, ou faston frouxo | `main.bancada()` passo 3 lista os que não apareceram |
| Um botão dispara duas vezes por aperto | debounce curto para esse micro-switch | suba `DEBOUNCE_MS` em `protocolo.py` (25 ms) e rode `pytest tests/test_a4_firmware.py` |
| **Todos** os LEDs mortos, botões OK | GND da fonte externa não está no barramento comum | o ULN2803A drena para o GND; sem referência comum ele não conduz |
| LEDs acendem **trocados em blocos de 8** | cascata invertida (U1↔U2) | `main.bancada()` passo 2; troque `U1.QH'(9) → U2.SER(14)` |
| Painel acende sozinho ao plugar, por ~1 s | falta o pull-up de 10 k no /OE | `ESQUEMA.md` §5.2 |
| Painel apaga sozinho no meio da rodada e volta | **brownout**: 13 LEDs comutando afundam o VBUS | 470 µF no trilho; se persistir, JP1 → fonte externa |
| `viva()` vira `False` com o cabo no lugar | Pico travado (`PING` parou) ou watchdog reiniciando em laço | segure START e pluge; leia o erro no REPL |
| Pico reiniciando em laço (heartbeat pisca, para, volta) | **CDC bloqueada**: a porta está aberta e ninguém lê (jogo travado, terminal esquecido aberto). O `write` do firmware bloqueia, o laço para, o watchdog reinicia | feche o terminal órfão / reinicie o jogo. É degradação, não perda: o `HELLO` de volta faz o host reenviar o quadro de LEDs. Ver `main.py::Botoeira.diz` |
| Painel discorda da tela depois de um susto | o Pico reiniciou (watchdog) | **já tratado**: `HELLO` fora de hora faz o host reenviar o quadro. Se não voltou, o `HELLO` não chegou — veja a linha acima |

### 4.1 Ler o fio na unha

Tudo é ASCII por linha. O que sai do dispositivo:

```
HELLO botoeira v1 n=12      no boot e a cada RESET
BTN 7                       borda do semaforo 7 (= H2V4)
START                       o botao grande
PING                        1 Hz, e o que sustenta viva()
```

O que o host manda:

```
LEDS oooooooooooon          13 chars: 12 semaforos + START (o ULTIMO)
LED 3 armed                 um LED so;  LED -1 <estado> = o START
RESET                       apaga tudo e pede HELLO
```

Alfabeto dos estados (`PROTO_CHAR`): `o` = off · `a` = armed · **`n` = on** ·
`d` = deny. ⚠️ **`n` é "on", não "não"** — ver §6.

---

## 5. Latência botão→evento (item (d) do DoD)

| parcela | ms | origem |
|---|---:|---|
| varredura do firmware | 2,0 | `sleep_ms(1)` + 13 leituras de GPIO — **estimativa**, `main.bancada()` mede |
| debounce | **0,0** | de propósito: a borda sai na **primeira** detecção; os 15 ms travam o *retorno* |
| transporte USB CDC (full-speed) | 3,0 | 1 quadro de 1 ms + folga do driver — **estimativa** |
| período de polling do motor | 33,3 | 1/30 Hz, **pior caso** — o termo que domina |
| host (`SerialInput.poll()`) | **0,006** | **MEDIDO**: p50 = 1,8 µs, p99 = 2,9 µs, máx = 49 µs em 2000 amostras |
| **total (pior caso)** | **38,3** | teto do DoD: 50 ms · **folga 11,7 ms** ✅ |

O único termo que importa é o último da lista de cima: **o motor precisa chamar
`poll()` a ≥ 30 Hz**. A 20 Hz o orçamento estoura (55 ms), e
`test_orcamento_de_pior_caso_fecha_sob_o_teto_do_dod` fica vermelho se alguém
baixar essa constante.

> ⚠️ **Achado para o agente A3 — hoje o motor não cumpre isso.** Durante a rodada
> quem drena a fonte é `MotorDoJogo._observa`, que é o observador da Arena,
> chamado **uma vez por sim-step**. Com `STEP_LENGTH = 1.0 s` e
> `Ritmo(sim_por_parede=1.0)`, isso dá **1 Hz** — latência de até 1000 ms, 20× o
> teto. (Fora da rodada, `espera_start(intervalo=0.05)` roda a 20 Hz, também
> abaixo.) O conserto mais barato é fatiar a espera do `Relogio.espera()` da Arena
> e chamar `bombeia()` entre as fatias; a alternativa é um pump em thread. Isto
> **não é bug do A4** (o termo do host é 6 µs), mas o DoD (d) é ponta a ponta e só
> fecha com essa mudança. Vale para o teclado igual: a 1 Hz o LED de "armado"
> demora até um segundo para acender, que é exatamente o efeito que o C6 quer
> evitar.

---

## 6. Defeitos e ambiguidades do contrato C6 (reportados, **não** consertados)

O C6 está congelado e é do dono do contrato consertar. Cada item abaixo tem a
decisão que tomei enquanto isso.

### 6.1 `feedback()` não tem por onde falar do 13º LED — **buraco real**

O quadro `LEDS` tem `n+1` caracteres (13), mas `feedback(estados)` recebe `n` (12)
e `valida_estados(estados, n)` recusa 13. **O contrato não tem como dizer o estado
do LED do START** — e ele é justamente o que precisa acender "pode começar" na
tela ociosa e "abortar armado" durante a rodada.

*Enquanto isso:* `SerialInput.feedback_start(estado)`, **fora** do Protocol. O
motor chama com `getattr(fonte, "feedback_start", None)` para o teclado não
precisar implementar. Sugestão de conserto: `feedback()` aceitar `n` **ou** `n+1`
estados, ou nascer `feedback_start()` no Protocol.

### 6.2 O C6 não diz **onde** o START mora no quadro `LEDS`

"`LEDS <n+1 chars, 1 por botao>`" não fixa a posição do 13º.

*Decisão:* **último caractere**, para que `quadro[BOTAO_START]` == `quadro[-1]`
seja literalmente o LED do botão grande — o índice do contrato indexa o quadro sem
tradução. Vale a pena escrever isso no C6: é um off-by-one silencioso à espera.

### 6.3 `LED <i>` e o quadro `LEDS` discordam sobre o índice do START

No comando avulso o índice natural é `BOTAO_START` = **-1**; na string, a posição
é **12**. Os dois endereçam o mesmo LED físico.

*Decisão:* o firmware aceita **os dois** (`interpreta()` normaliza), e há teste
para os dois (`test_led_do_start_pelos_dois_enderecos`). Aceitar só um seria
escolher qual metade dos leitores do contrato erra.

### 6.4 O C6 não diz se `viva()` pode ter efeito colateral

*Decisão:* **pode, e aqui tem.** `viva()` drena a porta para uma fila interna que o
`poll()` seguinte devolve. Sem isso um motor que perguntasse `viva()` antes de
`poll()` mataria a botoeira por **ordem de chamada**: o `PING` estaria no buffer do
sistema, não lido, e o relógio já teria passado dos 2 s. Nada se perde — mas o
contrato deveria dizer, porque a implementação óbvia (sem efeito colateral) é a
errada.

### 6.5 `PROTO_CHAR[ACEITO] == "n"` é uma armadilha de bancada

`o`=off, `a`=armed, **`n`=on**, `d`=deny. Lendo `LEDS oonoodoooooo` num terminal,
`n` se lê como "não/negado" e `d` como... também. É a única colisão mnemônica do
conjunto, e ela mora exatamente onde a pessoa está com a placa na mão tentando
entender por que o LED errado acendeu.

*Não é bug* (o wire está congelado e a implementação está correta). Registrado
porque custa uma linha de comentário no C6 evitar meia hora de depuração.

### 6.6 `EventoBotao.t_wall` é carimbado no **host**

O `BTN <i>` não traz relógio do dispositivo, então `t_wall` é o instante do
`poll()` — inclui o transporte e o período de polling do motor. Para o placar
tanto faz; para **medir** latência ponta a ponta em bancada, não dá para separar
fio de laço do jogo. **Não peço mudança** (carimbo exigiria relógio sincronizado no
Pico, e o C6 acertou em não pedir isso), mas fica registrado que o número de
latência da §5 é host-side por construção.

### 6.7 O C6 não define o que fazer com linha desconhecida

*Decisão nos dois lados:* **ignorar e contar**, nunca morrer. Firmware mais novo
pode falar mais coisas; um terminal esquecido aberto na porta não pode derrubar a
rodada. `SerialInput.linhas_ignoradas` e `Linhas.descartadas` existem para isso
aparecer no diagnóstico em vez de sumir.

---

## 7. O que **só** se prova com a botoeira montada

Nada abaixo foi medido. Não há hardware na mesa, e onde este documento estima,
ele diz que estima.

| Item | Estado | Como fechar |
|---|---|---|
| Corrente real dos LEDs comprados | **aberto** — a conta de energia assume 20 mA/LED | multímetro em série num botão; regra de corte em `ESQUEMA.md` §6.2 |
| Período real do laço do firmware | **estimado 2 ms** | `main.bancada()` passo 1 |
| Ruído do micro-switch com o chicote real | **aberto** — `DEBOUNCE_MS = 15` é valor de catálogo | `main.bancada()` passo 3, procurando aperto duplo |
| Ordem da cascata dos 595 no fio | provado em software, **aberto** no cobre | `main.bancada()` passo 2 |
| Diâmetro do furo | **28 mm nominal** | fure uma sobra antes dos 13 |
| Latência USB CDC real | **estimada 3 ms** | osciloscópio no GPIO + timestamp no host |
| Item (b) do DoD do plano — *"13 botões/LEDs verificados na bancada"* | **coberto em software** (159 casos), **aberto no fio** | §3.3 e §3.4 deste documento |

O resto do DoD do A4 está fechado sem hardware: (a) mesma suíte do teclado,
(c) queda do USB, (d) latência, (e) `pytest` verde e `ruff` limpo.
