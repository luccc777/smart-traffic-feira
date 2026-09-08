# O modo jogo — protocolo da rodada, máquina de estados e operação

Agente **A3 — Motor do Jogo & Camada de Input**, Onda 1. Entrega o
`ControladorHumano` (C3), a camada de entrada (C6), o motor da rodada com os
fantasmas (C8) e o placar (C7).

Tudo aqui foi **medido** nesta bancada, no cenário `aberta.maquete`, com SUMO
1.27.0 e o venv compartilhado. `pyserial` **não** está instalado — e a rodada
completa roda assim mesmo, que é o ponto.

---

## 0. A rodada, em uma tela

| | |
|---|---|
| cenário | `aberta.maquete` — 12 semáforos, **12 controláveis**, 3500 veh/h |
| janela | **120 s simulados**, playback **1:1** → 2 min de relógio |
| aquecimento | 300 s com o plano fixo, **igual para os três braços** |
| grade | `di5/vm7/am3/mr0` — decisão a cada 5 s, verde mínimo 7 s, amarelo 3 s |
| botões | 12 (`Q W E R / A S D F / Z X C V`) + **Espaço** = START/ABORTAR |
| adversários | **fantasmas pré-computados**: timer fixo 27 s e a política RL |
| manchete | **carros entregues**. Nunca tempo de viagem |

    python -m feira.jogo                    # a rodada de verdade, no teclado
    python -m feira.jogo --rodadas 1        # uma rodada e sai
    python -m feira.jogo --auto --rapido    # ensaio: sem esperar START, sem 1:1
    python -m feira.jogo --sem-rl           # modo degradado: só TIMER x VOCÊ

---

## 1. O protocolo da rodada

### 1.1 O botão enfileira intenção — ele não troca a fase

Apertar o botão **arma uma intenção**. Ela é consumida no **próximo tick da
grade** (a cada 5 s), sujeita a verde mínimo e amarelo — exatamente como o bit
de ação da rede neural.

    t=101,2  visitante aperta Q       -> LED "armado"
    t=105,0  tick da grade            -> H1V1 tem 19 s de verde: ACEITO  (LED "aceso")
                                      -> ou tem 3 s de verde: NEGADO     (LED "piscando")

**Por que a intenção negada é descartada e não guardada.** "Consumida no próximo
tick" quer dizer **gasta**. Guardar a intenção para disparar sozinha quando o
verde fechasse daria ao humano um efeito que a ação da RL não tem — a RL emite
um bit por tick e o bit recusado se perde. Duas consequências boas: a sequência
de ações do humano é função só de *quais botões foram apertados entre dois
ticks* (é isso que torna a rodada gravável e reproduzível), e o `deny` **ensina
a restrição** em vez de escondê-la.

**Pior espera:** apertar logo depois de uma troca custa `min_green + amarelo`
arredondado para cima na grade = **10 s**. O `verde_minimo_alcancavel` do
`RestricoesFase` é o número que descreve isso.

### 1.2 O bit `TROCAR` só sai quando vai ser aceito

`Observacao.pode_trocar` é, por construção da Arena, o **mesmo predicado** que o
`TrafficEnv._apply_actions` usa para aceitar um switch
(`controlável ∧ ¬amarelo ∧ verde_desde ≥ MIN_GREEN`, no mesmo instante `t`).
O `ControladorHumano` emite `TROCAR` só dentro dele; fora, emite `MANTER` mais o
feedback `deny`.

Medido (`tests/test_a3_integracao.py::test_humano_e_controlador_direto_medem_o_mesmo`):
aplicar a mesma sequência de botões ao `ControladorHumano` e os **vetores crus**
(todo botão apertado vira `TROCAR`, sem máscara) a um controlador que os emite
direto produz o **mesmo `Resultado`**, campo a campo. Ou seja: o mascaramento não
é gentileza do código do jogo — o espaço de ação do visitante **é** o da política.

### 1.3 Feedback: quatro estados, e ele é contrato

| estado | LED (botoeira) | quando |
|---|---|---|
| `off` | apagado | nada armado |
| `armed` | pulsando | intenção registrada, esperando o tick |
| `on` | aceso | a troca foi aceita neste tick |
| `deny` | piscando | recusada: verde mínimo não fechou, ou TL não controlável |

