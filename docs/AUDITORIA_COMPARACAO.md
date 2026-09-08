# Auditoria da comparação — o número offline e o número da tela

Agente **A2 — Bancada de Medição & Auditoria**, Onda 1. Fecha os 7 achados de
`docs/PLANO.md` §1 com número medido ou com a marca *refutado*.

Tudo aqui foi **medido**, não lido. Todas as corridas são do cenário
`small.maquete` (a rede fechada de hoje: 10 semáforos, 6 controláveis, frota
persistente de 30, `ST_STATE=ats`), com o checkpoint em produção
`results/maq30_ats_full_best.pt` e o baseline `BASELINE_GREEN=27`. A máquina é a
mesma que roda a demo (Windows 11, SUMO 1.27.0, torch 2.12 CPU).

Nada do `smart-traffic-maquete` foi modificado — as medições ao vivo entram pelo
WebSocket que o dashboard já publica.

---

## 0. Veredito, em uma tela

| | o número **offline** | o número **da tela** |
|---|---|---|
| o que é | +16,0% tempo / +34,4% fila / +19,5% vazão, 12 seeds held-out, p ≤ 1e-11 | os três deltas do `updateVerdict`, ao vivo |
| protocolo | janela fixa de 3600 s, mesma seed nos dois braços, média da run inteira | contadores acumulados desde o boot de cada processo, fila = média das últimas 20 amostras |
| **honesto?** | **sim** — e agora também **reproduzível fora do maquete**: a Arena bate o `evaluate.py` com **0,000%** de diferença | **sim, e no sentido conservador**: os desvios medidos empurram o número para **baixo**, não para cima |
| ressalva que fica | o baseline não tem offset nem split (A5); a geometria comprimida infla o ganho | a vantagem **cresce com o tempo de demo** — a tela às 3 h de feira mostra mais do que o paper (§9) |

**Resposta direta ao dono do projeto:** o número que você exibe hoje **não é
inflado por erro de medição** — os desvios medidos se cancelam.

| # | achado | veredito | efeito na manchete |
|---|---|---|---|
| 1 | deriva entre os dois braços | **mecanismo real, consequência REFUTADA no ponto de operação** | offset constante de 2,6 s; a deriva que cresce só aparece a ~60x (§2) |
| 2 | `updateVerdict` ignora o `t` | **confirmado** | **-1,38 pp** na vazao (§3) |
| 3 | `SEED=42` e in-sample | **confirmado** | **+0,99 pp** tempo, **+1,42 pp** vazao, **+0,08 pp** fila (§4) |
| 4 | fila da tela = 20 amostras | **confirmado** | nao e vies, e **variancia** — a mesma vantagem oscila numa faixa larga (§5) |
| 5 | `heat` ignora faixas de juncao | **confirmado** | **+0,94 pp** na fila (§6) |
| 6 | gate `AQUECIMENTO=8` | **confirmado** | dura ~40 s simulados; nao e aquecimento, e cortina (§7) |
| 7 | `coherence_gap` morre na rede aberta | **confirmado, e pior** | fragil ate na fechada: errar `N` em 27% move o detector 35 pp (§8) |

**Somando os vieses na métrica que vira manchete (vazão):**

    seed in-sample     +1,42 pp   (a favor da RL)
    deriva/pareamento  -1,38 pp   (contra a RL)
    ---------------------------------------------
    líquido            +0,04 pp

Na **fila** o líquido é **+1,02 pp** (+0,08 da seed, +0,94 do `heat`) sobre uma
vantagem de +34,6% — 3% do valor. No **tempo de viagem**, só a seed pesa:
**+0,99 pp** sobre +16,3%. **Nenhum dos sete achados, isolado ou somado, explica
o tamanho do ganho publicado.**

O que **é** um problema de honestidade não estava na lista: **a vantagem exibida
não é estacionária.** Na seed que a demo roda, o timer fixo **trava** em
t ≈ 3995 s (≈ 1 h 35 min de relógio de parede a 0,7×) e nunca mais entrega um
carro. A vantagem de vazão passa de **+20,8% na primeira hora** para **+231% em
três horas** (§9). O número não é falso — é o que aquele plano fixo faz nessa
densidade —, mas **não é o número do paper**, e a tela não avisa quando deixou
de ser.

---

## 1. Método — a Arena, e por que ela pode ser usada como régua

A auditoria não vale mais que o instrumento. Antes de qualquer achado, a
`feira.arena.ArenaSumo` foi calibrada contra as duas implementações de
referência do maquete, na mesma seed, na mesma janela e com o mesmo baseline.

`scripts/reproduz_evaluate.py`, seed 42, janela [0, 3600 s):

| braço | métrica | referência | Arena | delta |
|---|---|---|---|---|
| **rl** (`policy_sim.evaluate_policy`, grade 10 s) | tempo de viagem | 54,7307 | 54,7307 | **+0,000%** |
| | fila | 8,0661 | 8,0661 | **+0,000%** |
| | espera | 66,0753 | 66,0753 | **+0,000%** |
| | vazão | 1961 | 1961 | **+0,000%** |
| **timer** (`FixedTimerSim`, decide a cada sim-step) | tempo de viagem | 65,6870 | 65,6870 | **+0,000%** |
| | fila | 12,1408 | 12,1408 | **+0,000%** |
| | espera | 127,7694 | 127,7694 | **+0,000%** |
| | vazão | 1623 | 1623 | **+0,000%** |

DoD (a) pedia 0,5%; saiu **0,000%** — bit a bit, e não por sorte: a Arena
**dirige o `TrafficEnv` do maquete** em vez de reimplementá-lo. Ela acrescenta o
que o `TrafficEnv` não tem (janela, aquecimento comum, contabilidade de
conservação, cadência única, `Chave`) e não toca na máquina de fases, no estado
de 26 dims nem no controlador de demanda. Reescrever qualquer uma dessas peças
teria criado uma segunda verdade — que é como este projeto acabou, uma vez, com
dois baselines diferentes no mesmo repositório.

Duas notas de procedência que valem para todo o resto do documento:

