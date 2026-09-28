# A projeção da feira — a rodada no chão

Agente **A7 — Projeção & Placar**, Onda 2. Entrega o transporte (`feira/jogo/web.py`),
o front (`web/**`), as ferramentas de bancada (`scripts/projecao_*.py`) e este
documento.

O que está aqui foi **medido nesta bancada**, com o venv compartilhado, Chrome 152 e
Node 24.16. O que **não** foi medido — e não podia ser, porque exige o projetor e uma foto
— está marcado como tal, com a lista do que o dono do projeto precisa fazer.

> **Sob que carga.** Todas as medições do §5 foram feitas com o treino do agente A6
> rodando **na mesma máquina** (seis processos de SUMO e cinco de Python ocupando os 16
> núcleos). Isso torna os números **conservadores**, não otimistas — mas é também a
> explicação mais provável do outlier de 16 ms do §5.2, e é honesto dizer que a bancada
> não estava ociosa.

    python scripts/projecao_servidor.py               # a rodada com a projeção
    python scripts/projecao_servidor.py --so-servidor # só a projeção (bancada)
    python scripts/projecao_contraste.py              # a auditoria de cor
    python scripts/projecao_bench.py                  # o desempenho
    python scripts/projecao_telas.py --saida telas    # uma foto de cada fase

Abra `http://127.0.0.1:8080/` na tela do projetor e aperte **F**.

---

## 0. A projeção em uma tela

| | |
|---|---|
| transporte | FastAPI + WebSocket, servidor numa **thread daemon** do processo do jogo |
| entrada | `publicador` do motor (placar) + `ArenaPublicada` (frames ao vivo) |
| telas | uma por fase de `FASES` (C7): ocioso · preparando · contagem · jogando · resultado |
| manchete | **carros entregues**, três braços no mesmo `t` simulado |
| tarja | **226 px**, uma só, na forma da `#solo` do maquete: coluna de identidade + coluna por métrica (§3.5) |
| métricas | na tela de jogo, só `carros entregues`; no RESULTADO, mais `tempo de viagem` e `carros parados` |
| delta | **▲/▼ %** do protagonista contra a régua, grande no topo da coluna, em 52′ (§3.8) |
| desenho do mapa | **luz contida**: nada aceso fora do asfalto, separação por borda escura, zero halo (§3.6) |
| régua | o **TIMER FIXO** vira uma marca vertical atravessando os três trilhos |
| escala da barra | de quem lidera **agora**, passo de 10 carros, nunca encolhe na rodada |
| queda do jogo | volta sozinha para `ocioso` em **2,19 s** medidos (teto da DoD: 3 s) |
| janela divergente | **denuncia**, não desenha |
| rodada não pareada | **denuncia**, não coroa e não classifica (§6.4) |

### As cinco telas

Uma por fase de `FASES` (C7). A troca é só um `data-fase` no `<html>`: a máquina de
estados do jogo é do motor, e o front não tem uma cópia dela para divergir.

| fase | mapa | placar | o que domina a tela |
|---|---|---|---|
| `ocioso` | **a RL ao vivo**, tela cheia | duas linhas (RL e timer) vindas dos `stats` do frame — no ocioso o motor não publica `placar`; o delta vira `rede vs timer` | o convite, numa tarja preta encostada no placar |
| `preparando` | congelado sob um véu de 76% | vazio (é o que o motor publica: `linhas: []`) | "PREPARANDO A RODADA" + o pulso dos três pontos |
| `contagem` | congelado sob o mesmo véu | vazio | o **3 · 2 · 1** a 422′ de arco |
| `jogando` | o braço **humano**, ao vivo | as três linhas na coluna de `carros entregues` + a régua do timer + o relógio | o mapa em cima, a tarja embaixo |
| `resultado` | **desligado** (a comparação é a mensagem, e mapa parado só joga luz de graça) | **a mesma grade**, em corpo grande e com as TRÊS métricas: o número vai a 80 px | o veredito, num dos quatro estados do §6.4 |

Fora das fases há quatro camadas de serviço: **espera** (o projetor nunca fica preto
sem explicação), **modo degradado** (§6), **denúncia de janela** (§7) e **denúncia de
pareamento** (§6.4) — as duas denúncias dividem a mesma camada, porque fazem a mesma
coisa: tiram o placar da tela quando a comparação não vale.

### Teclas (operador)

`H` hud · `G` asfalto · `D` pegada · `V` carro real dentro do sprite ·
`I` **régua de bancada** · `T` grade · `R` girar · `M` espelhar · setas alinhar ·
`+ −` zoom · `, .` texto · `0` reset · `F` tela cheia.

`?demo=<tela>` desenha uma tela com dados sintéticos, sem servidor de jogo — vale
qualquer fase e mais `nao_pareada`, `empate`, `sem_placar`, `denuncia`, `degradado`;
`?bench=<n>` roda o medidor de render com `n` carros.

---

## 1. O ponto de operação — e por que ele muda tudo

Todo número deste documento depende de **onde a luz cai**. A projeção da feira **não é**
a mesa de 1,30 m do maquete: o projetor fica numa torre de 2,00 m e joga **no chão**.

A escolha da altura da torre é do dono do projeto, com o projetor na mão. O que este
documento entrega é a conta, nos três pontos que importam — e a coluna do meio é uma
hipótese, não uma recomendação disfarçada:

| | mesa (maquete) | torre mais baixa | **chão a 2,00 m (feira)** |
|---|---|---|---|
| distância óptica | 1,43 m | 1,60 m | **2,00 m** |
| largura da imagem (TR 1,10) | 1,30 m | 1,45 m | **1,82 m** |
| área | 0,95 m² | 1,18 m² | **1,86 m²** |
| branco na imagem (Φ = 300 lm) | 316 lux | 254 lux | **161 lux** |
| preto vazado (CR 150:1) | 2,10 lux | 1,69 lux | **1,08 lux** |
| 1 px a 1080p | 0,677 mm | 0,755 mm | **0,947 mm** |
| dinâmica total a 25 lux de ambiente | 12,6 | 10,5 | **7,19** |
| **teto de ambiente** (§4.3) | 90 lux | **72 lux** | **46 lux** |
| pegada do carro a 2 m (§3.3) | 7,4′ | 8,2′ | **10,3′** |

Duas linhas fazem a decisão, e elas **puxam para lados opostos**: encolher a imagem
compra brilho (o teto de ambiente sobe de 46 para 72 lux) e paga com o carro (a pegada
cai de 10,3′ para 8,2′). Aumentar a imagem faz o contrário. Não há altura que otimize as
duas — é uma escolha entre "a sala pode ter luz" e "o carro se resolve de longe".

A linha da dinâmica é a que manda na cor: **no chão, a imagem inteira tem 7,19 de
dinâmica**. Tudo o que a tela precisa distinguir — preto, trilho, três barras — tem que
caber aí dentro. Isso é o que decidiu a paleta (§4), não o gosto.

Todos os números saem do mesmo script; para conferir outra largura, é
`ponto()` em `scripts/projecao_contraste.py` com a medida da trena.

> **Não medido.** `Φ = 300 lm`, `CR_ANSI = 150:1` e `TR = 1,10` são o ponto de projeto
> herdado do `PLANO_PROJECAO.md` do maquete e **nunca foram medidos com o aparelho**. Se
> o projetor real entregar metade do fluxo, o teto de ambiente do §4 cai junto. O
> `scripts/projecao_contraste.py` aceita `--fluxo` para refazer a conta em dois segundos.

---

## 2. Legibilidade a 2 m — **(a) da DoD, e ela é do dono**

**Eu não consigo verificar (a).** Ela exige o projetor real, o chão real, a luz da sala
real e uma foto — e quem tem os quatro é o dono do projeto. O que dá para entregar no
lugar é (i) o proxy mensurável, com a conta à vista, e (ii) uma lista curta de bancada.

### 2.1 O proxy: tamanho angular

A grandeza que decide se algo se lê **não é** o tamanho em pixels nem em milímetros: é o
ângulo que o objeto ocupa no olho.

    α = s / d          (rad)          α' = (s_mm / d_mm) × 3437,75   (minutos de arco)

Com a montagem do §1 (imagem de 1,82 m, painel de 1920 px) e a plateia a 2,00 m:

    1 px = 0,947 mm  →  1 px = 1,628' de arco

**Piso adotado: 22′ de arco para qualquer texto que a plateia lê.** A ISO 9241-303
recomenda 16–22′ como altura mínima de caractere e 20–25′ como faixa confortável; 22′ é
o topo do mínimo, escolhido porque aqui a leitura é de relance, em pé, com gente na
frente.

