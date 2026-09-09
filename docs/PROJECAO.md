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
| `ocioso` | **a RL ao vivo**, tela cheia | duas barras (RL e timer) vindas dos `stats` do frame — no ocioso o motor não publica `placar` | o convite, numa tarja preta encostada no placar |
| `preparando` | congelado sob um véu de 76% | vazio (é o que o motor publica: `linhas: []`) | "PREPARANDO A RODADA" + o pulso dos três pontos |
| `contagem` | congelado sob o mesmo véu | vazio | o **3 · 2 · 1** a 422′ de arco |
| `jogando` | o braço **humano**, ao vivo | as três barras + a régua do timer + o relógio | o mapa em cima, o placar embaixo |
| `resultado` | **desligado** (a comparação é a mensagem, e mapa parado só joga luz de graça) | as três linhas do `Resultado` (C5), em corpo maior | o veredito, num dos quatro estados do §6.4 |

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
| contagem 3·2·1 | 360 px | 259 px | 245,4 | **422′** (7,0°) |
| número do placar (jogando) | 76 px | 55 px | 51,8 | **89′** |
| número do placar (resultado) | 104 px | 75 px | 70,9 | **122′** |
| título das telas de fase | 68 px | 49 px | 46,4 | **80′** |
| veredito (VOCÊ VENCEU) | 46 px | 33 px | 31,4 | **54′** |
| convite (APERTE O BOTÃO) | 40 px | 29 px | 27,3 | **47′** |
| rótulo do braço | 34 px | 24 px | 23,2 | **40′** |
| secundárias (fila, viagem) | 24 px | 17 px | 16,4 | **28′** |
| selo "pré-computado" / "ao vivo" | 19 px | 14 px | 13,0 | **22′** |
| cromo do operador (chave, seed) | 18 px | 13 px | 12,3 | **21′** |

Cap-height = 0,72 × corpo, a proporção da família em uso (Inter / Segoe UI).

**Todo elemento da plateia fica em 22′ ou mais**, e só dois encostam nesse piso: as
secundárias (28′) e o selo "pré-computado"/"ao vivo" (22′). O selo estava em 15 px, ou
17,6′, e subiu para 19 px justamente por causa desta tabela — ele diz que os adversários
são fantasmas, e isso é informação de honestidade, não cromo. O único elemento abaixo do
piso é o cromo do operador, em 21′, e é deliberado: cenário, seed e sha da demanda não
são para a plateia, são para quem opera e para a foto de auditoria.

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
3. **A régua.** `I` liga o diagnóstico. Fotografe. Confira que `mm/px` bate com o item 2
   e que a linha do sprite diz **"o sprite NÃO passa da pegada"**.
4. **A 2 m, de pé.** Fique a 2 m da borda da imagem, na altura dos olhos de um visitante.
   Sem se abaixar, leia: (a) os três números do placar; (b) os três rótulos; (c) quem
   está na frente. Se qualquer um exigir aproximar, aumente o texto com `.` e repita.
5. **As secundárias.** Ainda a 2 m, leia "fila" e "viagem". Elas são o item de fronteira
   (28′): se falharem, a decisão é do dono — ou o texto sobe (e o mapa encolhe), ou as
   secundárias saem da tela de jogo e ficam só no RESULTADO.
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

### 3.2 A regra herdada não serve aqui — e o número diz por quê

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
que garantia a honestidade — **nunca seria desenhada**. Carros parados passariam a se
sobrepor 3 para 1, e a fila viraria um borrão de comprimento certo e densidade errada.

Isto **não é defeito do maquete**. Lá a rede é outra e a desigualdade tem o sinal
contrário: o sprite fica *mais curto* que a pegada, e o rastro é exatamente o conserto
disso. O que muda aqui é o lado da desigualdade, e o conserto tem que valer para os dois.
(Mesmo com o mapa em tela cheia, sem placar nenhum, a regra herdada ainda daria 2,02× a
pegada — não é uma questão de sobrar espaço.)