`armed` acende **no ato** (não no tick): sem isso o visitante conclui que o botão
quebrou e para de jogar. `on`/`deny` duram até o tick seguinte (5 s) e depois
voltam a `off` — sem relógio de parede dentro do controlador, que o C3 proíbe.

**O 13º LED (o botão START)** não cabe no `feedback()` do C6, que define o vetor
com `n` estados — um por semáforo — enquanto o quadro `LEDS` do protocolo tem
`n+1` (buraco reportado ao dono do repo; ver §7). Enquanto ele existe, o motor
chama `feedback_start(estado)` em quem souber implementá-lo, com este mapa:

| fase | LED do START | leitura |
|---|---|---|
| `ocioso` / `resultado` | `armed` (pulsando) | *pode começar* |
| `preparando` | `deny` (piscando) | *calculando, aguarde* |
| `contagem` / `jogando` | `on` (aceso) | *rodada correndo — apertar aborta* |

### 1.4 O que o placar mostra

Três barras — **TIMER FIXO · REDE NEURAL · VOCÊ** — em **carros entregues**, os
três no **mesmo `t` simulado**. Tempo de viagem e fila aparecem como secundárias.

**Por que a manchete não é tempo de viagem:** a média só conta quem *chegou*,
então um jogador que trave a rede ganharia com a média dos poucos sobreviventes.
`entregues` colapsa sob travamento e não é enganável do mesmo jeito. É o mesmo
motivo pelo qual a seleção de checkpoint deste projeto passou a ser por vazão.

Na tela de RESULTADO as três linhas saem do `Resultado` (C5) — o número que o
repo publica —, não da última amostra da série.

---

## 2. A máquina de estados

```
   ┌──────────────────────────────────────────────────────────────────────────┐
   │                                                                          │
   ▼                                                                          │
 OCIOSO ──START──> PREPARANDO ──fantasmas ok──> CONTAGEM ──3·2·1──> JOGANDO ──┤
   ▲                    │                                             │       │
   │                    └── nenhum fantasma ──> (degradado) ──────────┘       │
   │                                                                          │
   └───────────────────────────── RESULTADO <──── t1 ou ABORTAR ──────────────┘
```

| fase | o que acontece | custo medido |
|---|---|---|
| `ocioso` | espera o START; a projeção mostra RL × timer | — |
| `preparando` | garante os 2 fantasmas da seed da vez (cache em disco ou cálculo) | **0 s** com cache; 3,1 s (timer) / 9,1 s (RL) sem |
| `contagem` | 3-2-1, **dentro do `reset()` do humano** | 3 s |
| `jogando` | **uma** chamada de `ArenaSumo.roda()` | 120 s (1:1) |
| `resultado` | placar final, vencedor, e agenda os fantasmas da PRÓXIMA seed | 8 s |

### Por que a contagem roda dentro do `reset()` do controlador

O aquecimento de 300 s roda **solto** (a Arena só aplica `Ritmo` dentro da
janela) e custa ~1,5 s. Se a contagem acontecesse antes de chamar a Arena,
haveria um buraco de ~1,5 s entre o "JÁ!" e o primeiro carro andar. O
`reset(topo, restricoes, t0)` do controlador é chamado **no instante exato em que
a janela abre** — e o `_Relogio` da rodada nasce depois dele, então o tempo gasto
ali não vira atraso acumulado. O motor passa um callback `ao_abrir_janela` e a
contagem mora nele.

Durante a contagem a fonte é drenada e o que vier é **descartado**: quem martela
o botão no "3, 2, 1" não começa a rodada com 12 trocas de graça.

### O estado neutro canônico, e o selo que prova

Os três braços partem do **mesmo estado em t0**, obtido pela via exata: replay do
aquecimento a partir de `t=0` com o plano fixo, que o agente A1 mediu ser
**bit-idêntico** entre corridas.

Isso é **mais forte** que o `loadState`, que reproduz `t0` só na precisão do
arquivo (2 casas decimais; 1 cm é 1,7% do carro sob similitude) e cuja
**continuação diverge** — ~150 veículos em 300 s. A regra do A1 continua valendo
e está implementada: fantasma e humano nunca podem vir de origens diferentes.

