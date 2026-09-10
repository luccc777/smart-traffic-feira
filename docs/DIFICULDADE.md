# Adversários e calibração de dificuldade — P(o visitante vence a RL)

Agente A8. Onda 3. Documento do experimento que responde, **sem público**, a
pergunta que o dono do projeto declarou como medo específico:

> se a RL vence por pouco, alguém do público controla bem, derruba a RL em
> público, e o estudo cai por água abaixo.

A resposta sai de rodadas headless de jogadores **roteirizados** sobre o mesmo
protocolo da rodada de feira, com intervalo de confiança — e não de opinião sobre
o que um visitante consegue fazer.

**Fora do escopo, e não foi feito:** mudar a rodada para a RL ganhar. Onde o dado
diz que dá para vencer a RL, o número está publicado aqui do mesmo tamanho que os
outros, e a decisão do que fazer é do dono (§9).

---

## 0. TL;DR

**7650 rodadas**, 12 seeds held-out (100–111), 4 durações, 31 classes de
adversário, todas passando pela camada de entrada do visitante.

- **O melhor humano plausível EMPATA com a RL numa rodada de 120 s — e talvez
  fique um fio à frente.** Com o parâmetro escolhido **fora das held-out**
  (§3.1), o oráculo `gulosa_fase:f=1,margem=2` vence **57,1%** das rodadas
  [IC95 35,4%–77,9%], margem **+1,24 carro**. O oráculo do catálogo fixado a
  priori vence 49,2% [27,1%–71,7%] com margem −0,20, e no teste pareado por seed
  os dois braços são indistinguíveis nas três métricas: p = 0,457 (vazão),
  0,893 (fila), 0,958 (tempo no sistema). **O medo declarado do dono do projeto
  está confirmado como possível.**
- **O visitante que só martela o painel perde**, mas não com folga: **17,9%**
  [2,1%–38,8%] de vitórias, margem −4,55 carros — ou seja, **martelando, o
  público derruba a RL em cerca de 1 rodada a cada 6.**
- **A mão é a barreira, mais que a informação ou a reação.** Limitar o jogador a
  6 botões por tick de 5 s leva P(vitória) de 33,8% para **0,0%**. E esse é o
  parâmetro do estudo que **não foi medido com gente** (§10.3).
- **Martelar continua vencendo os dois baselines em 120 s** — `coordenado_c60`
  +10,65% (11/12, p = 2,5e-05) e `timer27` +7,28% (12/12), o que replica o
  +7,1% do A3. **Mas empata com o `c60` a 240 s**: a vitória em rodada curta é,
  em boa parte, o transiente de engate do plano coordenado (§6.5).
- **A duração escolhida é 120 s**, e a conta está no §6.4. A ressalva do A3
  ("margem ≤3,4 carros ⇒ a duração volta à mesa") está **ativada no pior grau**:
  a margem é 0,20 carro. Só que **nenhuma duração testada resolve** — a 240 s a
  razão margem/ruído ainda é 1,01, e o preço é metade da vazão de público.
- **A seed é um botão de dificuldade.** P(vitória) do melhor humano vai de **0%
  (seeds 101, 104, 109) a 100% (107, 108, 111)** entre as 12 held-out.
- **O visitante que só lê o mapa de calor** (aperta os 6 cruzamentos mais cheios)
  vence **25,8%** [12,1%–41,2%]. A faixa em que o visitante real mora é, portanto,
  **26% a 57%**, e este estudo não estreita mais que isso.
- **`sane()` e `sinais_de_travamento` não dispararam uma única vez em 4752
  rodadas de 120 s** — nem para o farol congelado, que entrega 36 carros contra
  112 do timer. Em janela curta os dois detectores do repositório são **cegos**,
  e o motivo é estrutural (§7). O substituto medido e calibrado (acúmulo
  excedente pareado, +20 pp) tem zero falso positivo e pega 528 de 528 rodadas
  congeladas — **e ele deveria morar em `feira/metricas.py`, que está fora da
  minha fronteira** (§10.1).
- **O artefato de sobrevivência, medido:** se a manchete fosse tempo médio de
  viagem, o **vencedor do jogo seria quem congela os semáforos** — `arterial`
  tem o melhor tempo de viagem de todo o catálogo (124,5 s) entregando 48
  carros contra os 125 do melhor humano (§8).

---

## 1. O que foi medido, e como

### 1.1 A rodada é EXATAMENTE a do jogo

| | |
|---|---|
| cenário | `aberta.maquete` — 12 semáforos, 12 controláveis, 3500 veh/h |
| grade | `di5/vm7/am3/mr0` (decisão a cada 5 s, verde mínimo 7 s, amarelo 3 s) |
| aquecimento | 300 s com o plano comum, **igual nos três braços** |
| janela | 120 s (as outras durações entram só no §6) |
| botões | 12, um por semáforo |
| manchete | **carros entregues** na janela |
| seeds | **100–111**, as 12 held-out do projeto |

Quem roda é a `ArenaSumo` (C4) — o mesmo laço único do resto do repositório —, e
cada rodada devolve um `Resultado` (C5) carimbado com a mesma `Chave` dos dois
oponentes. Rodadas de braços diferentes na mesma seed são pareadas por
construção: mesma demanda, mesmo aquecimento, mesmo `t0`.

### 1.2 O adversário entra pela porta do visitante — e isso foi medido, não suposto

A armadilha nomeada nº1 desta trilha: um adversário implementado direto como
`Controlador` (C3) devolve o vetor de ações e **pula a camada que define o
jogo** — a intenção que entra numa fila, é consumida só no próximo tick da grade,
e só é aceita se o verde mínimo fechou. Um adversário assim mede outro jogo.

Aqui o caminho é o do público, peça por peça:

    Roteirista.aperta() -> FonteRoteirizada (C6) -> ControladorHumano -> Arena

`AdversarioHumano` (`feira/adversarios/fonte.py`) **não emite ação nenhuma**: ele
forma a intenção, carrega o botão na fonte e delega o `decide` ao
`ControladorHumano` do agente A3 — o mesmo objeto que o teclado e a botoeira
alimentam na feira. O que isso preserva, e um atalho C3 perderia:

* a máscara `pode_trocar` (`controlável ∧ ¬amarelo ∧ verde_desde ≥ min_green`),
  que é o mesmo predicado do `TrafficEnv._apply_actions`;
* o **descarte da intenção negada** — "consumida no próximo tick" quer dizer
  *gasta*: um botão recusado não dispara sozinho depois
  (`test_a_intencao_negada_e_gasta_e_nao_dispara_no_tick_seguinte`);
* a gravação por tick, que reproduz a rodada byte a byte no `ReplayInput`.