### 3.3 A regra adotada

> **A extensão longitudinal desenhada É a pegada do SUMO. Sempre.**
>
>     corpo sólido = min(comprimento · mult, pegada)
>     rastro       = pegada − corpo            (translúcido, só em quem está parando)
>     largura      = min(largura · mult, corpo · 0,72)
>
> com `mult` = o mesmo exagero transversal com que a **via** já é desenhada.

Consequências, medidas (`tests/test_a7_front.py`, harness em Node; a tecla `I` mostra os
mesmos números na tela que está projetando):

| 1080p, fase `jogando` | px | mm no chão | arcmin @2 m |
|---|---|---|---|
| carro **real** | 4,22 × 1,69 | 4,00 × 1,60 | 6,9′ × 2,7′ |
| **pegada** (= extensão desenhada) | 6,33 | 6,00 | **10,3′** |
| **sprite** (corpo × largura) | 6,33 × 4,56 | 6,00 × 4,32 | **10,3′ × 7,4′** |
| faixa desenhada | 14,37 (real 3,84) | — | — |

    exagero de comprimento  ×1,50      exagero de largura  ×2,70      área  ×4,06

A 720p os fatores são os mesmos (×1,50 e ×2,81) e o sprite dá 9,8′ × 7,3′ — a escala
tipográfica `--u` e o exagero da via mantêm o tamanho FÍSICO praticamente igual entre
as duas resoluções, que é o que se quer num projetor.

Por que isso continua honesto, item a item:

* **comprimento**: nunca passa do espaço reservado, então a fila desenhada tem o mesmo
  comprimento *e* a mesma contagem que a fila simulada. Carros parados encostam,
  nunca se sobrepõem;
* **largura**: exagerada pelo **mesmo fator com que a via já é exagerada**. A razão
  carro/faixa **desenhada** dá 0,32, *abaixo* dos 0,44 reais — o carro não invade
  lateralmente mais do que já invade na realidade. O teste
  `test_o_sprite_nunca_passa_da_pegada_do_sumo` guarda essa desigualdade em cinco
  layouts, de 720p a 4K;
* **posições**: são as do SUMO, sem toque. O que se exagera é o tamanho do desenho,
  nunca onde ele está.

E há o **modo verdade** (tecla `V`): desenha o retângulo do carro real, na escala real,
dentro do sprite. É a prova visual do exagero, para a foto de bancada.

### 3.4 O que isso custa, e a escolha que ficou

10,3′ × 7,4′ é **pequeno**. A 2 m, um carro individual está no limite do que se resolve.
Poderia ser esticado — e não foi, porque esticar não resolveria: só faria os carros
parados se sobreporem.

A alternativa honesta é dar mais tela ao mapa, e ela tem preço conhecido. Com o mapa em
**tela cheia** (sem placar), a escala sobe para 11,68 px/m e a pegada vira **10,22 px =
9,67 mm = 16,6′** — 61% maior. Ou seja: **a tarja do placar custa ao carro 38% do
tamanho angular dele**. É uma troca real, e a escolha é a do C7: `entregues` é a
manchete, e a manchete precisa estar grande *enquanto a rodada corre*.

Então a leitura de longe é a **banda da fila** (que cresce e encolhe, com 1,6 a 2,4 de
contraste) e o **placar**; o carro individual é para quem chega perto. É a mesma
doutrina que o maquete já tinha escrito: *"a três metros, 'parado' se lê pelo que está
embaixo do carro, não pela cor dele"*.

Um piso mecânico de 3 px existe só para o sprite não sumir numa janela minúscula. Quando
ele morde, `Board.spriteExcede` fica `true` e a régua de bancada denuncia o excesso —
não há caso silencioso. Nas resoluções de feira (720p e 1080p) ele **não** morde.

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