1. **O braço do timer roda com `decision_interval=1`** para reproduzir o
   `FixedTimerSim`, que consulta o relógio a cada sim-step. A RL roda na grade de
   10 s. Colocar o timer na grade da RL foi medido à parte e **não muda nada**
   (§11) — por uma coincidência aritmética que não vai sobreviver ao baseline
   coordenado do A5.
2. **As leituras de faixa usam TraCI subscriptions** em vez de chamadas
   individuais. Os 0,000% acima são a prova de que os valores são os mesmos.

---

## 2. Achado nº1 — deriva de tempo simulado entre os dois braços

> `nn_runner.py` / `timer_runner.py`: dois processos, dois deadlines; ao atrasar
> fazem `deadline = perf_counter()` — o atraso some da vista e nunca volta.

### Veredito: **o mecanismo existe e foi demonstrado; a consequência descrita (deriva que cresce) é REFUTADA no ponto de operação da demo.**

Coleta ao vivo com `scripts/medir_deriva.py`, cliente do `/ws` do dashboard
(nenhuma linha do maquete tocada). A demo foi subida com
`run_dashboard.ps1 maquete`.

**10 minutos no ponto de operação real (`ST_PLAYBACK_SPEED=0,7`):**

| | valor medido |
|---|---|
| frames coletados | 842 (421 por braço) |
| ritmo do braço timer | **0,7009** s simulado por s de parede |
| ritmo do braço nn | **0,7015** s simulado por s de parede |
| deriva `t_timer − t_nn` inicial | **+3,0 s** |
| deriva final (após 599 s de parede) | **+2,6 s** |
| deriva máxima | **3,0 s** |
| cresce monotonicamente? | **não** — encolheu 0,4 s em 10 min |
| passos que estouraram o deadline | **0 de 420, nos dois braços** |

A deriva **não cresce**: é um **offset constante de 2,6–3,0 s**, e ele não vem do
`deadline = perf_counter()`. Vem do **boot**: o braço da rede neural precisa
importar torch e carregar o checkpoint antes do primeiro passo, e entra na
simulação ~4 s de parede depois do braço do timer. O ramo de re-sincronização
**nunca é executado** na demo: em 420 passos nenhum dos dois braços chegou
atrasado ao seu deadline.

**O mecanismo, porém, é real — e foi forçado a aparecer.** Com
`ST_PLAYBACK_SPEED` acima do que a máquina sustenta, o braço da rede neural
(inferência DDQN) satura antes do braço do timer:

| playback | ritmo timer | ritmo nn | deriva | forma |
|---|---|---|---|---|
| 0,7× (a demo) | 0,7009 | 0,7015 | +2,6 s | **constante** |
| 8× | 8,0048 | 8,0048 | +13,0 s | **constante** |
| 60× | **60,003** | **58,490** | +137 s → **+302 s em 120 s de parede** | **cresce, monotônica, +1,44 s por s de parede** |

A 60× a deriva cresce sem teto e nunca recupera — exatamente o que o achado
descreve. A margem entre o ponto de operação (0,7×) e o ponto em que o mecanismo
dispara é de **~83×** nesta máquina. **Continua sendo um bug** (o notebook da
feira pode ser mais lento, e o modo jogo vai somar carga), mas **não está
disparando hoje**.

Conserto estrutural, já implementado: `feira/arena/sumo.py:_Relogio` **acumula** o
atraso em vez de reajustar o deadline, e o reporta em
`arena.ultimo_diagnostico["atraso_max_s"]`. Coberto por
`tests/test_a2_arena.py::test_relogio_acumula_o_atraso_em_vez_de_reajustar_o_deadline`.

---

## 3. Achado nº2 — `updateVerdict` compara `completed` sem olhar o `t`

> `projecao.js:366`: `updateVerdict` compara `completed` acumulado dos dois
> braços **sem olhar o `t`** de cada frame.

### Veredito: **CONFIRMADO. Efeito medido: −1,38 ponto percentual — contra a RL.**

O código é inequívoco (`projecao.js:344-369`): `pct(sa.completed, sb.completed)`
onde `sa`/`sb` são o **último frame recebido** de cada braço, e nada no cálculo
olha `f.t`. Com o offset de §2 os dois contadores estão em instantes simulados
diferentes.

`scripts/medir_deriva.py` calcula o mesmo número das duas formas, sobre a mesma
coleta de 10 minutos:

| | timer | nn | vantagem de vazão |
|---|---|---|---|
| **como a tela faz** (último frame de cada braço) | 188 | 241 | **+28,19%** |
| **pareado no mesmo `t` = 431,0 s simulado** | 186,0 | 241 | **+29,57%** |
| | | | **viés: −1,38 pp** |

A 8×, com offset de 13 s: **+17,12%** na tela contra **+18,24%** pareado
(−1,12 pp).

**A direção importa:** como o braço do timer está *à frente* no tempo simulado,
ele tem mais segundos para concluir viagens, e a tela **subestima** a vantagem da
RL. O erro existe, é sistemático e é **conservador**. Se o offset invertesse (por
exemplo com um checkpoint que carregasse mais rápido, ou com o braço do timer
subindo depois), o sinal inverteria junto — e aí seria inflação. Não dá para
contar com a sorte: **o conserto é o `Chave` do C5**, que torna impossível
comparar dois braços que não estão na mesma janela.

---

## 4. Achado nº3 — `SEED=42` é uma das seeds que escolheram o checkpoint

> `config.py:SEED=42`: a demo roda na seed usada para **escolher o checkpoint** —
> levemente in-sample.

### Veredito: **CONFIRMADO por construção; efeito medido em §4.1.**

A parte estrutural é fato documental, verificada em três arquivos:

- `sim/training/train.py:119` — `eval_seeds: tuple = (42, 43)`;
- `experiments/maq30_ats_full/config.json` — `"eval_seeds": [42, 43]`,
  `"eval_seconds": 1200`, e o `best.pt` selecionado **por vazão** nessas duas
  seeds (`train.py:413`);
- `dashboard/backend/config.py:67` — `SEED = int(os.environ.get("ST_SEED", "42"))`.

