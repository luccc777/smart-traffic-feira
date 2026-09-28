# Gamificação — regras do jogo, ranking, comparação com a IA e o que protege a simulação

Plano de construção. Escrito em 2026-09-14, feira ≈ 2026-09-28 (duas semanas).
Trilha **A9 — Gamificação**, Onda 3½: entra depois do A8 e antes do ensaio com gente.

Este documento **não** reabre o que já está medido: a rodada de 120 s, os 12 botões, a
grade `di5/vm7/am3/mr0`, a manchete em carros entregues e os fantasmas pré-computados são
decisões fechadas em `PLANO.md`, `JOGO.md` e `DIFICULDADE.md`. O que ele faz é desenhar a
**camada de jogo** por cima disso — o livro de regras, a pontuação, o ranking com nome, a
moldura da comparação com a IA e os portões que impedem uma rodada quebrada de virar
placar — e dizer onde cada peça mora, o que ela custa e o que ainda é decisão do dono.

---

## 0. TL;DR

| pergunta | resposta curta |
|---|---|
| o visitante já controla os semáforos? | **Sim.** `ControladorHumano` + teclado/botoeira, jogável hoje (`JOGO.md`). Nada a construir aqui, só a regra escrita. |
| existe leaderboard? | **Metade.** `feira/jogo/ranking.py` + `GET /api/ranking` + `MELHORES DA FEIRA` na tarja, **não commitados** (§1.2). Sem nome, ordenado por número cru (injusto entre seeds), sem portão de saúde. |
| a comparação com a IA existe? | **Sim**, três barras no mesmo `t`, veredito em quatro desfechos. O que falta é a **moldura honesta** que o A8 pede: a RL empata com o melhor humano, e a tela ainda promete "vença a rede". |
| o visitante consegue quebrar a simulação? | **Não a simulação; só o número dele.** Cada rodada é um SUMO novo, replay de `t=0`; o espaço de ação é o da RL. O que ele consegue é **travar a malha por omissão** (36 carros contra 112), e hoje **nenhum portão recusa esse número** — o detector existe em `feira/metricas.py` desde `d25dd3b` e **não está ligado ao motor**. |
| o que este plano constrói | (1) pontuação **pareada** contra o timer + medalhas; (2) o teclado junto do projetor lido pela página (`FonteWeb`), nome digitado pelo visitante na tela do chão, ranking com nome e moderação; (3) portão de saúde na rodada + 5º desfecho "TRAVOU"; (4) START à prova de visitante; (5) moldura da IA + dificuldade da seed; (6) ensaio com gente para o parâmetro que o A8 não mediu. |
| contratos | **Zero campo obrigatório novo.** Dois campos **aditivos** no `Placar` (C7) — `rodada` e `sinais` — que o dono adiciona no passo 0 (§6.2). Tudo o resto mora fora dos contratos. |
| decisões | **Tomadas** (§8), com o critério "público, plateia se divertindo, manipulação fácil" e os recursos reais (notebook + projetor no chão + teclado): o visitante digita o nome e joga **no teclado junto do projetor**, lido pela página (`FonteWeb`); Δ vs timer; START do visitante ignorado na rodada; 12 seeds; nível na tela; 12 s de resultado; um jogador por rodada; rodada grátis automática; o operador não toca em nada. |

---

## 1. Onde estamos

### 1.1 O que já roda (e não muda)

| peça | onde | estado |
|---|---|---|
| botão → intenção → tick da grade → `TROCAR` mascarado por `pode_trocar` | `feira/controladores/humano.py` | medido igual ao bit da RL (`test_a3_integracao`) |
| máquina de estados `ocioso → preparando → contagem → jogando → resultado` | `feira/jogo/motor.py` | 663 testes verdes em `d25dd3b` |
| fantasmas timer27 + RL `v1_queue_di5`, cache em disco, prefetch da próxima seed | `feira/jogo/fantasmas.py` | ~0 s com cache |
| selo de `t0` — rodada não pareada não coroa | `feira/jogo/estado.py` | `pareado=false` no fio |
| projeção: mapa ao vivo do braço humano, tarja, delta, veredito, modo degradado | `web/`, `feira/jogo/web.py` | `PROJECAO.md` |
| P(humano vence a RL): 18% (martelo) a 57% (oráculo); seed vale 0%–100% | `DIFICULDADE.md` | 7650 rodadas |
| detector de travamento para janela curta: acúmulo excedente > +20 pp vs timer27 | `feira/metricas.py::sinais_de_travamento(referencia=...)` | calibrado, **não chamado pelo jogo** |

### 1.2 O que está em disco e não em git (o começo do ranking)

`git status` mostra `feira/jogo/ranking.py`, `tests/test_a7_ranking.py` (10 testes) e as
alterações em `web.py`, `placar.js`, `index.html`, `projecao.css`, `PROJECAO.md §3.7`.
É a v1 do quadro de recordes: `Marca(entregues, seed, venceu, rl, timer, quando)`,
top 5 por `entregues`, dedup por `(seed, entregues, rl, timer)`, arquivo
`results/feira/ranking.json` com escrita atômica, `GET /api/ranking?n=`.

**O que essa v1 acerta e este plano preserva:** alimentar-se da mesma mensagem `placar`
que a tela recebe (nada novo no motor), recusar rodada não pareada e rodada sem humano,
nunca levantar, sobreviver ao processo, gravar `venceu` como a única coluna justa entre
seeds.

**O que ela ainda não tem, e é o trabalho:** identidade do jogador, ordenação justa,
portão de saúde, moderação, uma tela que dê ao visitante a posição dele, e um `id` de
rodada (a dedup por tupla de números colide legitimamente quando duas pessoas entregam
o mesmo tanto na mesma seed).

**Primeiro passo, antes de qualquer coisa deste plano: commitar a v1.** Ela está testada
e é a base; construir por cima de arquivo não versionado é como se perde trabalho.

---

## 2. As regras do jogo

O texto abaixo é o **livro de regras** — o que o operador diz, o que a tela mostra e o
que o código faz têm que ser a mesma coisa. Cada regra traz a origem (medida ou decisão).

### 2.1 A rodada

| regra | valor | origem |
|---|---|---|
| duração | **2 minutos** (120 s simulados, 1:1) | `PLANO.md` §7, confirmado pelo A8 §6.4 |
| cruzamentos | **12**, todos seus | `PLANO.md` Frente 3 |
| o botão | **pede** a troca; ela acontece no próximo tick (até 5 s), se o verde mínimo (7 s) já passou | `JOGO.md` §1.1 |
| LED / tela | amarelo = pedido registrado · verde = trocou · vermelho = **descartado** (cedo demais); placa translúcida = não dá para apertar agora | C6 + §2.8 |
| começo | 3-2-1; botão apertado durante a contagem **não vale** | `motor._contagem` |
| adversários | TIMER FIXO (27 s) e REDE NEURAL, **pré-computados na mesma hora de trânsito** | C8 |
| ponto de partida | os três partem do **mesmo estado**, provado por selo | `estado.py` |
| a hora de trânsito (seed) | sorteada em **rodízio** das 12 held-out (100–111), anunciada na tela antes de começar | §2.6 |
| quem joga | **uma pessoa** por rodada, os 12 botões | §8, decisão 11 |

Frase do operador (uma só, testada no ensaio): *"Cada botão é um cruzamento. Apertar
pede para trocar o sinal — a troca vem no próximo ciclo, e se o verde acabou de abrir
ela é negada e o botão pisca. Você tem 2 minutos para entregar mais carros que o
semáforo fixo e que a nossa rede neural."*

### 2.2 O que conta

**Manchete: carros entregues na janela.** Nunca tempo de viagem: quem congela os
semáforos tem o **melhor** tempo médio de viagem do catálogo inteiro entregando 40% dos
carros (`DIFICULDADE.md` §8). Já é a regra do C7; aqui ela vira também a regra do ranking.

O que aparece no resultado além disso — tempo de viagem e carros parados — é **análise**,
não pontuação, e a tela já os trata assim (`PROJECAO.md` §3.5).

### 2.3 Os desfechos

