# Calibração do cenário `aberta.maquete`

Agente A1, Onda 1. Tudo aqui é MEDIDO — inclusive o que não deu certo. Dados
brutos versionados em [`sumo/aberta/calibracao/*.json`](../sumo/aberta/calibracao);
agregador em [`sumo/aberta/analisa.py`](../sumo/aberta/analisa.py).

> **TL;DR — o resultado desconfortável.** A rede aberta congestiona e trava (o
> risco 1 do plano **não** se materializou), mas **não existe patamar estável em
> 45–55% de veículos parados**. O piso de fluxo livre desta rede já é 38%
> parados — é o custo do próprio semáforo, não do trânsito — e a faixa 45–55% só
> aparece **acima** da capacidade, onde a malha está enchendo até travar.
> Ponto de operação entregue: **3500 veh/h → 158 carros ativos, 37,9% parados,
> 20,1 km/h equivalentes**, estável nas 6 seeds por **7200 s** (o dobro da janela
> de avaliação). Ver §3.5 e §7.

---

## 1. O que foi construído

| artefato | quem gera |
|---|---|
| `sumo/aberta/network/maquete_aberta.net.xml` | `sumo/aberta/build_rede_aberta.py` |
| `sumo/aberta/config/maquete_aberta.sumocfg` + `.view.xml` | idem |
| `sumo/aberta/demanda/maquete_aberta.add.xml` (vType) | idem |
| `sumo/aberta/demanda/demanda_s{seed}.rou.xml` + manifesto | `python -m feira.demanda` |

Fontes canônicas (escala real, no repo do maquete) **não foram tocadas**:
`nodes_loop.nod.xml`, `edges_loop.edg.xml`, `connections_loop.con.xml`,
`types.typ.xml`.

### 1.1 A rede — DoD (a) e (b)

`netconvert` **sem nenhum warning**. Contagens conferidas por dois caminhos
independentes: leitura direta do `.net.xml` e `sim.environment.net_topology`
apontado para a rede nova (é o mesmo objeto que a política e a Arena consomem).

| | rede fechada de hoje (`maquete`) | **rede aberta** |
|---|---|---|
| semáforos | 10 | **12** |
| controláveis (≥2 fases verdes) | 6 | **12** |
| aproximações não classificadas | 0 | **0** |
| fontes / sorvedouros | 0 / 0 | **9 / 9** |
| edges normais | 22 | 40 (22 internos + 18 cotos) |

Os 6 semáforos que voltaram a ser controláveis:

- **H1V4, H3V4** — eram junções de prioridade com U-turn interno (o `ret_*` que
  `scale_to_maquete.py` transformou em curva, porque o carrinho físico não podia
  parar ali). Sem retorno, voltam a ser `traffic_light`;
- **H1V1, H1V3, H3V1, H3V2** — eram términos de corredor com **uma aproximação
  só**, logo uma fase verde só e "switch" no-op. O coto de borda dá a segunda
  aproximação.

Os 9 corredores de mão única (H1, H2E, H2W, H3, V1, V2, V3, V4S, V4N) rendem
exatamente 9 cotos de entrada e 9 de saída — contados no `.net.xml`, não supostos:
fonte = edge normal sem `getIncoming()`, sorvedouro = sem `getOutgoing()`.

### 1.2 Similitude (`x'=x/6, v'=v/6, a'=a/6, t'=t`)

Verificada contra a rede `real` (escala 1:1) faixa a faixa, nas 50 faixas normais
que as duas têm em comum: **erro mediano de tempo de travessia 0,94%**, pior faixa
6,3% (as duas quadras curtas da V1 — o `netconvert` apara o edge no raio da junção,
e na rede aberta H1V1/H3V1 ganharam aproximações, logo raio um pouco diferente). O
desvio é de geometria de junção, não de escala.

| | valor |
|---|---|
| v_max | 2,32 m/s (= 13,89/6) |
| carro | 0,583 m + minGap 0,292 m = slot de **0,875 m** |
| quarteirão interno | 15,8 / **28,2** (mediana) / 37,6 m |
| coto de borda | 23,2 m (150 m em escala real) |
| lane-metros | 2194 (internos 1264 + cotos 931) |
| vagas na rede | **2508** (internos 1444 + cotos 1064 = 42%) |

O 1444 interno bate com os 1453 documentados para `maquete_sim`
(`RESULTADOS_MAQUETE.md` §2.1) — a diferença são os arcos `ret_*` que sumiram.