Ou seja: a demo roda **exatamente uma das duas seeds contra as quais o
checkpoint foi escolhido**, com demanda determinística — a mesma demanda,
carro a carro. Não é *overfitting de treino* (o treino usa
`deterministic_demand=False` e RNG global), é **seleção de modelo in-sample**: de
250 episódios, o `best.pt` é o que ganhou nessas duas seeds.

### 4.1 Quanto vale, medido

`scripts/mede_achados.py`, 8 seeds × 3600 s × 2 braços (timer `di=1`, RL `di=10`):

| seed | | tempo ↓ | fila ↓ | vazão ↑ | lacuna da RL | sã? |
|---|---|---|---|---|---|---|
| 42 | **in-sample** | +16,68% | +33,56% | +20,83% | −0,9% | sim |
| 43 | **in-sample** | +17,36% | +35,72% | +20,98% | −0,5% | sim |
| 100 | held-out | +16,97% | +37,80% | +21,30% | −0,9% | sim |
| 101 | held-out | +13,89% | +31,87% | +16,07% | +0,2% | sim |
| 102 | held-out | +14,47% | +34,09% | +17,46% | −0,7% | sim |
| 103 | held-out | +15,07% | +32,44% | +18,01% | −0,5% | sim |
| 104 | held-out | +19,26% | +37,14% | +23,89% | −0,5% | sim |
| 105 | held-out | +16,50% | +34,01% | +20,15% | −0,5% | sim |

| métrica | média **in-sample** (42, 43) | média **held-out** (100–105) | **viés da seed da demo** |
|---|---|---|---|
| tempo de viagem | +17,02% | +16,03% | **+0,99 pp** |
| fila | +34,64% | +34,56% | **+0,08 pp** |
| vazão | +20,90% | +19,48% | **+1,42 pp** |

**O achado se confirma, e o tamanho é pequeno: ~1 pp no tempo, ~1,4 pp na vazão,
~0 na fila.** A seed da demo é de fato levemente favorável, na direção esperada
(foi uma das duas que escolheram o checkpoint), mas o efeito é da ordem da
dispersão entre seeds — a held-out 104 é mais favorável (+19,3% / +23,9%) que
qualquer uma das duas in-sample.

**Subproduto: o número publicado foi reproduzido de forma independente.** As 6
seeds held-out desta bancada dão **+16,03% / +34,56% / +19,48%**, contra os
**+16,0% / +34,4% / +19,5%** publicados com 12 seeds em `RESULTADOS_ATS.md` §4.
As 8 seeds juntas, com t-test pareado:

```
tempo_medio_entregue     base=  66,201±1,508   novo=  55,416±1,221   +16,27%  vitórias 8/8  p=6,4e-08
tempo_medio_no_sistema   base=  65,853±1,516   novo=  55,131±1,336   +16,27%  vitórias 8/8  p=5,5e-08
fila_media               base=  12,147±0,166   novo=   7,947±0,291   +34,58%  vitórias 8/8  p=6,3e-10
entregues                base=1611,250±38,243  novo=1930,500±46,263  +19,84%  vitórias 8/8  p=5,5e-08
travamentos: 0/8 no timer, 0/8 na RL · corridas não-sãs: nenhuma
```

**Recomendação:** trocar `ST_SEED` da demo para uma seed held-out (100–111) custa
uma variável de ambiente e remove a única objeção metodológica que a tela ainda
tem. O ganho exibido cai ~1 pp — e passa a ser o mesmo número do paper.

---

## 5. Achado nº4 — a fila da tela é uma janela de 20 amostras

> `projecao.js:tail()`: fila da tela = média dos últimos 20 **frames recebidos**,
> acumulada no cliente, zera ao recarregar. O paper usa média da run inteira.

### Veredito: **CONFIRMADO em todas as partes. É o achado com maior efeito sobre o que a plateia lê.**

Os quatro fatos, verificados no código:

1. `tail(arr)` (`projecao.js:344`) = média das **últimas 20** entradas de `hist`;
2. `hist[f.sim].push(q)` (`projecao.js:238-242`) é **acumulado no cliente**, com
   `HIST_MAX = 180`; `const hist = { timer: [], nn: [] }` é estado de módulo, logo
   **recarregar a página zera a série** e o gráfico recomeça do nada;
3. `q = Σ f.heat` — que é um **conjunto de faixas diferente** do que o paper usa
   (§6);
4. o paper usa `MetricsCollector.mean_queue` = média sobre **todos** os sim-steps
   da run.

### O que isso faz com o número que a plateia lê

Não é um viés — é **variância**, e ela é enorme. `scripts/mede_achados.py tela`
roda os **dois braços no mesmo processo** (garantindo que as duas séries fiquem
alinhadas amostra a amostra) e calcula a vantagem de fila **exatamente como o
`updateVerdict` calcula**: `pct(tail(hist.timer), tail(hist.nn))`, quadro a
quadro, sobre 3581 quadros de uma run de 3600 s.

| seed | vantagem da **run inteira** | p01 | p05 | **p50** | p95 | p99 | quadros em que a RL **empata ou perde** |
|---|---|---|---|---|---|---|---|
| 42 | **+33,41%** | −52,5% | −28,1% | +30,2% | +65,6% | +74,3% | **18,0%** |
| 43 | **+35,45%** | −61,2% | −27,8% | +33,2% | +67,6% | +74,8% | **15,9%** |
| 100 | **+37,29%** | −53,9% | −14,5% | +34,4% | +67,8% | +75,6% | **12,9%** |

Traduzindo: numa demo de uma hora simulada, **em 13% a 18% dos quadros a
tela mostra a rede neural empatando ou PERDENDO em fila** — e em 1% deles mostra
a RL com mais de 50% de fila a mais que o timer. A média da run diz +33%; o
número da tela passeia entre −52% e +74%.

Isso não é erro de medição: é o que uma média móvel de 20 amostras faz com uma
série cujo desvio é da ordem da média. Mas é **exatamente a métrica que o público
lê**, e ela contradiz o número publicado várias vezes por minuto — sem que nada
na tela indique que aquilo é uma janela de 20 segundos e não o resultado.