| elemento | corpo @1080p | cap-height | mm no chão | **arcmin @2 m** |
|---|---|---|---|---|
| contagem 3·2·1 | 380 px | 274 px | 259,3 | **446′** (7,4°) |
| número do placar (resultado) | 80 px | 58 px | 54,6 | **94′** |
| convite (APERTE O BOTÃO) | 52 px | 37 px | 35,4 | **61′** |
| **manchete do delta** (▲ 6,0%) | 44 px | 32 px | 30,0 | **52′** |
| veredito (A REDE NEURAL VENCEU) | 46 px | 33 px | 31,4 | **54′** |
| relógio (faltam N s) | 38 px | 27 px | 25,9 | **45′** |
| **número do placar** (jogando) | 36 px | 26 px | 24,5 | **42′** |
| rótulo do braço (TIMER FIXO) | 28 px | 20 px | 19,1 | **33′** |
| recorde do quadro (número) | 30 px | 22 px | 20,5 | **35′** |
| valor das colunas de contexto (159 s) | 26 px | 19 px | 17,7 | **30′** |
| rótulo da métrica (CARROS ENTREGUES) | 22 px | 16 px | 15,0 | **26′** |
| de quem é o delta (VOCÊ VS TIMER) | 22 px | 16 px | 15,0 | **26′** |
| delta em carros (+9 carros) | 22 px | 16 px | 15,0 | **26′** |
| MELHORES DA FEIRA | 22 px | 16 px | 15,0 | **26′** |
| selo "pré-computado" / "ao vivo" | 21 px | 15 px | 14,3 | **25′** |
| linha do quadro (bateu a IA) | 21 px | 15 px | 14,3 | **25′** |
| cromo do operador (chave, seed) — **só com `I`** | 19 px | 14 px | 13,0 | **22′** |

Cap-height = 0,72 × corpo, a proporção da família em uso (IBM Plex Sans / IBM Plex Mono,
servidas de `web/fonts/` — ver §3.5).

**O MENOR TEXTO DA PLATEIA ESTÁ EM 25′**, contra um piso de 22′, e essa folga não veio
de aumentar corpo: veio de TIRAR TEXTO. A tela carregava dez textos entre 15 e 19 px que
ninguém lia a dois metros, e enquanto eles estavam lá não havia espaço para o resto
crescer. Saíram, nesta ordem de convicção:

| saiu | estava em | por quê |
|---|---|---|
| catálogo de cores (semáforo · acúmulo · carro · régua) | 17 px, **20′** | era o único texto abaixo do piso, e as bolinhas ao lado diziam sozinhas o que as palavras repetiam |
| pastilhas de cenário, seed + sha e janela | 19 px | cromo do OPERADOR: foi para trás da tecla `I`, junto da régua de bancada |
| pastilha da fase (`fase JOGANDO`) | 19 px | a tela inteira já diz em que fase está |
| hora no quadro de recordes (`14:22`) | 19 px | não diz quem jogou nem quão difícil foi; continua no `ranking.json` |
| resumo do quadro (`27 rodadas · …`) | 15 px | o MENOR texto da tela, e falava do dia, não de quem está na frente do projetor — ficou só no `resultado` |
| `tempo de viagem` e `carros parados` na tela de jogo | — | são análise; análise é o que a tela de RESULTADO faz (§3.5) |

Com eles fora, tudo o que sobrou subiu: o rótulo do braço de 24 para 28 px, o número do
placar de 32 para 36, o valor das colunas de contexto de 21 para 26, o selo
"pré-computado" de 19 para 21, a manchete do delta de 36 para 44 — **e a tarja ainda
encolheu de 250 px para 226 px**, porque uma coluna de métrica ocupa menos que três.

O selo "pré-computado"/"ao vivo" foi o que sobreviveu à limpeza apesar de ser pequeno, e
de propósito: ele diz que dois dos três adversários são fantasmas, e isso é informação de
honestidade para a plateia, não cromo. Ele já esteve em 15 px (17,6′), foi para 19 e hoje
está em 21 (25′).

E o NÚMERO DO PLACAR não voltou ao que era: 76 px na primeira versão, 42 na segunda, 32
na terceira, **36 px hoje**. A 36 px ele mede 42′, quase o dobro do piso. Quem lê de
longe já sabe quem está ganhando pela BARRA, que agora atravessa a tarja inteira — o
número é a confirmação, não a manchete. **A manchete é o delta**, em 52′: é ele que
responde a pergunta que a tela faz.

Se a imagem sair menor que 1,82 m (por exemplo, se a torre encolher), tudo escala junto:
numa imagem de 1,30 m os números viram 64′ / 29′ / 20′ / 15′ — a manchete continua
folgada e as secundárias encostam no piso. A tecla `,`/`.` multiplica o texto de 0,7× a
2,0×, e a projeção guarda o ajuste no `localStorage`.

**A tela mostra a própria conta.** A tecla `I` liga a *régua de bancada*: escala do mapa,
mm/px, tamanho do sprite em mm e em minutos de arco, e o cap-height de cada classe de
texto — tudo calculado no navegador que está projetando, não copiado deste documento.
É o que deve aparecer na foto.

### 2.2 Lista de conferência de bancada — para o dono, com o projetor ligado

Cada item leva menos de um minuto. O que falhar, anote o número e devolva.

**Antes de subir na torre**, gere as imagens de referência para comparar com o chão:

    python scripts/projecao_telas.py --saida telas --denuncia

Sai um PNG de 1920×1080 por fase (`ocioso`, `preparando`, `contagem`, `jogando`,
`resultado`) mais os quatro desfechos e as duas camadas de serviço: `nao_pareada`,
`empate`, `sem_placar`, `denuncia`, `degradado`. São o mesmo código que a feira roda,
com dados sintéticos — servem para saber o que **deveria** aparecer, não para
substituir a foto.

1. **Alinhamento.** `T` liga a grade de teste. As quatro bordas e a cruz central têm que
   estar dentro da área útil do chão. Se sobrar imagem fora, corrija o zoom (`+`/`−`) e
   o pan (setas) — nunca o *keystone* do projetor, que borra o pixel.
2. **Escala real.** Meça a largura da imagem projetada com uma trena. Anote. Se não for
   1,82 m, é este número que entra em `MONTAGENS["chao"]["largura_m"]` no
   `scripts/projecao_contraste.py` e em `MONTAGEM.larguraM` no `web/js/projecao.js`.
3. **A régua.** `I` liga o diagnóstico. Fotografe. Confira três coisas: que `mm/px` bate
   com o item 2; que a linha do sprite diz **"o sprite NÃO passa da pegada"**; e que a
   linha `enquadre:` diz quantos metros de ponta estão fora do quadro (13 m de cada
   lado, com `MARGEM_M = 12`). A foto de auditoria precisa mostrar o que foi cortado. Se ela disser o
   contrário, o piso anti-sumiço de 3 px mordeu (janela pequena demais) e a fila
   desenhada não é mais contável — ver §3.3.
4. **A 2 m, de pé.** Fique a 2 m da borda da imagem, na altura dos olhos de um visitante.
   Sem se abaixar, leia: (a) os três números do placar; (b) os três rótulos; (c) quem
   está na frente. Se qualquer um exigir aproximar, aumente o texto com `.` e repita.
5. **O selo e o quadro.** Ainda a 2 m, leia `pré-computado` / `ao vivo` e uma linha do
   quadro de recordes. São os itens de fronteira (25′): se falharem, o texto sobe com a
   tecla `.` e o mapa encolhe junto — a tarja é reservada, então os dois estão sempre
   trocando de tamanho um com o outro.
6. **Ambiente.** Meça o lux no chão da imagem (app de celular serve para ordem de
   grandeza). Acima de ~50 lux a paleta sai do piso (§4) e não há cor que conserte:
   apague luz ou encolha a imagem.
7. **A fila.** Com a rodada correndo, olhe de 2 m: a banda quente atrás dos cruzamentos
   tem que crescer e encolher visivelmente. Carro individual **não** se resolve a 2 m —
   e não deve; ver §3.
8. **Foto do RESULTADO.** É a tela que vira registro. Confira que o vencedor está marcado
   por moldura **e** por texto, e que a chave (cenário/seed/janela/sha) aparece.
9. **A rodada que não vale.** Abra `?demo=nao_pareada` e leia de 2 m: tem que dar para
   entender, sem ajuda, que **aquela rodada não conta**. É a tela que protege o projeto
   de publicar uma comparação inválida na frente do público, e a única que ninguém quer
   ver — o que é exatamente o motivo de ela precisar ser ensaiada.

---

## 3. O fator de exagero do sprite — resolvido com número

### 3.1 O problema

Sob similitude K = 6, o carro do `aberta.maquete` mede **0,583 × 0,233 m** de SUMO
(`sumo/aberta/demanda/maquete_aberta.add.xml`) e a rede tem 153,33 × 90 m. No layout de
jogo a 1080p (mapa de 1920 × 680 px, o que sobra depois do cromo e do placar) isso dá
uma escala de **7,24 px/m**, e portanto:

    carro real desenhado  =  4,22 × 1,69 px  =  4,00 × 1,60 mm  =  6,9' × 2,7'