**O atalho C3, medido:** para o `martelo` (que aperta TUDO em TODO tick) o
caminho fiel e um controlador C3 que emite `TROCAR` em tudo dão o **mesmo
`Resultado`, campo a campo** — porque a Arena aplica a mesma máscara. A
equivalência **não** se estende a nenhum adversário com intenção seletiva: aí a
fila de intenções e o descarte do bit recusado mudam o que chega ao tick
seguinte. Guardado em
`tests/test_a8_bancada.py::test_o_atalho_c3_mede_o_mesmo_que_o_caminho_fiel_no_martelo`,
com a ressalva escrita na própria docstring.

### 1.3 O catálogo de adversários

| adversário | o que ele é |
|---|---|
| `parado` | não aperta nada — o piso, e o controle do experimento |
| `martelo` | os 12 botões em todo tick (as duas palmas no painel 3x4) |
| `periodica:p=K` | os 12 a cada `K` ticks — o visitante com ritmo (varre o ciclo) |
| `aleatoria:p=X` | cada botão com probabilidade `X` por tick — o visitante sem plano |
| `arterial` | segura o verde na arterial (o eixo E/W, as vias `H*`) |
| `gulosa_fila:k=K` | aperta os `K` cruzamentos de maior fila — o que se faz olhando o mapa de calor |
| `gulosa_fase:f=F` | **oráculo**: troca quando o lado no vermelho tem mais fila que o lado no verde |
| `sabotador` | o contrário da gulosa: serve sempre o lado vazio (existe para pegar bug de métrica) |

Modificadores compostos com `@`: `lag=L` (reage à tela de `L` ticks atrás, 5 s
por tick), `mao=M` (no máximo `M` botões por tick), `falha`/`extra` (o ruído de
mão do §1.4).

**`gulosa_fase` é oráculo e está rotulado como tal.** Ele separa a fila entre
aproximações no verde e no vermelho decodificando o estado `ats` (colunas 0/4/8/12
= parados por aproximação N,S,E,W) com o mapa fase→aproximação derivado do
`.net.xml`. Um visitante não lê o vetor da política; ele lê o mapa de calor, que
mostra os parados por faixa — então o oráculo é um **teto plausível**, não uma
descrição de visitante médio. O `gulosa_fila` é a versão que um humano de fato
consegue executar, e a diferença entre os dois está medida no §4.

### 1.4 O ruído de mão, e por que 200 rodadas exigem ele

Nenhum visitante aperta com regularidade de relógio. Os adversários da campanha
principal carregam `falha=0.05` (5% das pressões pretendidas se perdem) e
`extra=0.02` (2% de chance por botão de uma pressão que ninguém quis).

Isso não é enfeite: **sem ruído, repetir a mesma seed é copiar a rodada.** As
"200 rodadas por adversário" da DoD seriam 12 rodadas clonadas 17 vezes, e o
intervalo de confiança sairia estreito por construção — pior que não ter
intervalo. A campanha detecta adversário determinístico
(`Roteirista.deterministica`) e roda **1 repetição por seed** para ele, em vez de
fingir 200 amostras: as versões puras aparecem nas tabelas do §3 e do §4 com
12 rodadas cada, sempre rotuladas.

`(adversário, seed, repetição)` determina a sequência inteira de botões, via
`zlib.crc32` — `hash()` do Python é aleatorizado por processo e produziria rodada
irreproduzível. Qualquer linha da campanha pode ser re-rodada e reauditada.

### 1.5 O intervalo de confiança é por SEED, não por rodada

As 240 rodadas de um adversário **não** são 240 amostras independentes: são 12
seeds × 20 repetições, e duas repetições na mesma seed enfrentam a MESMA demanda.
Um intervalo binomial sobre 240 ensaios trata isso como independente e sai
estreito por construção — exatamente o erro que o pareamento deste projeto existe
para não cometer.

O intervalo publicado vem de **bootstrap agrupado**: reamostra as 12 seeds com
reposição e, dentro de cada seed sorteada, as repetições (5000 réplicas,
percentis 2,5/97,5). O Wilson binomial aparece ao lado nas tabelas, **rotulado
como ingênuo**, para mostrar o tamanho do erro que ele cometeria.

### 1.6 O que é "vencer"

`entregues` do humano **estritamente maior** que o do oponente, na mesma seed e
na mesma janela. Empate conta separado — na tela do jogo ele aparece como
"EMPATE", e chamar empate de vitória seria dar ao visitante um resultado que ele
não fez.

`tempo_medio_entregue` não decide nada aqui, e o §8 mede por quê.

---

## 2. Os três braços de referência, na janela de 120 s

12 seeds held-out, uma corrida por seed (os três são determinísticos dada a seed —
é por isso que os fantasmas do modo jogo podem ser pré-computados):

| braço | entregues (dp) | fila média | tempo no sistema | travou | não-sãs | `sinais` |
|---|---|---|---|---|---|---|
| **`rl:v1_queue_di5`** | **124,1** (12,3) | 34,85 | 111,6 s | 0/12 | 0/12 | 0/12 |
| `timer:uniforme_27s` | 112,5 (12,9) | 49,48 | 114,3 s | 0/12 | 0/12 | 0/12 |
| `timer:coordenado_c60` | 109,2 (13,1) | 53,35 | 115,0 s | 0/12 | 0/12 | 0/12 |

**Duas leituras que precisam ser ditas antes de qualquer outra coisa:**

1. **A RL abre +10,3% de vazão sobre o timer de 27 s numa janela de 120 s** —
   contra os +0,35% que ela abre sobre o `coordenado_c60` numa janela de 7200 s
   (`RESULTADOS_ABERTA.md` §4.1). Não é contradição: são grandezas diferentes.
   Na janela longa, com backlog zero, a diferença de vazão se reduz a
   `ativos_fim` e o teto útil é ~+0,4% (§4.3 de lá). Na janela curta a política
   está **drenando a fila herdada do aquecimento**, e isso aparece como carro
   entregue. O jogo mede a fase transitória de propósito: é ela que cabe em 2 min
   de projetor.
2. **O `coordenado_c60` fica ABAIXO do timer uniforme nesta janela** (109,2
   contra 112,5), invertendo o resultado da janela de 7200 s. A causa é
   estrutural e conhecida: o aquecimento roda o **timer uniforme** nos três
   braços (`ArenaSumo._plano_de_aquecimento`, e tem de ser igual para os três,
   senão a rodada não é pareada), então o plano coordenado começa a janela fora
   de fase e precisa de ~1 ciclo (60 s) para se prender ao relógio absoluto. Em
   120 s isso é metade da rodada. O §6 mede a curva por duração.

---

## 3. P(o humano vence a RL) — a manchete

Contra `rl:v1_queue_di5`, janela de 120 s, 12 seeds held-out. Intervalo por
bootstrap agrupado (5000 réplicas). Os adversários da campanha principal têm 240
rodadas cada; as versões puras (determinísticas), 12.