Duas consequências práticas, as duas do agente A7:

1. **Alargar a janela ou mostrar a acumulada.** O `avg_travel_time` e o
   `completed` da tela já são **acumulados desde o boot** (é o default
   `ST_STATS_WINDOW=0`, escolhido justamente para bater com o eval held-out). A
   fila é a **única** das três métricas do veredito que usa janela curta — e é a
   única que oscila de sinal. A inconsistência é interna à própria tela.
2. **Zerar ao recarregar é um risco operacional.** `hist` é estado de módulo:
   apertar F5 no projetor durante a feira reinicia a série e as barras de fila
   recomeçam de uma janela de 1 amostra — mostrando qualquer coisa por 20
   segundos.

Nota de método: os dois braços aqui rodam na mesma grade (`di=10`) para ficarem
alinhados amostra a amostra; §11 mostra que a grade não muda o timer de 27 s (a
vantagem da run inteira sai +33,41% contra os +33,51% medidos com `di=1`).

---

## 6. Achado nº5 — o `heat` ignora as faixas internas de junção

> `snapshot.py:LaneStream`: `heat` ignora lanes internas de junção (`:`) — carro
> parado dentro do cruzamento não conta.

### Veredito: **CONFIRMADO; efeito na manchete de fila: ~0,9 ponto percentual, contra a RL.**

`snapshot.py:100` — `if lid.startswith(":"): continue`. O comentário diz o
motivo real (essas faixas não são desenhadas pelo front), mas a consequência é
que a mesma variável serve de **dado de desenho** e de **métrica de fila**, e
como métrica ela é incompleta.

Medido na Arena (ela assina TODAS as faixas e separa as duas somas), 8 seeds ×
3600 s:

| braço | fila nas aproximações (o paper) | fila desenhável (o `heat`) | fila interna de junção | % da fila fora da tela |
|---|---|---|---|---|
| timer 27 s | 12,147 | 12,217 | 0,216 | **1,74%** |
| RL (ats) | 7,947 | 8,012 | 0,288 | **3,47%** |

Na seed 42 isolada — a da demo — os números são 12,1408 / 12,1986 / 0,2264
(1,82%) no timer e 8,0661 / 8,1114 / 0,2611 (3,12%) na RL. A vantagem de fila
calculada sobre cada conjunto de faixas, nessa seed:

| conjunto de faixas | timer | RL | vantagem da RL |
|---|---|---|---|
| aproximações (o do paper) | 12,1408 | 8,0661 | **+33,56%** |
| desenháveis (o do `heat`) | 12,1986 | 8,1114 | **+33,51%** |
| **todas, com as internas** | 12,4250 | 8,3725 | **+32,62%** |

Isto é: a fila que o `heat` não vê é **proporcionalmente o dobro no braço da RL**
(3,47% contra 1,74%, média de 8 seeds) — a política de verde curto deixa mais
carro parado *dentro* do cruzamento. Contá-la reduz a vantagem de fila em
**0,94 pp** (de +33,56% para +32,62% na seed 42). É pequeno, é sistemático, e de
novo **está a favor da RL na tela**.

Aviso para a rede aberta: este número é pequeno **porque nenhum braço trava**.
Em regime travado a mesma cegueira vira um erro de fator 2 — ver §9(3), onde a
fila publicada reporta 12,06 de uma fila real de 22,90.

Nota de escopo: corrigir isto é do agente A7 (o `heat` é dado de desenho). A
`ArenaSumo` já mede os dois conjuntos e expõe em
`arena.ultimo_leitor.fila_media_total`; o `heat` do observador tem o parâmetro
`heat_com_internas` (default `True`).

---

## 7. Achado nº6 — o gate `AQUECIMENTO = 8`

> `projecao.js:AQUECIMENTO=8`: gate de 8 viagens por lado; não corresponde a
> protocolo nenhum, e **quebra na rede aberta** (que começa vazia).

### Veredito: **CONFIRMADO nas duas partes, com uma correção de ênfase.**

Medido: quantos **segundos simulados** cada braço leva para concluir as 8
viagens do gate, 8 seeds, rede fechada:

| braço | tempo até a 8ª viagem (8 seeds) |
|---|---|
| timer 27 s | 50, 32, 61, 46, 39, 40, 40, 47 s — **mediana 43 s** |
| RL | 39, 26, 42, 37, 33, 34, 36, 42 s — **mediana 36 s** |

Na rede fechada o gate dura **cerca de 40 segundos simulados** (≈ 1 minuto de
parede a 0,7×), e o braço da RL o atravessa **7 s antes** do braço do timer —
então há uma janela em que um lado já passou e o outro não. Como o gate é
`sa.completed < 8 || sb.completed < 8`, ele só libera quando os **dois** passam;
nesse aspecto está correto.

A correção de ênfase: o problema do gate **não é o valor 8** nem o tempo que ele
dura. É que ele **não é um aquecimento**. Um aquecimento descarta o transiente;
este gate apenas **esconde o placar** enquanto o transiente acontece — e depois
mostra números que **incluem** esse transiente, porque `stats.completed` e
`stats.avg_travel_time` são acumulados desde o boot do runner. Na rede fechada
isso é inofensivo (a frota nasce cheia; não há transiente a descartar, e o
`evaluate.py` também mede desde t=0). Numa **rede aberta que começa vazia** os
dois problemas aparecem juntos:

- o gate cai cedo demais — bastam 8 viagens curtas, que numa rede em enchimento
  são justamente as menos representativas;
- e os números exibidos depois continuam carregando a fase de enchimento para
  sempre, porque nada é descartado.

O conserto é estrutural e já está no contrato: a `Janela` (C5) começa em
`cenario.warmup_s`, e a `ArenaSumo` **recusa rodar** um cenário cujo warm-up não
foi medido (`ArenaNaoConfigurada`). O `warmup_s` da rede aberta é entregável do
agente A1.

---

## 8. Achado nº7 — o `coherence_gap` morre na rede aberta