E não fica na promessa: `ControladorSelado` grava o **sha256 da primeira
`Observacao`** (o estado observável em `t0`) de cada braço. O motor compara o selo
do humano com o dos fantasmas e, se divergirem, publica o placar **sem vencedor**
com o motivo escrito. Provado em
`tests/test_a3_integracao.py::test_fantasma_e_humano_saem_do_mesmo_estado_em_t0`,
que também mostra que o selo tem dentes (outra seed → outro selo).

### Fantasma velho é o risco, e ele levanta

Todo carregamento passa por `Fantasma.confere(chave)` (C8). A `Chave` fecha
cenário, seed, janela, **sha256 da demanda** e **assinatura do espaço de ação** —
um fantasma de ontem, de outra `min_green`, parece perfeitamente válido na tela e
produz um placar mentiroso na frente do público.

---

## 3. A camada de entrada

### 3.1 Teclado (sempre existe)

```
   Q W E R        H1V1 H1V2 H1V3 H1V4
   A S D F   →    H2V1 H2V2 H2V3 H2V4
   Z X C V        H3V1 H3V2 H3V3 H3V4
   espaço = START / ABORTAR
```

O bloco é isomorfo ao painel 3×4 da botoeira **e** à ordem em que a rede aberta
entrega `tls_ids` (`H1V1..H3V4`, linha a linha, verificado no `net_topology`).
Índice do botão significa a mesma coisa nas duas fontes.

Leitura não-bloqueante por `msvcrt` (stdlib). Sem console — pytest, serviço,
pipe — o `poll()` devolve vazio em vez de levantar. O teclado **nunca morre**
(`viva()` só vira False depois de `close()`): ele é o fallback de todo mundo.

### 3.2 Frequência de leitura — o achado do agente A4, e o conserto

Durante a rodada quem drena a fonte é o **observador da Arena**, chamado uma vez
por sim-step. Com `STEP_LENGTH=1.0` e ritmo 1:1 isso seria **1 Hz**: latência
botão→evento de até 1000 ms contra um teto de 50 ms — e, pior para o jogo, o LED
de "armado" demorando um segundo, que é exatamente o efeito que o C6 existe para
evitar.

O conserto certo é na Arena (fatiar a espera do `_Relogio` e chamar um gancho
entre as fatias); `feira/arena/**` está fora da fronteira do A3, então a mudança
foi pedida ao dono do repo. Enquanto ela não chega, a rodada roda com `Ritmo`
**solto** e a cadência 1:1 é imposta pelo `Marcapasso` do lado do observador, que
dorme até o deadline do sim-step em fatias de 20 ms e bombeia a fonte entre elas.
A disciplina de atraso é a mesma do `_Relogio`: o deadline **não** é reajustado
quando o laço fica para trás — o atraso é acumulado e reportado.

**Medido numa rodada ao vivo real (SUMO, janela de 15 s, 1:1): 48,2 Hz de
`poll()`, atraso máximo de 3 ms.** Quando a Arena expuser `ao_esperar`, o motor
devolve a cadência para ela sozinho (`MotorDoJogo._cadencia`).

### 3.3 Replay (rodada gravada)

`ReplayInput` reproduz uma rodada gravada. **A gravação é por tick, não por tempo
de parede**: o que determina a ação é só *quais botões estavam armados quando o
tick chegou*, e gravar o `t_wall` seria gravar o jitter — reproduzir num notebook
mais lento entregaria a tecla em outro tick e o `Resultado` mudaria.

Consequência (DoD (c), medido com SUMO): `GravacaoRodada` → `ReplayInput` →
**mesmo `Resultado`**, campo a campo. É o que torna a rodada testável e é a fonte
que o agente A8 vai usar para rodar adversários scriptados em massa.

### 3.4 Queda para a reserva

`FonteComReserva(primaria, reserva)`: quando `primaria.viva()` vira False, tudo
passa a ir para a reserva **sem interromper a rodada**. A troca é de mão única —
uma botoeira que reconecta no meio da rodada voltaria a mandar bordas de um
dispositivo que perdeu o estado dos LEDs, e o painel discordaria da tela.
Reconexão é entre rodadas (`reconecta()`), com o operador olhando.

---

## 4. O operador

### 4.1 O laço normal

1. `python -m feira.jogo` no notebook da feira. A tela lista o mapa de teclas.
2. Convida o visitante, explica em uma frase: *"cada botão é um cruzamento; o
   verde muda no próximo ciclo, não na hora"*.