| adversário | n | **P(vitória)** | IC95 agrupado | empate | margem média (carros) | seeds vencidas |
|---|---|---|---|---|---|---|
| `gulosa_fase:f=1` (**oráculo, sem ruído**) | 12 | **58,3%** | [33,3%, 83,3%] | 0,0% | **+1,08** | 7/12 |
| `gulosa_fase:f=1` + ruído de mão | 240 | **49,2%** | [27,1%, 71,7%] | 6,7% | **−0,20** | 6/12 |
| `gulosa_fase:f=1` + lag 1 tick + ruído | 240 | **33,8%** | [17,9%, 50,4%] | 8,8% | −1,69 | 4/12 |
| `gulosa_fila:k=12` + ruído | 240 | **18,3%** | [2,1%, 40,0%] | 4,6% | −3,63 | 2/12 |
| `martelo` + ruído | 240 | **17,9%** | [2,1%, 38,8%] | 3,8% | −4,55 | 2/12 |
| `martelo` (puro) | 12 | 16,7% | [0,0%, 41,7%] | 0,0% | −3,83 | 2/12 |
| `periodica:p=2` + ruído | 240 | 8,8% | [1,2%, 18,8%] | 3,3% | −6,28 | 0/12 |
| `gulosa_fila:k=4` + ruído | 240 | 7,5% | [1,2%, 15,4%] | 6,7% | −6,76 | 0/12 |
| `aleatoria:p=0.85` | 240 | 7,1% | [0,0%, 18,3%] | 1,7% | −6,37 | 1/12 |
| `gulosa_fase` + lag + **mão de 6 botões** | 240 | **0,0%** | [0,0%, 0,0%] | 1,3% | −14,74 | 0/12 |
| `aleatoria:p=0.35` | 240 | 0,0% | [0,0%, 0,0%] | 0,0% | −19,52 | 0/12 |
| `arterial` + ruído | 240 | 0,0% | [0,0%, 0,0%] | 0,0% | −68,02 | 0/12 |
| `sabotador` + ruído | 240 | 0,0% | [0,0%, 0,0%] | 0,0% | −81,38 | 0/12 |
| `parado` | 24 | 0,0% | [0,0%, 0,0%] | 0,0% | −88,00 | 0/12 |

A tabela completa, com as 31 classes e o Wilson ingênuo ao lado de cada
intervalo, está em [`results/a8/tabelas.md`](../results/a8/tabelas.md).

**A manchete, sem rodeio: o melhor humano plausível empata com a RL.** O oráculo
sem ruído vence 58,3% das rodadas com margem de **+1,08 carro**; com ruído de mão
vence 49,2% com margem de **−0,20 carro**. O teste pareado por seed, nas três
métricas, não distingue os dois:

| métrica (oráculo puro vs RL, 12 seeds) | RL | oráculo | Δ | vitórias | p |
|---|---|---|---|---|---|
| entregues | 124,08 | 125,17 | +0,97% | 7/12 | **0,457** |
| fila média | 34,85 | 34,96 | −0,87% | 4/12 | **0,893** |
| tempo no sistema | 111,62 | 111,62 | −0,01% | 6/12 | **0,958** |

Três p-valores acima de 0,45 é o retrato de um empate, não de uma vitória de
ninguém. **O medo declarado do dono do projeto está confirmado como possível:**
existe uma estratégia executável em 120 s que fica lado a lado com a política e
vence a rodada individual em cerca de metade das vezes.

**O que separa esse oráculo de um visitante de verdade — e o preço de cada
degrau, em carros:**

| degrau | P(vitória) vs RL | margem |
|---|---|---|
| oráculo: vê a fila por aproximação, reage no mesmo tick, aperta quantos botões quiser | 58,3% | +1,08 |
| + ruído de mão (5% de falha, 2% de aperto acidental) | 49,2% | −0,20 |
| + reação de 1 tick (5 s) | 33,8% | −1,69 |
| + mão limitada a 6 botões por tick | **0,0%** | −14,74 |
| só o mapa de calor por cruzamento (`gulosa_fila:k=12`), sem separar aproximação | 18,3% | −3,63 |
| martelar os 12 | 17,9% | −4,55 |

**A limitação física da mão é o degrau que mais custa** — mais que a informação e
mais que a reação. Um visitante que só alcança 6 dos 12 botões por tick de 5 s
perde por 14,7 carros e não vence nenhuma das 240 rodadas. Esse é o degrau em que
o dado é mais fraco, e está dito no §10: quantos botões uma pessoa de verdade
alcança em 5 s no painel 3x4 **não foi medido com gente**, foi parametrizado.

### 3.1 O teto, com o parâmetro escolhido FORA das held-out

O catálogo do §1.3 foi fixado antes de rodar, sem varredura — o que é a
disciplina certa, e também deixa em aberto se o teto de P(vitória) está
subestimado. Fechei essa ponta do jeito que este projeto exige: **varri 12
configurações em seeds que NÃO são as held-out** (42–47 e 230–233, 10 seeds,
5 repetições, 600 rodadas), escolhi as duas vencedoras lá, e só então rodei
essas duas nas 12 held-out.

Escolher olhando a held-out é o erro que o `BASELINE_ABERTO.md` §4.6 documenta
para o `c50` e que o A6 se recusou a cometer com o `v3`; não vou cometê-lo aqui
para deixar a manchete mais forte.

| configuração | P(vitória) na varredura (42–47, 230–233) | P(vitória) nas **held-out** |
|---|---|---|
| `gulosa_fase:f=1,margem=2` | 58,0% | **57,1%** [35,4%, 77,9%] |
| `gulosa_fila:k=6` | 52,0% | **25,8%** [12,1%, 41,2%] |
| `gulosa_fase:f=1` (o do catálogo a priori) | 52,0% | 49,2% [27,1%, 71,7%] |
| `gulosa_fila:k=12` (o do catálogo a priori) | 18,0% | 18,3% [2,1%, 40,0%] |

**O teto medido, então, é P(vitória) = 57,1% [35,4%, 77,9%], margem +1,24
carro** — o melhor humano plausível fica ligeiramente **à frente** da RL, e o
intervalo não exclui nem 35% nem 78%.

E a tabela traz de brinde a razão de a varredura ter de ser fora da amostra: o
`gulosa_fila:k=6` prometeu 52% na varredura e entregou **25,8%** na held-out.
Escolher parâmetro no conjunto de teste teria publicado o primeiro número.

| adversário ajustado (held-out, 240 rodadas) | vs RL | vs `coordenado_c60` | vs `timer27` |
|---|---|---|---|
| `gulosa_fase:f=1,margem=2` (oráculo) | **57,1%**, +1,24 | 100%, +16,15 | 100%, +12,82 |
| `gulosa_fila:k=6` (só o mapa de calor) | 25,8%, −2,99 | 98,7%, +11,92 | 98,3%, +8,59 |

Os dois passam em `sane()` nas 480 rodadas, com zero sinais e zero acúmulo acima
do limiar.