**Detalhe que quase quebrou a similitude em silêncio:** o `netconvert` limita a
velocidade das faixas INTERNAS de junção por `v = sqrt(a_lat · r)` com `a_lat`
fixo em 5,5 m/s². Sob similitude `r' = r/6`, então `v'` sairia `v/sqrt(6)` —
**2,45× rápido demais**, e um teste que só olhe faixas normais não pegaria.
Corrigido passando `--junctions.limit-turn-speed 5.5/6` (aceleração lateral é uma
aceleração: escala como `accel`/`decel`). Há teste para isso.

### 1.3 Escolha de rota — o risco 3 do plano

> *"Mão única com 9 fontes/9 sorvedouros pode limitar demais a escolha de rota."*

Medido sobre os 81 pares (fonte × sorvedouro):

| | |
|---|---|
| pares alcançáveis | **81 de 81** (nenhum par sem caminho) |
| pares usados na demanda | **67** (14 descartados por `min_edges=4`, §2.2) |
| caminhos simples por par | mín **1**, mediana **7**, máx 17 |
| pares com caminho ÚNICO | **2**: `V1_SRC→V1_SNK` e `V4N_SRC→V4N_SNK` |
| edges do caminho mais curto | 4 / **6** (mediana) / 9 |
| rotas alternativas de fato usadas (Yen, k≤4) | mediana **4** |

**Não é degenerado.** Os 2 pares de caminho único são o mesmo corredor de ponta a
ponta, onde caminho único é o comportamento correto — não há alternativa dentro de
uma coluna de mão única. **Nenhuma decisão do dono do projeto é necessária aqui:
a rede não precisa de corredor bidirecional.**

---

## 2. A demanda (`GeradorDemandaAberta`, contrato C2)

### 2.1 Forma e invariante — DoD (c)

Arquivo de rotas por seed, veículo a veículo, com a **rota inteira escrita no
arquivo**. Nada de `<flow>`; nada de `<trip>` sem rota — um `<trip from= to=>`
faria o SUMO rotear no instante da inserção usando os tempos de viagem correntes,
e a rota inicial deixaria de ser propriedade da DEMANDA para virar propriedade do
BRAÇO.

**Mesma seed → mesmo sha256, byte a byte.** Provado de três formas: mesma seed
duas vezes no mesmo processo; seeds diferentes dando sha diferentes; e **gerando em
três subprocessos com `PYTHONHASHSEED` 0, 1 e 12345** — a única forma de provar que
nenhuma ordem de `dict`/`set` vazou para o arquivo (o `hash()` de str/tupla é
aleatorizado por processo). Testes em `tests/test_a1_demanda.py`.

### 2.1.1 O `.sumocfg` por seed — a lacuna que o A2 achou

Escrever um `.rou.xml` por seed **não bastava**: quem escolhe o arquivo de rotas é
o `.sumocfg`, e o `TrafficEnv` do maquete monta a linha de comando do SUMO sozinho
e **não aceita `--route-files`**. Com um `.sumocfg` só, a Arena subia a mesma
demanda para qualquer seed, **sem erro**. Sha diferente do `.rou.xml` não pegava:
os arquivos sempre foram diferentes; igual era o que o SUMO de fato carregava.

Fechado assim (`feira/demanda/config_seed.py`):

| | |
|---|---|
| o gerador escreve | `config/maquete_aberta_s<seed>.sumocfg`, derivado do canônico + uma linha `<route-files>` |
| por que derivado, e não um template | se `build_rede_aberta.py` mudar o canônico, os por-seed herdam na próxima geração em vez de divergirem calados |
| versionado? | **não** — o `.rou.xml` que ele aponta também não é. O manifesto guarda `sumocfg_seed` e `sumocfg_seed_sha256` |
| falha alto | `sumocfg_da_seed(cenario, seed)` levanta `ConfigDaSeedAusente` se faltar; `gerador.manifesto()` chama a verificação, e é por ele que todo braço passa antes de subir o SUMO |
| recriação | `gera()` reescreve o cfg quando ele falta, inclusive no caminho idempotente (some num clone novo), sem tocar no `.rou.xml` |
| armadilha coberta | `calibra.py` usa `escreve_cfg=False`: ele gera demanda descartável em várias taxas apontando para o **mesmo** `Cenario`, e sobrescreveria o cfg oficial da seed 42 para a demanda de 3900 veh/h |

Verificado ponta a ponta, subindo o SUMO só com `-c` (sem `-r`), 600 s:

| cfg | veículos inseridos |
|---|---|
| `maquete_aberta_s42.sumocfg` | 562 |
| `maquete_aberta_s43.sumocfg` | 618 |
| `maquete_aberta_s44.sumocfg` | 604 |
| `maquete_aberta.sumocfg` (canônico) | **0** |