**2,7 minutos de arco de largura.** Isso é o dobro do limite de acuidade e não se
distingue de sujeira de render. Sem exagero não há carro na tela.

### 3.2 A regra herdada estoura a pegada aqui — e o número diz por quanto

O `paint.js` do maquete dimensiona o sprite pela **faixa**, não pelo carro:

    D = max(7, laneW · s · 1,15)        L = D · 2,9

e desenha a **pegada real do SUMO** (comprimento + `minGap`) como um rastro atrás,
*quando* `footPx > L · 1,15`. Nesta rede, no layout de jogo a 1080p:

| | px |
|---|---|
| pegada do SUMO (`0,583 + 0,292 = 0,875 m`) | **6,33** |
| sprite pela regra do maquete | **20,30 × 7,00** |
| razão sprite / pegada | **3,21×** |
| a condição `footPx > L·1,15` dispara? | **não** |

Ou seja: aplicada aqui, a regra herdada produz um sprite **mais de três vezes mais
comprido que o espaço que o modelo reserva**, e por isso a pegada verdadeira — a peça
que garantia a honestidade da DENSIDADE — não chega a ser desenhada. Carros parados se
sobrepõem 3 para 1.

Isto **não é defeito do maquete**. Lá a rede é outra e a desigualdade tem o sinal
contrário: o sprite fica *mais curto* que a pegada, e o rastro é exatamente o conserto
disso. O que muda aqui é o lado da desigualdade. (Mesmo com o mapa em tela cheia, sem
placar nenhum, ela ainda daria 2,02× a pegada — não é uma questão de sobrar espaço.)

Este número foi um motivo para recusar a regra herdada, depois um preço que se
escolheu pagar, e hoje é de novo um motivo para recusá-la — desta vez com o conserto no
lugar certo, que não era o sprite. O §3.3 conta a volta inteira.

### 3.3 A regra adotada — o desenho nunca passa da vaga

Esta seção já disse as duas coisas opostas, e o vaivém é o argumento.

**Primeira versão — o corpo É a pegada.** `corpo = min(comprimento·mult, pegada)`.
Impecável no papel: fila desenhada com a mesma contagem *e* o mesmo comprimento da fila
simulada. Produzia, nesta rede em K = 6, **6,3 × 4,6 px de carro** — 10,3′ × 7,4′ contra
um piso de 22′. Uma fila honesta feita de pontos que ninguém enxerga.

**Segunda — a regra da projeção do maquete**, `D = max(7 px, laneW·s·1,15)`, `L = D·2,9`.
Entregou **20,3 × 7,0 px**, legível de longe. E **2,5 sprites por vaga**: em qualquer
fila os carros parados montavam uns nos outros, e a fila virava um borrão claro de
comprimento certo e densidade errada. Um mapa que existe para mostrar trânsito não pode
desenhar o trânsito errado para o carro ficar bonito.

**A terceira encontrou o conflito onde ele de fato estava — na LARGURA DA VIA.**

> ```
> corpo   = min(comprimento·mult, pegada · 0,88)
> largura = min(largura·mult,     corpo  · 0,66)
> faixa desenhada = 11,5 px   (era 15)
> ```

O carro não cresceu: **a rua parou de ser grande demais para ele.** O exagero da via é
lateral e livre — nada empacota de lado; o do carro não é, porque o comprimento dele
está preso à vaga. Com a faixa a 15 px e o carro a 7 px de largura, o veículo ocupava
**0,28** da faixa desenhada contra **0,42** na realidade: a pista parecia larga demais e
o trânsito, ralo. A 11,5 px a razão volta a **0,40**, e o mesmo sprite passa a ler como
carro numa pista.

Medido pela régua de bancada (tecla `I`) a 1920×1080, escala de **9,24 px/m**:

| 1080p, fase `jogando` | px | mm no chão | arcmin @2 m |
|---|---|---|---|
| carro **real** | 5,4 × 2,2 | 5,10 × 2,04 | 8,8′ × 3,5′ |
| **vaga** do SUMO (`0,583 + 0,292 m`) | 8,1 | 7,67 | 13,2′ |
| **sprite** (corpo × largura) | **7,1 × 4,7** | 6,74 × 4,45 | **11,6′ × 7,6′** |
| faixa desenhada | 11,7 | — | — |

    exagero de comprimento  ×1,32     exagero de largura  ×2,18     razão carro/faixa  0,40

E a régua imprime, em toda resolução de feira: **"o sprite NÃO passa da pegada"**.

O que cada número protege:

* **`0,88` da vaga é a costura.** Com o corpo na vaga cheia os carros parados se
  ENCOSTAM, e uma fila carregada vira uma barra clara contínua em que não se distingue
  um veículo do seguinte — tecnicamente não é sobreposição, visualmente é o mesmo
  defeito. Os 12% que sobram são ~1 px de preto entre um carro e o próximo: o menor vão
  que ainda se lê, e é ele que faz a fila PARECER uma fila de carros. (O modelo reserva
  33% de vão — `minGap`/vaga = 0,292/0,875. O desenho usa 12%: ele exagera o veículo
  dentro do próprio slot, nunca para fora dele.)
* **`0,66` do corpo é ASPECTO, não espaço.** Com o comprimento preso à vaga, deixar a
  largura ir até `vehW·s·mult` daria um sprite quase quadrado, e quadrado não lê como
  carro. O teto segura a silhueta em ~1,5:1.
* **A largura nunca passa de `vehW/laneW`** (0,42 aqui). Se passasse, o veículo estaria
  invadindo a faixa vizinha no desenho sem invadir na simulação. O teste
  `test_carro_parado_nunca_monta_em_carro_parado` guarda as quatro propriedades em cinco
  layouts, de 720p a 4K.
* **11,5 px de faixa** = 10,9 mm no chão = 19′ de arco: continua sendo uma rua com
  folga, e não um fio de cabelo. Abaixo de 1080p esse piso em PIXELS passa a mandar, a
  via fica proporcionalmente mais larga e a razão carro/faixa cai — é conhecido, está no
  teste, e é o preço de projetar numa resolução menor.

* **posições**: são as do SUMO, sem toque. O que se exagera é o tamanho do desenho,
  nunca onde ele está.
* **modo verdade** (tecla `V`): desenha o retângulo do carro real, na escala real,
  dentro do sprite. É a prova visual do exagero, para a foto de bancada.

**O que isso custa, dito em voz alta:** 11,6′ × 7,6′ é pequeno. A dois metros o carro
individual está no limite do que se resolve, e é para ficar — a rede tem 153 m de
largura e a tela tem 1,82 m. Quem carrega a leitura de longe é a **banda de acúmulo**,
cujo comprimento sai do `reach` físico, e o **placar**. O carro individual é para quem
chega perto, e para quem chega perto ele agora está certo.

### 3.4 O que isso custa em tela, e o teto que a geometria impõe

O sprite resolveu-se com um piso em pixels, mas a **malha** só cresce de um jeito:
sobrando altura. E aqui a geometria é dura — esta rede é **1,70:1** numa tela
**1,78:1**, quase o mesmo formato. A malha encaixa pela ALTURA, e **cada pixel tirado da
altura custa 1,7 px de largura de malha**. Não há margem vertical de graça para o HUD
ocupar: a folga desta rede é lateral, e margem lateral não vira tarja sem o texto ficar
de lado para quem está de pé na frente da imagem.

Medido pela régua de bancada, em 1920×1080:

| altura reservada | escala | malha (medida no PNG) |
|---|---|---|
| 388 px (tarja de 344 + faixa de topo de 44) | 7,24 px/m | 1159 px |
| 256 px (tarja de 212 + faixa de topo de 44) | 8,85 px/m | 1373 × 809 px |
| 250 px (tarja única, três colunas de métrica) | 8,90 px/m | 1380 × 815 px |
| **226 px (tarja única, uma coluna de métrica)** | **9,24 px/m** | **1422 × 837 px** |
| 0 px (mapa em tela cheia — teto teórico) | 11,68 px/m | 1795 px |

**Diga-se com o número na mão: a terceira linha não foi ganho de mapa.** +0,5% de
largura sobre a segunda — invisível. O que a faixa de topo devolveu, as três colunas de
métrica gastaram numa linha de cabeçalho que a versão de barras empilhadas não tinha.

A QUARTA linha é ganho de verdade, e ele não veio de espremer tipografia: veio de mandar
duas das três métricas para o RESULTADO (§3.5) e de tirar da tela os dez textos miúdos
que o §2.1 lista. **+3,6% de largura e +7,2% de área sobre o ponto de partida, com todo
texto que sobrou MAIOR do que era.** É o tipo de ganho que só aparece cortando: enquanto
`tempo de viagem` e `carros parados` dividiam a tarja com a manchete, cada pixel que a
tipografia crescia saía do mapa.