**A faixa em que o visitante real mora, então, é 26% a 57%** — 26% se ele só
consegue ler o mapa de calor por cruzamento e apertar os 6 mais cheios, 57% se
ele enxerga a fila separada por aproximação e reage no mesmo tick. Este estudo
não estreita mais que isso, e o §10.3 diz o que faltaria para estreitar.

---

## 4. Pergunta 1 — martelar ainda vence?

**Contra o `coordenado_c60`: vence, e com folga.** Teste pareado por seed,
`martelo` puro, 12 seeds:

| métrica | `coordenado_c60` | `martelo` | Δ | vitórias | p |
|---|---|---|---|---|---|
| entregues | 109,17 | 120,25 | **+10,65%** | 11/12 | 2,5e-05 |
| fila média | 53,35 | 39,27 | **+26,86%** | 12/12 | 4,0e-07 |
| tempo no sistema | 114,97 | 112,10 | +2,51% | 12/12 | 1,3e-05 |

Com ruído de mão, 240 rodadas: **P(vitória) = 96,2%** [87,5%, 100%], margem
**+10,37** carros.

**Contra o timer uniforme de 27 s: vence 12/12** (+7,28%, p = 1,3e-04), o que
**reproduz o número do A3** (+7,83 carros / +7,1%, 6 de 6 seeds, `JOGO.md` §6.2)
numa bancada com o dobro de seeds e 20x mais rodadas.

**Contra a RL: perde.** 17,9% de vitórias, margem −4,55 carros; no pareado puro,
−2,95% de vazão (2/12, p = 0,010) e −12,58% de fila (1/12, p = 4,9e-05).

**A resposta completa: martelar continua vencendo o baseline — os dois —, e para
de vencer a RL.** Com duas ressalvas obrigatórias:

1. **Parte da vitória sobre o `coordenado_c60` é o transiente de engate do
   plano** (§2, item 2), não fraqueza do plano. A curva por duração está no §6.
2. **A margem sobre a RL é de 4,5 carros e o ruído de jogada é de 3,3** (§6.1).
   "Martelar perde para a RL" é verdade na média de 240 rodadas; **na rodada
   individual, martelar vence a RL em cerca de 1 de cada 6.**

### Um resultado de validação que caiu no colo

`periodica:p=6` — apertar os 12 botões a cada 6 ticks (30 s) — realiza verde de
`max(10, 30) − 3 = 27 s`, que é **exatamente** o `ControladorTimer(27)`. Medido:
os dois dão o **mesmo número em 12 de 12 seeds** — entregues, fila e tempo
idênticos, Δ = 0,00%, empate em 12/12. É a prova ponta a ponta de que o caminho
`botão -> FonteEntrada -> ControladorHumano -> Arena` produz o mesmo controlador
que a implementação direta em C3 quando as duas descrevem a mesma política, e ela
apareceu sem ninguém procurar.

Pelo mesmo mecanismo, `martelo` e `periodica:p=2` são o **mesmo adversário** (verde
realizado de 7 s nos dois, porque o piso da grade é 10 s), e a campanha os mediu
idênticos em 12/12 seeds. A varredura de período tem, portanto, quatro pontos
úteis e não seis.

---

## 5. Seed a seed — a seed é um parâmetro de dificuldade

`gulosa_fase:f=1` + ruído de mão (o adversário do empate), 20 rodadas por seed:

| seed | RL | c60 | timer27 | humano média (min–max) | P(vitória) na seed | margem |
|---|---|---|---|---|---|---|
| 100 | 120 | 105 | 111 | 118,1 (114–122) | 10% | −1,90 |
| 101 | 126 | 110 | 109 | 121,0 (117–124) | 0% | −5,00 |
| 102 | 121 | 100 | 112 | 119,3 (115–125) | 20% | −1,70 |
| 103 | 107 | 96 | 92 | 107,8 (103–113) | 60% | +0,85 |
| 104 | 146 | 129 | 130 | 141,1 (136–145) | 0% | −4,90 |
| 105 | 118 | 105 | 104 | 120,3 (113–126) | 70% | +2,30 |
| 106 | 131 | 126 | 123 | 131,2 (127–134) | 50% | +0,15 |
| 107 | 101 | 84 | 89 | 104,3 (102–108) | **100%** | +3,30 |
| 108 | 128 | 115 | 115 | 131,7 (129–134) | **100%** | +3,70 |
| 109 | 123 | 102 | 114 | 114,8 (113–119) | 0% | −8,15 |
| 110 | 137 | 117 | 126 | 140,4 (133–144) | 80% | +3,45 |
| 111 | 131 | 121 | 125 | 136,4 (133–143) | **100%** | +5,45 |

O P(vitória) agregado de 49,2% é a média de doze números que vão de **0% a 100%**.
Em quatro seeds (100, 101, 104, 109) o melhor humano plausível não vence quase
nunca; em três (107, 108, 111) ele vence sempre. **A seed da rodada é, na prática,
um parâmetro de dificuldade** — e é um parâmetro que o operador escolhe
(`JOGO.md` §4.3). O que fazer com isso é decisão do dono, e as opções estão no
§9. O que este documento não faz é escolher a seed para a RL ganhar.

---

## 6. Pergunta 2 — 120 s aguenta? A conta, e a duração escolhida

### 6.1 O ruído de jogada, agora MEDIDO por dentro

O A3 estimou o ruído de jogada em **3,39 carros** comparando dois adversários
aleatórios de mesma habilidade com sementes diferentes. Aqui ele sai por
construção, de dentro do próprio adversário: **o desvio-padrão agrupado das 20
repetições dentro de cada seed** (mesma demanda, mesma estratégia; o que muda é só
a mão), vezes `sqrt(2)` para virar o desvio da *diferença* entre duas rodadas:

| adversário (120 s) | dp intra-seed | **ruído de jogada** |
|---|---|---|
| `martelo` + ruído | 2,30 | **3,26** |
| `gulosa_fase:f=1` + ruído | 2,44 | **3,45** |
| `gulosa_fila:k=12` + ruído | 2,56 | **3,63** |
| `gulosa_fase` + lag + ruído | 2,61 | **3,69** |
| `aleatoria:p=0.35` | 5,89 | 8,33 |
| `parado` / `sabotador` | 7,39 | 10,45 |

**O número do A3 estava certo**: 3,26–3,69 para os adversários de habilidade alta,
contra os 3,39 que ele estimou por outro caminho, com outro tipo de jogador e um
quinto das rodadas. E o sinal de habilidade também replica: `martelo` (119,5)
menos `aleatoria:p=0.35` (104,6) dá **+14,9 carros** com ruído de 3,3, ou seja
**S/R = 4,5** — o A3 mediu +15,7 e 4,6.

### 6.2 A conta da duração

Adversário mais forte (`gulosa_fase:f=1` + ruído de mão), contra a RL, 240 rodadas
por duração:

| duração | P(vitória) | IC95 agrupado | margem média | ruído de jogada | \|margem\|/ruído |
|---|---|---|---|---|---|
| 60 s | **49,2%** | [27,5%, 71,7%] | +0,12 | 2,06 | 0,06 |
| **120 s** | **49,2%** | [27,1%, 71,7%] | −0,20 | 3,45 | 0,06 |
| 180 s | **29,2%** | [12,5%, 47,1%] | −2,24 | 3,60 | 0,62 |
| 240 s | **21,2%** | [6,2%, 37,9%] | −3,85 | 3,82 | 1,01 |

E o `martelo`, que é o visitante que de fato aparece:

| duração | P(vitória) | margem | ruído | \|margem\|/ruído |
|---|---|---|---|---|
| 60 s | 35,0% | −0,65 | 2,46 | 0,26 |
| **120 s** | 17,9% | −4,55 | 3,26 | 1,40 |
| 180 s | **0,0%** | −10,07 | 4,18 | 2,41 |
| 240 s | **0,0%** | −16,15 | 4,43 | 3,64 |

**A leitura, em três frases:**

1. **A margem cresce mais rápido que o ruído** — a margem quase quadruplica de 120
   para 240 s (0,20 → 3,85) enquanto o ruído sobe 11% (3,45 → 3,82), porque o
   ruído de jogada cresce com `sqrt(T)` e a margem, com `T`. Duração maior
   **separa** melhor: é o que a teoria previa e o dado confirma.
2. **Mas nenhuma duração testada torna a rodada individual DECISIVA contra o
   melhor humano.** Mesmo a 240 s, `|margem|/ruído = 1,01` — a margem é do tamanho
   do ruído, e a rodada individual continua sendo essencialmente uma moeda
   viciada, não um resultado. Contra o martelo, sim: a partir de 180 s ele perde
   em 240 de 240 rodadas.
3. **O que a duração compra é P(vitória), não certeza:** 49,2% → 21,2% dobrando a
   rodada.

### 6.3 O preço do relógio

A rodada não custa só a janela: `JOGO.md` §2 mede contagem (3 s) + resultado (8 s)
+ fantasma com cache (~0 s). Então:

| duração da janela | rodada de ponta a ponta | visitantes por hora | P(melhor humano vence a RL) |
|---|---|---|---|
| **120 s** | ~131 s | **~27** | 49,2% |
| 180 s | ~191 s | ~19 | 29,2% |
| 240 s | ~251 s | ~14 | 21,2% |

Dobrar a rodada **corta a vazão de público pela metade** para levar P(vitória) de
49% a 21%. Nenhum dos dois números é "certo"; os dois são o preço um do outro, e a
escolha entre eles é sobre o que a banca quer — não sobre o que a estatística
manda.

### 6.4 A duração que este dado escolhe: **120 s**

A conta, explícita:

* **120 s cumpre o que a rodada existe para fazer.** Ela separa níveis grosseiros
  de habilidade com S/R = 4,5 (§6.1) — o mesmo critério com que o A3 aprovou os
  120 s, agora confirmado com 12 seeds e 4752 rodadas em vez de 6 seeds e 30.
* **A ressalva registrada quando o dono escolheu 120 s contra a recomendação de
  180 s está ATIVADA, e ativada no pior grau possível:** a margem humano-vs-RL não
  é "≤3,4 carros", é **0,20 carro**. A rodada individual contra o melhor humano
  plausível é moeda, e isso é fato medido.
* **Só que a duração não é o remédio disso.** Ir para 180 s move `|margem|/ruído`
  de 0,06 para 0,62, e para 240 s, para 1,01 — nenhum dos dois chega perto de
  tornar a rodada decisiva. O empate do §3 é **real**, não artefato de janela
  curta: ele sobrevive a dobrar a rodada. Trocar 120 por 240 compra uma redução de
  P(vitória) de 49% para 21% pagando metade da vazão de público, e essa é uma
  decisão de banca, não de estatística (§9, opção B).
* **Contra o adversário que de fato aparece na feira — o que martela —, 120 s já
  decide**: `|margem|/ruído = 1,40`, P(vitória) 17,9%.

**Portanto: 120 s fica, e a ressalva do A3 fica fechada com número em vez de
opinião** — não porque a margem seja confortável (ela é 0,20 carro), mas porque
nenhuma duração alcançável a torna confortável, e as durações maiores custam
público. Se o dono quiser comprar P(vitória) mais baixo, o preço está na tabela do
§6.3.

### 6.5 De quebra: quanto do "martelar vence o coordenado" é transiente de engate

A duração também mede a ressalva do §4. `coordenado_c60` menos `timer:uniforme_27s`,
mesma seed, mesma janela:

| duração | c60 − timer27 | seeds em que o c60 vence |
|---|---|---|
| 60 s | **−4,08** | 2/12 |
| 120 s | **−3,33** | 4/12 |
| 180 s | +0,50 | 5/12 |
| 240 s | **+2,75** | **9/12** |

O plano coordenado só **alcança** o timer uniforme a partir de ~180 s — que é
exatamente a ordem de grandeza de 1 a 2 ciclos de 60 s de engate, contados a partir
de um aquecimento que rodou o timer. E a vitória do martelo sobre ele derrete na
mesma escala:

| duração | `martelo` vs `coordenado_c60` | P(vitória) |
|---|---|---|
| 60 s | +10,02 | 100,0% |
| 120 s | +10,37 | 96,2% |
| 180 s | +5,84 | 76,2% |
| 240 s | **−0,07** | **39,6%** |

**Então a resposta honesta da pergunta 1 tem duas metades:** martelar vence o
`coordenado_c60` numa rodada de feira (120 s) com folga e significância — e
**empata com ele numa rodada de 240 s**. A afirmação "um visitante que só martela o
teclado bate o baseline coordenado" é verdadeira **no regime do jogo** e falsa
fora dele; quem citar a frase precisa citar a janela junto. Contra o timer
uniforme de 27 s, que é o que o projetor de fato mostra, martelar vence em toda
duração testada.

---

## 7. Saúde — e o achado de que o detector padrão é CEGO em 120 s

**Nas 4752 rodadas de 120 s: zero `travou`, zero reprovações em `sane()`, zero
`sinais_de_travamento`.** Inclusive nas 24 rodadas de `parado` e nas 252 de
`sabotador`, que entregam **36 a 43 carros contra os 112 do timer** e deixam a
população ativa crescer mais de 50%.

Isso não é a rede estando saudável — é o detector não alcançando este regime, e
os três motivos são estruturais:

1. **`Resultado.travou` não pode disparar.** O critério da Arena é `seca_max_s =
   600 s` sem nenhuma chegada. A rodada inteira tem 120 s: o maior jejum possível
   é menor que um quinto do limiar. Numa rodada de feira, o carimbo de travamento
   da Arena é, por construção, sempre `False`.