3. **Espaço** começa. 3-2-1 e a rodada corre por 2 minutos.
4. Placar. **Espaço** de novo para a próxima (a seed roda em rotação e os
   fantasmas da próxima já foram calculados durante esta).

### 4.2 Abortar

**Espaço durante a rodada aborta.** O placar sai sem vencedor, com o motivo
registrado, e o motor volta sozinho para `ocioso`. Latência de ~20 ms (a fonte é
lida a ~48 Hz).

### 4.3 Seeds

Padrão: `100..105`, held-out (fora das `eval_seeds` do treino e fora da seed 42,
em que o timer trava em t≈3995 s). Uma seed por rodada, em rotação.

---

## 5. Modo degradado

| o que caiu | o que acontece | quem cobre |
|---|---|---|
| **botoeira** (USB fora) | `FonteComReserva` cai para o teclado no meio da rodada, sem parar | A3/A4 |
| **`pyserial` ausente** | nada: o jogo nunca importa `serial` | A3 |
| **checkpoint da RL / torch** | `Fantasmaria.garante` devolve só o timer; o placar perde **uma barra**, não a feira | A3 |
| **SUMO não sobe / cai na rodada** | a rodada devolve `ResultadoRodada(humano=None, motivo=...)` e o motor volta a `ocioso` | A3 |
| **projeção caída** | `publicador` levantando é engolido; a rodada continua e o terminal desenha o placar em texto | A3/A7 |
| **console ausente** | `TecladoInput` devolve vazio em vez de levantar; use `--auto` para ensaio | A3 |

O que **não** é coberto e precisa do operador: se os dois fantasmas falharem, a
rodada roda com uma barra só (VOCÊ) — sem adversário não há jogo, e o operador
deve parar e olhar o log.

---

## 6. Números medidos

Cenário `aberta.maquete`, seeds 100–105, janela de 120 s, 6 seeds por braço
(30 corridas), 2026-09-07.

### 6.1 Custo dos fantasmas — cabe no intervalo entre rodadas?

| | parede |
|---|---|
| uma corrida completa (300 s de aquecimento + 120 s de janela) | **3,12 s** (min 2,78 · max 4,26 · n=30) |
| fantasma do timer, em processo | 3,1 s |
| fantasma da RL, em processo (inclui boot do torch) | 9,1 s |
| **os dois fantasmas em subprocessos paralelos, do zero** | **17,2 s** |
| os dois, com cache em disco | ~0 s |

Contra os **120 s** da rodada anterior: **14% do orçamento** no pior caso (tudo
frio, dois subprocessos). Cabe com folga. O subprocesso existe porque `traci` é
uma conexão de módulo, singleton no processo: duas Arenas na mesma interpretação
brigam pela sessão.

### 6.2 A rodada de 120 s é dominada por ruído?

Entregues em 120 s, 6 seeds:

| braço | média | dp | cv |
|---|---|---|---|
| timer 27 s | 109,7 | 12,37 | 11,3% |
| "aleatório A" (aperta 35% dos botões por tick) | 101,8 | 10,01 | 9,8% |
| "aleatório B" (mesma habilidade, outra semente) | 101,3 | 10,07 | 9,9% |
| "martelo" (aperta os 12, todo tick) | 117,5 | 10,77 | 9,2% |
| "parado" (não aperta nada) | 34,5 | 5,01 | 14,5% |

**Diferença PAREADA contra o timer** — que é o que o placar mostra:

| braço | Δ médio | dp do Δ | Δ por seed |
|---|---|---|---|
| aleatório A | **−7,83** | 3,71 | −4 −9 −12 −4 −12 −6 |
| aleatório B | **−8,33** | 2,80 | −11 −9 −9 −4 −11 −6 |
| martelo | **+7,83** | 4,02 | +3 +8 +4 +14 +8 +10 |
| parado | −75,17 | 10,46 | −73 −72 −84 −59 −89 −74 |

**O pareamento funciona:** o desvio do número absoluto é 10–12 carros; o desvio
da *diferença* contra o timer é **2,8–4,0**. A maior parte da variância de janela
cancela, exatamente como o dono do projeto argumentou ao fixar 120 s.

**Ruído de jogada** (dois jogadores da MESMA habilidade, mesma seed):
média +0,50, **dp 3,39 carros**.
**Sinal de habilidade** (martelo − aleatório): **+15,7 carros**, e o sinal separa
os dois em **6 de 6 seeds sem sobreposição**.