Hoje são quatro (`PROXIMOS_PASSOS.md` §5). Este plano acrescenta o quinto:

| # | desfecho | quando | tela | entra no ranking? |
|---|---|---|---|---|
| 1 | **venceu** | humano estritamente acima dos dois | coroa, medalha | sim |
| 2 | **empate** | topo compartilhado | "EMPATE" | sim |
| 3 | **perdeu** | alguém acima do humano | colocação (2º/3º) | sim |
| 4 | **não pareada** | selos de `t0` divergem | denúncia, sem colocação | **não** |
| 5 | **não concluída** | abortada, SUMO caiu | "RODADA NÃO CONCLUÍDA" | **não** |
| **6** | **TRAVOU** *(novo)* | portão de saúde disparou (§5.3) | "O TRÂNSITO TRAVOU" + o número, sem colocação | **não** |

"Perdeu" não é um estado do fio (é `vencedor != humano`), está na tabela porque o
visitante precisa ouvir a palavra. O 6 é o único novo, e é o que fecha o buraco que o A8
reportou: hoje uma rodada em que o visitante deixou a malha encher **coroa** o timer e
ainda entra no quadro como uma rodada válida de 36 carros.

### 2.4 O que é proibido — para nós

Estas são regras sobre **o que o jogo não faz**, e são as que a banca vai perguntar:

1. **Nenhuma restrição ao visitante além das da RL.** Sem limite de botões por tick, sem
   grade mais grossa, sem cruzamento morto. É a opção F do A8, explicitamente fora: se um
   dia entrar, tem de ir para `RESULTADOS_ABERTA.md` com o número que ela move
   (`mão=6` sozinha leva P(vitória) de 34% a **0%**).
2. **Nenhuma escolha silenciosa de seed.** Rodízio das 12 held-out. Se o operador fixar
   uma seed (ensaio, demonstração), a tela rotula `seed fixa`. É a opção D do A8, e o
   custo de usá-la sem dizer é o estudo inteiro.
3. **Martelar é permitido.** É estratégia, está medida (vence o timer, perde da RL em
   5 de 6 rodadas), e proibir seria calibrar para a RL ganhar.
4. **A RL não roda ao vivo e a tela diz isso** (selo "pré-computado", 25′). Não muda.
5. **O ranking só aceita rodada que o placar aceitaria.** Os filtros são os mesmos, mais
   o portão de saúde.

### 2.5 Abortar — e o START acidental

Hoje **qualquer START durante a rodada aborta** (`motor._bomba`). Na botoeira, o START é
o botão grande, iluminado, no meio de 12 outros botões que o visitante está martelando.
Uma rodada abortada não conta, não entra no ranking, e o visitante — que não sabia que
aquele botão existia — perde os 2 minutos.

**Regra (decidida, §8):** durante `contagem` e `jogando`, o START **do visitante é ignorado**
(o LED dele fica `deny`, piscando, para dizer "agora não"). Abortar é ato do
**operador**: `Esc` **três vezes em 1,5 s** no teclado (o mesmo teclado do visitante — e
Esc é a tecla do reflexo: sair da tela cheia, "cancelar". Um Esc sozinho não faz nada;
na rodada do dono em 2026-09-14 o risco ficou claro) ou o botão na página do operador (§3.6).
`Ctrl-C` continua encerrando o processo. O `ReplayInput` e o `FonteRoteirizada` do A8
não emitem START no meio da rodada, então nada da campanha muda.

Alternativa que não recomendo: exigir dois STARTs em 1,5 s. Resolve o acidente, mas o
martelo acerta o START duas vezes com facilidade, e a regra "aperte duas vezes" precisa
ser ensinada a quem está com pressa.

### 2.6 A seed é dificuldade — e a tela diz qual

`DIFICULDADE.md` §5 mede, para o melhor humano plausível, P(vitória) de **0%** (seeds
101, 104, 109) a **100%** (107, 108, 111). Isso não é defeito: é a hora de trânsito
sorteada, e o pareamento garante que os três braços enfrentam a mesma. Mas um ranking
por número cru compara quem jogou a seed 104 (RL entrega 146) com quem jogou a 107 (RL
entrega 101), e a pessoa não tem como saber que a diferença era o sorteio.

Duas consequências:

1. **A pontuação é pareada** (§3.1) — a seed cancela na subtração.
2. **A tela anuncia o nível** no `ocioso`, antes do START, com a linguagem de jogo:
   `HORA DE TRÂNSITO 107 · NÍVEL: DIFÍCIL` (ou FÁCIL/MÉDIO). O nível sai de uma tabela
   fixa derivada do A8 §5 (P(vitória) da gulosa com ruído: ≤20% difícil, 20–70% médio,
   ≥80% fácil — difícil **para o humano**, isto é, seeds em que a RL é forte) e é
   **atualizado ao vivo** com o que a feira produzir: "ninguém bateu a IA aqui ainda
   (0 de 4)". Os dois números aparecem juntos; o do A8 rotulado como "previsto".

Quem quiser argumentar que isso "avisa demais": a barra da RL já mostra em tempo real
quanto ela entrega naquela seed. O nível não acrescenta informação — acrescenta
**contexto** antes da rodada, que é quando ele serve.

---

### 2.7 Ritmo: o relógio da plateia, não o da simulação

Jogado pelo dono em 2026-09-14: "pouco dinâmico, os faróis demoram para transicionar".
Três causas somadas, e só uma mexível sem mudar o experimento:

| causa | número | mexível? |
|---|---|---|
| similitude: o carro anda a 1,85 m/s na tela e leva 15 s por quarteirão | `x'=x/6`, `t'=t` | não — decisão de modelagem da Onda 1 |
| a grade da RL: botão vale no próximo tick (≤ 5 s) + amarelo 3 s; se acabou de trocar, + verde mínimo 7 s | 3 a 10 s do aperto ao efeito | não — é o espaço de ação da rede; grade mais fina exige retreinar a RL e refazer o A8 |
| ritmo 1:1 | 120 s simulados em 120 s de parede | **sim — é só apresentação** |

**Decidido: `--ritmo` (s simulados por s de parede), preset da feira em 2×** (o dono
jogou em 1,5× e ainda achou longo). A simulação, os fantasmas, o selo de `t0` e todo
número do A8 são indexados em tempo simulado e não mudam; o que muda é o relógio da
plateia (a rodada dura 60 s) e a vazão de público (~50/h). O `Marcapasso`/`Ritmo` da Arena recebem o valor, o status
do servidor o publica (`ritmo`) e o interpolador do front acompanha (`speed`); o
"faltam N s" da tarja passa a ser de **parede**, que é o que a pessoa sente.

**O custo, dito:** o visitante tem `ritmo` vezes menos tempo de parede por tick para
reagir — a mão fica mais difícil, e o A8 não mediu isso (ele roda em tempo simulado).
P(vitória) real deve cair em 2× (o tick passa a 2,5 s de parede). É o parâmetro nº 1
do ensaio com gente (§9): comparar 1×, 1,5× e 2× com as mesmas pessoas e escolher
pelo dado.

### 2.8 A linguagem das placas — e o visitante que martela a mesma tecla

Pedido do dono depois de jogar (2026-09-14): "vendo de fora não sei o porquê daquelas
cores". A primeira versão usava os três estados do LED da botoeira (`armed` azul
pulsando, `on` verde, `deny` vermelho piscando) — a linguagem certa para um painel
físico e a errada para uma plateia que nunca viu o painel. A placa de cada cruzamento
passa a falar a língua do próprio farol, com **cinco estados** e as cores que o mapa
já usa:

| estado | quem decide | placa | o que a pessoa lê |
|---|---|---|---|
| **livre** | página | escura, letra branca | "pode apertar" |
| **bloqueado** | página (estimado dos frames: farol no amarelo, ou verde há menos de 7 s) | **translúcida** (38%), **anel esvaziando** + segundos que faltam | "não dá para apertar agora; espere N s" |
| **pedido** (`armed`) | servidor, na hora do aperto | **amarela**, **anel de carregamento** enchendo até o próximo tick | "registrado; vale no próximo ciclo" |
| **trocou** (`on`) | servidor, no tick | **verde** por 1,2 s | "trocou" |
| **negado** (`deny`) | servidor, no tick | **vermelha** com "DESCARTADO": o anel do pedido desenrola até zero, a placa treme, um X cruza a letra; 1,2 s depois cai para bloqueado | "aquele aperto morreu; espere o anel e aperte de novo" |