2. **A lacuna de sobrevivência sai NEGATIVA para todo mundo** (−24% nos
   adversários bons, −5,6% no `parado`, +0,6% no `arterial`), porque numa janela
   de 120 s metade da população está censurada por construção — é exatamente a
   nota que o C5 já escrevia sobre limiar dependente de regime, acontecendo. Com
   `lacuna_max=25%`, `sinais_de_travamento` devolve lista vazia para o farol
   congelado. E note a direção: o `parado` tem a lacuna MENOS negativa dos
   adversários ruins, isto é, a métrica move para o lado errado.
3. **O backlog de inserção também não pega.** O pior caso (`parado`) para 9
   veículos na borda de ~131 agendados = 6,9%, abaixo dos 10% do `sane()`.

### O detector que funciona nesta janela, calibrado e publicado

A malha está em regime, então a população ativa deveria ficar aproximadamente
constante na janela; crescimento sustentado é acúmulo. Mas o crescimento
**absoluto** não serve de limiar, e isso foi medido: nas seeds 103 e 107 a
demanda sobe dentro da janela e **todos** os braços acumulam — o `coordenado_c60`
chega a +37,5% na seed 107 sem nada de errado.

O sinal que funciona é **pareado**, como o resto do projeto:

    acúmulo excedente = crescimento_relativo(humano) − crescimento_relativo(timer27 na MESMA seed)

| grupo | acúmulo excedente médio | máximo | rodadas acima de +20 pp |
|---|---|---|---|
| braços de referência (`rl`, `c60`) contra o `timer27` | −8,1 / +2,4 pp | +8,7 pp | **0 de 24** |
| adversários sãos (24 classes, 3708 rodadas) | −8 a +5 pp | **+18,1 pp** | **0** |
| `aleatoria:p=0.1` | +26 pp | +49 pp | 190 de 240 |
| `arterial` | +39 / +45 pp | +57 pp | 252 de 252 |
| `aleatoria:p=0.02` | +45 pp | +69 pp | 239 de 240 |
| `sabotador` | +47 / +51 pp | +71 pp | 252 de 252 |
| `parado` | +51 pp | +65 pp | 24 de 24 |

**Limiar declarado: +20 pontos percentuais.** Ele cai no vazio entre os dois
grupos — o maior excedente de um adversário são é **+18,1 pp** e o menor excedente
MÉDIO da família congelada é **+26,4 pp** —, tem **zero falso positivo** nos
braços de referência (0 de 24 em 120 s; 0 de 96 somando as quatro durações) e
pega **100%** das rodadas de `parado`, `sabotador` e `arterial` — **528 de 528**. Está implementado em
`scripts/adversarios_analise.py::LIMIAR_ACUMULO` e sai por adversário na tabela
de saúde de [`results/a8/tabelas.md`](../results/a8/tabelas.md).

**Isto é um buraco de contrato, reportado e não consertado** (§10, item 1): quem
publica um número de rodada curta hoje não tem, no repositório, nenhuma checagem
que recuse a rodada travada.

---

## 8. O artefato de sobrevivência, medido — e por que a manchete é `entregues`

A armadilha nº3 da trilha diz que um adversário que trave a rede **melhora** o
tempo médio de viagem, porque os presos saem da média e sobram as viagens curtas.
Isto é o que a campanha mediu, ordenado pelo tempo médio de quem chegou:

| adversário | entregues | **tempo médio ENTREGUE** | tempo no SISTEMA | fila |
|---|---|---|---|---|
| `arterial` (puro) | **48,0** | **124,5 s** ← o melhor | 125,1 s | 128,6 |
| `arterial` + ruído | 56,1 | 135,0 s | 123,8 s | 119,4 |
| `parado` / `sabotador` (puro) | **36,1** | 137,1 s | 129,0 s | 150,2 |
| `martelo` | 120,2 | 146,1 s | 112,1 s | 39,3 |
| `gulosa_fase:f=1` (o melhor humano) | 125,2 | 146,2 s | 111,6 s | 35,0 |
| `aleatoria:p=0.1` | 74,0 | 161,3 s ← o pior | 122,2 s | 96,2 |

**Se a manchete do jogo fosse "tempo médio de viagem", o vencedor seria quem
congela os 12 semáforos na arterial e entrega 48 carros.** Ele bate o melhor
humano por 22 segundos de viagem média — entregando 40% do que ele entrega. O
número é este, e é o motivo pelo qual `JOGO.md` §1.4 fixou `entregues` como
manchete antes de qualquer visitante encostar no botão.

**A métrica secundária que aguenta 120 s é `tempo_medio_no_sistema`**, e isso
também é medido: ela ordena certo (`parado` 129,0 s é pior que `martelo` 112,1 s)
porque conta quem ficou preso, censurado em `t1`. `tempo_medio_entregue` pode
aparecer na tela como curiosidade; **não pode aparecer como critério.**

---

## 9. O que fazer com isto — as opções, com o custo de cada uma

Esta seção **não recomenda nada**: a decisão é do dono do projeto. O que ela faz é
pôr o preço em cada caminho, com o número medido ao lado.

| # | opção | o que o dado diz do custo |
|---|---|---|
| A | **Não mexer em nada** | O visitante que executa a melhor estratégia plausível vence a RL em **57,1%** das rodadas (§3.1); lendo só o mapa de calor, 25,8%; martelando, 17,9%. Em três das doze seeds o melhor humano vence sempre. Custo: a RL perde em público, com alguma frequência. Benefício: nada a explicar depois, e o placar é honesto. |
| B | **Rodada de 240 s** | P(vitória) do oráculo do catálogo cai de 49,2% para 21,2%, e a do martelo de 17,9% para 0,0% (§6.2). Custo: 4 min de relógio por visitante em vez de 2 — metade da vazão de público na banca, e o ensaio do A3 sobre atenção do visitante não foi refeito para 4 min. |
| C | **Modo corredor** (visitante controla só os 4 da arterial) | **O dado diz que ele NÃO funciona como está.** Semáforo que ninguém aperta fica congelado: `parado` entrega 36 contra 112 do timer, e `arterial` (que congela os 12 na avenida) entrega 48. O modo corredor exige que os 8 semáforos restantes rodem um plano de fundo — o que **não existe hoje** e é código do A3/A5, não deste agente. Custo: implementação nova + o adversário passa a ser outro jogo. |
| D | **Escolher a seed da demo** | P(vitória) varia de 0% a 100% entre as 12 seeds (§5). Escolher entre 101/104/109 (o humano nunca vence) e 107/108/111 (vence sempre) é um botão de dificuldade de custo zero. **É também a opção que mais compromete o estudo se for usada sem dizer:** o número held-out de 12 seeds é a manchete científica, e uma demo rodada só nas seeds favoráveis precisa estar rotulada como tal na tela. |
| E | **Mudar a moldura do placar** — "bata o TIMER" em vez de "bata a REDE NEURAL" | Contra o `timer27`, o martelo vence 91,2% e o oráculo 96,2%: o visitante quase sempre ganha alguma coisa, e a RL continua no placar como a terceira barra, com o número dela. Custo: é decisão de narrativa, e ela troca "a RL é imbatível" (que o dado não sustenta) por "a RL joga no nível do melhor humano" (que o dado sustenta, §3). |
| F | **Apertar a restrição do jogador** (menos botões por tick, grade mais grossa, menos semáforos) | O degrau `mão de 6 botões` sozinho leva P(vitória) de 33,8% para **0,0%** (§3). Custo: é calibrar a dificuldade para a RL ganhar, e **está explicitamente fora do escopo deste agente** — se for feito, tem de ser dito no documento de resultados, senão o número publicado deixa de descrever o jogo que o público jogou. |