O canônico inserir zero é de propósito: não existe "demanda default" que alguém
possa medir sem perceber qual seed estava rodando.

> **`versao_gerador` foi de `aberta-1.0` para `aberta-1.1`** — o manifesto ganhou
> dois campos e o cabeçalho do `.rou.xml` carrega a versão, então **o sha256 de
> toda a demanda mudou** (as rotas em si são idênticas: mesma rede, mesma seed,
> mesmo sorteio). Qualquer run gravada com manifesto `aberta-1.0` continua
> descrita pelo manifesto dela; para regerar, `python -m feira.demanda --forcar`.

Uma armadilha que este trabalho abriu e fechou: o teste de determinismo entre
processos criava um `Cenario` no subprocesso a partir do canônico e só desviava o
`rou_pattern` — e passou a **reescrever o cfg oficial da seed 42 apontando para um
arquivo em `tmp`**. A fixture dos testes agora espelha o cenário inteiro
(`config/`, `network/`, `demanda/`) dentro do `tmp`, e há verificação de que a
suíte não toca em `sumo/aberta/config/`.

Propriedade extra, testada: **aumentar o horizonte só acrescenta veículos no fim.**
A demanda de horizonte menor é prefixo exato da de horizonte maior (mesma seed,
mesma taxa) — é o que permite calibrar com runs curtas sem desconfiar que "é outro
trânsito".

### 2.2 Parâmetros e de onde vêm

| parâmetro | valor | origem |
|---|---|---|
| chegadas | Poisson | a exponencial é escrita na mão a partir de `random()`, um número por chegada |
| `departLane` | `best` | MEDIDO na Vila Olímpia: `first` (o default) fazia todo carro nascer na faixa 0 — avenida de 3 faixas escoando em fila única. Produção +119% |
| `od_weight` | `capacity`, expoente **1** | MEDIDO na Vila Olímpia: produção +7%, parados −4 pp. **Expoente ≥1,5 COLAPSA** (−50% de produção) |
| `reroute_period` | 60 s | MEDIDO na Vila Olímpia: sem isto a malha travava em 98% parados |
| `departSpeed` | `max` | testado contra o default (partida parada): sem efeito no regime, ver §6 |
| `min_edges` | **4** | decisão minha, documentada abaixo |
| rotas alternativas | Yen k=4, logit `exp(−4·(cᵢ−c₀)/c₀)` | decisão minha, documentada abaixo |
| taxa | **3500 veh/h** | §3 |
| horizonte | 5400 s | warm-up (300) + janela (3600) + folga |

**`min_edges=4`** (rota com ≥2 edges internos, ou seja ≥2 cruzamentos atravessados)
descarta 14 dos 81 pares. Motivo: 4 pares têm caminho de **2 edges** (entra pelo
coto e sai pelo coto vizinho, atravessando um cruzamento só) e 10 têm 3. Essas
viagens inflam a vazão sem carregar a malha — e na Frente 3 o placar é em **carros
entregues**. É o análogo do `TRIP_LEN_MIN=3` da rede fechada, corrigido pelos 2
cotos que toda rota daqui tem.

**Rotas alternativas:** com a rota escolhida na geração, todo carro do mesmo par OD
levaria a MESMA rota, e a carga concentraria antes de o `device.rerouting` (60 s)
ter chance de espalhar. O gerador sorteia entre os até 4 caminhos mais baratos com
peso logit — determinístico, e o número de alternativas por par é o dado da §1.3.

### 2.3 H2 tem participação dominante?

Sim, e ela sai da capacidade (`3 faixas × v` contra `2 faixas × v`), não de um
número escolhido a mão. Medido em `demanda_s42`:

| | |
|---|---|
| origens em H2 (E+W) | **34,8%** — contra 9,3% de cada corredor secundário |
| destinos em H2 | **34,8%** |
| **viagens que passam por H2** | **67,4%** |
| veículo-metros em H2 | 29,1% (H2W 15,4 + H2E 13,7) |

O corredor **isolado** de maior carga é a H3, com 18,6% dos veículo-metros — maior
que qualquer uma das duas pistas da H2 sozinha. Isso é geometria: a H3 é um
corredor de mão única atravessando o grid inteiro, a H2 é a mesma avenida partida
em duas pistas. Somadas, a H2 domina (29,1% contra 18,6%), e é por ela que passam
2 de cada 3 viagens.

---

## 3. Calibração do regime

### 3.1 Protocolo