**A tarja FLUTUANTE foi tentada e descartada.** Ela ganhava mais ~40 px de malha
deixando o HUD por cima do canvas com um degradê — e pagava com **texto sobre via
desenhada**, que não se lê nem some. O ganho que sobrou veio de encolher o que é
reservado, não de escondê-lo.

### A alavanca que sobrou não era o HUD nem a rede: era o ENQUADRAMENTO

Com a tarja em 226 px, o mapa ainda era 1427 × 841 px num quadro de 1920 × 854, com
~250 px de preto de cada lado. A conta de por quê:

| | m | formato |
|---|---|---|
| a rede inteira | 153,3 × 90,0 | **1,70:1** |
| os 12 semáforos | 103,3 × 40,0 | 2,58:1 |
| ponta de entrada/saída, em CADA um dos 4 lados | **25,0** | — |

O quadro era 1,70:1 dentro de uma tela de 2,25:1, então ele encaixava pela ALTURA — e
**55% dessa altura era ponta vazia**. Tudo o que é informação (via, carro, fila, farol)
era desenhado na escala que sobrava depois de reservar espaço para rua por onde o carro
só chega e some.

**O enquadramento passou a ser o miolo + 12 m de aproximação** (`MARGEM_M` em
`paint.js`). Doze metros são ~14 vagas de fila em cada entrada, quase o triplo do
`Q_JAM = 5` que já satura a rampa: uma fila que estoure isso está gritando em vermelho
dentro do quadro há muito tempo. O recorte só pode APERTAR — ele é interseccionado com a
geometria de verdade, nunca mostra mais do que existe.

| | antes | agora |
|---|---|---|
| quadro | 153,3 × 90,0 m (1,70:1) | **127,3 × 64,0 m (1,99:1)** |
| escala | 9,24 px/m | **12,92 px/m** |
| malha na tela | 1427 × 841 px | **1920 × 854 px** (sangra nos quatro lados) |
| faixa desenhada | 11,7 px | **13,7 px** |
| carro | 7,1 × 4,7 px · 11,6′ × 7,6′ | **9,9 × 6,0 px · 16,2′ × 9,8′** |
| vaga do SUMO | 8,1 px | **11,3 px** |

**+40% em tudo, e nada disso toca no que o SUMO calcula.** A rede continua a mesma, as
pontas continuam lá, os carros continuam entrando e saindo por elas: o que mudou é onde
a câmera corta. Um carro some no enquadramento, não na simulação — e a régua de bancada
(tecla `I`) publica quantos metros de ponta ficaram fora do quadro em cada lado, para a
foto de auditoria mostrar o que está sendo cortado.

Era esta a alavanca, e não encurtar as pontas na rede (o que mudaria a capacidade de
fila das bordas, ou seja, mudaria o experimento — ver §9.1). Com ela gasta, o teto
passou a ser a própria tela: a malha já sangra nos quatro lados.

### 3.5 O redesenho: derivado do front do maquete

A primeira versão desta tela era funcional e feia. O redesenho tomou por base o front de
projeção que o **maquete** já tinha (`smart-traffic-maquete/dashboard/frontend/
projecao/`) — mesma família (IBM Plex Sans + IBM Plex Mono), mesmo fundo preto, mesma
ideia de HUD sobreposto ao canvas. O que muda é que aqui existe um JOGO: três braços em
vez de dois, um humano ao vivo, contagem regressiva e veredito.

O que mudou, e por quê:

| | antes | agora |
|---|---|---|
| altura reservada | 344 px de tarja **+ 44 px de faixa de topo** | **226 px**, tarja única, **sem faixa de topo** |
| distribuição da tarja | três barras empilhadas de UMA métrica | **coluna de identidade + coluna por métrica**, como a `#solo` da referência |
| métricas na tela de JOGO | 1 (entregues); fila e viagem em corpo miúdo | 1 — e as outras duas mudaram de tela, não de corpo (ver abaixo) |
| métricas no RESULTADO | as mesmas, em corpo maior | **3**, cada uma com rótulo, delta e barra próprios |
| manchete de cada métrica | não existia | **`▲ 6,0%`** com seta, verde/âmbar por direção, em 52′ |
| delta contra a régua | `+8%` por linha, ao lado da barra | porcentagem grande no topo da coluna, `+9 carros` atrás |
| onde mora o cromo do operador | faixa reservada no topo, que o mapa pagava | **atrás da tecla `I`**, com a régua de bancada |
| catálogo de cores | não existia | existiu, e saiu: era o único texto abaixo do piso (§2.1) |
| número da plateia | 76 px (metade da tarja) | 36 px (jogando) · 80 px (resultado) |
| tipografia | Inter / Segoe UI, pilha de sistema | IBM Plex Sans + Mono, **servidas do próprio repo** |
| quadro de recordes | não existia | coluna própria, `GET /api/ranking`, sem a coluna de hora |
| `preparando` / `contagem` | tarja vazia com cabeçalho órfão | tarja some; a contagem ganha a tela |
| `resultado` | outro layout, com a linha quebrada em duas | **a mesma grade**, só que em corpo grande e com as três métricas |

**Por que `tempo de viagem` e `carros parados` saíram da tela de jogo.** Não é economia
de tinta: é que durante a rodada o que está ACONTECENDO é a corrida por carros
entregues, e o resto é análise. Análise é o que a tela de RESULTADO faz — ela é a tarja
em tela cheia, tem 1080 px de altura e o público chega perto dela para fotografar. Na
tela de jogo, as duas colunas custavam duas coisas ao mesmo tempo: a largura que fazia a
barra da manchete ser um terço do que podia ser, e a linha de cabeçalho que segurava a
tarja em 250 px. Com uma coluna só, a barra atravessa a tarja inteira, o número vai a
36 px e a tarja cai para 226.

**As treze cores da auditoria não mudaram.** `scripts/projecao_contraste.py` continua
dando os mesmos degraus (1,62 · 1,64 · 1,61) e zero reprovados a 25 lux. O redesenho
mexeu em tipografia, hierarquia e layout — que é onde estava a feiura —, não na paleta,
que estava resolvida.

### 3.6 O desenho do mapa: luz contida

O mapa foi herdado do front de projeção do maquete e, com ele, a linguagem de **luz
espalhada**: o calor do trânsito é desenhado com halo. São quatro, e vale listar o que
cada um custava nesta rede, porque juntos eram a razão de a malha ler como lente suja e
não como trânsito:

| halo | tamanho | quantos por quadro |
|---|---|---|
| bloom da fila | traço de **1,75× a largura da via**, α 0,30 | um por aproximação carregada — e ele vaza para FORA do asfalto |
| farol | disco de 1,2·w, α 0,45 | **48** (12 cruzamentos × 4 aproximações) |
| pressão no cruzamento | anel + disco de 1,7·r | 12 |
| carro parado | disco de 1,7·D, α 0,20 | um por carro parado — e carro parado anda em FILA, então eles se somam |

Lá isso se defende, e não é descuido: o alvo do maquete é um painel de 300 lm a três
metros, e num projetor fraco o que espalha luz é o que sobrevive ao ambiente. Aqui os
quatro se somavam na mesma região da tela — a linha de parada é exatamente onde a fila
está acesa, onde o farol está e onde os carros estão parados.

**A regra que ficou no lugar: TODA LUZ É CONTIDA.**

* nada é aceso fora do asfalto. A banda da fila é um traço de 0,88 da faixa desenhada,
  com um fio de via de cada lado — é esse fio que diz que a mancha está numa rua;
* o que precisa se separar do fundo se separa por **BORDA**, não por brilho. A barra do
  farol ganhou um traço quase-preto mais largo por baixo (`COL.sigEdge`). Isto não é
  gosto: `farol vermelho sobre a banda` mede **1,12** de contraste (§4.3) — some. O
  preto é o único valor que um projetor consegue pôr abaixo de qualquer fundo, porque
  ele soma luz e nunca subtrai;
* a fila tem **BORDA DE ATAQUE**. A banda é sólida até 88% do alcance e acaba ali, em
  degrau. É o degrau que se acompanha a dois metros — ele anda para trás enquanto a
  fila cresce e volta quando o verde abre. Degradê que morre devagar não se acompanha;
* o pulso caiu de 18% em LARGURA para 4% em ALFA, e só na saturação. Pulsar de tamanho,
  num projetor a 2 m, lê como tremor de foco;