**O que o dado NÃO autoriza a dizer,** em nenhuma das opções: que a RL vence o
humano no cenário aberto. Ela vence o `coordenado_c60` em 7200 s (12/12,
`RESULTADOS_ABERTA.md`) e vence os dois timers em 120 s (§2). Contra o melhor
humano plausível em 120 s ela **empata** — e, com o parâmetro do adversário
escolhido fora da amostra, fica um fio atrás (§3.1).

---

## 10. Onde eu discordo, e o que ficou aberto

### 10.1 Um buraco de contrato, reportado e não consertado

**Não existe checagem de saúde que recuse uma rodada curta travada.** `sane()`
(C5) e `sinais_de_travamento` (`feira/metricas.py`) são os dois portões do
repositório, e nas 4752 rodadas de 120 s deste experimento **nenhum dos dois
disparou uma única vez** — nem para o farol congelado que entrega 32% do que o
timer entrega (§7). Isso não é defeito dos dois: os limiares deles são de outro
regime, e o C5 diz isso na própria docstring. O buraco é que **a camada do jogo
publica número de rodada curta e não tem portão nenhum**.

O detector pareado do §7 (+20 pp de acúmulo excedente) é a proposta, medida e
calibrada, com zero falso positivo em 24 rodadas de referência. Ele mora hoje no
script de análise do A8. **Onde ele deveria morar é `feira/metricas.py`**, ao lado
do `sinais_de_travamento`, com o limiar declarado pelo chamador — mas
`feira/metricas.py` está fora da minha fronteira de escrita, e a regra do projeto
é reportar com motivo técnico, não consertar. Fica reportado.

### 10.2 Onde eu discordo de uma decisão já tomada

**Comparar humano contra `coordenado_c60` numa janela de 120 s mede, em parte,
outra coisa.** O aquecimento roda o timer uniforme nos três braços — e tem de
rodar, senão a rodada não é pareada —, então o plano coordenado entra na janela
fora de fase e gasta ~1 ciclo (60 s, metade da rodada) se prendendo ao relógio
absoluto. O sintoma está medido: em 120 s o `c60` fica **abaixo** do timer
uniforme (109,2 contra 112,5), invertendo o resultado da janela de 7200 s.

Isso **não afeta o jogo** — o projetor mostra `timer:uniforme_27s`, não o `c60`
(`feira/jogo/fantasmas.py::VERDE_TIMER_PADRAO`). Afeta qualquer frase da forma "o
visitante bate o baseline coordenado", que herda o artefato. A recomendação
técnica: **não citar comparação contra o `coordenado_c60` em janela menor que dois
ciclos do plano (120 s)**; a curva por duração do §6 é o dado para decidir onde
esse piso fica.

### 10.3 O que ficou aberto — e o que é fraco neste estudo

1. **`mao=M` não foi calibrado com gente.** Quantos dos 12 botões uma pessoa de
   verdade alcança num tick de 5 s no painel 3x4 é o parâmetro **mais influente do
   estudo inteiro** — sozinho ele leva P(vitória) de 33,8% a 0,0% — e é o único
   que saiu de suposição, não de medida. Medir custa dez minutos com uma pessoa,
   um teclado e o `--auto` do modo jogo, e **deveria ser feito antes de qualquer
   decisão baseada no §3.**
2. **O oráculo lê o que o visitante talvez não leia.** `gulosa_fase` separa a fila
   por aproximação decodificando o vetor de estado. A projeção mostra os parados
   por faixa, então a informação está na tela — mas se uma pessoa consegue
   extraí-la e agir em 5 s não foi medido. O `gulosa_fila` (só fila por
   cruzamento, 18,3%) é o piso dessa faixa e o oráculo é o teto; **o visitante
   real está entre 18% e 49%, e este estudo não estreita mais que isso.**
3. **A varredura de parâmetro do adversário foi feita, e é rasa.** 12
   configurações, 10 seeds fora das held-out, 5 repetições (§3.1). Ela levou o
   teto de 49,2% para 57,1%, mas varreu só `f`, `k`, `margem` e `limiar` das duas
   famílias gulosas — não tocou em estratégias de classe diferente (ciclo
   adaptativo por cruzamento, coordenação manual em onda, alternar entre táticas
   dentro da rodada). **O teto continua podendo estar subestimado**, agora por
   falta de imaginação e não por falta de varredura.
4. **P(vitória) é condicionado a uma estratégia FIXA na rodada inteira.** Um
   visitante de verdade troca de tática, cansa, conversa. O catálogo cobre a faixa
   (de 36 a 125 carros entregues), mas não modela a troca de tática dentro da
   rodada.
5. **Uma só política RL.** Todo o estudo é contra `results/rl/v1_queue_di5.pt`. O
   A6 registrou que o `v3_queue_mr60` é melhor na held-out longa (7029,0 contra
   7025,7) e não foi promovido de propósito; se o dono trocar o ponteiro, **este
   documento inteiro precisa ser re-rodado** — são ~40 min de máquina.
6. **A rede aberta tem teleportes.** As corridas registram 1–2 teleportes por
   rodada em algumas seeds (visíveis no log do SUMO como `Teleports: 2
   (Collisions: 2)`). A conservação fecha em zero em todas as 7650 rodadas, então
   eles estão contabilizados; ainda assim, é ruído físico que ninguém deste
   projeto investigou.

---

## 11. Como reproduzir