> `metrics.py:coherence_gap` assume frota fechada (`esperado ≈ N × T / tt`) —
> **morre na rede aberta**. É o único detector de artefato de sobrevivência do
> projeto.

### Veredito: **CONFIRMADO, e pior do que descrito: ele é frágil até na rede fechada.**

`coherence_gap(result, n_vehicles, sim_seconds)` precisa de `n_vehicles`. Numa
rede aberta não existe esse número: a população varia com a demanda e com o
controlador — que é justamente a variável sob teste. Não há substituto óbvio (a
população média não serve: ela **cai** quando o controlador estrangula a borda,
que é o caso que se quer detectar, e isso faz o `esperado` cair junto,
mascarando o problema).

O que a medição acrescentou ao achado: **ele é hipersensível ao `N` que se passa**.
Rodando o detector com o `N` errado por 8 carros (22 em vez de 30 — o número de
carros *vivos* logo após o boot, em vez do tamanho da frota):

| braço | seed | `coherence_gap` com N=30 | com N=22 | lacuna de sobrevivência (§10) |
|---|---|---|---|---|
| timer | 42 | +2,14% | **−33,44%** | −1,4% |
| rl | 42 | +1,71% | **−34,03%** | −1,3% |
| travado | 42 | +99,74% | +99,64% | +7086,7% |

Um erro de 27% no `N` move o detector em **35 pontos percentuais** e o leva para
território negativo, onde ele não significa mais nada. O `+2,14%` / `+1,71%` com
o `N` certo confirma o número publicado ("políticas sãs ficam em 1-2%",
`RESULTADOS_ATS` §5.1) — o detector **funciona**, mas só se alguém acertar um
parâmetro que a rede aberta não tem.

O substituto está em §10.

---

## 9. O achado que não estava na lista — a vantagem exibida não é estacionária

### O timer de 27 s **trava** nesta rede — e trava justamente na seed da demo

O protocolo publicado mede **3600 s**. A demo roda **indefinidamente**. Os dois
não medem a mesma coisa, e a diferença não é sutil.

`scripts/mede_achados.py braco --segundos 10800` (3 h simuladas), seeds 42 e 43,
vazão em janelas de 600 s:

| braço | seed | vazão por bucket de 600 s (18 buckets = 3 h) | total | travou? |
|---|---|---|---|---|
| timer | **42** | 265 279 264 275 275 265 **152 0 0 0 0 0 0 0 0 0 0 0** | **1775** | **SIM** |
| timer | 43 | 265 265 279 276 259 271 278 260 262 263 269 286 271 301 288 269 271 286 | 4920 | não |
| RL | **42** | 332 347 285 342 310 342 322 332 314 306 335 324 353 341 302 309 340 337 | **5875** | não |
| RL | 43 | 324 336 316 314 331 333 271 309 306 329 340 342 334 294 333 315 318 342 | 5791 | não |

Na **seed 42 — a seed que a demo roda** — o timer fixo de 27 s **gridlocka em
t ≈ 3995 s** e nunca mais entrega um carro: **6806 s simulados de seca**, 29 dos
30 carros parados, `travou = True`, `sane() = False`. A RL na mesma seed atravessa
as 3 h em regime, com a mesma vazão do primeiro minuto (maior seca: **17 s**,
lacuna de sobrevivência **−0,2%**, `sane() = True` nas duas seeds).

Três consequências, em ordem de importância:

**(1) A vantagem exibida cresce sem limite com o tempo de demo.**

| janela | timer (entregues) | RL (entregues) | vantagem na tela |
|---|---|---|---|
| 3600 s (o protocolo publicado) | 1623 | 1961 | **+20,8%** |
| 10800 s (3 h de simulação) | 1775 | 5875 | **+231%** |

A 0,7× de playback, t = 3995 s cai em **1 h 35 min de relógio de parede**. Uma
demo aberta às 9 h mostra o timer paralisado às 10 h 35, e a partir daí o placar
sobe indefinidamente. O número não é falso — é o que aquele plano fixo faz nessa
densidade —, mas **não é o número do paper**, e ninguém na sala vai saber disso.

**(2) O travamento do timer é, ele mesmo, um artefato de sobrevivência.** Repare
no tempo de viagem do timer travado: **65,8 s** em 3 h, contra **65,7 s** na
primeira hora. *Não muda.* Só as viagens que ainda terminam entram na média, e
elas são as curtas. Se a manchete da tela fosse "tempo de viagem", a paralisia
total do baseline seria **invisível**. O que denuncia é o
`tempo_medio_no_sistema`: **179,5 s** contra 65,5 s da seed sã — e a lacuna de
sobrevivência, **+172,9%** contra −0,3%. O detector de §10 pega isso sem nenhum
ajuste.

**(3) A `mean_queue` publicada é cega para metade da fila num travamento.**
`mean_queue` é somada sobre as **lanes de aproximação dos semáforos**
(`policy_sim._unique_approach_lanes`). Num travamento a fila transborda para
edges cujo nó de jusante **não é semáforo** — os corredores de retorno
`ret_N`/`ret_S` e os cantos des-semaforizados H1V4/H3V4:

| seed 42, timer, 10800 s | valor |
|---|---|
| `fila_media` (aproximações — a métrica publicada) | **12,06** |
| fila em todas as faixas desenháveis | **22,90** |
| mediana da média móvel de 20 amostras | **29,0** de 30 carros |

Em regime saudável a diferença é 0,5% (§6) e não importa. **Num travamento a
métrica publicada reporta 12 de uma fila real de 29.** Isso não afeta o número de
3600 s (nenhum braço trava lá), mas é um aviso direto para os agentes A5 e A6:
na rede aberta, medir fila só nas aproximações vai subestimar exatamente o
regime que interessa detectar.

**Nota sobre "0/12 travamentos".** A tabela de `RESULTADOS_ATS.md` §4 reporta
0/12 travamentos do timer, e está certa: **em 3600 s**, nenhuma das 12 seeds
trava. Em 10800 s, 1 de 2 seeds testadas trava. O número publicado não está
errado — a janela dele é que é parte do resultado, e isso precisa aparecer junto.