* **a banda é LAVAGEM, não tijolo.** As alfas da rampa baixaram de 0,30–0,95 para
  0,34–0,80. A 0,95 a banda saturada apaga o asfalto embaixo, some com a marcação da
  faixa, e — pior — passa a disputar no olho com a barra do farol fechado, que é o
  outro vermelho da tela e é o que mais importa ler. A 0,80 a via continua aparecendo
  por baixo e o farol volta a ser o único vermelho SÓLIDO. Medido: `farol vermelho
  sobre a banda` subiu de 1,12 para 1,19, e `miolo branco do farol sobre a banda` de
  2,97 para 3,14 (§4.3). As alfas espelham `RAMPA` em `projecao_contraste.py`;
* **a banda começa ATRÁS do farol**, recuada por uma largura de barra. Os dois nascem
  na mesma linha de parada e se encostavam: farol fechado + fila saturada viravam uma
  mancha vermelha só. Não se perde informação — o primeiro carro parado continua
  desenhado ali, e é ele quem ocupa esse pedaço;
* **o piso do alcance é UMA VAGA**, não uma fração da via. Era 10% do comprimento da
  faixa, o que numa quadra de 25 m pintava 30 px de banda para UM carro parado de 8 px.
  Enquanto o sprite era 2,5× maior que a vaga isso passava despercebido; com o carro no
  tamanho certo (§3.3) a banda passou a desmentir os carros que estão dentro dela.

E duas coisas que a limpeza permitiu:

* **cada faixa virou uma fita**, com ~1,2 px de preto entre elas (traço a 0,92 da
  largura). Na largura cheia as faixas se encostam e a avenida vira uma laje lisa de
  60 px em que não dá para ver quantas pistas existem, nem onde acaba um sentido e
  começa o outro;
* **o tracejado passou a ter passo proporcional à faixa desenhada**, não a metros de
  mundo. Em metros ele dava traço de 6,7 px com vão de 4,9 px dentro de uma faixa de
  15 px: quatro pontilhados por avenida, densos a ponto de a via ler como textura
  tremida. Marcação precisa ser ESPARSA para ser marcação;
* **a faixa desenhada encolheu de 15 px para 11,5 px** — e essa mudança é do §3.3, não
  daqui: é ela que devolve ao carro a proporção que ele tem na pista de verdade. Como
  efeito colateral, tudo que é medido em `w` (banda, barra do farol, tracejado) veio
  junto, e a malha inteira ficou mais fina e menos "de brinquedo".

**A pressão no cruzamento SAIU.** Ela somava as filas que chegam em cada junção e
desenhava um anel — e a informação dela já está na tela três vezes: são as próprias
bandas das aproximações, que convergem. Um cruzamento entupido mostra quatro barras
quentes apontando para ele, o que é mais forte e mais legível que um círculo borrado
por cima do asfalto. Foi tentada também como POLÍGONO da junção pintado com a cor da
rampa, e não funcionou: a junção é a coisa mais clara do asfalto (`#708095`, escolhida
assim para se separar da via), e laranja translúcido sobre cinza-azulado claro não dá
laranja, dá rosa-barro.

**A paleta auditada não mudou.** Nenhuma das treze cores de `projecao_contraste.py` saiu
do lugar; o que mudou foi quanta área cada uma cobre, com que alfa e com que borda. O
auditor continua dando zero reprovados a 25 lux, e
`tests/test_a7_contraste.py::test_a_paleta_do_mapa_e_a_do_paint_js` trava as cores do
mapa contra o script: mudou numa, tem de mudar na outra.

O que sobrou de próprio deste repo no `paint.js`, fora o desenho acima:

| | maquete | aqui, e por quê |
|---|---|---|
| pegada do carro | `1,7 × comprimento` (o `/api/network` não exportava `minGap`) | **`length + minGap`** exato, do `/api/rede` |
| velocidade de fluxo livre | constante 11,11 m/s | **vem do `/api/rede`** — em K = 6 são 1,852 m/s, e herdar 11,11 pintaria a frota inteira de "parada" |
| junção | `#637183` (1,37 contra a via na mesa de 1,30 m) | **`#708095`** — o mesmo par cai para 1,26 na imagem de 1,82 m; re-resolvido para 1,45 (§4.4) |
| modo verdade (tecla `V`) | não existe | desenha o retângulo do carro REAL dentro do sprite — a prova visual do exagero do §3.3 |

### 3.7 O quadro de recordes

`MELHORES DA FEIRA`, na direita da tarja: as cinco melhores rodadas HUMANAS do dia, com
carros entregues, a hora, e se aquela pessoa **bateu a rede neural**.

Ele existe porque o placar mostra uma disputa só (você contra a máquina) e a feira tem
outra, que é a que faz a pessoa querer jogar de novo: contra quem jogou antes dela.

**Onde ele mora, e por quê.** Em `feira/jogo/ranking.py`, alimentado pela MESMA
mensagem `placar` do C7 que a tela já recebe — nada novo no contrato, nada novo no
motor. O front lê por `GET /api/ranking`, não por uma mensagem nova no fio: recorde do
dia é assunto de TELA, e o C7 é contrato congelado.

**O que NÃO entra:** rodada não pareada (`pareado: false`) e rodada sem linha do humano.
São os mesmos dois filtros que o resto da tela aplica — um recorde tirado de uma
comparação que não vale é pior que não ter quadro: vira um número que ninguém consegue
bater porque ele nunca aconteceu nas mesmas condições.

**E a coluna "bateu a IA" existe por honestidade.** O quadro ordena por carros
entregues, e carros entregues dependem da SEED: `docs/DIFICULDADE.md` §5 mede de **89 a
146** entregues na mesma política, dependendo da hora de trânsito sorteada. Então o
primeiro lugar do quadro pode ter jogado um cenário mais fácil que o quinto. "Bateu a
IA" compara cada visitante com a rede neural da rodada DELE, e é a única coluna do
quadro que é justa entre seeds. Sem ela, o quadro seria um ranking de sorte com cara de
ranking de habilidade.

O arquivo é `results/feira/ranking.json` (`--ranking ''` desliga), escrito de forma
atômica: uma feira que acaba em Ctrl-C no meio de um `write` não pode deixar o recorde
do dia pela metade.

### 3.8 O delta: por que ele é uma PORCENTAGEM

O placar mostra `+8%` grande e `+9 carros` atrás, e a ordem é essa de propósito.

São o mesmo dado. A campanha do A8 mede, na janela de 120 s e nas 12 seeds held-out,
**RL 124,1 contra timer27 112,5** — que é **+11,6 carros** e **+10,3% de vazão**. Ler
só o absoluto fez o dono do projeto perguntar *"a rede neural só conseguindo entregar 10
carros a mais? esse não é o ganho que você tinha apontado em porcentagem"*. Era o mesmo
ganho: dez carros em dois minutos numa malha de 12 cruzamentos **são** dez por cento.

A porcentagem diz o TAMANHO do efeito; o absoluto o torna auditável. A tela mostra os
dois, com a porcentagem no corpo maior.

**As fontes são servidas daqui, não do Google.** O maquete faz `@import` de
`fonts.googleapis.com`. Numa feira isso é uma aposta: sem rede (ou com rede cativa) a
página cai para a pilha de sistema no meio da apresentação e o layout muda de métrica na
frente do público. `web/fonts/` guarda o subconjunto **latino** das oito faces (237 KB),
servido pelo mesmo `StaticFiles` que serve o resto do front. A pilha de fallback continua
declarada em `--sans`/`--mono`: se um arquivo sumir do disco a página fica feia, não
quebra.

---

## 4. Contraste — **(c) da DoD**

`python scripts/projecao_contraste.py` — portado de
`smart-traffic-maquete/scripts/projecao/contraste.py` (commit `18ea6dd`), que este repo
não pode escrever. O modelo, as funções `lum`/`sobre`/`parede` e os pisos (**BOM = 1,60**,
**LIMITE = 1,30**) vieram de lá sem alteração. O que é novo: o ponto de operação virou
parâmetro, e os elementos do placar entraram na lista.

**O port foi conferido contra a origem**: no ponto de operação do maquete ele reproduz
316 lux de branco e 2,10 de preto vazado, e a coluna da mesa bate número a número com a
saída do script original (`test_o_port_reproduz_o_ponto_de_operacao_do_maquete`).

### 4.1 A paleta foi resolvida, não escolhida

No chão, a 25 lux de ambiente, a dinâmica inteira é 7,19. O placar precisa de quatro
degraus (preto < trilho < TIMER < REDE < VOCÊ), e `7,19^(1/4) = 1,64` — praticamente o
piso BOM. Então as cores saíram da conta, e só depois receberam matiz:

| papel | cor | L | degrau sobre a anterior |
|---|---|---|---|
| fundo | `#000000` | 0,000 | — |
| trilho vazio | `#4e5c6c` | 0,104 | **1,64** |
| barra TIMER FIXO | `#cb7a18` | 0,267 | **1,62** |
| barra REDE NEURAL | `#7fcbfa` | 0,541 | **1,64** |
| barra VOCÊ | `#fafcff` | 0,972 | **1,61** |