```powershell
# 1) a campanha principal: 18 adversários x 12 seeds x 20 repetições, 120 s
#    (~4100 rodadas, ~70 min em 10 processos nesta máquina)
..\smart-traffic\.venv\Scripts\python.exe scripts\adversarios.py `
    --catalogo padrao --seeds 100-111 --reps 20 --duracao 120 --procs 10 `
    --saida results\a8\campanha_d120.json

# 2) as versões PURAS (sem ruído de mão), 1 rodada por seed
..\smart-traffic\.venv\Scripts\python.exe scripts\adversarios.py `
    --catalogo puros --seeds 100-111 --reps 1 --duracao 120 --procs 10 `
    --sem-oponentes --saida results\a8\campanha_puros_d120.json

# 3) a varredura de duração (3 adversários x 12 seeds x 20 reps, por duração)
foreach ($d in 60,180,240) {
  ..\smart-traffic\.venv\Scripts\python.exe scripts\adversarios.py `
      --catalogo duracao --seeds 100-111 --reps 20 --duracao $d --procs 10 `
      --saida results\a8\campanha_d$d.json
}

# 3b) a varredura de parâmetro do adversário, FORA das held-out (§3.1),
#     e as duas vencedoras rodadas nas held-out
$sweep = "gulosa_fase:f=0.6@falha=0.05@extra=0.02;gulosa_fase:f=0.8@falha=0.05@extra=0.02;" +
         "gulosa_fase:f=1@falha=0.05@extra=0.02;gulosa_fase:f=1.3@falha=0.05@extra=0.02;" +
         "gulosa_fase:f=1.6@falha=0.05@extra=0.02;gulosa_fase:f=1,margem=2@falha=0.05@extra=0.02;" +
         "gulosa_fase:f=1,margem=5@falha=0.05@extra=0.02;gulosa_fila:k=6@falha=0.05@extra=0.02;" +
         "gulosa_fila:k=8@falha=0.05@extra=0.02;gulosa_fila:k=12@falha=0.05@extra=0.02;" +
         "gulosa_fila:k=12,limiar=3@falha=0.05@extra=0.02;martelo@falha=0.05@extra=0.02"
..\smart-traffic\.venv\Scripts\python.exe scripts\adversarios.py --adversarios $sweep `
    --seeds 42-47,230-233 --reps 5 --duracao 120 --procs 6 `
    --saida results\a8\ajuste_fora_da_amostra.json

..\smart-traffic\.venv\Scripts\python.exe scripts\adversarios.py `
    --adversarios "gulosa_fase:f=1,margem=2@falha=0.05@extra=0.02;gulosa_fila:k=6@falha=0.05@extra=0.02" `
    --seeds 100-111 --reps 20 --duracao 120 --procs 10 --sem-oponentes `
    --saida results\a8\campanha_ajustados_d120.json

# 4) a análise. A varredura do passo 3b entra SEPARADA, e o motivo é sério: ela
#    roda em seeds 42-47/230-233, e jogá-la no mesmo comando faria o confronto
#    agrupar essas seeds com as 12 held-out para os adversários que aparecem nos
#    dois arquivos — a manchete sairia de 22 seeds misturadas, em silêncio.
#    (Dá para ver quando acontece: a coluna "seeds vencidas" diz x/22, não x/12.)
..\smart-traffic\.venv\Scripts\python.exe scripts\adversarios_analise.py `
    --entradas results\a8\campanha_d60.json results\a8\campanha_d120.json `
               results\a8\campanha_d180.json results\a8\campanha_d240.json `
               results\a8\campanha_puros_d120.json results\a8\campanha_ajustados_d120.json `
    --saida results\a8\analise.json --md results\a8\tabelas.md `
    --foco "gulosa_fase:f=1,margem=2@falha=0.05@extra=0.02"

..\smart-traffic\.venv\Scripts\python.exe scripts\adversarios_analise.py `
    --entradas results\a8\ajuste_fora_da_amostra.json `
    --saida results\a8\analise_ajuste.json --md results\a8\tabelas_ajuste.md

# 5) a suíte
..\smart-traffic\.venv\Scripts\python.exe -m pytest -q
..\smart-traffic\.venv\Scripts\python.exe -m ruff check .
```

### Duas armadilhas de operação, medidas nesta trilha

1. **O TraCI cai sozinho, e mais do que o `JOGO.md` §7 registrou.** Com 10-14
   processos em paralelo, `struct.error: unpack requires a buffer of 3 bytes` no
   meio de uma corrida derrubou **duas campanhas inteiras** antes de o laço ganhar
   retentativa. A taxa não é estável: 0 rodadas refeitas em 4128 na campanha
   principal, **55 em 756** na de 240 s e **227 em 480** na dos adversários
   ajustados — mesma máquina, mesmo código, mesma noite. Hoje `scripts/adversarios.py` trata a falha como dado
   (`tarefa_segura`), limpa a sessão do processo (`bancada._reseta_processo`) e
   refaz a rodada num processo novo; e grava um diário `.jsonl` a cada rodada, de
   forma que `--retomar` custa minutos em vez de horas.
2. **`ProcessPoolExecutor(max_tasks_per_child=...)` TRAVA.** Com `25`, o pool
   parou de repor worker depois da primeira leva de reciclagem, ficou com 5 dos 10
   processos e nunca mais entregou resultado — sem erro, sem SUMO vivo, CPU
   ocioso, 226 de 4128 rodadas feitas. O default do script é `--por-filho 0`
   (desligado). Quem reativar isso vai perder uma noite.

### Artefatos

| arquivo | o que é |
|---|---|
| `results/a8/campanha_d120.json` | as 4128 rodadas da campanha principal, uma linha por rodada, com saúde junto |
| `results/a8/campanha_puros_d120.json` | as 144 rodadas dos adversários sem ruído |
| `results/a8/campanha_d{60,180,240}.json` | a varredura de duração (756 rodadas cada) |
| `results/a8/ajuste_fora_da_amostra.json` | as 630 rodadas da varredura de parâmetro, em seeds FORA das held-out |
| `results/a8/campanha_ajustados_d120.json` | as 480 rodadas das duas configurações vencedoras, nas held-out |
| `results/a8/analise.json` | P(vitória), intervalos, saúde e ruído por adversário — **só seeds held-out** |
| `results/a8/analise_ajuste.json` · `tabelas_ajuste.md` | a mesma análise para a varredura de parâmetro, em separado (seeds 42-47/230-233) |
| `results/a8/tabelas.md` | as tabelas completas (31 classes de adversário x 3 oponentes, nas 4 durações) |
| `results/a8/campanha_*.jsonl` | o diário incremental que `--retomar` lê. **Transitório e não versionado** — foi apagado depois da campanha, porque duplica linha a linha o `.json` ao lado, e duas fontes de verdade para o mesmo dado é como se mede a coisa errada sem perceber. Uma corrida nova o recria. |

### Código e testes

| onde | o quê |
|---|---|
| `feira/adversarios/politicas.py` | as políticas, o ruído de mão, o parser de spec |
| `feira/adversarios/fonte.py` | `FonteRoteirizada` (C6) + `AdversarioHumano` (C3) — o caminho fiel |
| `feira/adversarios/bancada.py` | mapa fase→aproximação, uma rodada, os oponentes, o worker |
| `scripts/adversarios.py` | a campanha (retentativa, diário, `--retomar`) |
| `scripts/adversarios_analise.py` | bootstrap agrupado, tabelas, detector de acúmulo |
| `tests/test_a8_politicas.py` | 23 testes das políticas, sem SUMO |
| `tests/test_a8_fonte.py` | 13 testes do caminho fiel (intenção gasta, lag, gravação) |
| `tests/test_a8_bancada.py` | 6 testes de integração com SUMO (mapa, reprodutibilidade, atalho C3, cegueira do detector) |