**Recomendação operacional para a feira:** reiniciar os dois braços em intervalo
fixo (ou reiniciar quando o detector marcar `travou`), de modo que o que está na
tela seja sempre uma janela comparável à publicada. É decisão do agente A7; a
`ArenaSumo` já entrega o sinal (`Resultado.travou`, `arena.ultimo_diagnostico
["maior_seca_s"]`).

---

## 10. O substituto do `coherence_gap` (DoD (b))

`feira/metricas.py` implementa um detector de **quatro pernas**, e nenhuma delas
usa `N` nem supõe frota fechada:

| perna | o que denuncia | onde vive |
|---|---|---|
| **conservação** `ativos_inicio + inseridos − entregues − ativos_fim − perdidos` | veículo que **evaporou** da contabilidade (teleporte, colisão, remoção) | `Resultado.conservacao` (C5) |
| **backlog de inserção** | o controlador que "vence" **estrangulando a borda** — a fila fica ótima porque o carro nem entrou | `Resultado.sane()` (C5) |
| **perdidos** | veículo perdido *e contabilizado* — fecha a conservação, mas continua sendo corrida inválida | `metricas.sinais_de_travamento` |
| **lacuna de sobrevivência** `(tempo_no_sistema − tempo_entregue) / tempo_entregue` | **população presa que não aparece na média** — o fenômeno exato que o `coherence_gap` detectava | `metricas.lacuna_sobrevivencia` |

A identidade de conservação só tem dentes porque as duas metades vêm de fontes
**independentes**: `ativos_inicio`/`ativos_fim` são a contagem de veículos vivos
lida do SUMO; `inseridos`/`entregues`/`perdidos` vêm do fluxo de eventos
(`getDepartedIDList`/`getArrivedIDList` na rede aberta; os `TripRecord` do
controlador de demanda na fechada). Se casassem por construção não haveria
detector nenhum.

A unidade contada é a **viagem ativa**, não o veículo — é o que faz a mesma
identidade valer nos dois modelos de demanda. Na rede fechada uma chegada não
tira o carro da rede: ela fecha uma viagem e abre outra no mesmo sim-step, então
entrega e ativação andam juntas e o balanço fecha em zero. O `backstop` do
`PersistentDemandController` (que registra um despawn como "viagem concluída") é
descontado da vazão e contado em `perdidos` — contá-lo como entrega infla a
vazão com um carro que evaporou.

### 10.1 Prova: denuncia travamento injetado, não acusa política sã

`scripts/detector_travamento.py`, três braços pelo **mesmo laço**, 1800 s, 3
seeds. O travamento injetado é `ControladorFake("nunca")` — todo `MANTER`, o
farol congela no eixo de referência e o cruzado nunca abre:

| braço | seed | entregues | tempo dos **entregues** | tempo **no sistema** | fila | conservação | maior seca | **lacuna** | `sane()` |
|---|---|---|---|---|---|---|---|---|---|
| timer | 42 | 809 | 65,3 s | 64,4 s | 11,94 | 0 | 17 s | **−1,4%** | sim |
| rl | 42 | 965 | 55,0 s | 54,3 s | 8,07 | 0 | 14 s | **−1,3%** | sim |
| **travado** | 42 | **7** | **20,3 s** | **1457,9 s** | 29,66 | 0 | **1741 s** | **+7086,7%** | **não** |
| timer | 43 | 820 | 64,4 s | 63,6 s | 12,08 | 0 | 21 s | −1,3% | sim |
| rl | 43 | 976 | 54,4 s | 53,7 s | 7,85 | 0 | 16 s | −1,3% | sim |
| **travado** | 43 | **8** | **18,6 s** | **1420,8 s** | 28,75 | 0 | **1772 s** | **+7528,3%** | **não** |
| timer | 100 | 762 | 69,0 s | 68,2 s | 12,46 | 0 | 18 s | −1,1% | sim |
| rl | 100 | 925 | 57,3 s | 56,6 s | 7,73 | 0 | 15 s | −1,3% | sim |
| **travado** | 100 | **3** | **27,3 s** | **1635,8 s** | 28,74 | 0 | **1766 s** | **+5884,5%** | **não** |

Leia a coluna do tempo dos entregues: o braço travado tem o **melhor tempo médio
de viagem das três** — 20,3 s contra 65,3 s do timer. Se a manchete fosse "tempo
de viagem", congelar todos os faróis seria a melhor política já produzida neste
projeto. É o artefato de sobrevivência em estado puro, e é por isso que a métrica
existe.

Agora leia a conservação: **zero nos três**. Ninguém evaporou, o backlog é zero,
e a perna que o `PLANO.md` propunha como substituto — balanço + backlog — é
**CEGA para este caso**. Na rede fechada o carro não some; ele só nunca chega. A
perna que denuncia é a **lacuna de sobrevivência**: −1,1 a −1,4% nas políticas
sãs, **+5884% a +7528%** no travamento. Três ordens de grandeza de separação, com
um limiar (25%) que não precisa de calibração fina.

A coluna `sane()` só diz "não" porque a Arena **carimbou** `travou=True` (critério
model-free: 600 s simulados sem nenhuma chegada). Os campos de MÉTRICA do
`Resultado` — conservação 0, backlog 0, 7 entregues > 0 — passam em `sane()`
sozinhos; ver §12(a).

Cobertura em teste:
`tests/test_a2_arena.py::test_detector_denuncia_travamento_injetado_e_nao_acusa_politica_sa`
(com SUMO) e `tests/test_a2_metricas.py` (sem SUMO, espelhando
`smart-traffic-maquete/tests/test_coherence_gap.py`, inclusive o caso de **borda
estrangulada** da rede aberta, que é o que a perna do backlog cobre).

---

## 11. O baseline na grade da RL (§1 nota 2)

Colocar o timer de 27 s na grade de decisão de 10 s da RL deveria mudar o
baseline: o verde só pode ser trocado num tick da grade, e 27 arredondaria para
30. Medido, seed 42, 3600 s:

| timer | entregues | tempo de viagem | fila |
|---|---|---|---|
| `di=1` (o `FixedTimerSim`, o baseline publicado) | 1623 | 65,69 s | 12,141 |
| `di=10` (na grade da RL) | 1624 | 65,6 s | 12,13 |

**Diferença desprezível — por coincidência aritmética.** Verde 27 s + amarelo
3 s = ciclo de fase de **exatamente 30 s**, que é múltiplo da grade de 10 s.
Depois do primeiro verde (que estica de 27 para 31 s, uma vez), todos os flips
caem em cima de um tick e o timer se comporta como se a grade não existisse.

**Isto não é uma propriedade do sistema, é uma coincidência de três números.** Ela
some assim que qualquer um deles mudar:

- as restrições da rede aberta são `decision_interval=5, min_green=7, yellow=3`
  (`RESTRICOES_ABERTA`), e nenhum ciclo de Webster vai cair em múltiplo de 5;
- o baseline coordenado do agente A5 tem ciclo por Webster e **split por
  interseção** — verdes diferentes por fase, quase certamente não múltiplos da
  grade.

**Recomendação ao A5:** meça o plano coordenado nas duas grades e publique a
diferença. Se o plano coordenado perder para o timer uniforme só porque a grade o
arredonda, o problema é a grade, não o plano.

---

## 12. Contratos que julgo errados (reportados, não consertados)

Os contratos estão congelados; nenhum foi tocado. Seis observações — as
cinco primeiras são buracos que apareceram MEDINDO, não lendo.

**(a) `Resultado.sane()`, sozinho, aprova uma corrida completamente travada.**
`sane()` checa quatro coisas: `travou`, `conservacao`, `backlog_insercao` e
`entregues == 0`. No braço travado de §10.1, com 7 viagens concluídas em 1800 s,
conservação zero e backlog zero, **as três checagens de MÉTRICA passam** — a
única coisa que reprova a corrida é o campo `travou`, que não é métrica: é um
carimbo que a Arena põe. Ou seja, `sane()` **não consegue** decidir a partir dos
números; ele depende de quem mediu ter percebido antes.

Isso importa porque `Resultado` é serializável e viaja: um resultado carregado
de disco, ou produzido por outra Arena (o `Fantasma` do C8, por exemplo), com
`travou=False` por omissão, passa em `sane()` com a malha parada.

Descoberto na prática: a primeira versão do meu detector de travamento só
atualizava a seca no instante de uma chegada, então uma malha que trava e nunca
mais entrega atravessava a corrida sem disparar — `travou` ficava `False` e
`sane()` devolvia `True` para as três corridas travadas. Corrigido
(`Contabilidade.seca_atual`), mas o buraco no contrato continua lá.

Sugestão: `sane()` deveria consultar a lacuna de sobrevivência (ou uma vazão
mínima), ou então o docstring deveria dizer que ele é um teste de
**contabilidade**, não de **saúde da corrida** — hoje diz "Checagem de sanidade",
que sugere a segunda coisa. Enquanto não muda,
`feira.metricas.sinais_de_travamento` faz o papel, e é ele que os scripts
consultam.

**(b) `Resultado.sane()` não olha `perdidos`.** Um veículo perdido *e
contabilizado* mantém `conservacao == 0` e passa. O docstring do campo diz
"deveria ser 0"; nada impõe isso. `sinais_de_travamento` acrescentou essa perna
(tolerância de 0,5% das viagens ativas).

**(c) `RestricoesFase.yellow` não chega ao pacote `sim`.**
`RestricoesFase.env()` exporta `ST_DECISION_INTERVAL`, `ST_MIN_GREEN` e
`ST_MAX_RED` — mas **não** o amarelo, porque `sim/environment/constants.py:98`
tem `YELLOW_DUR = 3` **hardcoded**, sem env var. Um cenário que declare
`yellow=4` seria aceito pelo `Cenario`, e a simulação rodaria com 3. A
`ArenaSumo._confere_constantes` fecha o buraco levantando `ArenaNaoConfigurada`
quando `C.YELLOW_DUR != restricoes.yellow`, mas o conserto de verdade é uma env
var `ST_YELLOW` no maquete — o que está fora da minha fronteira.

**(d) a `Chave` (C5) não carrega as `RestricoesFase`.** `Chave` é
`(cenario, seed, janela, demanda_sha)`. O C1 diz, com todas as letras, que as
restrições de fase são "as mesmas para os três braços" e que sem isso "a
comparação não vale nada" — mas nada em `comparar()` verifica isso: duas
corridas com `decision_interval` diferente produzem `Chave`s **idênticas** e a
comparação passa.

Isso não é hipotético: é **exatamente o que este documento faz** em §1 e §4.1
(timer em `di=1` contra RL em `di=10`), porque é assim que a comparação
publicada é produzida — o `FixedTimerSim` decide a cada sim-step e a RL a cada
10. A comparação continua defensável (§11 mostra que a grade não muda o timer de
27 s), mas ela é defensável **por medição**, não por construção, e a `Chave` não
ajuda. Sugestão: acrescentar um `restricoes_sha` à `Chave`, ou registrar em
`Comparacao.aviso` quando as restrições diferirem.

**(e) a guarda de `Cenario.aplicar()` (C1) compara ENV VAR, não o estado
congelado — e é contornável.** `aplicar()` levanta `CenarioJaImportado` quando
`sim.environment.constants` já está importado **e** as env vars divergem do
alvo. Basta a env var estar no lugar certo para a guarda passar, mesmo com os
escalares congelados errados. É exatamente o que acontece quando um teste faz
`monkeypatch.setattr(C, "NET_FILE", outra_rede)`, importa `net_topology` e
depois deixa o `monkeypatch` restaurar a env var.

**Isso aconteceu de verdade nesta Onda**, entre a suíte do agente A1 e a minha:
com os dois arquivos de teste no mesmo processo, a Arena rodava o cenário
`small.maquete` medindo **12 semáforos onde há 10** — sem erro, sem aviso, com
números plausíveis. Foi pego porque um teste meu afirma `topo.n == 10`.