**Não há folga.** Qualquer cor "mais bonita" que se aproxime de outra reprova no script.

### 4.2 Os sobrepostos são escuros — e isso é uma regra, não um estilo

Ticks da escala, a régua do timer e a moldura do vencedor cruzam fundos de luminância
qualquer (o trilho, a barra âmbar, a barra branca). **Um projetor não consegue ir abaixo
do próprio preto**, então o preto é o único valor garantidamente mais baixo que tudo que
está embaixo. Um tick claro que funciona sobre o trilho some sobre a barra do VOCÊ; um
tick com a luminância certa para separar do trilho vira, ele mesmo, uma barra.

Por isso: ticks `#060a10`, régua = núcleo âmbar entre **dois flancos escuros**, vencedor
marcado por **moldura escura por dentro + contorno verde por fora + texto**, nunca por
cor de barra (medido: qualquer realce sobre a barra do VOCÊ fica em 1,1 — não existe cor
acima do branco).

**E quem perde não é escurecido.** A primeira versão baixava a opacidade dos perdedores
para 0,78 na tela de RESULTADO. Isso quebra a escada inteira: com a REDE atenuada a
L = 0,42 contra um TIMER cheio em L = 0,267, a razão entre as duas cai para **1,36**
(abaixo do piso) e a **ordem de brilho pode inverter** — se quem vence for o TIMER, que
é a barra mais escura por construção, o perdedor atenuado ainda fica mais claro que o
vencedor. Escurecer o perdedor é editar, por estilo, um contraste que foi resolvido por
conta. Quem perdeu já está dito pela barra menor e pelo selo de colocação.

### 4.3 O resultado (montagem `chao`, aceite em 25 lux)

    reprovados em 25 lux (fora os assumidos): 0
    TETO DE AMBIENTE: elementos do A7 aguentam até 53 lux;
                      com o mapa herdado junto, 46 lux.

| par crítico (elementos NOVOS) | amb 25 | amb 90 |
|---|---|---|
| trilho vazio sobre o preto | 1,64 | 1,18 ✗ |
| barra TIMER sobre o trilho | 1,62 | 1,24 ✗ |
| barra REDE sobre a barra TIMER | 1,64 | 1,33 ! |
| barra VOCÊ sobre a barra REDE | 1,61 | 1,39 ! |
| barra VOCÊ sobre o trilho | 4,27 | 2,30 |
| tick escuro sobre o trilho | 1,61 | 1,18 ✗ |
| tick escuro sobre a barra VOCÊ | 6,89 | 2,71 |
| régua: flanco escuro sobre o trilho | 1,61 | 1,18 ✗ |
| régua: núcleo âmbar sobre o flanco | 5,40 | 2,28 |
| vencedor: moldura escura sobre a barra VOCÊ | 6,89 | 2,71 |
| número do placar sobre o preto | 7,19 | 2,77 |
| rótulo secundário sobre o preto | 4,85 | 2,10 |
| denúncia: faixa de alerta sobre o preto | 2,59 | 1,45 ! |
| denúncia: núcleo branco sobre o alerta | 2,78 | 1,91 |

**Todos os elementos novos ficam em BOM (≥ 1,60) a 25 lux** — não só em LIMITE. É o que
`test_os_elementos_novos_ficam_acima_de_BOM_no_chao` guarda.

**A coluna de 90 lux é o achado desconfortável**: com a sala acesa, a imagem de 1,82 m
não funciona — e não é a paleta, é o meio. A 90 lux até a via herdada mede 1,17 contra o
fundo. O número operacional é o **teto de 46 lux** (com o mapa herdado junto). Acima
dele, as opções são apagar luz, aproximar a torre (imagem menor = mais lux por m²), ou
um projetor com mais fluxo.

### 4.4 Uma cor herdada foi reajustada

O `#637183` da **junção** media 1,37 contra a via na mesa de 1,30 m — aceito no maquete.
Na imagem de 1,82 m o mesmo par cai para **1,26**, abaixo do piso, *só* por causa do
ponto de operação. Foi re-resolvido para `#708095` (1,45), preservando o matiz e a
intenção original. Guardado por `test_a_juncao_foi_reajustada_para_o_ponto_de_operacao_do_chao`.

Dois pares herdados continuam abaixo do piso e estão marcados como **assumidos**, com o
motivo que a origem já tinha escrito: *carro andando vs carro parado* (1,17) e *farol
vermelho sobre a banda* (1,12). Nos dois, quem entrega a leitura é outra coisa — a banda
quente embaixo do carro, e o miolo branco do farol (2,97).

### 4.5 A paleta não pode divergir

O script e o front carregam a mesma paleta em dois arquivos. Duas cópias divergem — já
divergiram neste projeto —, e auditar uma paleta que não está na tela não audita nada.
`test_a_paleta_do_script_e_a_do_css` e `test_a_paleta_do_mapa_e_a_do_paint_js` comparam
`scripts/projecao_contraste.py` com `web/css/projecao.css` e `web/js/paint.js`, cor a cor.

---

## 5. Desempenho — **(b) da DoD**, e como foi medido

A DoD pede "180+ carros a 1 Hz sem perder frame no notebook da feira". São **dois**
gargalos diferentes e eles não se medem do mesmo jeito, então foram medidos separados.

### 5.1 Transporte — jogo → servidor → WebSocket → cliente

`python scripts/projecao_bench.py --transporte --carros 250 --segundos 120 --clientes 3`

Um produtor sintetiza frames com 250 veículos a 1 Hz exato (o `frame_wire` do C7, mesmo
formato que a Arena produz) e três clientes WebSocket contam o que chega.

| | |
|---|---|
| frame com 250 carros | **20 389 bytes** |
| frames publicados | 120 |
| recebidos por cliente | **120 / 120 / 120** |
| **buracos no `t` simulado** | **0 / 0 / 0** |
| descartados no servidor | **0** |
| clientes derrubados | **0** |
| custo de publicar, no caminho do jogo | **p50 0,170 ms · máx 1,31 ms** |
| atraso ponta a ponta | p50 4,7–9,0 ms · máx 57–293 ms |

O **custo de publicar** é o número que prova a passividade: é o tempo que a rodada paga
por chamar `publicador(...)`. 0,17 ms mediana contra um sim-step de 1 000 ms é 0,017%.

### 5.2 O mesmo, numa rodada de verdade

`python scripts/projecao_servidor.py --auto --rodadas 1` — a rodada da feira inteira,
seed 100, `aberta.maquete`, janela de 120 s em ritmo **1:1**, com **216 veículos ativos**
no fim (acima dos 180 da DoD), publicando pelo caminho de verdade (`publicador` do motor
+ `ArenaPublicada`):

    rodada 1: seed=100 humano=38 vencedor=timer
    projeção: 245 mensagens · 0 descartadas
              custo de publicar  p50 0,113 · p95 0,258 · p99 0,289 · máx 0,351 ms
              (o máximo caiu na chamada 187 de 245)

**0,113 ms de mediana contra um sim-step de 1 000 ms: 0,011%.** O pior caso da rodada
inteira foi 0,351 ms. É este o número que prova a propriedade "a projeção é observador
passivo" — não uma afirmação de arquitetura, o tempo que a rodada de fato pagou.

**Um caso de estresse, e um outlier que ficou sem explicação.** A mesma rodada com
`--rapido` (a janela de 120 s em ~12 s, ou seja publicando a ~20 Hz em vez de 1 Hz)
também não descartou nada, mas registrou um pior caso de **16,1 ms** numa única
publicação — 46× o pior caso do regime 1:1. O instrumento agora grava p50/p95/p99/máx e
em qual chamada o máximo caiu, exatamente para isso não virar anedota; a explicação
provável é escalonamento (o treino do A6 estava ocupando os 16 núcleos), mas **não foi
isolada**. Mesmo assim: 16 ms contra 1 000 ms de sim-step é 1,6% de um passo, e nem
naquele regime houve descarte.

### 5.2b E se fosse pygame em vez de navegador?

A pergunta apareceu junto com o redesenho e a resposta é **não**, com número.

**O render não é o gargalo, e não é nem perto.** O §5.3 mede 59,9 fps de mediana com
**250 carros** em rasterização por SOFTWARE (SwiftShader — o piso pessimista, sem GPU),
com **zero** quadros de dado perdidos. O dado chega a **1 Hz**; o desenho roda a 60. São
sessenta quadros de folga entre dois dados. Trocar o renderizador para ganhar desempenho
é otimizar o que já sobra.