- Plano de semáforo: **timer fixo uniforme de 27 s verde + 3 s amarelo**
  (`BASELINE_GREEN` do projeto), todos os 12 em fase, sem offset — é o
  `warmup_plano="timer"` do `Cenario` e o adversário declarado do projeto. O
  programa `actuated` que o `netconvert` gera é substituído por um estático via
  TraCI (senão a calibração mediria um controlador que nenhum braço usa).
- Amostragem a cada 10 s; janela de medição `t ≥ 300 s` (o warm-up, §4).
- **Limiar de "parado": 0,1/6 = 0,0167 m/s.** O `getLastStepHaltingNumber` do SUMO
  usa 0,1 m/s FIXO; nesta rede isso equivale a 0,6 m/s da rede real, ou seja
  contaria como parado um carro andando a 2 km/h reais. As duas colunas estão
  reportadas (`%par` e `%par 0,1`).
- Velocidade também em **km/h equivalentes da rede real** (`v × 6 × 3,6`), que é a
  única forma de comparar com os 21 km/h da Vila Olímpia.
- Veredito de estabilidade (`analisa.py`): a população ativa não pode estar
  crescendo (|deriva entre o terço do meio e o último| < 15% da população) **e** o
  backlog de inserção máximo tem que ficar < 20.

### 3.2 A varredura larga (seed 42, 3600 s)

| taxa veh/h | ativos | interno | coto | %par | %par 0,1 | km/h* | backlog máx | vazão/h |
|---|---|---|---|---|---|---|---|---|
| 300 | 11 | 8 | 3 | 38,8 | 39,4 | 23,4 | 1 | 268 |
| 900 | 33 | 24 | 9 | 37,9 | 39,0 | 23,0 | 2 | 827 |
| 1800 | 68 | 50 | 18 | 36,2 | 37,7 | 22,7 | 3 | 1649 |
| 2700 | 110 | 82 | 28 | 36,7 | 38,2 | 21,7 | 3 | 2495 |
| 3600 | 165 | 127 | 39 | 38,5 | 41,1 | 19,6 | 4 | 3325 |
| **4500** | **870** | 654 | 215 | **89,2** | 91,1 | **2,5** | **1362** | **1762** |
| 5400 | 1149 | 832 | 318 | 97,5 | 98,1 | 0,5 | 2786 | 1168 |
| 7200 | 1303 | 906 | 398 | 99,2 | 99,4 | 0,2 | 4806 | 884 |
| 9000 | 1337 | 921 | 415 | 99,2 | 99,3 | 0,2 | 6581 | 934 |
| 12000 | 1343 | 899 | 444 | 99,3 | 99,3 | 0,3 | 9582 | 1021 |

\* km/h da rede real equivalente.

Duas leituras:

1. **O piso de "parados" desta rede é ~38%, com a rede praticamente vazia.** Com
   ciclo de 60 s (27+3, duas fases) e 33 s de vermelho, um carro que chega em
   instante aleatório espera em média `33²/(2·60) ≈ 9,1 s` por cruzamento, e a
   rota média tem 6,45 edges = 5,4 cruzamentos: **~50 s parado numa viagem de
   ~140 s** (152 m de rota a 1,08 m/s, os dois medidos). Dá 36%, contra os 38,8%
   medidos a 300 veh/h. **"% parados" não é, nesta rede, um indicador
   de congestionamento** — é majoritariamente o custo do semáforo.
2. **A malha trava, e trava feio.** Acima da capacidade o backlog de inserção
   cresce sem teto (9582 carros a 12000 veh/h) e a vazão **cai** de 3325 para
   ~1000/h. O risco 1 do plano ("a rede aberta pode não congestionar") **não se
   materializou**; o risco 2 (travamento irreversível) é o que existe aqui, e é
   por isso que o ponto de operação foi escolhido com margem.

### 3.3 A varredura fina (seed 42, 3600 s) — o penhasco

| taxa | ativos | %par | km/h* | backlog final | vazão/h |
|---|---|---|---|---|---|
| 3600 | 165 | 38,5 | 19,6 | 0 | 3325 |
| 3800 | 190 | 40,4 | 18,3 | 1 | 3513 |
| **4000** | 418 | 64,8 | 8,3 | **92 e subindo** | 3004 |
| 4100 | 685 | 81,9 | 4,0 | 407 e subindo | 2402 |
| 4200 | 838 | 88,5 | 2,3 | 676 e subindo | 2145 |

De 3800 para 4000 veh/h (+5% de demanda) a população ativa **dobra** e a vazão
**cai 14%**. Não há patamar intermediário.