**Veredito: 120 s NÃO é dominado por ruído para distinguir níveis grosseiros de
habilidade** — relação sinal/ruído ≈ 4,6. O que 120 s **não** resolve é
distinguir dois jogadores parecidos: se a diferença típica humano-vs-RL for da
ordem de **≤3,4 carros**, a rodada individual é moeda. **É isso que o agente A8
tem que medir contra a RL de verdade**, e é o gatilho para a duração voltar à
mesa.

### 6.3 Dois achados que não são sobre o jogo

1. **"Martelar todos os botões" bate o timer de 27 s em 6 de 6 seeds** (+7,83
   carros, +7,1%). Não é sofisticação: apertar tudo todo tick equivale a trocar
   de fase a cada 10 s (verde mínimo 7 + grade 5), e isso já é melhor que verde
   fixo de 27 s uniforme sem offset. **Um visitante que só martela o teclado vence
   o baseline.** Se ele também vencer a RL, o discurso muda — e a resposta correta
   é o baseline coordenado do agente A5, não encurtar o alcance do botão.
2. **A política atual perde para o timer no cenário aberto.** Fantasma da RL com
   `results/maq30_ats_full_best.pt`: **93 entregues (seed 100) e 82 (seed 101)**
   contra 111 e 109 do timer. Esperado — o checkpoint foi treinado na rede
   FECHADA com `di10/vm10`, e aqui roda em rede aberta com `di5/vm7` —, mas
   enquanto o agente A6 não retreinar, **o jogo mostra a RL perdendo no
   projetor**. Rodar com `--sem-rl` até lá é a saída honesta.

---

## 7. Fronteiras e defeitos reportados

Escrito pelo A3: `feira/jogo/**`, `feira/entrada/**`,
`feira/controladores/humano.py`, `tests/test_a3_*.py`, este documento.

Dois defeitos **reportados e não consertados** (código de outro agente):

1. **`ArenaSumo.roda()` roda o `.sumocfg` CANÔNICO em cenário de demanda em
   arquivo.** Ele reaponta `constants.SUMOCFG` para o arquivo da seed e logo
   depois chama `self.topologia(cenario)`, que passa por `_aponta_constants` de
   novo e devolve `SUMOCFG` ao canônico — que **não tem `<route-files>`**, de
   propósito. Medido: uma corrida de `aberta.maquete` pela Arena insere **0
   veículos**, e o `ultimo_diagnostico` ainda reporta o caminho da seed.
   Contornado dentro da fronteira por `feira.jogo.cenario_da_seed()`, que passa o
   cenário já com o `.sumocfg` da seed.
2. **A janela medida é `[t0+1, t1+1]`, não `[t0, t1)`.** `TrafficEnv.reset()` já
   dá um `simulationStep`, então o aquecimento fecha em `t0+1`. Mesma duração,
   deslocada, e **idêntica nos três braços** — o pareamento não sofre —, mas a
   `Chave` rotula outra coisa. O `ColetorDeSerie` recorta a série à janela
   declarada para o `Fantasma` (C8) não recusar as próprias amostras.

Um **buraco de contrato** reportado (C6, não consertado): `FonteEntrada.feedback()`
recebe `n` estados — um por semáforo — mas o quadro `LEDS` do protocolo serial tem
`n+1`, e não há como dizer o estado do LED do botão START. A assinatura que serve
ao motor é **`feedback(estados: list[str], start: str = OFF)`**, com o `start`
opcional: `n` continua significando "semáforos" em `valida_estados` e em toda
implementação existente, e quem monta o quadro de `n+1` compõe os dois. Passar
`n+1` posições no mesmo vetor quebraria `valida_estados(estados, n)` e faria o
índice do botão deixar de ser o índice do semáforo. Enquanto isso, o motor usa o
`feedback_start()` que o agente A4 pôs fora do Protocol (ver §1.3).

Uma **falha transitória** vista uma vez em 30+ corridas: `FatalTraCIError:
Connection closed by SUMO` no meio do aquecimento, com a mesma seed passando nas
três tentativas seguintes num processo novo. O motor já degrada (a rodada volta
com `motivo` e o jogo segue), mas se aparecer no ensaio com público vale medir.