**pygame não elimina o transporte, que é o que parece prometer.** `traci` é uma conexão
de MÓDULO: duas Arenas no mesmo processo brigam pela sessão. É por isso que o feed ocioso
já roda em dois subprocessos e o prefetch dos fantasmas também. Uma tela em pygame
continuaria precisando de IPC entre os processos de SUMO e o display — ela troca
WebSocket por outra coisa, não tira a camada. E o transporte custa **0,113 ms de mediana**
no caminho do jogo (§5.2), 0,011% de um sim-step: não há o que economizar ali.

**O que se perderia é caro e já está testado.** ~2.200 linhas de front (renderizador,
máquina de estados das cinco fases, placar, interpolação) e onze testes que rodam em
Node. Mais o que o navegador dá de graça e em pygame é trabalho manual: quebra de linha,
`tabular-nums`, letterspacing, a escala `--u` por regra de CSS, o `localStorage` dos
ajustes do operador, e tela cheia pelo próprio sistema.

**E uma propriedade de feira que se perderia junto:** hoje a projeção SOBREVIVE à morte
do processo do jogo — cai em modo degradado, continua desenhando o último quadro e
reconecta sozinha (§6). Com o display no mesmo processo do jogo, um `traci` que cai leva
a tela junto, na frente do público.

**O que pygame de fato compraria:** um processo pesado a menos no notebook da feira, e
controle de pixel sem o fator de escala do Windows atravessar (foi o que reduziu a
corrida com GPU do §5.3 a 1604×825). O segundo resolve-se com
`--force-device-scale-factor=1`; o primeiro é conforto, não requisito — o render aguentou
60 fps com sete processos de SUMO do treino disputando os 16 núcleos.

**A condição que inverteria a decisão:** o notebook da feira medir, no `?bench=250`,
quadro de dado perdido (buraco no `t`) — não p95 ruim, **perda**. Aí o gargalo seria o
render, e a conversa muda. Enquanto o número for zero, é reescrever o que funciona.

### 5.3 Render — o custo de desenhar

`python scripts/projecao_bench.py --render --carros N`. A página real roda `?bench=N`, que
sintetiza N carros andando na rede de verdade e empurra um frame por segundo pelo **mesmo
caminho** de um frame do WebSocket. A página mede o tempo de quadro e devolve o resultado
por `POST /api/bench` — assim o número sai do navegador sem ninguém transcrever da tela.

| corrida | palco | carros | fps p50 | quadro p95 | quadro máx | **buracos no `t`** |
|---|---|---|---|---|---|---|
| Chrome headless (software) | 1904×985 | 180 | **59,9** | 16,8 ms | 33,3 ms | **0** |
| Chrome headless (software) | 1904×985 | 250 | **59,9** | 33,3 ms | 33,4 ms | **0** |
| Chrome com GPU, nesta máquina | 1604×825 | 250 | **56,5** | 33,3 ms | 33,4 ms | **0** |

Com **180 carros** — o alvo da DoD — 95% dos quadros saem dentro de um v-sync (16,8 ms):
o render nem chega perto de ser o gargalo. Com 250 carros o p95 dobra para 33,3 ms, ou
seja, 5% a 50% dos quadros gastam **dois** intervalos de v-sync. A 1 Hz de dado isso não
perde informação nenhuma — só tira suavidade da interpolação.

**O p95 é bimodal, e é contenção.** Três corridas idênticas (180 carros, 20–25 s) na
mesma sessão deram p95 = **33,2 · 33,3 · 16,7 ms**, com `fps_p50` fixo em 59,9 e **zero
buracos no `t` nas três**. O p95 salta entre um e dois v-syncs conforme o escalonador —
com sete processos de SUMO do treino do A6 disputando os 16 núcleos, é o esperado. O que
NÃO se mexe entre corridas é o que a DoD cobra (quadro de dado perdido: zero) e a
mediana. Se o número do notebook da feira sair pior que estes, a primeira coisa a
conferir é o que mais está rodando na máquina.

**Zero quadros de dado perdidos em todas as corridas.** "Perder quadro", aqui, é o que a
DoD cobra: um buraco no `t` simulado, contado como `Δt/passo − 1` na chegada de cada
frame — e o front conta isso sozinho, por braço, na régua de bancada.

> **O que ainda falta para fechar (b) do jeito que ela está escrita.** As três corridas
> acima são **nesta máquina**, não no notebook da feira. O headless usa rasterização por
> software (SwiftShader) e é piso pessimista; a corrida com GPU foi numa janela de
> 1604×825 por causa do fator de escala do Windows, não em 1920×1080 cheios. **O número
> que vale é o do notebook da feira**, e ele se obtém em trinta segundos: abrir
> `http://127.0.0.1:8080/?bench=250&diag=1` naquele notebook, com o projetor ligado, e
> ler a caixa verde (ou `GET /api/bench`).

---

## 6. Modo degradado — **(d) da DoD**

A queda que importa é a **silenciosa**: o motor não avisa que morreu, ele simplesmente
para de chamar o `publicador`. Nada no protocolo diz "acabou" — então quem percebe é o
relógio.

### 6.1 Rédea por fase

Uma rédea única não serve, e isso é medido, não estético:

| fase | rédea | por quê |
|---|---|---|
| `contagem` | **2,0 s** | publica 3·2·1 a 1 Hz |
| `jogando` | **2,0 s** | publica um placar por sim-step (1 Hz) |
| `preparando` | 25 s | fica legitimamente mudo até **9,1 s** calculando o fantasma da RL sem cache (JOGO.md §2), mais o boot do SUMO e os 300 s de aquecimento |
| `resultado` | 20 s | publica **uma** vez e o motor dorme 8 s |
| `ocioso` | — | não publica nada; nunca arma |

Armar 2 s em `preparando` produziria uma "queda" falsa **em toda rodada**.

### 6.2 Dois vigias

O do **servidor** (`feira/jogo/web.py`) pega o motor morto. O do **front**
(`web/js/projecao.js`, 2,5 s) pega o servidor inteiro morto — sem ele, "o jogo caiu" e "a
rede caiu" teriam desfechos diferentes na tela, e para a plateia é a mesma coisa.

### 6.3 O número

`tests/test_a7_degradado.py::test_queda_do_jogo_volta_para_ocioso_em_menos_de_3s` mede o
relógio de parede entre a **última publicação do motor** e o `ocioso` chegando no
cliente WebSocket:

    [DoD d] queda do jogo -> ocioso no cliente em 2.19 s (teto 3.0 s)

Pior caso teórico: rédea 2,0 s + tique do vigia 0,25 s = 2,25 s.

O placar degradado vai **sem linhas**. Desenhar barra com número que ninguém mediu é
mentir na frente do público — e é justamente o que a projeção antiga fazia.

### 6.4 O veredito tem QUATRO estados, e `vencedor: null` juntava dois opostos

Este era o defeito nº 3 que eu tinha reportado, e o coordenador achou que ele era pior
do que eu tinha descrito — estava certo. `vencedor: null` significava, ao mesmo tempo:

* **empate** — resultado legítimo, e o visitante empatou com a máquina; e
* **rodada não pareada** — os braços partiram de estados diferentes em t0, o
  `ControladorSelado` pegou a divergência, e **a comparação inteira não vale**.

O motor já sabia a diferença e escrevia o texto em `ResultadoRodada.motivo`; ele
simplesmente não viajava no fio. A tela mostrava os dois casos idênticos. O C7 ganhou
`motivo: str` e `pareado: bool`, e a decisão virou `veredito()` em `web/js/placar.js` —
uma função pura, que é o que o teste prova:

| o que chega no fio | estado | a tela |
|---|---|---|
| `pareado: false` | `nao_pareada` | **denúncia em tela cheia**, com o `motivo`. Sem coroa, **sem colocação**, sem régua. O placar sai da tela. |
| `vencedor: "x"` | `vencedor` | coroa `x`: moldura, contorno verde e o texto do veredito |
| sem linha do humano | `sem_placar` | "RODADA NÃO CONCLUÍDA" em vermelho + o `motivo` (abortada, ou o SUMO caiu) |
| resto (humano presente, topo compartilhado) | `empate` | "EMPATE", em cor neutra |

**Por que "sem colocação" e não só "sem vencedor".** Colocação, régua e coroa são as
três a mesma afirmação: *este braço está à frente daquele*. Se os braços não partiram
do mesmo estado, essa afirmação não se sustenta para o primeiro lugar nem para o
segundo. Mostrar "2º REDE NEURAL" numa rodada não pareada seria trocar uma mentira
grande por uma menor. Então `compara: false` desliga as três de uma vez, e o selo de
colocação vira `—`.

**Duas coisas que eu resolvi diferente do enunciado, com motivo.** O coordenador pediu
"`pareado === true` e `vencedor === null` ⇒ empate". Isso é verdade *quase* sempre: uma
rodada **abortada** e uma em que o **SUMO caiu** também chegam pareadas e sem vencedor,
e chamá-las de empate daria ao visitante um resultado que ele não fez. As duas se
distinguem no próprio fio, sem campo novo: **rodada que não aconteceu não tem linha do
humano**. Daí o quarto estado. E o `motivo` não vazio, sozinho, **não** invalida nada —
"modo degradado: sem fantasma de rl" é uma rodada boa com dois braços, e ela coroa
normalmente.