Conserto do meu lado (`feira/arena/sumo.py:_amarra_sim`): a Arena confere o
**estado congelado** (`net_topology.NET_FILE`), não a env var, e reimporta o
pacote `sim` quando ele está desalinhado. Isso é também o que torna possível
rodar a rede **aberta**, cujos arquivos moram neste repo e que o `scenarios.py`
do maquete não conhece. Coberto por
`tests/test_a2_arena.py::test_arena_reamarra_o_sim_quando_outro_cenario_congelou_o_pacote`.

Sugestão para o contrato: `aplicar()` poderia checar
`sim.environment.constants.NET_FILE` além das env vars — é o único campo que
identifica sem ambiguidade a configuração congelada.

**(f) registro na suíte de conformidade — ação do dono do projeto.**
`ControladorTimer` e `ControladorRL` passam a suíte parametrizada do C3, mas
`tests/test_conformidade.py` está na minha lista de arquivos proibidos. Para
ligá-los, acrescente em `IMPLS_CONTROLADOR`:

```python
from feira.controladores import ControladorRL, ControladorTimer
_CKPT = "../smart-traffic-maquete/results/maq30_ats_full_best.pt"

IMPLS_CONTROLADOR = [
    ...,
    pytest.param(lambda: ControladorTimer(27), id="timer-27s"),
    pytest.param(lambda: ControladorRL(_CKPT), id="rl-ats"),   # exige torch + o .pt
]
```

Enquanto isso não acontece, a mesma suíte está **espelhada** em
`tests/test_a2_arena.py` (protocolo, ações válidas, `reset` idempotente,
`decide` antes de `reset`), e o bloco espelhado pode sair no dia do registro.

---

## 13. O que a Arena precisa da rede aberta (handoff para o A1)

A `ArenaSumo` já roda os dois modelos de demanda — a contabilidade da rede
aberta está implementada e coberta por teste (com um SUMO falso e roteirizado,
em `tests/test_a2_arena.py`), e a amarração com o pacote `sim` já reaponta
`NET_FILE`/`SUMOCFG` para `sumo/aberta/` e zera a frota persistente do `sim`
(senão ela injetaria 30 carros por cima da demanda do `.rou.xml`).

Falta **uma** coisa, e ela é do lado do A1: **quem escolhe o `.rou.xml` da seed
é o `.sumocfg`**, e quem monta a linha de comando do SUMO é o `TrafficEnv` do
maquete, que não aceita `--route-files`. A convenção que a Arena já procura é um
`.sumocfg` por seed ao lado do canônico:

    sumo/aberta/config/maquete_aberta.sumocfg
    sumo/aberta/config/maquete_aberta_s42.sumocfg   <- este, com <route-files value="../demanda/demanda_s42.rou.xml"/>

Se o arquivo por seed existir, a Arena o usa e registra
`ultimo_diagnostico["sumocfg_por_seed"] = True`. Se não existir, ela cai no
canônico — e aí **todas as seeds rodam a mesma demanda**, o que destruiria o
pareamento sem levantar erro. A alternativa (melhor) seria uma env var
`ST_ROU_FILE` no `sim`, mas isso é mudança no maquete, que está congelado.

---

## 14. Como reproduzir

```powershell
$py = '..\smart-traffic\.venv\Scripts\python.exe'

# §1 — a Arena reproduz o evaluate.py (processo novo por `--di`)
& $py scripts\reproduz_evaluate.py --braco rl    --seed 42 --segundos 3600
& $py scripts\reproduz_evaluate.py --braco timer --seed 42 --segundos 3600 --di 1

# §2/§3 — deriva ao vivo (com a demo de pé, em outro terminal)
cd ..\smart-traffic-maquete ; .\run_dashboard.ps1 maquete -NoBrowser
& $py scripts\medir_deriva.py --minutos 10 --out deriva.csv
& $py scripts\medir_deriva.py --analisar deriva.csv

# §4/§5/§6/§8/§9 — os achados por seed
& $py scripts\mede_achados.py braco --braco timer --di 1  --seeds 42,43,100,101,102,103,104,105 --segundos 3600 --out timer.json
& $py scripts\mede_achados.py braco --braco rl    --di 10 --seeds 42,43,100,101,102,103,104,105 --segundos 3600 --out rl.json
& $py scripts\mede_achados.py analisa --base timer.json --novo rl.json

# §5 — o `tail()` da tela, com as duas séries PAREADAS (um processo, dois braços)
& $py scripts\mede_achados.py tela --seeds 42,43,100 --segundos 3600

# §9 — o horizonte longo: o timer trava na seed da demo
& $py scripts\mede_achados.py braco --braco timer --di 1  --seeds 42,43 --segundos 10800 --out longo_timer.json
& $py scripts\mede_achados.py braco --braco rl    --di 10 --seeds 42,43 --segundos 10800 --out longo_rl.json

# §10 — o detector, com travamento injetado
& $py scripts\detector_travamento.py --seeds 42,43,100 --segundos 1800
```

Os CSV/JSON desta rodada ficaram fora do repositório (diretório de trabalho da
sessão); os comandos acima os regeram integralmente — todas as corridas são
determinísticas por seed.

**Estado da suíte no fecho desta auditoria:** `pytest -q` dá **134 passed, 1
failed** e `ruff check .` fica limpo, e a única falha é `tests/test_contratos.py::
test_cenario_aberto_ainda_nao_medido` — um teste do agente A0 que afirma
`aberta.maquete.warmup_s is None` e que ficou obsoleto quando o agente A1
preencheu o número medido (`warmup_s = 300,0`). Os dois arquivos envolvidos
(`tests/test_contratos.py` e `feira/contratos/cenario.py`) estão fora da minha
fronteira de escrita, então a correção fica com quem é dono deles. O invariante
que aquele teste protegia continua coberto, por
`tests/test_a2_arena.py::test_arena_recusa_cenario_sem_warmup_medido`, que
constrói um cenário sem warm-up em vez de depender do `aberta.maquete` estar
pendente.