Duas escolhas de honestidade: o `bloqueado` é **estimativa da página** (ela só vê o
estado do farol nos frames; quem aceita ou nega é o tick), então o aperto é sempre
enviado e o servidor decide; e `on`/`deny` do servidor persistem 5 s simulados, mas a
**duração visual é da página** (1,2 s) — uma placa verde por 5 s parece travada.

**A demora, dissecada** (segunda rodada do dono: "aperto, a bola amarela gira, demora
mais um pouco, aí sim começa o amarelo"). Do aperto ao verde do outro lado, em s
simulados: até 5 s até o tick (média 2,5) + 3 s de amarelo do farol; e a tela ainda
mostrava o resultado do tick **antes** do mapa, porque a mensagem `leds` chega na hora
e o mapa anda `DELAY` = 1,15 s simulados atrás do frame mais novo (o render-delay do
`interp.js`, que existe para sempre haver um par de frames para interpolar). Três
consertos, nenhum deles na simulação:

1. **O tick é anunciado, não adivinhado.** `ControladorHumano.decide()` chama
   `fonte.ao_tick(t)`; a `FonteWeb` publica o quadro de LEDs com `tick: true` e o `t`.
   A página passa a saber o período exato desde o primeiro tick da rodada — o anel
   do pedido enche até o instante em que a intenção é julgada, sem spinner.
2. **A placa espera o mapa.** O `PainelLeds` aplica o resultado do tick com atraso
   `DELAY / ritmo` (0,58 s de parede a 2×): a placa fica verde no mesmo quadro em que
   o farol amarela. O aperto da pessoa (`armed`) continua aparecendo na hora — é a mão
   dela, não o mundo —, e um aperto feito depois do tick não é engolido pelo tick
   atrasado.
3. **As pílulas dizem o que está acontecendo.** Pedido: `CICLO 2s` (até o tick), ou
   `CEDO · 2s` quando o farol ainda vai estar travado nesse instante (previsão, o tick
   decide). Bloqueado no amarelo: `AMARELO 2s` — é a transição que a pessoa pediu
   acontecendo, com nome. Depois: `5s` de verde mínimo.

O que **não** mudou: a grade (tick de 5 s, verde mínimo 7 s, amarelo 3 s) é a da RL e
é o que torna a comparação justa — encurtar só para o humano quebraria o pareamento.
A 2× a espera do aperto ao efeito fica em 1,5 a 4 s de parede, e agora com o motivo
escrito na placa.

**O visitante que aperta a mesma tecla dez vezes.** No motor isso já era inócuo:
`armed` é booleano e a intenção vale uma vez por tick. O que faltava era a tela
dizer que não adianta — agora a placa pulsa a borda a cada aperto repetido (a tecla
foi vista) e o anel/segundos mostram por que esperar. Na página, `keydown` repetido de
tecla segurada é ignorado e cada tecla tem debounce de 120 ms (START, 500 ms), com as
descartadas contadas no diagnóstico. Uma legenda de uma linha no `ocioso` fecha o
vocabulário: *amarelo = pedido registrado · verde = trocou · vermelho = cedo demais,
espere o anel*.

## 3. Pontuação, medalhas e o ranking

### 3.1 A pontuação: Δ contra o timer, pareado

    score = entregues(você) − entregues(timer27, mesma seed, mesma janela)

**Por que não o número cru.** O desvio-padrão do absoluto numa rodada de 120 s é
**10–12 carros** (seed); o da **diferença** contra o timer é **2,8–4,0** (`JOGO.md` §6.2,
replicado pelo A8 §6.1). Ordenar por absoluto é ordenar por sorte com três quartos do
peso; ordenar pela diferença é ordenar por habilidade com o ruído de jogada (3,3) como
piso. A régua da tela **já é** o timer — o placar mostra `▲ 6,0% · +7 carros` contra ele
—, então o ranking passa a ordenar pelo mesmo número que o visitante viu grande na tarja.

**Por que o timer e não a RL como referência.** A RL é o **adversário**; o timer é a
**régua**. Contra a RL o visitante mediano perde (P(vitória) 18–57%), e um ranking em que
quase todos os scores são negativos lê como derrota coletiva. Contra o timer o martelo
vence 91% e o oráculo 96%: quase todo mundo pontua positivo, e a RL continua ali, como o
adversário que poucos batem — que é exatamente a moldura honesta do §4. O Δ contra a RL
**é gravado** e aparece na linha (`IA fez 120`), só não ordena.

Desempate: `entregues` maior primeiro, depois a marca mais antiga (quem fez primeiro
fica na frente).

### 3.2 Medalhas

A medalha é uma **leitura** da marca, não um estado do contrato. `vencedor`, `pareado` e
`motivo` continuam significando o que o C7 diz; a medalha é calculada no ranking a
partir das três linhas:

| medalha | condição | quantos devem ganhar (A8) |
|---|---|---|
| 🥇 **ouro** | `entregues(você) > entregues(rl)` | martelo 18%, mapa de calor 26%, oráculo 57% |
| 🥈 **prata** | não ouro, e `entregues(você) ≥ entregues(rl) − 3` | "lado a lado com a IA": dentro do ruído de jogada (3,3 carros) |
| 🥉 **bronze** | não prata, e `entregues(você) > entregues(timer)` | martelo 91%, oráculo 96% |
| — | o resto | `parado`, `arterial`, aleatória rala |

O **3** da prata é o ruído de jogada medido (§6.1 do A8, dp da diferença 3,26–3,69) e
mora numa constante com esse comentário. Prata não é "empate" — empate continua sendo
igualdade estrita no placar. Prata diz "a diferença entre você e a rede é menor que a
diferença entre duas jogadas suas", que é verdade e é a frase que a banca precisa ouvir.

Rodada **degradada sem RL** (fantasma da RL não carregou): não há ouro nem prata
possíveis; a marca entra com bronze/nada e a linha diz `sem IA nesta rodada`. Rodada
sem **timer**: não há score; a marca **não entra** (sem régua não há pontuação — e uma
rodada sem os dois fantasmas já é "operador, olhe o log" pelo `JOGO.md` §5).

### 3.3 Identidade: nome, e por onde ele entra

Um ranking sem nome é uma lista de números; a gamificação vive de "eu estou em 3º".

**Os recursos, sem invenção:** um notebook, um projetor no chão e um teclado. Não há
celular, não há segunda tela para o público, não há rede da feira garantida. A botoeira
(A4) tem 13 botões e nenhuma letra. O operador está lá para **orientar**, não para
operar.

**Decidido: arcade puro — o visitante digita o próprio apelido no teclado, olhando
para o chão.** O teclado fica **junto do projetor** (sem fio, ou USB longo), é o
mesmo teclado que joga, e a tela projetada é a única interface. O fluxo, do ponto de
vista de quem chega:

    OCIOSO     "QUAL O SEU APELIDO?  ANA_"          letras/dígitos, até 12, Backspace apaga
               ENTER confirma  ->  "ANA · HORA DE TRÂNSITO 107 · DIFÍCIL
                                    APERTE ESPAÇO PARA COMEÇAR"
               (o bloco 3x4 com as letras Q W E R / A S D F / Z X C V desenhado no chão,
                na posição dos cruzamentos: é o mapa de teclas E o manual)
    ESPAÇO     3-2-1 -> JOGANDO (as letras agora são botões; o nome está fechado)
    RESULTADO  12 s -> OCIOSO, campo de nome vazio de novo

ESPAÇO sem nome confirmado começa como `Visitante N` — ninguém é obrigado a digitar.
Durante o nome, ESPAÇO **não** começa (é a única tecla que muda de sentido, e ela só
muda quando o campo está aberto). Nome é apelido: sem espaço, sem sobrenome — a tela
diz isso em uma linha embaixo do campo.

**O que isso muda na arquitetura, e é a mudança mais importante deste plano:** hoje
quem lê o teclado é `TecladoInput` por `msvcrt`, **no terminal**. Para o visitante
digitar olhando para o chão, o foco tem que estar na **página projetada**, e então quem
recebe as teclas é o navegador. A saída é uma `FonteEntrada` (C6) nova, **`FonteWeb`**:
a página captura `keydown` (com `preventDefault` no espaço, senão a página rola), manda
`{"tipo": "tecla", "k": "q"}` por um WebSocket `/entrada`, o servidor (mesmo processo
do motor) enfileira em uma fila thread-safe, e `poll()` a drena a ~48 Hz como hoje. O
`feedback()` vai no sentido contrário pelo mesmo canal, e a página **desenha os 12
LEDs no chão** (a linguagem das placas do §2.8) — o que a botoeira faria no painel, a
plateia inteira vê no mapa. O modo texto (nome) é só da página: no `ocioso` as teclas
viram letras; o servidor recebe o nome pronto em `POST /api/jogador`.

Latência: `keydown` → WS local → fila → `poll()` é de poucos milissegundos, muito
abaixo dos 50 ms do C6; **é medido** (DoD (k)), não suposto. `TecladoInput` continua
existindo como reserva (`FonteComReserva(FonteWeb, TecladoInput)`): se o WebSocket
cair, o teclado do terminal assume — desde que o terminal esteja com foco, o que é a
fraqueza dessa reserva e está dita no §5.4. A botoeira, quando existir, entra na mesma
composição; o nome continua vindo do teclado.

O nome é assunto de **tela**, não de rodada: fica em `EstadoProjecao.jogador`, é
carimbado na marca quando o `placar` de `resultado` chega, e é **limpo** em seguida — a
próxima rodada sem nome novo vira `Visitante N`, não herda o anterior. O motor e o C7
não sabem que existe nome.

**A tela do notebook** fica com o terminal (log) e, opcionalmente, `/operador` aberto
no navegador com o mouse: abortar, marcar rodada de teste, remover uma marca. Nada
disso é necessário para uma rodada acontecer — é para quando algo dá errado.

### 3.3b Validade: o quadro é dos últimos 30 minutos

**Decisão do dono (2026-09-14):** uma marca conta no quadro por **30 min**
(`--ranking-validade 30`, no preset `--feira`). Sem isso, quem jogou bem às 9h é o
campeão o evento inteiro e quem chega às 15h não tem o que bater — o quadro deixa
de ser disputa e vira monumento. O que expira é a **colocação**: o arquivo do dia
guarda tudo (auditoria), os totais (`27 rodadas · 11 venceram a IA`) e o nível da
seed continuam contando o dia inteiro. O título da tarja diz qual dos dois está na
tela: `MELHORES · ÚLTIMOS 30 MIN`. Sem rodada nova o servidor não difunde nada, então
a página rebusca o quadro a cada minuto no `ocioso` para a expiração aparecer.

### 3.4 Uma linha por pessoa no topo

Arcade puro deixa a mesma pessoa ocupar o top 5 inteiro. Regra: o **arquivo** guarda
todas as rodadas (auditoria, §3.5); o **topo exibido** mostra a **melhor rodada de cada
apelido**. Apelidos iguais de pessoas diferentes se fundem — é o preço de não pedir
documento numa feira, e o operador pode renomear (`Ana` → `Ana 2`) pela página.

### 3.5 O arquivo (`ranking.json` v2) e a migração

```json
{"versao": 2, "dia": "2026-09-28",
 "marcas": [{"id": "r017-1727530911", "nome": "Ana", "seed": 107,
             "entregues": 104, "timer": 89, "rl": 101,
             "score": 15, "delta_rl": 3, "medalha": "ouro",
             "sinais": [], "degradada": false, "teste": false,
             "quando": 1727530911.4}]}
```

- `id` = `rodada` do placar (§6.2) + epoch; é a dedup. Enquanto o campo `rodada` não
  existir no fio, a dedup continua pela tupla de números **e** uma janela de 30 s
  (o `ultimo_placar` é reenviado a cada cliente que conecta, e é isso que a dedup
  protege — não duas rodadas iguais em horas diferentes).
- `teste=true` marca rodada do operador/ensaio: fica no arquivo, sai do topo.
- Arquivo v1 (o de hoje) carrega sem erro: `score` é derivado de `entregues − timer`,
  `nome` vira `Visitante N`, `medalha` é recalculada. Arquivo corrompido continua
  começando vazio, como já faz.
- **Um arquivo por dia** (`results/feira/ranking_<dia>.json`): a feira pode ter dois
  dias, e "melhores de hoje" e "melhores da feira" são duas telas; a segunda é a união.
- Limite de 500 marcas fica; a poda descarta as piores por **score**, não por
  `entregues`.

### 3.6 As telas

| tela | onde | o que mostra |
|---|---|---|
| tarja `MELHORES DA FEIRA` (já existe) | direita da tarja, `ocioso` e `resultado` | top 5 por score: `1º ANA +15 🥇`, `2º LUCAS +12 🥉` — o nome substitui a hora que saiu; o número cru some da linha (está no `/ranking`) |
| **posição do visitante** *(novo)* | `resultado`, ao lado do veredito | `VOCÊ FICOU EM 7º DE 31` + medalha em corpo de veredito (46 px). Se entrou no top 5, a linha dele **pisca uma vez** na tarja. Se é o 1º: `NOVO RECORDE DA FEIRA` |
| `nível` da seed *(novo)* | `ocioso`, junto do convite | `HORA DE TRÂNSITO 107 · DIFÍCIL · 0 de 4 bateram a IA aqui` |
| **campo de nome** *(novo)* | `ocioso`, no lugar do convite, em corpo de convite (52 px) | `QUAL O SEU APELIDO?  ANA_` · `ENTER confirma` · depois `APERTE ESPAÇO`; o bloco 3×4 de teclas desenhado sobre os cruzamentos |
| **as 12 placas** *(novo)* | sobre cada cruzamento, em todas as fases com mapa | letra da tecla + os cinco estados do §2.8 (livre · bloqueado com anel · pedido amarelo · trocou verde · negado vermelho) |
| **`/ranking`** *(fase 3)* | o próprio projetor, tecla `R` no `ocioso` | top 20 do dia + da feira, com número cru, seed, medalha, hora |
| **`/operador`** *(novo)* | tela do notebook, mouse | ABORTAR, PULAR RESULTADO, marcar TESTE, renomear/remover marca; estado do jogo (fase, seed, fantasmas prontos, hz da fonte, atraso máx). Não é necessário para a rodada |

`resultado_s` é **10 s** no preset (o dono pediu 10; era 12): posição e medalha cabem,
e depois disso a tela **volta sozinha** para o `ocioso` com o quadro. Isso exigiu um
conserto: o motor voltava a `ocioso` **em silêncio**, e a projeção só saía do
RESULTADO quando o vigia do servidor declarava queda (20 s de rédea) — ou nunca, com o
feed ocioso mantendo o `visto_em` fresco. Com `anuncia_ocioso` (preset), o fim da tela
de resultado publica um placar de `ocioso` sem linhas, já com a seed da próxima
rodada, e a tela volta na hora. O operador encurta pela página quando a fila está
grande. Um som curto, só no `NOVO RECORDE`, desligável por `?som=0`.

### 3.7 Moderação

Tela pública com nome livre precisa de um botão de apagar. `DELETE /api/ranking/{id}`
e `PATCH /api/ranking/{id}` (`nome`, `teste`) só pela página do operador, que fica em
`127.0.0.1` ou atrás de um token simples na URL (`--operador-token`). Remoção é
**soft** (`removida=true` no arquivo): auditoria não perde linha.

---

## 4. A comparação com a IA — a moldura honesta

### 4.1 O que o dado autoriza a dizer

`DIFICULDADE.md` §9 fecha: a RL vence o `coordenado_c60` em 7200 s (12/12), vence os
dois timers em 120 s (+10,3% sobre o timer27), e **empata com o melhor humano plausível
em 120 s** (57,1% de vitórias para o oráculo ajustado, p ≥ 0,45 nas três métricas). O
que ela não autoriza: "a RL é imbatível".

A tela de hoje pede "bata a REDE NEURAL" implicitamente — a coroa vai para quem tem mais
carros. Não muda; o que muda é a **moldura** ao redor, que é a opção E do A8 escrita na
tela:

| onde | hoje | proposto |
|---|---|---|
| convite (`ocioso`) | "APERTE O BOTÃO" | "APERTE O BOTÃO · **vença o timer, encare a rede**" |
| veredito | "A REDE NEURAL VENCEU" | "A REDE NEURAL VENCEU · **você ficou a 4 carros**" (o Δ_rl em corpo de veredito, quando |Δ| ≤ 10) |
| resumo do dia | "27 rodadas · 11 venceram a IA" | fica — e ganha "· 25 venceram o timer" |
| medalha | — | ouro/prata/bronze (§3.2): prata é a frase "lado a lado com a rede" |

**Por que isso é gamificação e não maquiagem:** ela dá ao visitante três metas em
escada (timer → lado a lado → bater a rede) em vez de uma meta binária que ele perde em
metade das vezes. E cada degrau é um número medido, não um ajuste de dificuldade.

### 4.2 "Como a IA jogou" — fase 3, condicional

Depois da rodada, uma linha: `você pediu 41 trocas, 33 aceitas · a rede trocou 28`.
Dá ao visitante a única comparação de **comportamento** que a tela pode mostrar, e
desmonta o mito "a IA aperta mais rápido" (não aperta; a grade é a mesma).

O lado do humano já existe (`ControladorHumano.n_aceitos/n_negados`). O lado da RL
exige que o fantasma **grave o número de trocas** ao ser calculado
(`fantasmas.py::Fantasmaria`, no processo que roda o `ControladorRL` selado —
`ControladorSelado` já conta `verde_nas_trocas`). O `Fantasma` (C8) é contrato
congelado; o número vai num arquivo **ao lado** (`.selo.json` já é um precedente) e não
no `.json` do C8. Entra se as fases 1 e 2 fecharem no prazo.

### 4.3 O que a tela NÃO vai fazer

- Não vai mostrar a RL "pensando" nem animar as decisões dela: o fantasma é uma série
  por segundo de `entregues/fila/tempo_medio`, e inventar um mapa da RL seria mostrar
  algo que não foi medido.
- Não vai esconder a barra da RL no `jogando` para "não desanimar": a comparação no
  mesmo `t` é a garantia estrutural do C7.

---

## 5. O que protege a simulação

A pergunta do dono é "garantir que não quebre a simulação, carrinhos e afins". A
resposta tem duas metades: o que o visitante **não consegue** fazer por construção, e o
que ele **consegue** — e o que o jogo faz com isso.

### 5.1 O que ele não consegue fazer — por construção

| tentativa | por que não acontece | onde está provado |
|---|---|---|
| trocar fase fora da grade | o botão enfileira intenção; só o tick decide | `humano.py`, `test_a3_integracao` |
| trocar antes do verde mínimo / no amarelo | `pode_trocar` é o mesmo predicado da Arena; fora dele o bit vira `MANTER` + `deny` | idem |
| acumular pedidos ("12 trocas de graça") | intenção negada é **gasta**; contagem 3-2-1 drena e descarta | `test_a8_fonte::…negada_e_gasta` |
| começar com vantagem de estado | os três braços partem do mesmo `t0`, selado | `estado.py`, `test_…_saem_do_mesmo_estado` |
| afetar a rodada seguinte | cada `roda()` é um `TrafficEnv` novo, replay de `t=0`, fechado em `finally` | `arena/sumo.py:558-564` |
| afetar os fantasmas | são arquivos, conferidos por `Chave` e por nome do controlador a cada carga | `fantasmas.py`, `test_a3_jogo` |
| fazer carro sumir | conservação `inseridos = entregues + ativos_fim + perdidos` fecha em 0 em 7650 rodadas | `Resultado.conservacao`, A8 §10.3 |
| derrubar o jogo pelo botão | qualquer exceção na rodada vira `ResultadoRodada(motivo=…)` e o motor volta a `ocioso` | `motor.rodada` |
| derrubar a projeção pelo ranking | `Ranking.registra` nunca levanta; escrita atômica | `ranking.py` |

O ponto que vale repetir para a banca: **o visitante joga com o mesmo espaço de ação
da rede neural, bit a bit.** Não há "modo humano" mais permissivo nem mais restrito.

### 5.2 O que ele consegue fazer — e o que o jogo faz com isso

| o que ele faz | o que acontece na malha | o que o jogo faz hoje | o que passa a fazer |
|---|---|---|---|
| **não aperta nada** (`parado`) | 36 entregues (vs 112), população +51% em 120 s, filas até a borda; **nenhum carro some** | coroa o timer, entra no quadro como "36" | **desfecho TRAVOU** (§5.3); não entra no ranking; a tela diz o que aconteceu |
| segura a arterial (`arterial`) | 48 entregues, acúmulo +39 a +45 pp | idem | idem |
| martela tudo | 120 entregues, vence o timer, perde da RL | resultado legítimo | idem — **é jogo válido** |
| aperta o START no meio | rodada abortada, 2 min perdidos | aborta | START do visitante **ignorado** em `jogando` (§2.5) |
| aperta muito rápido | fonte lida a ~48 Hz; bordas, não níveis | nada de errado | nada muda; `hz_entrada` e `atraso_max_s` vão para a página do operador |
| joga mal a ponto de colisões numéricas | teleportes de SUMO: 1–2 por rodada em algumas seeds, **em todos os braços**, contabilizados | `perdidos` no `sane()` | nada muda; item aberto (§5.6) |

Ou seja: a simulação não quebra. O que quebra é a **validade do número**, e é isso que o
§5.3 fecha.

### 5.3 O portão de saúde na rodada — o 6º desfecho

O detector já existe e está calibrado: `sinais_de_travamento(res, referencia=timer27)`
com `acumulo_max_pp=20` — zero falso positivo em 96 rodadas de referência, 528/528
rodadas congeladas pegas (`DIFICULDADE.md` §7, `metricas.py:297-303`). Falta **chamá-lo**.

**Onde:** `MotorDoJogo._placar_final`. O `referencia` é `rodada.fantasmas["timer"].final`
— o `Resultado` do timer27 na mesma `Chave`, que já está em memória (é de onde saem as
linhas finais). Quando o fantasma do timer não existe (degradado), o portão fica
**desligado e a tela diz** (`motivo`: "sem portão de saúde nesta rodada").

**O que acontece quando dispara:**

- `vencedor = None`, `motivo = "o trânsito travou: acúmulo +34 pp sobre o timer"`;
- o placar carrega os sinais (§6.2) para o front distinguir "TRAVOU" de "EMPATE" — hoje
  os dois chegariam iguais (`pareado=true`, sem vencedor, com linha do humano), que é
  exatamente a família de ambiguidade que o `PROXIMOS_PASSOS.md` §5 já teve de
  desfazer uma vez;
- a tela mostra `O TRÂNSITO TRAVOU` em corpo de veredito, os três números **ficam**
  (o visitante vê os 36 dele contra 112), sem colocação e sem medalha;
- o ranking recusa (`sinais` não vazio);
- o operador oferece jogar de novo, mesma seed (os fantasmas estão em cache: 0 s).

**O que ele não faz:** não interrompe a rodada no meio. Os 120 s correm inteiros; a
malha entupindo no projetor é parte da lição, e a rodada precisa terminar para o
`Resultado` existir. Um vigia ao vivo (como o `_Vigia` de 320 ativos/60 s do feed
ocioso) não entra na rodada: em 120 s ele não tem tempo de ser útil sem falso positivo.

**Guardado por:** um teste com `FonteRoteirizada` do A8 rodando `parado` e `martelo`
pelo motor — o primeiro tem de sair com `sinais` não vazio e fora do ranking, o segundo
limpo e dentro. É o mesmo caminho fiel da campanha, então o teste mede o jogo.

### 5.4 Falhas de infraestrutura — o que o visitante vê

| falha | o que o código faz (já) | regra de jogo (nova) |
|---|---|---|
| TraCI cai no meio (visto 1/30 no A3, até 227/480 no A8 com 10 processos) | `rodada` volta com `motivo`, `humano=None` → "NÃO CONCLUÍDA" | **rodada grátis**: mesma seed, mesmo nome, imediatamente. O operador aperta de novo |
| SUMO não sobe | idem | idem; se repetir 2×, operador reinicia o processo (`run_*.ps1`) |
| fantasma da RL falta (torch/ckpt) | placar com duas barras, `motivo` "modo degradado" | rodada **vale**, medalha máxima = bronze, linha diz `sem IA` |
| fantasma do timer falta | placar com uma barra | rodada **não pontua**; operador olha o log |
| projeção cai | motor segue; terminal desenha texto; tela volta sozinha em ≤ 3 s | a marca **não se perde**: se o processo morreu antes de gravar, ela é reconstruída da gravação da rodada (§5.5) |
| botoeira desconecta | `FonteComReserva` cai para o teclado sem parar | operador assume o teclado; reconecta entre rodadas |
| **o navegador perde o foco** (alguém clicou no notebook, Alt-Tab, pop-up) | as teclas param de chegar à `FonteWeb` | a página detecta `blur` e mostra **no chão**, grande: `CLIQUE NA TELA DO NOTEBOOK`; o operador clica. Navegador em `--kiosk`, notebook sem outras janelas abertas, é a prevenção. É a única falha nova que este plano introduz, e é visível na hora |
| WebSocket `/entrada` cai | `FonteComReserva` cai para o `TecladoInput` do terminal | só funciona com o terminal em foco — na prática, o operador recarrega a página (F5), que reconecta em < 1 s |
| notebook lento (atraso do 1:1) | `Marcapasso` acumula e reporta `atraso_max_s` | se `atraso_max_s > 2 s`, a marca entra com `sinais=["atraso"]` e sai do topo — uma rodada em que o relógio escorregou não é a mesma rodada |

### 5.5 Reprodutibilidade da marca

Toda rodada já grava `results/jogo/rodadas/<cenario>/s<seed>_<t0>-<t1>_rNNN.json`
(`GravacaoRodada`, por tick). Com o `id` da marca apontando para esse arquivo, **qualquer
linha do ranking pode ser re-rodada** com `ReplayInput` e tem de dar o mesmo `Resultado`
campo a campo (DoD (c) do A3). É o que torna o ranking auditável — e é a resposta para
"esse 15 aí é verdade?".

Um script `scripts/ranking_reproduz.py --id r017-…` faz isso. Custa ~3 s por marca
(`JOGO.md` §6.1).

### 5.6 Aberto: teleportes

1–2 por rodada em algumas seeds, em todos os braços, contabilizados (conservação zero).
Ninguém investigou a causa (A8 §10.3 item 6). Não bloqueia este plano — o pareamento
absorve —, mas é a pergunta que um jurado de tráfego faz ao ver um carro pular na
tela. Fica registrado; não é do A9.

---

## 6. Arquitetura — onde cada peça mora

### 6.1 Fronteiras

Regra das ondas anteriores: quem implementa **não** edita `feira/contratos/**`,
`docs/PLANO.md`, `README.md`, nem roda `git`. Os contratos que este plano precisa mudar
são dois campos aditivos (§6.2) e são do dono.

| peça | arquivo | escreve |
|---|---|---|
| score, medalha, nome, `id`, `teste`, poda por score, arquivo por dia, v1→v2 | `feira/jogo/ranking.py` | A9 |
| **`FonteWeb`** (C6): fila thread-safe alimentada pelo WS `/entrada`, `feedback()` de volta pelo mesmo WS | `feira/entrada/web.py` (novo) | A9 |
| `EstadoProjecao.jogador`, `POST /api/jogador`, WS `/entrada`, `GET /api/ranking` (+ `dia`, `feira`), `DELETE/PATCH /api/ranking/{id}`, `/operador`, `POST /api/abortar`, `POST /api/pular` | `feira/jogo/web.py` | A9 |
| captura de teclas, modo texto do nome, os 12 LEDs no mapa, aviso de `blur` | `web/js/entrada.js` (novo), `paint.js` | A9 |
| portão de saúde em `_placar_final`; START ignorado em `jogando`; `abortar()`/`pula_resultado()` públicos chamados pelo servidor; rodada grátis; `resultado_s` | `feira/jogo/motor.py` | A9 |
| página do operador (notebook) e tela `/ranking` (projetor, fase 3) | `web/operador.html`, `web/ranking.html`, `web/js/*.js` | A9 |
| tarja: nome no quadro, posição do visitante, medalha, nível da seed, desfecho TRAVOU no `veredito()` | `web/js/placar.js`, `projecao.js`, `index.html`, `projecao.css` | A9 |
| tabela `NIVEL_DA_SEED` (do A8 §5) | `feira/jogo/dificuldade.py` (novo, 30 linhas) | A9 |
| `scripts/projecao_servidor.py`: `--ranking-dir`, `--operador-token`, `--resultado-s` | script | A9 |
| `scripts/ranking_reproduz.py` | script | A9 |
| testes | `tests/test_a9_*.py`, estende `test_a7_ranking.py`, `test_a7_front.py` | A9 |
| docs | este, `JOGO.md` (§1.3, §4.2, §5), `PROJECAO.md` §3.7 | A9 |
| **C7 aditivo** (`rodada`, `sinais`) + `test_contratos.py` | `feira/contratos/frame.py` | **dono** |

### 6.2 Os dois campos aditivos no `Placar` (decidido: abrir — edita o dono)

```python
rodada: int = 0            # contador do motor (n_rodadas): identidade da rodada no fio
sinais: list[str] = ()     # sinais de saúde do braço humano; vazio = são
```

Os dois têm default, então nenhum consumidor existente quebra (o front já ignora campo
desconhecido; é a regra do cabeçalho do C7). `rodada` é o que faz a dedup do ranking
deixar de ser por tupla de números. `sinais` é o que faz "TRAVOU" ser distinguível de
"EMPATE" no fio — hoje seria preciso **parsear `motivo`**, e string livre como
discriminador de estado é a classe de erro que o `pareado` foi criado para eliminar.

É o **passo 0 da fase 1**, feito pelo dono antes de a trilha começar: os dois campos,
`test_contratos.py` cobrindo o default, `Placar.monta()` aceitando-os. Sem eles o plano
ainda andaria (dedup por tupla + janela de tempo, TRAVOU por prefixo em `motivo`), mas
não é o caminho escolhido.

### 6.3 O fluxo de uma rodada com nome

    visitante digita "ANA" + ENTER na página  -> POST /api/jogador -> EstadoProjecao.jogador
    tela ociosa: "ANA · HORA DE TRÂNSITO 107 · DIFÍCIL · APERTE ESPAÇO"
    ESPAÇO na página -> WS /entrada -> FonteWeb.poll() -> motor.espera_start() -> rodada()
      preparando / contagem / jogando  (nada muda)
      _placar_final: sinais = sinais_de_travamento(humano, referencia=timer.final)
                     vencedor = None se sinais
      publica Placar(fase=resultado, rodada=17, sinais=[...])
    EstadoProjecao.absorve(placar):
      ranking.registra(placar, nome=self.jogador)  -> Marca(id="r017-…", score, medalha)
      self.jogador = None
      difunde placar + {"tipo": "ranking", ..., "posicao_da_rodada": 7}
    tela resultado: veredito + "VOCÊ FICOU EM 7º DE 31" + medalha; tarja atualizada

O motor continua sem saber de nome, ranking ou medalha, e recebe a `FonteWeb` como
recebe qualquer `FonteEntrada`. O `Ranking` continua sem saber de motor. A única aresta
nova motor→fio é `sinais`; a aresta nova fio→motor é a `FonteWeb`, atrás do C6.

---

## 7. Plano de construção

Quatro fases, em ordem de valor por dia. Cada uma fecha com a suíte verde
(`.\run_testes.ps1 -Lint`) e é entregável sozinha — se o prazo cortar, corta por baixo.

### Fase 1 — o que não pode faltar (dias 1–3)

0. **Dono:** `rodada` e `sinais` no `Placar` (§6.2). Meia hora.
1. **Commitar a v1 do ranking** (o que está em `git status`).
2. Portão de saúde no motor + `sinais` no fio + `veredito()` com o 6º estado + tela
   TRAVOU.
   Teste: `parado` e `martelo` via `FonteRoteirizada`, pelo motor, `--rapido`.
3. Score pareado + medalhas + poda por score no `Ranking`; migração v1→v2.
   Teste: as marcas do §3.2 com os números do A8 §5 (seed 107: humano 104, rl 101,
   timer 89 → score +15, ouro; seed 104: humano 144, rl 146, timer 130 → +14, prata;
   seed 100: 116/120/111 → +5, bronze).
4. START ignorado em `jogando`; `Esc` aborta; rodada grátis automática após falha de
   infra (mesma seed, mesmo nome, `motivo` na tela).
   Teste: START no meio da rodada roteirizada **não** aborta; `Esc` aborta; uma
   exceção injetada na Arena re-enfileira a mesma seed e mantém o nome.
5. `resultado_s` parametrizado (12 s default); `--grava` **ligado por padrão** em
   `projecao_servidor.py` (sem gravação não há marca auditável, §5.5).

### Fase 2 — o jogo com nome (dias 4–7)

6. **`FonteWeb`** (C6) + WS `/entrada` + captura de teclas na página + os 12 LEDs
   desenhados no mapa + `FonteComReserva(FonteWeb, TecladoInput)` em
   `projecao_servidor.py`. Passa a suíte de conformidade do C6 como o teclado e a
   botoeira (`test_conformidade.py`, importada). Latência medida.
7. Campo de nome no `ocioso` (modo texto da página) + `POST /api/jogador` +
   `EstadoProjecao.jogador`; `Visitante N` sem nome; ESPAÇO só começa com o campo
   fechado.
8. Tarja: nome no quadro; posição do visitante e medalha no `resultado`; nível da seed e
   o bloco de teclas no `ocioso`. `test_a7_front` ganha as fotos das telas novas
   (`projecao_telas.py`). Som do `NOVO RECORDE`, desligável.
8b. `/operador` na tela do notebook (mouse): ABORTAR, PULAR RESULTADO, TESTE, remover
   marca. Opcional para a rodada; obrigatório para o dia dar errado com elegância.
9. Arquivo por dia; `GET /api/ranking?feira=1`.
10. `scripts/ranking_reproduz.py`.

### Fase 3 — se sobrar (dias 8–10)

11. Moderação completa: `DELETE/PATCH`, soft-delete, renomear.
12. "Como a IA jogou" (§4.2): trocas da RL gravadas ao lado do fantasma.
13. `/ranking` completo (top 20 do dia e da feira) como tela alternativa do próprio
    projetor, alternada pela tecla `R` no `ocioso` — não há celular para QR.

### Fase 4 — ensaio e congelamento (dias 11–14)

14. **Ensaio com gente** (§9). É a única parte que nenhum agente faz.
15. Ajuste do que o ensaio mandar (`resultado_s`, frase do operador, limiar da prata se
    o ruído medido com gente for outro).
16. `JOGO.md` e `PROJECAO.md` atualizados; roteiro do operador de uma página.

### DoD

**Do agente** (verificável sem gente nem projetor):

- (a) rodada `parado` sai como TRAVOU, fora do ranking; `martelo` sai válida, dentro;
- (b) `ranking_reproduz.py` reproduz o `score` de toda marca gravada no ensaio, campo a
  campo;
- (c) START durante `jogando` não aborta; `Esc` aborta em ≤ 50 ms (fonte a ~48 Hz);
- (d) o arquivo v1 de hoje carrega como v2 sem perder marca;
- (e) uma marca apagada do `ranking.json` é reconstruída da gravação da rodada + os
  fantasmas em cache (`ranking_reproduz.py --regrava`), com o mesmo `score`;
- (f) `pytest` verde, `ruff` limpo, nenhum arquivo de contrato editado pelo agente;
- (k) `FonteWeb` passa a suíte de conformidade do C6; latência `keydown` → `poll()`
  medida em ≤ 20 ms (p99) numa rodada real de 1:1;
- (l) com o campo de nome aberto, nenhuma tecla vira botão nem START; com ele fechado,
  ESPAÇO começa e as 12 letras viram botões — provado em teste sem navegador
  (o modo texto é função pura da página, testável como o `veredito()`).

**Do dono** (precisa de gente ou do projetor):

- (g) 5 pessoas digitam o nome e jogam 2 rodadas cada, olhando só para o chão, sem o
  operador tocar no notebook; o ranking da tela bate com o arquivo;
- (h) a 2 m, ler nome + score + medalha do 1º do quadro (piso 25′ do `PROJECAO.md`);
- (i) a frase do operador cabe no `preparando` + `contagem` (≤ 5 s com cache);
- (j) `mão` medida (§9).

---

## 8. Decisões tomadas (2026-09-14)

Critério declarado pelo dono: **evento em público, a plateia tem que se divertir, e o
sistema tem que ser de manipulação fácil.** Os recursos são **um notebook, um projetor
no chão e um teclado** — sem celular, sem segunda tela para o público. O operador está
lá para orientar; a rodada inteira tem de acontecer **sem ele tocar em nada**.

**O que "manipulação fácil" quer dizer, em regras de desenho:**

- a **tela projetada é a única interface** do visitante: nome, mapa de teclas, START,
  jogo, resultado, ranking — tudo no chão, com o teclado ao lado;
- todo campo tem default: sem nome é `Visitante N`, resultado volta sozinho, fantasma
  faltando degrada sozinho, falha de infra dá rodada grátis sozinha;
- a tecla de cada coisa está **escrita na tela no momento em que serve** (`ENTER
  confirma`, `ESPAÇO começa`, o bloco 3×4 sobre os cruzamentos) — ninguém precisa
  decorar nem perguntar;
- o que é do operador (abortar, marcar teste, remover marca) fica na tela do notebook,
  com mouse, e pede um segundo clique. Nunca terminal, nunca senha;
- o terminal só sobe e desce o jogo (`run_*.ps1`).

| # | decisão | **decidido** | por quê, sob o critério |
|---|---|---|---|
| 1 | ordem do ranking | **Δ vs timer** | quase todo mundo pontua positivo (martelo vence o timer em 91%); um quadro de números negativos não diverte ninguém. E é o número que a tarja já mostra grande |
| 2 | como o nome entra | **o visitante digita no teclado, olhando para o chão** (arcade); as teclas passam a ser lidas pela página projetada (`FonteWeb`, §3.3) | é o único dispositivo que existe, e é o mesmo que joga. Digitar o próprio nome na tela grande é a cerimônia de entrada — e o mapa de teclas desenhado sobre os cruzamentos vira o manual |
| 3 | START do visitante durante a rodada | **ignorado** (LED `deny`); `Esc` 3x em 1,5 s ou a página do operador abortam | um botão grande e iluminado no meio de 12 que a pessoa está martelando **vai** ser apertado. Perder 2 minutos de um visitante por isso é a pior experiência possível em público |
| 4 | abrir o C7 para `rodada` e `sinais` | **abrir** (dono edita `frame.py` + `test_contratos.py`) | "TRAVOU" contra "EMPATE" na frente da plateia não pode depender de parsear string |
| 5 | seeds | **12 held-out em rodízio** | um dia de feira tem ~150 rodadas; 6 seeds repetem a mesma hora de trânsito 25 vezes, e a plateia que fica nota |
| 6 | nível da seed na tela | **sim** | é contexto de jogo ("nível difícil") — e transforma a sorte em desafio declarado em vez de derrota inexplicada |
| 7 | `resultado_s` | **12 s**, e o operador pode encurtar pela página | 8 s não dá para a plateia ler posição + medalha + veredito. 12 s custam 1 visitante/hora e compram a celebração |
| 8 | apelido em tela pública | **uma linha no `/operador`: "só apelido, sem sobrenome"** | é tela pública com foto; a regra tem de estar no campo, não na cabeça do operador |
| 9 | limiar da prata | **3 carros** | é o ruído de jogada medido; outro valor exige medida |
| 10 | rodada grátis após falha de infra | **sim, automática**: mesma seed, mesmo nome, a tela diz "falha nossa — de novo" | recuperação é zero toques, não um procedimento |
| 11 | dupla no painel | **não** | um jogador por rodada. O ranking é de pessoas, e a comparação com a RL é de um controlador contra outro |
| 12 | fila de nomes | **não** | sem celular não há onde a fila viver; o próximo digita quando chega a vez, são 5 s |
| 13 | som *(nova)* | **um só**, curto, no `NOVO RECORDE` — e desligável (`?som=0`) | feira é barulhenta; um som por recorde chama a plateia para o projetor, dez sons por rodada viram ruído |
| 14 | o que o operador faz por rodada | **nada** | nome, START, jogo e resultado são do visitante; o operador explica em uma frase e aponta o teclado |
| 16 | validade da marca no quadro *(nova)* | **30 min** (`--ranking-validade`); o arquivo e os totais do dia guardam tudo | um vencedor da manhã não pode reinar o evento inteiro; quem chega depois precisa ter o que bater (§3.3b) |
| 17 | ritmo do relógio *(nova)* | **2×** no preset (`--ritmo`); 1× continua o default fora dele | só apresentação; a sim não muda. O ensaio compara 1×/1,5×/2× (§2.7) |
| 18 | volta ao ocioso *(nova)* | **anunciada** pelo motor (`anuncia_ocioso`, preset); resultado em **10 s** | a tela ficava presa no RESULTADO até o vigia declarar queda (§3.6) |
| 15 | onde ficam teclado, notebook e telas *(nova)* | **teclado junto do projetor** (sem fio ou USB longo); navegador em tela cheia no projetor (`--kiosk`), com foco; notebook com o terminal e, se quiser, `/operador` | é a única disposição em que o visitante digita olhando para o que está digitando. O foco do navegador é a fraqueza (§5.4) |

O que essas decisões **não** mudam: a rodada, a grade, a manchete, o pareamento e o
espaço de ação. O nome é regra de mesa, não de simulação.

---

## 9. O ensaio com gente — o que só ele responde

`DIFICULDADE.md` §10.3 é explícito: **`mão=M`** — quantos dos 12 botões uma pessoa
alcança num tick de 5 s no painel 3×4 — é o parâmetro mais influente do estudo inteiro
(leva P(vitória) de 34% a 0%) e o único que saiu de suposição. Custa 10 minutos por
pessoa, com o `--grava` ligado; a gravação por tick dá `M` direto (`max(len(t) for t in
ticks)` e a distribuição).

O ensaio deste plano mede, com 5 pessoas × 2 rodadas:

| o que | como | decide |
|---|---|---|
| `M` real | gravações | se P(vitória) do §3 está super ou subestimada; se o ranking vai ser 90% bronze |
| ruído de jogada humano | dp de `score` entre as 2 rodadas da mesma pessoa | o limiar da prata (§3.2) |
| tempo de `resultado` | cronômetro: a pessoa leu posição + medalha? | `resultado_s` |
| a frase do operador | a pessoa entendeu "negado" sem perguntar? | o texto do §2.1 |
| o START acidental | quantas vezes alguém tocou o botão grande no meio | se a regra do §2.5 era necessária |
| leitura a 2 m | foto do projetor com nome + score + medalha | DoD (h) |

Resultado do ensaio vai para o §6 do `JOGO.md`, com os números, como tudo aqui.

---

## 10. Estado da implementação (2026-09-14)

**Fases 1 e 2 construídas, tudo OPT-IN.** Sem flag nenhuma, `python -m feira.jogo` e
`scripts/projecao_servidor.py` se comportam como antes (735 testes da suíte anterior
continuam verdes; 44 novos). A feira liga tudo com um preset:

    ..\smart-traffic\.venv\Scripts\python.exe scripts\projecao_servidor.py --feira
    # = --entrada web --abortar operador --resultado-s 12 --ranking-dir results/feira
    #   --ranking-validade 30 --ritmo 2 --anuncia-ocioso --grava results/jogo
    #   --repete-falha --seeds 100..111  (resultado: 10 s)
    # projetor: http://127.0.0.1:8080/  (F = tela cheia; foco NA PÁGINA)
    # notebook: http://127.0.0.1:8080/operador.html

| peça | onde | estado |
|---|---|---|
| `Placar.rodada` + `Placar.sinais` (C7, aditivos) | `feira/contratos/frame.py` | ✅ `test_contratos` |
| portão de saúde na rodada (acúmulo excedente vs timer, +20 pp) → desfecho TRAVOU | `motor._sinais`, `_placar_final` | ✅ medido ao vivo: rodada sem ninguém apertar = 38 entregues, **+53,0 pp**, sem vencedor, fora do quadro |
| START do visitante ignorado (`abortar_por="operador"`), `Esc`/página abortam | `motor._bomba`, `TecladoInput.ao_abortar` | ✅ |
| rodada grátis (`repete_falha`) e `pula_resultado()` | `motor.rodada` | ✅ |
| ranking v2: score pareado, medalhas, nome, `Visitante N`, uma linha por pessoa, posição, moderação soft, arquivo por dia, v1→v2 | `feira/jogo/ranking.py` | ✅ `test_a9_ranking` + os 10 do A7 |
| `FonteWeb` (C6) + `FonteComposta` | `feira/entrada/{web,composta}.py` | ✅ na suíte de conformidade do C6 |
| servidor: `/api/jogador`, `/api/proxima`, `/api/abortar`, `/api/pular`, `/api/teste`, `PATCH/DELETE /api/ranking/{id}`, WS `/entrada`, `ranking`/`leds`/`jogador` no fio | `feira/jogo/web.py` | ✅ `test_a9_web` (com uvicorn de verdade) |
| nível da seed (tabela do A8 §5 + o que a feira já viu) | `feira/jogo/dificuldade.py` | ✅ |
| front: campo de apelido no chão, bloco de teclas sobre os cruzamentos, 12 LEDs, veredito TRAVOU, quadro v2 (rótulo · score · medalha), posição + medalha no resultado, som do recorde, aviso de foco | `web/js/entrada.js`, `placar.js`, `projecao.js`, `index.html`, `projecao.css` | ✅ `test_a9_front` (node + Chrome headless) |
| página do operador | `web/operador.html` | ✅ |

**Três defeitos achados jogando (2026-09-14, noite), consertados:** a identidade da
marca por `rodada` colidia entre reinícios do servidor (o contador recomeça em 1 e a
rodada 2 da tarde engolia a da manhã na mesma seed — do disco só entra a chave por
tupla); o preset gravava em `results/jogo/rodadas/rodadas/` (o `caminho_gravacao` já
põe o `/rodadas`); e o `Esc` de um visitante abortava a rodada. O `motivo` do TRAVOU
passou a dizer quantas trocas a pessoa pediu ("2 trocas em 24 ciclos"), porque é
essa a resposta, e o status ganhou os contadores da entrada web (`entrada`) para o
operador ver se as teclas estão chegando.

**Ainda não feito** (fase 3 e 4): `scripts/ranking_reproduz.py` (DoD (b)/(e)); tela
`/ranking` no projetor (tecla `R`); "como a IA jogou" (§4.2); a latência
`keydown → poll()` está medida só no teste local (três mensagens em < 1 s, sem p99) —
a medição de DoD (k) precisa da rodada 1:1 real; e o **ensaio com gente** (§9), que
nenhum agente faz. A v1 do ranking e tudo isto continuam **fora do git** — o commit
é do dono.

## 11. Fora de escopo

Multiplayer em rede · carrinhos físicos · pontuação por tempo de viagem · qualquer
restrição ao visitante além das da RL · escolher seed para a RL ganhar · animar a RL
"pensando" · refazer o A8 com o `v3_queue_mr60` (se o ponteiro da política mudar, o
estudo inteiro re-roda, ~40 min — e este plano não depende dele).