**Onde o `motivo` aparece, e onde não aparece duas vezes.** Ele tem três lugares
possíveis — a denúncia em tela cheia, a linha sob o veredito e a tarja do operador — e
a regra é: quem está mais perto do olho do público ganha, a tarja é a última opção.
Nas fases que não são `resultado`, `motivo` é o modo degradado do JOGO.md §5, e agora a
tarja mostra **o texto do motor** em vez do que o servidor infere pelo relógio: "sem
fantasma de rl" diz o que quebrou; "sem publicação há 2,3 s" só diz que alguém calou.

Contraste dos textos novos, no chão a 25 lux: EMPATE **4,85**, RODADA NÃO CONCLUÍDA
**2,59**, motivo sob o veredito **4,85**, motivo na denúncia **7,19** — todos acima de
BOM. `python scripts/projecao_telas.py --denuncia` gera a foto dos quatro desfechos.

A denúncia é sobre **uma** rodada: ao sair da fase `resultado` ela some junto, senão a
tela ociosa da rodada seguinte abriria acusando a anterior.

---

## 7. A janela que denuncia

A `Chave`/`janela` viaja no frame (C7) porque a projeção antiga comparava contadores de
**simulações derivadas**. Se dois braços chegarem com janelas diferentes, esta tela
**tira o placar** e mostra a denúncia, com as janelas discordantes escritas.

A conta é feita **duas vezes, independentes**: `EstadoProjecao.divergencia()` no servidor
(testável, e é o que o `/api/estado` publica) e no próprio front, que compara as janelas
dos frames de cada braço com a do placar. Não é redundância decorativa: o servidor pode
estar certo e o cliente ter ficado com um frame velho de outra rodada.

`python scripts/projecao_telas.py --denuncia` gera a foto dessa tela.

---

## 8. Arquitetura, em uma passada

    motor (thread principal)                     servidor (thread daemon)
    ─────────────────────────                    ────────────────────────
    MotorDoJogo._publica ──► publicador(dict) ──► fila limitada (512) ──► asyncio loop
                                  │                                            │
    ArenaSumo.roda(observador) ◄──┤ ArenaPublicada encadeia o observador        ▼
                                  │                                    difusor paralelo
                                  └► pub.frame(Frame) ──► frame_wire ──►      │
                                                                              ▼
                                                                      WebSocket /ws
                                                                              │
                                                       web/index.html ◄───────┘

Quatro decisões que sustentam a passividade:

1. `publicador(...)` só faz `put_nowait` numa fila **limitada** e um
   `call_soon_threadsafe` para acordar o laço. Fila cheia **descarta o mais velho** e
   conta — o público quer o placar de agora, não a reprise do que perdeu;
2. o difusor manda para todos os clientes **em paralelo**, com `wait_for(send, 1,0 s)`.
   Cliente lento cai do broadcast em vez de segurar os outros;
3. o servidor vive numa **thread daemon**. Se ele morrer, o motor não fica sabendo;
4. `ArenaPublicada` publica **antes** de chamar o observador de dentro — o `_observa` do
   motor dorme até o deadline do `Marcapasso` (~1 s), e publicar depois dele entregaria
   o quadro um segundo velho.

### O feed da tela ociosa

`ocioso` mostra a RL rodando ao vivo com o timer de régua: são **duas** simulações, e
`traci` é uma conexão de módulo — duas Arenas no mesmo processo brigam pela sessão (o
mesmo motivo do prefetch dos fantasmas rodar em subprocesso). Por isso o feed é outro
processo, entrando por `ws://.../ingest`:

    python scripts/projecao_servidor.py --so-servidor
    python scripts/projecao_ocioso.py --braco rl
    python scripts/projecao_ocioso.py --braco timer

Os dois **precisam** da mesma seed e da mesma janela. Se não tiverem, a tela denuncia —
que é o comportamento correto.

---

## 9. O que ficou aberto, e o que foi reportado

### 9.1 Aberto (decisão do dono)

* **(a) da DoD não fecha comigo.** Está entregue o proxy (§2.1) e a lista de bancada
  (§2.2). A foto do projetor é do dono.
* **(b) medido nesta máquina, não no notebook da feira** (§5.3). O caminho para fechar
  está escrito e leva trinta segundos naquele notebook.
* **Nenhum número deste documento foi calibrado contra a colocação de hoje.** A escala
  da barra sai de quem lidera, a paleta sai da dinâmica da imagem, e o sprite sai da
  pegada do SUMO — nenhum dos três olha para qual braço está ganhando. Os testes rodam
  os casos "RL em primeiro", "RL em último" e "empate" de propósito.
* **O ponto óptico do projetor nunca foi medido** (§1). Se o aparelho real não for
  300 lm / TR 1,10, o teto de ambiente do §4.3 muda.
* **A tela `ocioso` exige dois processos extras de SUMO.** O TRANSPORTE do feed está
  exercitado e guardado (`test_o_feed_do_ocioso_entra_pelo_ingest` percorre
  `Remetente` -> `/ingest` -> estado do servidor, com a janela viajando junto), mas o
  lado SUMO — dois braços ao vivo a 1:1 **junto** com uma rodada acontecendo — nunca
  rodou. Com 16 núcleos deve caber; é ensaio de bancada, não de agente.

### 9.2 Reportado ao coordenador (não consertado aqui)

1. **O motor não expõe gancho de frame.** `MotorDoJogo` consome o `observador` da Arena
   para si (é ali que mede a cadência e atende o ABORTAR) e só publica `Placar`. Sem um
   gancho, a projeção não teria os carros do braço humano durante a rodada. Contornado
   com `ArenaPublicada`, um decorador de `Arena` (C4) passado no `arena=` do construtor —
   funciona e não toca em contrato, mas o lugar natural disso é um
   `MotorDoJogo(ao_quadro=...)` ao lado do `publicador`.
2. ~~**O C7 mistura `tipo` e `type`.**~~ **FECHADO pelo coordenador:** `Placar.json()`
   agora emite `type` junto de `tipo`, com o mesmo valor. O despacho por
   `m.tipo || m.type` do front continua correto — só deixou de ser obrigatório.
3. ~~**O `Placar` não carrega o motivo do degradado.**~~ **FECHADO pelo coordenador, e
   era pior do que eu tinha descrito:** faltava também separar empate de rodada não
   pareada. O C7 ganhou `motivo: str` e `pareado: bool`; o front consome os dois no
   §6.4.
4. **`Placar` não diz qual seed vem a seguir.** A tela `ocioso` gostaria de anunciar
   ("próxima: seed 101"); hoje só o motor sabe.
5. **`frame_wire` levanta em braço desconhecido.** Correto como contrato, mas o nome do
   controlador é `familia:variante` (`humano:teclado`), então quem espelha frames
   precisa normalizar antes. A normalização mora em `braco_do_controlador()`; se um dia
   o contrato quiser expô-la, o lugar é o C7.

### 9.3 Onde eu discordo

* **A DoD (a) não é verificável por nenhum agente, e isso devia estar no plano.** "Legível
  a 2 m, em foto do projetor real" é um critério de aceitação do dono, não do agente. O
  que dá para exigir de quem escreve o código é o proxy e a lista de conferência — foi o
  que está aqui. Sugiro que o `PROXIMOS_PASSOS.md` separe DoDs "do agente" e "do dono".
* **A montagem no chão a 1,82 m está no limite do projetor.** A 25 lux funciona com zero
  folga (todo degrau em 1,61–1,64 contra um piso de 1,60); a 46 lux já não funciona. Uma
  torre mais baixa, ou o projetor mais perto do chão, comprariam margem de brilho
  proporcional ao quadrado. Medido com o próprio script: encolher a imagem de 1,82 m para
  **1,45 m** leva o branco de 161 para 254 lux (+57%) e o teto de ambiente de **46 para
  72 lux** — de "sala escura obrigatória" para "sala com uma luz acesa". O custo é o
  sprite do carro, que encolhe na mesma proporção. **Recomendo medir o fluxo real antes
  de fixar a altura da torre**, e decidir a altura por esta troca, não por marcenaria.
* **As secundárias (fila, tempo de viagem) na tela de JOGO são o item mais frágil.**
  Ficam em 28′, logo acima do piso, e disputam pixel com o mapa. Se a foto de bancada
  reprovar, minha recomendação é **tirá-las da tela de jogo** e deixá-las só no
  RESULTADO — a manchete é `entregues`, e é ela que precisa estar grande enquanto a
  rodada corre.