### 3.4 O erro que a janela de 1 h esconde — e por que o ponto é 3500

Medir só 3600 s dá a resposta errada. A 3800 veh/h as 6 seeds passam folgadas em
3600 s (190–212 ativos, 40,7% parados, backlog ≤6). Rodando as **mesmas seeds até
7200 s**:

| taxa | horizonte | seeds estáveis | o que acontece nas que quebram |
|---|---|---|---|
| 3800 | 3600 s | 6 de 6 | — |
| **3800** | **7200 s** | **1 de 3** | seed 45: 552 ativos, 69,8% parados, backlog 556. seed 47: 582 ativos, 70,5%, backlog 798 |
| 3600 | 7200 s | 2 de 3 | seed 47: 298 ativos, 53,6% parados, backlog 14 e subindo |
| **3500** | **7200 s** | **6 de 6** | — |
| 3400 | 7200 s | 6 de 6 | — |

Perto da capacidade a malha é **metaestável**: a fila cresce devagar, e uma janela
de 1 hora não a vê. O indicador que denuncia cedo é a **deriva da população ativa**
(`dAtiv` em `analisa.py`) — a 3800/3600 s ela já era +17 a +21 carros por terço de
run, e foi exatamente nessas seeds que a run longa quebrou.

**Ponto de operação: 3500 veh/h.** É a maior taxa testada estável em 6 de 6 seeds
por 7200 s.

| horizonte | ativos | interno | coto | %par | %par 0,1 | km/h* | vazão/h | backlog máx | estáveis |
|---|---|---|---|---|---|---|---|---|---|
| 3600 s | **158,4** (154–163) | 117–124 | 37–39 | **37,9** (37,6–38,1) | 40,1 | **20,1** | 3332 | 6 | **6/6** |
| 7200 s | 160,5 (156–167) | 118–128 | 38–39 | 38,2 (37,6–38,6) | 40,5 | 19,9 | 3411 | 6 | **6/6** |

Para referência, 3400 veh/h em 7200 s dá 153,4 ativos / 37,8% / 20,2 km/h, também
6/6 — é a opção com mais margem, se o A5/A6 preferirem folga.

### 3.5 Por que 45–55% não é alcançável de forma estável

Três medições, nesta ordem:

1. o piso de fluxo livre já é 38,8% (§3.2, leitura 1);
2. a faixa 45–55% só aparece de 3900 veh/h para cima — **acima** da capacidade;
   nessas taxas a malha está enchendo, não em regime (a 3900/3600 s, 4 das 6 seeds
   chegam a 48–52% parados **com a população crescendo 130–200 carros por terço de
   run**);
3. no maior ponto estável (3500 veh/h) o valor é 37,9%, e **a dispersão entre 6
   seeds é de 0,5 pp** — não é ruído que se possa empurrar para 45%.

O alvo de 45–55% veio da Vila Olímpia (850 carros, 48–54% parados, 21 km/h). Lá o
fluxo livre era 10,2 m/s = 37 km/h e a operação 21 km/h — **57% do livre**. Aqui o
fluxo livre COM semáforo é 23,4 km/h e a operação 20,1 km/h — **86% do livre**.
Pela velocidade absoluta equivalente as duas estão no mesmo lugar (20,1 contra
21 km/h); pela velocidade relativa a Vila Olímpia operava bem mais carregada.

**A malha é pequena — 12 cruzamentos, 2194 lane-m, tempo médio no sistema de
~160 s (Lei de Little: 158 carros / 0,97 chegada por s) contra 330 s da Vila
Olímpia.** Rede pequena tem pouco amortecedor: passa de subsaturada a
travada num degrau, em vez de num declive. E o baseline uniforme sem offset (que é
o adversário declarado do projeto) limita a capacidade a ~3600–3900 veh/h; o plano
coordenado do agente A5 deve subir esse teto, e aí um ponto de operação mais
carregado volta à mesa.

---

## 4. Warm-up medido — `Cenario.warmup_s = 300 s`

**Definição operacional** (`calibra.detecta_warmup`): o menor `t0` tal que a média
de `[t0, fim]` da velocidade da rede E da população ativa já está a menos de 5% da
média de regime (último terço da run). É o que warm-up significa na prática — "de
onde em diante posso abrir a janela sem que o enchimento puxe o número" — e não
"onde a curva parece plana". Comparar bloco a bloco (o critério ingênuo) não serve:
a oscilação de regime chega a 11% na população, e um único bloco ruidoso perto do
fim invalidaria todos os candidatos.

Série binada em blocos de 120 s, 3600 veh/h, seed 42:

| bloco (s) | ativos | v (m/s) | %par |
|---|---|---|---|
| 0–120 | 49 | 1,163 | 33,3 |
| 120–240 | 123 | 0,987 | 36,9 |
| **240–360** | **153** | **0,959** | 36,1 |
| 360–480 | 159 | 0,931 | 38,1 |
| … regime | ~160 | ~0,93 | ~37 |

- critério da média sem viés: **120 s**;
- população ativa chega a 90% do regime: **240 s**;
- o `device.rerouting` só tem estimativa de tempo de viagem depois de
  `adaptation-steps 18 × adaptation-interval 10 s` = **180 s**;
- **300 s = 5 ciclos inteiros de 60 s**, o menor múltiplo do ciclo acima dos três.

É 4× menor que os 1200 s da Vila Olímpia, e isso é esperado: a viagem média aqui é
muito mais curta e a população de regime é 158 contra 850 carros.

> Nas taxas acima da capacidade o detector devolve 1800–2400 s — corretamente: lá a
> malha **nunca** entra em regime, ela enche até o fim da run.

---

## 5. Replay determinístico — DoD (e)

`sumo/aberta/replay.py`. A impressão digital do estado é
`(id, edge, posição, velocidade)` de **todo** veículo vivo mais a fase dos 12
semáforos, ordenado — não a contagem: duas runs com os carros em lugares diferentes
têm a mesma contagem e não são o mesmo estado.

| pergunta | resposta medida |
|---|---|
| rodar 0→1200 s duas vezes com a mesma seed dá o mesmo estado? | **SIM, idêntico**, em 3 seeds (140, 151 e 178 veículos vivos) |
| `saveState` em t0 + `loadState` reproduz o estado de t0? | **SIM, na precisão do próprio arquivo** |
| … e a continuação de t0 até t1 bate? | **NÃO** (≈150 veículos divergentes) |

O motivo do "não" está medido e não é bug: o arquivo de estado do SUMO grava
posição e velocidade com **2 casas decimais**. Exemplo real:
`14.849 → 14.85`, `0.0277 → 0.03`, `1.8033 → 1.8`. Sob similitude 1 cm é 1,7% do
comprimento do carro; num sistema com car-following e troca de faixa isso amplifica
e as trajetórias divergem em poucas dezenas de segundos.

**Consequência prática para o agente A3 (jogo):** `loadState` serve para colocar os
três braços no MESMO estado inicial (todos carregam o mesmo arquivo quantizado),
mas **não** serve para comparar uma run carregada contra uma run replayada do zero
— e portanto os fantasmas pré-computados precisam ser gerados a partir do mesmo
`loadState`, não de um replay independente. O fallback do plano (replay do zero) é
barato aqui: 300 s de warm-up a 250–400× tempo real custa **~1 s de parede**.

---

## 6. O que foi testado e NÃO mudou nada

| hipótese | medição | conclusão |
|---|---|---|
| `departSpeed="max"` estaria causando as colisões de inserção | 18 teleportes com `max` contra 24 com o default (partida parada), mesma demanda, 3600 s | não é a causa; `max` fica porque partida parada estrangula o coto |
| `--lanechange.duration 1` reduziria as colisões de troca de faixa | 28 teleportes (contra 18) | **piorou**; descartado |
| `--collision.mingap-factor 0` (só sobreposição real conta) | 7 teleportes (contra 18) | reduz, mas muda a semântica de colisão do SUMO — **não aplicado**, é decisão do dono (§7) |

---

## 7. Decisões que precisam do dono do projeto

1. **Os 37,9% parados — minha recomendação: aceitar agora, recalibrar UMA vez
   depois do A5, e trocar a métrica de aceite.** O motivo técnico, em três passos:

   - **"% parados" não mede congestionamento nesta rede.** O piso de fluxo livre é
     38,8% e o ponto de operação é 37,9% — a métrica praticamente não se move entre
     rede vazia e rede carregada. O que se move é a velocidade.
   - **E a velocidade diz que 3500 veh/h é um regime LEVE, e eu não vou disfarçar
     isso.** Decompondo (tudo em km/h equivalentes da rede real): desimpedido, sem
     semáforo, **45,4**; com o timer uniforme e a rede vazia, **23,4** (−48%, custo
     do semáforo); no ponto de operação, **20,1** (−7 pp a mais, custo da
     interação entre veículos). Ou seja: **o atraso é dominado pelo plano
     semafórico, não pelo trânsito.** A Vila Olímpia operava a 57% do seu livre;
     aqui estamos a 86%.
   - **Mas isso é limite do BASELINE, não da rede nem da demanda.** A capacidade de
     ~3600–3900 veh/h é a do timer uniforme de 27 s sem offset — "um plano que
     nenhum engenheiro instalaria" (PLANO.md §1). Subir a demanda agora não
     produziria congestionamento estável, produziria travamento (§3.4, medido).

   **Previsão testável, para o A5 cobrar de mim depois:** para chegar aos 57% de
   velocidade relativa da Vila Olímpia esta malha precisa operar a ~13,3 km/h eq.,
   que é o regime de 4000–4100 veh/h — hoje instável. Se o plano coordenado subir a
   capacidade os 10–20% típicos de coordenação de arterial, **4000–4200 veh/h
   passam a ser estáveis e caem exatamente na faixa de 45–55% parados**. Se o A5
   subir a capacidade e a faixa não vier junto, a explicação acima está errada e
   isso vale tanto quanto o resultado positivo.

   **O que eu recomendo formalmente:**
   (a) congelar 3500 veh/h para a Onda 1 — destrava A5/A6/A3 sem risco de
       travamento em nenhum braço;
   (b) trocar o critério de aceite de "45–55% parados" para **velocidade
       equivalente + vazão**, mantendo "% parados" reportado como saiu;
   (c) **recalibrar uma única vez** assim que o A5 congelar o plano coordenado,
       com a mesma varredura de 7200 s × 6 seeds — mas exigindo estabilidade sob o
       **pior braço que de fato roda**, que na feira é o **humano**, não o timer
       (risco 8: uma pessoa apertando botão errado trava a malha mais rápido que
       qualquer plano fixo). O `calibra.py` já faz isso: só troca a função que
       aplica o plano. Custo: ~10 min de máquina.

   Não recomendo (c') alongar o ciclo do baseline para inflar o "% parados":
   `BASELINE_GREEN=27` está congelado por decisão do projeto, e mexer nele
   enfraqueceria o adversário — que é exatamente o que o §1 do RESULTADOS_MAQUETE
   se compromete a não fazer.
2. **Colisões numéricas → teleporte.** 18 por 3600 s a 3800 veh/h (0,49% dos
   veículos), todas em trecho de múltiplas faixas, com sobreposição entre −0,7 e
   0 m. O teleporte tira um carro da fila e quebra a conservação que o detector do
   A2 vai usar. Opções: deixar como está e o A2 conta; `--collision.action warn`
   (não teleporta); `--collision.mingap-factor 0` (7 em vez de 18). **Não mudei
   nada** — é decisão de modelagem que afeta os três braços igualmente.
3. **A rodada de 120 s do PLANO.md §2 supõe "~270 viagens".** Medido: **116**
   (0,968 viagem/s em regime). 250–300 viagens exigem **258–310 s**; os 270 do
   texto, **279 s**. A curva inteira, com dispersão, está na §8 — e ela mostra que
   o ganho de estabilidade satura em 180–240 s, então alongar até 300 s compra
   pouco e custa atenção do público.
4. **`tests/test_contratos.py::test_cenario_aberto_ainda_nao_medido` agora falha,
   e falha pelo motivo certo.** Ele afirma `assert c.warmup_s is None` — o estado
   pré-A1. Preencher `warmup_s` era o entregável; o arquivo está na minha lista de
   "não editar", então quem fecha é o dono. Sugestão de troca (mantendo a garantia
   que o teste protege, agora contra um cenário sintético em vez do real):

   ```python
   def test_cenario_aberto_tem_warmup_medido():
       c = cenario("aberta.maquete")
       assert c.warmup_s == 300.0          # docs/CALIBRACAO_ABERTA.md §4
       assert c.modelo_demanda == "arquivo"
       assert janela_padrao(c) == Janela(300.0, 3900.0)

   def test_janela_padrao_recusa_warmup_nao_medido():
       c = replace(cenario("aberta.maquete"), warmup_s=None)
       with pytest.raises(ArenaNaoConfigurada, match="warmup_s"):
           janela_padrao(c)
   ```

   Consequência para a A2: `janela_padrao(aberta.maquete)` passa a devolver
   `Janela(300.0, 3900.0)` e a rodada, `Janela(300.0, 420.0)`. A demanda de
   horizonte 5400 s cobre as duas com folga.
5. **Registrar `GeradorDemandaAberta` na suíte de conformidade**: descomentar
   `pytest.param(GeradorDemandaAberta, id="aberta")` em
   `tests/test_conformidade.py:194` (não editei o arquivo, conforme combinado). O
   gerador já foi escrito para funcionar com o `cenario_fake_arquivo`, que aponta
   para um `.net.xml` inexistente — ele cai na rede canônica da rede aberta nesse
   caso, e o motivo está documentado no docstring da classe.

---

## 8. Duração da rodada — a curva

O PLANO.md §2 fixa a rodada em 120 s supondo "~270 viagens". No ponto de operação
a vazão de regime é **0,968 viagem/s** (3485/h), então 120 s entregam **116**.

Janelas de largura *D* dentro do regime (`t ≥ 300 s`), todas as posições a cada
60 s, 6 seeds — 3500 veh/h:

| duração (s) | viagens (média) | dp | cv | mín | máx |
|---|---|---|---|---|---|
| 60 | 58,1 | 6,9 | 11,8% | 38 | 76 |
| **120** (o plano de hoje) | **116,1** | 9,2 | 7,9% | 89 | 139 |
| 180 | 174,2 | 10,8 | 6,2% | 148 | 205 |
| 240 | 232,3 | 11,9 | 5,1% | 204 | 266 |
| **270** | **264,1** | 12,3 | 4,7% | 238 | 301 |
| **300** | **290,3** | 13,0 | 4,5% | 258 | 326 |
| 360 | 348,2 | 13,9 | 4,0% | 311 | 388 |
| 480 | 464,0 | 15,5 | 3,3% | 422 | 512 |
| 600 | 579,9 | 17,3 | 3,0% | 527 | 638 |

**Resposta direta: 250–300 viagens exigem uma rodada de 258 s a 310 s** (~4,3 a
5,2 min), contra os 120 s do plano. Para os 270 do texto: **279 s**.

Duas leituras honestas antes de alongar a rodada:

1. O `dp` da tabela é a variabilidade do **número do placar**, não a da
   **diferença entre braços**. Os três braços leem o mesmo `.rou.xml` na mesma
   janela, então boa parte dessa variância é comum e cancela no pareamento. A
   tabela diz quanto o placar oscila de rodada para rodada — que é o que o público
   vê —, não quanta potência estatística a comparação tem.
2. O ganho de estabilidade satura: dobrar 120 → 240 s corta o cv de 7,9% para
   5,1%; dobrar de novo (240 → 480) corta só de 5,1% para 3,3%. Se o critério for
   "o placar não pode parecer sorte", **180–240 s** já compra quase tudo o que há
   para comprar, a metade do custo de atenção de 300 s.

A escolha é do dono do projeto (rodada mais longa × teto de atenção em pé); o
número que **não** se sustenta é "120 s ⇒ 270 viagens".

---

## 9. Como reproduzir

```powershell
$py = "..\smart-traffic\.venv\Scripts\python.exe"

# 1) a rede (netconvert; ~1 s)
& $py sumo\aberta\build_rede_aberta.py
& $py sumo\aberta\build_rede_aberta.py --verifica

# 2) a demanda canônica (seeds 42-47 e 100-111)
& $py -m feira.demanda

# 3) a calibração. 3600 s custam ~12 s de parede; 7200 s, ~25 s.
& $py sumo\aberta\calibra.py --taxa 3500 --end 7200 --seeds 42,43,44,45,46,47 --rotulo operacao_7200
& $py sumo\aberta\analisa.py sumo\aberta\calibracao\operacao_7200.json --t0 300

# 4) o replay determinístico (+ o teste de saveState/loadState)
& $py sumo\aberta\replay.py --seeds 42,43,44 --t0 1200 --t1 1500

# 5) a suíte
& $py -m pytest -q ; & $py -m ruff check .
```

### Arquivos de dados brutos

| arquivo | o que é |
|---|---|
| `varredura_taxa_s42.json` | varredura larga 300–12000 veh/h, seed 42, 3600 s (§3.2) |
| `varredura_fina_s42.json` | 3800–4300 veh/h, seed 42, 3600 s (§3.3) |
| `regime_6seeds.json` | 3700/3800/3900 veh/h × 6 seeds, 3600 s (§3.4) |
| `estabilidade_7200.json` | 3800 veh/h × 3 seeds, 7200 s — as duas que travam (§3.4) |
| `longo_7200.json` | 3200/3400/3600 veh/h × 3 seeds, 7200 s (§3.4) |
| `operacao_7200.json` | **3400/3500 veh/h × 6 seeds, 7200 s — o ponto escolhido** |
| `operacao_3600.json` | 3500 veh/h × 6 seeds, 3600 s — a janela de avaliação |
| `replay.json` | resultado do DoD (e) (§5) |
