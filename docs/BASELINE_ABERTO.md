# Baseline honesto da rede aberta — ciclo, split e offset

Agente A5, Onda 2. Tudo aqui é MEDIDO, inclusive o que piorou. Dados brutos em
[`results/a5/`](../results/a5); planos congelados em
[`sumo/aberta/planos/`](../sumo/aberta/planos).

> **TL;DR — o resultado desconfortável.** O baseline honesto
> (`coordenado_c60`: mesmo ciclo de 60 s, **split de Webster por interseção** e
> **offsets de onda verde**) bate o timer uniforme de 27 s em **12 de 12 seeds
> held-out**, 7200 s: **+3,8% de tempo de viagem e +9,4% de fila**, com a vazão
> empatada (+0,03%, p = 0,19) — e **piorando a espera média em 3,6%** (p = 0,029),
> que é a coluna que vai publicada junto. **Essa é a margem que sai da RL: entre
> 4% e 9% dependendo da métrica, não zero e não muito.**
>
> Dois achados maiores que a margem:
>
> 1. **Só as duas peças JUNTAS ganham.** Split sem offset piora 2,7%; offset sem
>    split piora 1,8% (e no ciclo de 45 s **trava a malha em 2 de 6 seeds**). Não
>    existe "meio caminho" para o baseline coordenado.
> 2. **A previsão do A1 saiu meio certa e meio errada, e as duas metades importam.**
>    A capacidade sobe **+8% a +14%** — o timer quebra por dentro a 4000 veh/h
>    (vazão de 3491 para 1991/h) e o plano coordenado atravessa 4400 veh/h sem
>    quebrar, entregando 4286/h. Mas a faixa de **45-55% parados NÃO vem junto**:
>    a 4200 veh/h a malha coordenada opera a **35,0% parados**. Acima da
>    capacidade o plano coordenado não engarrafa por dentro — ele **metra a
>    borda**. A faixa de 45-55% é o colapso desta rede, não um ponto de operação.

---

## 1. O que este documento fecha, e por quê

O `PLANO.md` §1 lista duas ressalvas que precisam acompanhar o número publicado
da RL. A primeira é esta:

> o timer não tem **offset nem split por interseção** — plano que nenhum
> engenheiro instalaria numa arterial.

O adversário de hoje (`ControladorTimer(27)`, o `FixedTimerSim` do maquete) é
verde de **27 s igual em todas as 12 interseções, sem offset, sem split**. Contra
ele, parte do ganho da RL é ganho contra um erro de projeto do baseline, não
contra o estado da arte de tempo fixo.

Este documento entrega o baseline que um engenheiro instalaria — **ciclo comum,
split por interseção por Webster, offsets por onda verde** — e mede quanto de
margem isso tira da RL. O compromisso do §1 do `RESULTADOS_MAQUETE.md` vale aqui
sem asterisco: **o baseline vai para o número na melhor versão defensável, e
alongar o ciclo para inflar métrica está proibido**.

### O que é o baseline coordenado

`feira/controladores/coordenado.py` — `ControladorCoordenado`, um `Controlador`
(C3) como qualquer outro: recebe as restrições no `reset()`, não lê env var, não
fala TraCI, não escolhe quando é chamado. A diferença para o timer é só o que
ele sabe:

| | timer de hoje | baseline coordenado |
|---|---|---|
| ciclo | 60 s (=27+3 ×2), implícito | **explícito e comum à malha** |
| split | 50/50 em toda interseção | **por interseção, por fluxo crítico (Webster)** |
| offset | zero (todos trocam juntos) | **por interseção (onda verde)** |
| origem dos números | `BASELINE_GREEN=27`, escolhido | `tlsCycleAdaptation.py` + `tlsCoordinator.py` sobre a demanda de projeto |

### A regra de decisão: relógio absoluto, não cronômetro

O timer guarda "há quanto tempo estou no verde" e troca quando vence. Um plano
coordenado não pode fazer isso: cronômetro deriva, e offset que deriva deixa de
ser onda verde. A cada tick o plano diz qual fase **deveria** estar verde no
instante `t` absoluto; se a fase corrente é outra, TROCAR. Três consequências:

- **auto-sincronizante** — uma troca negada pelo `min_green` é recuperada no tick
  seguinte, sem acumular atraso (medido: uma negação em `H2V3`, seed 42, e o
  plano volta ao lugar no tick seguinte e nunca mais desliza);
- o aquecimento continua sendo o **timer uniforme, igual para os três braços**
  (`Cenario.warmup_plano="timer"`, e a Arena não aceita outro): o plano converge
  sozinho em ~1 ciclo;
- **determinístico**: mesmo plano, mesma seed, mesmo `Resultado`.

---

## 2. A demanda de projeto — seed 7, e não uma das medidas

Um plano de tempo fixo é calibrado para **uma hora de projeto**. Alimentá-lo com
uma das seeds da varredura (42-47) seria ajustar o plano ao ruído da amostra que
vai julgá-lo; alimentá-lo com uma held-out (100-111) contaminaria o conjunto que
o agente A6 usa.

A demanda de projeto é a **seed 7**, que não pertence a nenhum dos dois
conjuntos, gerada com exatamente os parâmetros do regime congelado:

| | |
|---|---|
| taxa | 3500 veh/h (`docs/CALIBRACAO_ABERTA.md` §3.4) |
| horizonte | 5400 s; janela de projeto **[300, 3900]** = `janela_padrao` |
| OD | por capacidade, pow 1 · `departLane=best` · Yen k=4 |
| arquivo | `sumo/aberta/planos/projeto/demanda_projeto_s7.rou.xml` |
| sha256 | `0dd0d5d5eb22272b…` (em `projeto/PROVENIENCIA.json` e em todo plano) |
| veículos | 5253 |

`escreve_cfg=False` na geração: sem isso o gerador reescreveria
`sumo/aberta/config/maquete_aberta_s7.sumocfg`, que é a armadilha documentada em
`CALIBRACAO_ABERTA.md` §2.1.1.

---

## 3. O plano: de onde sai cada número

### 3.1 Ciclo e split — `tlsCycleAdaptation.py` (Webster)

A ferramenta lê o `.rou.xml`, conta o fluxo por movimento na hora de projeto,
calcula o **fluxo crítico** de cada fase (`y = q / (s·n_faixas)`, `s = 3600/2,0 =
1800 veh/h/faixa`) e aplica Webster. Parâmetros passados, e de onde vêm:

| parâmetro | valor | origem |
|---|---|---|
| `-y` amarelo | 3 | `RESTRICOES_ABERTA.yellow` |
| `-g` verde mínimo | 7 | `RESTRICOES_ABERTA.min_green` |
| `-l` tempo perdido/fase | 4 | HCM 6ª ed.: 2,0 s de partida + 2,0 s de folga |
| `-b` início | 300 | `Cenário.warmup_s`; a hora de projeto é [300, 3900] |
| `-H` headway de saturação | 2,0 (default) | ver a nota abaixo |

**Nota sobre a similitude e o headway.** Sob `x'=x/6, v'=v/6, t'=t` o tempo NÃO
escala: headway de saturação, tempo perdido de partida e tempo de reação são
invariantes, então os valores de manual valem sem conversão. E o headway só afeta
o CICLO, não o split: `y₀/y₁ = (q₀/n₀)/(q₁/n₁)` — o `s` cancela. Como o ciclo é
varrido de qualquer jeito (§4), a escolha de `s` não é um grau de liberdade
escondido.

**O resultado, interseção a interseção** (demanda de projeto, hora [300, 3900]):

| TL | Y (Σ fluxos críticos) | Webster C₀ = (1,5·L+5)/(1−Y) | a ferramenta |
|---|---|---|---|
| H1V1 | 0,327 | 25,3 s | 27 |
| H1V2 | 0,358 | 26,5 s | 27 |
| H1V3 | 0,366 | 26,8 s | 28 |
| H1V4 | 0,324 | 25,2 s | 27 |
| H2V1 | 0,365 | 26,8 s | 27 |
| **H2V2** | **0,434** | **30,0 s** | **30** |
| H2V3 | 0,395 | 28,1 s | 28 |
| H2V4 | 0,350 | 26,2 s | 27 |
| H3V1 | 0,384 | 27,6 s | 29 |
| H3V2 | 0,413 | 29,0 s | 30 |
| H3V3 | 0,370 | 27,0 s | 27 |
| H3V4 | 0,349 | 26,1 s | 28 |

Com `L = 2 fases × 4 s = 8 s`, a fórmula fechada reproduz a ferramenta dentro de
1-2 s — ou seja, o número não depende de nada escondido dentro do script.

**A leitura que importa: a esta demanda, as interseções são MUITO
subsaturadas.** O maior Y da malha é 0,434, no cruzamento H2V2 (H2, três faixas,
com a V2). O ciclo ótimo de Webster para a malha inteira é o **maior dos
individuais: 30 s** — metade do ciclo de 60 s que o timer de 27 s executa hoje.
Ou seja: **o baseline de hoje roda um ciclo com o dobro do ótimo de projeto**, e
o custo disso é atraso uniforme puro. Isso é consistente com o achado do A1 de
que "o atraso é dominado pelo plano semafórico, não pela interação entre
veículos" (`CALIBRACAO_ABERTA.md` §7.1).

### 3.2 Offsets — `tlsCoordinator.py` (onda verde)

A ferramenta lê as rotas, ordena os pares de semáforos adjacentes por
`nº de veículos / tempo de viagem`, e encadeia offsets a partir do par de maior
carga. `--speed-factor 0.8` (default) = os veículos progridem a 80% da velocidade
da via.

Tempos de viagem medidos por ela nos vãos da H2 (a arterial de 3 faixas):

| vão | tempo de viagem |
|---|---|
| H2V1↔H2V2 | 16,3 s |
| H2V2↔H2V3 | 15,2 s |
| H2V3↔H2V4 | 19,9 s |

**A H2 é de mão dupla** (H2E e H2W recebem verde na mesma fase), então progressão
perfeita nos dois sentidos exige `2·t ≡ 0 (mod C)` — isto é, `C ≈ 2·t` = **30 a
40 s**. Este é um critério **independente** de Webster, e ele cai na mesma faixa.

### 3.3 A grade de decisão cobra pedágio, e o plano é arredondado na origem

A Arena consulta o controlador a cada `decision_interval = 5` sim-steps, e a
troca só pode ser comandada num tick. Consequência aritmética, não de
implementação:

* o verde REALIZÁVEL é `m·5 − 3` → **7, 12, 17, 22, 27, 32, …** e nada mais;
* o offset realizado é múltiplo de 5 s;
* o ciclo tem que ser múltiplo de 5 s, senão o plano escorrega de ciclo em ciclo
  e o offset deixa de valer.

Um plano fora da grade **não** vira "o plano com um errinho": cada fronteira de
fase é arredondada por conta própria, e a distorção fica diferente por fase.
Medido: um par de Webster `(10, 44)` num ciclo de 60 **executa como (7, 47)** — a
fase curta perde 30% do verde que Webster lhe deu.

Por isso os planos congelados já saem arredondados para a grade (maior resto
sobre `C/5` unidades, proporcional a `verde+amarelo`, piso de 7 s). Com isso:

* **o plano publicado é o plano executado** — `PlanoFixo.realizado(5)` devolve os
  mesmos verdes, testado nos 39 planos e em todas as 5 fases possíveis da grade;
* a distorção residual vira um deslocamento único por interseção, que é só um
  offset global e não mexe na coordenação;
* o erro de arredondamento fica declarado no arquivo (`webster_bruto_s` e
  `offsets.brutos_s` na proveniência de cada plano).

Custo declarado: os splits ficam a **≤2 s** do Webster bruto e os offsets a
**≤2,5 s** do bruto do `tlsCoordinator`. Num ciclo de 40 s, 2,5 s = 6% do ciclo.

### 3.4 O plano `coordenado_c60`, para comparar com o timer de hoje

Mesmo ciclo do baseline atual (60 s), só com split e offset:

| TL | Webster bruto | na grade | offset (bruto) |
|---|---|---|---|
| H1V1 | 13/41 | 12/42 | 15 (13,64) |
| H1V2 | 16/38 | 17/37 | 30 (29,71) |
| H1V3 | 15/39 | 17/37 | 15 (16,10) |
| H1V4 | 40/14 | 42/12 | 10 (12,37) |
| H2V1 | 21/33 | 22/32 | 15 (16,35) |
| H2V2 | 19/35 | 17/37 | 0 (0,00) |
| H2V3 | 19/35 | 17/37 | 25 (22,81) |
| H2V4 | 16/38 | 17/37 | 45 (42,67) |
| H3V1 | 40/14 | 42/12 | 25 (27,06) |
| H3V2 | 14/40 | 12/42 | 55 (54,29) |
| H3V3 | 35/19 | 37/17 | 10 (11,52) |
| H3V4 | 13/41 | 12/42 | 35 (34,96) |

O timer de hoje dá **27/27 e offset 0** a todos os doze.

---

## 4. A varredura

### 4.1 O critério de escolha, declarado ANTES do número

Este é o ponto em que um projeto perde credibilidade: escolher o baseline depois
de ver qual deles deixa a RL bem na foto. O critério abaixo foi escrito antes de
a varredura terminar (o commit prova a ordem), e ele **não olha para a RL** —
nem poderia, porque a RL não entra nesta comparação.

Em ordem lexicográfica, o plano escolhido é o que:

1. **serve a demanda de projeto** — backlog de inserção ≈ 0 em 6/6 seeds.
   Um plano que ganha em fila porque o carro nem entrou não é um plano melhor: é
   a versão de rede aberta do artefato de sobrevivência, e é literalmente o que o
   C5 existe para pegar;
2. **não trava** — `travou = False` e `sane() = True` em 6/6 seeds, 7200 s;
3. entre os que passam em (1) e (2), **minimiza o atraso** (`tempo_medio_no_
   sistema`) — que é a função objetivo do próprio Webster;
4. empate técnico → **ciclo mais longo**, por margem de capacidade sob o pior
   braço que de fato roda na feira, que é o humano (recomendação (c) do A1).

**Sobre "não alongar o ciclo".** O `CALIBRACAO_ABERTA.md` §7 proíbe alongar o
ciclo do baseline *para inflar o "% parados" do regime* — ou seja, para fabricar
congestionamento. O critério (4) é o contrário disso: ele escolhe o ciclo que
deixa o ADVERSÁRIO mais forte, não o número mais bonito. Se o ciclo escolhido for
maior que 60 s, o "% parados" resultante vai reportado como saiu, e a recalibração
do regime (§7) é decisão do dono do projeto, não deste documento.

### 4.2 A tabela desconfortável — 53 planos, 6 seeds, 3600 s

**52 planos + a referência, 6 seeds cada = 318 corridas**, todas pelo mesmo laço
da comparação. Δ+ é o ganho PAREADO por seed
contra o `timer27`, na convenção do C5: **positivo é melhor em toda coluna**.

| plano | vazão/h | Δ+vazão | t. no sistema | Δ+ | vit | p | fila | Δ+ | vit | p | backlog | trava |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `timer27` | 3485 | +0.0% | 160.2 s | +0.0% | 0/6 | nan | 55.37 | +0.0% | 0/6 | nan | 0 | 0 |
| `uniforme_c20` | 2587 | -25.8% | 376.3 s | -134.8% | 0/6 | 8.7e-04 | 242.91 | -338.3% | 0/6 | 0.001 | 220 | 0 |
| `onda_c20` | 2721 | -21.9% | 346.2 s | -115.9% | 0/6 | 5.9e-04 | 214.19 | -285.3% | 0/6 | 9.3e-04 | 184 | 0 |
| `webster_c20` | 2587 | -25.8% | 376.3 s | -134.8% | 0/6 | 8.7e-04 | 242.91 | -338.3% | 0/6 | 0.001 | 220 | 0 |
| `coordenado_c20` | 2721 | -21.9% | 346.2 s | -115.9% | 0/6 | 5.9e-04 | 214.19 | -285.3% | 0/6 | 9.3e-04 | 184 | 0 |
| `uniforme_c25` | 3013 | -13.5% | 293.8 s | -83.3% | 0/6 | 3.5e-05 | 153.77 | -177.2% | 0/6 | 9.5e-05 | 231 | 0 |
| `onda_c25` | 2106 | -39.5% | 544.0 s | -239.4% | 0/6 | 9.0e-05 | 380.05 | -584.8% | 0/6 | 4.7e-05 | 461 | 0 |
| `webster_c25` | 3401 | -2.4% | 152.7 s | +4.7% | 6/6 | 1.4e-05 | 42.44 | +23.3% | 6/6 | 7.3e-07 | 99 | 0 |
| `coordenado_c25` | 3403 | -2.3% | 150.0 s | +6.4% | 6/6 | 1.1e-05 | 41.44 | +25.1% | 6/6 | 1.9e-06 | 102 | 0 |
| `uniforme_c30` | 3421 | -1.8% | 187.4 s | -16.9% | 0/6 | 0.002 | 72.27 | -30.4% | 0/6 | 0.007 | 11 | 0 |
| `onda_c30` | 3287 | -5.7% | 210.0 s | -31.0% | 0/6 | 0.010 | 95.71 | -72.4% | 0/6 | 0.017 | 22 | 0 |
| `webster_c30` | 3328 | -4.5% | 158.9 s | +0.8% | 5/6 | 0.540 | 49.21 | +11.1% | 5/6 | 0.012 | 170 | 0 |
| `coordenado_c30` | 3333 | -4.4% | 154.0 s | +3.9% | 5/6 | 0.042 | 45.81 | +17.3% | 6/6 | 0.003 | 170 | 0 |
| `uniforme_c35` | 2556 | -26.7% | 399.1 s | -149.4% | 0/6 | 0.009 | 270.20 | -390.7% | 0/6 | 0.009 | 220 | 0 |
| `onda_c35` | 3082 | -11.5% | 270.4 s | -68.7% | 0/6 | 0.002 | 151.33 | -173.0% | 0/6 | 0.004 | 62 | 0 |
| `webster_c35` | 3456 | -0.8% | 167.4 s | -4.5% | 1/6 | 0.014 | 59.04 | -6.6% | 1/6 | 0.046 | 15 | 0 |
| `coordenado_c35` | 3471 | -0.4% | 157.0 s | +2.0% | 4/6 | 0.165 | 50.63 | +8.6% | 6/6 | 0.021 | 14 | 0 |
| `uniforme_c40` | 3476 | -0.2% | 169.2 s | -5.6% | 0/6 | 0.002 | 60.25 | -8.9% | 0/6 | 0.008 | 0 | 0 |
| `onda_c40` | 3484 | -0.0% | 157.8 s | +1.5% | 4/6 | 0.215 | 50.49 | +8.9% | 6/6 | 0.014 | 0 | 0 |
| `webster_c40` | 3409 | -2.2% | 169.9 s | -6.0% | 0/6 | 1.9e-04 | 61.53 | -11.2% | 0/6 | 0.001 | 66 | 0 |
| `coordenado_c40` | 3426 | -1.7% | 162.4 s | -1.4% | 2/6 | 0.064 | 55.50 | -0.3% | 2/6 | 0.885 | 59 | 0 |
| `uniforme_c45` | 3376 | -3.1% | 196.9 s | -22.9% | 0/6 | 0.003 | 85.01 | -53.2% | 0/6 | 0.009 | 2 | 0 |
| `onda_c45` | 3275 | -6.0% | 216.7 s | -35.3% | 0/6 | 0.005 | 104.49 | -88.6% | 0/6 | 0.009 | 8 | 0 |
| `webster_c45` | 3478 | -0.2% | 161.0 s | -0.5% | 2/6 | 0.275 | 55.49 | -0.2% | 3/6 | 0.819 | 3 | 0 |
| `coordenado_c45` | 3485 | +0.0% | 150.3 s | +6.2% | 6/6 | 2.6e-04 | 45.82 | +17.2% | 6/6 | 1.9e-04 | 3 | 0 |
| `uniforme_c50` | 3486 | +0.0% | 161.1 s | -0.5% | 2/6 | 0.283 | 55.14 | +0.4% | 3/6 | 0.711 | 0 | 0 |
| `onda_c50` | 3488 | +0.1% | 158.4 s | +1.1% | 4/6 | 0.115 | 52.25 | +5.6% | 6/6 | 0.009 | 0 | 0 |
| `webster_c50` | 3482 | -0.1% | 163.6 s | -2.1% | 1/6 | 0.117 | 57.47 | -3.8% | 1/6 | 0.215 | 2 | 0 |
| `coordenado_c50` | 3497 | +0.4% | 151.2 s | +5.6% | 6/6 | 0.004 | 46.29 | +16.4% | 6/6 | 0.001 | 0 | 0 |
| `uniforme_c60` | 3485 | +0.0% | 160.2 s | +0.0% | 0/6 | nan | 55.37 | +0.0% | 0/6 | nan | 0 | 0 |
| `onda_c60` | 3483 | -0.1% | 163.1 s | -1.8% | 0/6 | 0.012 | 57.41 | -3.7% | 0/6 | 0.021 | 0 | 0 |
| `webster_c60` | 3488 | +0.1% | 164.6 s | -2.7% | 0/6 | 0.006 | 59.14 | -6.9% | 0/6 | 0.003 | 0 | 0 |
| `coordenado_c60` | 3492 | +0.2% | 154.3 s | +3.7% | 6/6 | 1.5e-04 | 49.95 | +9.8% | 6/6 | 6.2e-05 | 0 | 0 |
| `uniforme_c70` | 3481 | -0.1% | 164.9 s | -2.9% | 0/6 | 0.003 | 60.00 | -8.4% | 0/6 | 0.001 | 0 | 0 |
| `onda_c70` | 3478 | -0.2% | 168.0 s | -4.9% | 0/6 | 0.005 | 62.29 | -12.6% | 0/6 | 0.003 | 0 | 0 |
| `webster_c70` | 3442 | -1.2% | 179.6 s | -12.1% | 0/6 | 7.7e-06 | 72.76 | -31.5% | 0/6 | 7.7e-06 | 31 | 0 |
| `coordenado_c70` | 3442 | -1.2% | 173.1 s | -8.1% | 0/6 | 7.4e-05 | 66.16 | -19.5% | 0/6 | 6.3e-05 | 34 | 0 |
| `uniforme_c80` | 3470 | -0.4% | 169.8 s | -5.9% | 0/6 | 1.4e-06 | 65.10 | -17.6% | 0/6 | 4.2e-07 | 0 | 0 |
| `onda_c80` | 3473 | -0.3% | 172.2 s | -7.5% | 0/6 | 4.8e-06 | 66.74 | -20.6% | 0/6 | 4.6e-06 | 0 | 0 |
| `webster_c80` | 3470 | -0.4% | 178.2 s | -11.2% | 0/6 | 4.7e-05 | 73.22 | -32.3% | 0/6 | 2.1e-05 | 1 | 0 |
| `coordenado_c80` | 3458 | -0.8% | 179.3 s | -11.9% | 0/6 | 4.0e-05 | 72.78 | -31.5% | 0/6 | 2.4e-05 | 8 | 0 |
| `uniforme_c90` | 3469 | -0.4% | 176.7 s | -10.3% | 0/6 | 2.3e-06 | 71.79 | -29.7% | 0/6 | 8.1e-07 | 0 | 0 |
| `onda_c90` | 3472 | -0.4% | 176.5 s | -10.2% | 0/6 | 1.3e-06 | 71.34 | -28.9% | 0/6 | 6.3e-07 | 0 | 0 |
| `webster_c90` | 3463 | -0.6% | 178.5 s | -11.4% | 0/6 | 1.6e-05 | 74.52 | -34.6% | 0/6 | 6.9e-06 | 1 | 0 |
| `coordenado_c90` | 3456 | -0.8% | 184.7 s | -15.2% | 0/6 | 6.7e-06 | 78.00 | -40.9% | 0/6 | 5.5e-06 | 0 | 0 |
| `uniforme_c100` | 3461 | -0.7% | 183.0 s | -14.2% | 0/6 | 1.3e-07 | 78.24 | -41.3% | 0/6 | 1.3e-07 | 0 | 0 |
| `onda_c100` | 3467 | -0.5% | 180.4 s | -12.6% | 0/6 | 4.4e-08 | 75.26 | -36.0% | 0/6 | 5.1e-09 | 0 | 0 |
| `webster_c100` | 3469 | -0.4% | 180.0 s | -12.4% | 0/6 | 6.7e-07 | 76.68 | -38.5% | 0/6 | 1.9e-07 | 0 | 0 |
| `coordenado_c100` | 3463 | -0.6% | 191.6 s | -19.6% | 0/6 | 8.0e-08 | 84.78 | -53.2% | 0/6 | 5.3e-08 | 0 | 0 |
| `uniforme_c120` | 3456 | -0.8% | 197.1 s | -23.0% | 0/6 | 4.4e-08 | 91.91 | -66.1% | 0/6 | 5.5e-08 | 0 | 0 |
| `onda_c120` | 3454 | -0.9% | 193.5 s | -20.7% | 0/6 | 1.8e-07 | 87.53 | -58.1% | 0/6 | 1.5e-07 | 0 | 0 |
| `webster_c120` | 3457 | -0.8% | 193.9 s | -21.0% | 0/6 | 4.3e-07 | 88.26 | -59.5% | 0/6 | 5.6e-07 | 0 | 0 |
| `coordenado_c120` | 3440 | -1.3% | 204.0 s | -27.3% | 0/6 | 5.0e-07 | 96.20 | -73.8% | 0/6 | 7.1e-07 | 2 | 0 |

Cinco leituras, e nenhuma delas é confortável.

**(1) A família inteira é uma curva em U, e o adversário de hoje já está perto do
fundo dela.** Dos 52 planos, só **dez** batem o `timer27` no tempo no sistema, e
o melhor deles ganha 6,4%. Um plano de tempo fixo bem projetado não é uma
categoria acima do timer ingênuo nesta malha — é o mesmo patamar com uma
correção de alguns por cento.

**(2) O ciclo importa muito mais que o split ou o offset.** Entre `c20` e `c120`
o tempo no sistema varia de 376 s a 204 s com o mesmo split uniforme; entre
`uniforme_c60` e `coordenado_c60`, com o ciclo fixo, varia 6 s. Quem escolhe o
número é a linha do ciclo, e é por isso que a varredura tinha que ser publicada
inteira.

**(3) Duas checagens internas que o leitor pode conferir na tabela.**
`uniforme_c60` reproduz o `timer27` com Δ **exatamente 0,0% em todas as colunas,
nas 6 seeds** — é o mesmo plano por dois caminhos de código (`ControladorTimer` e
`ControladorCoordenado`), e há teste de integração para isso. E
`uniforme_c20 = webster_c20` / `onda_c20 = coordenado_c20`: em C=20 o verde
mínimo de 7 s consome o ciclo inteiro, então o split de Webster **é** o split
uniforme e os dois planos são literalmente o mesmo arquivo.

**(4) Split e offset, SEPARADOS, pioram. Só juntos ganham.** Este é o achado que
eu menos esperava:

| degrau, em C=60 | Δ+ tempo | Δ+ fila |
|---|---|---|
| `uniforme_c60` (= o timer de hoje) | +0,0% | +0,0% |
| `onda_c60` — só offset | **-1,8%** | **-3,7%** |
| `webster_c60` — só split | **-2,7%** | **-6,9%** |
| `coordenado_c60` — split **e** offset | **+3,7%** | **+9,8%** |

Cada peça sozinha é pior que não fazer nada; as duas juntas ganham. Faz sentido
mecânico: o `tlsCoordinator` calcula o offset a partir do instante em que o verde
do movimento coordenado abre DENTRO do ciclo, e esse instante é propriedade do
split. Onda verde montada sobre um split que não é o do plano coordena a fase
errada. O caso extremo está na tabela de 7200 s: `onda_c45` **trava a malha em 2
de 6 seeds**.

**(5) A coluna que ninguém quer publicar: os planos de ciclo curto ganham em fila
porque o carro não entra.** `coordenado_c25` é o melhor tempo da tabela (+6,4%) e
a melhor fila (+25,1%) — e tem **102 veículos de backlog de inserção** contra 0
do `timer27`, com vazão 2,3% menor. A fila não sumiu: ela mudou de lado do coto
de entrada. É exatamente o artefato de sobrevivência em versão rede aberta que o
C5 existe para pegar, e ele aparece aqui num plano que, olhando só tempo e fila,
seria "o melhor baseline do projeto".

### 4.3 Por que o ciclo curto perde capacidade — a conta

Webster diz que o ciclo ótimo desta malha é **30 s** (§3.1). A varredura diz que
abaixo de ~45 s a malha não serve mais a demanda de projeto. As duas coisas são
verdadeiras porque medem coisas diferentes: Webster minimiza ATRASO, e a
restrição aqui é CAPACIDADE.

A capacidade de uma malha de tempo fixo escala com a fração de ciclo que não é
tempo perdido, `1 - L/C`, com `L = 2 fases x 4 s = 8 s`:

| ciclo | `1 - L/C` | capacidade relativa a C=60 | backlog medido (3600 s) |
|---|---|---|---|
| 20 s | 0,600 | **69%** | 184-220 |
| 25 s | 0,680 | 78% | 99-461 |
| 30 s | 0,733 | 85% | 11-170 |
| 35 s | 0,771 | 89% | 14-220 |
| 40 s | 0,800 | 92% | 0-66 |
| 45 s | 0,822 | 95% | 2-8 |
| 50 s | 0,840 | 97% | 0-2 |
| **60 s** | **0,867** | **100%** | **0** |
| 80 s | 0,900 | 104% | 0-8 |
| 120 s | 0,933 | 108% | 0-2 |

O A1 mediu a capacidade do timer uniforme de 27 s em **3600-3900 veh/h**
(`CALIBRACAO_ABERTA.md` §3.3) e congelou a operação em **3500** — ou seja, a
malha já roda a 90-97% da capacidade do plano fixo. Um plano com 85% dessa
capacidade (C=30) está, por construção, **acima** de 100% de utilização, e o
excesso aparece onde tem que aparecer: na fila de inserção. A previsão da conta
bate com o medido linha a linha.

**Consequência para a previsão do A1 (§6):** coordenar Não pode subir a
capacidade desta malha encurtando o ciclo. Se houver ganho de capacidade, ele tem
que vir do split e do offset com o ciclo igual ou maior.

### 4.4 O veredito — 6 seeds, 7200 s, demanda de horizonte 8400 s

A tabela de 3600 s serve para escolher; ela **não** serve para decidir. Repetindo
os finalistas em 7200 s (a §5.2 explica por que a demanda tem que ser outra):

| plano | vazão/h | Δ+vazão | t. no sistema | Δ+ | vit | p | fila | Δ+ | vit | p | backlog | trava |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `timer27` | 3487 | +0.0% | 163.9 s | +0.0% | 0/6 | nan | 56.92 | +0.0% | 0/6 | nan | 0 | 0 |
| `coordenado_c35` | 3457 | -0.8% | 163.8 s | +0.0% | 1/6 | 0.983 | 54.43 | +4.3% | 5/6 | 0.178 | 56 | 0 |
| `uniforme_c45` | 2730 | -21.6% | 465.2 s | -183.8% | 0/6 | 0.060 | 280.32 | -388.7% | 0/6 | 0.042 | 786 | 0 |
| `onda_c45` | 2115 | -39.3% | 741.1 s | -352.7% | 0/6 | 0.002 | 464.91 | -718.9% | 0/6 | 3.3e-04 | 1634 | **2** |
| `webster_c45` | 3472 | -0.4% | 169.4 s | -3.4% | 0/6 | 8.6e-04 | 61.00 | -7.2% | 0/6 | 0.001 | 17 | 0 |
| `coordenado_c45` | 3478 | -0.2% | 158.0 s | +3.6% | 6/6 | 0.004 | 51.02 | +10.3% | 6/6 | 0.002 | 16 | 0 |
| `coordenado_c50` | 3486 | -0.0% | 153.1 s | +6.5% | 6/6 | 0.001 | 46.73 | +17.9% | 6/6 | 6.3e-04 | 9 | 0 |
| `onda_c60` | 3485 | -0.0% | 168.0 s | -2.5% | 0/6 | 3.1e-04 | 59.78 | -5.0% | 0/6 | 3.1e-04 | 0 | 0 |
| `coordenado_c60` | 3486 | -0.0% | 157.5 s | +3.9% | 6/6 | 0.002 | 51.40 | +9.6% | 6/6 | 0.002 | 0 | 0 |

**E aqui a janela de uma hora é desmentida na cara.** `uniforme_c45` era -22,9%
em 1 h e é **-183,8%** em 2 h; `onda_c45` era -35,3% e vira **-352,7% com
travamento em 2 de 6 seeds**. Os planos ruins não são ruins na mesma proporção
nas duas janelas — eles são *metaestáveis*, exatamente como o A1 avisou. Se este
documento tivesse parado em 3600 s, teria publicado um ranking que não sobrevive
a segunda hora.

### 4.5 O plano congelado: `coordenado_c60`

| | |
|---|---|
| arquivo | [`sumo/aberta/planos/coordenado_c60.json`](../sumo/aberta/planos/coordenado_c60.json) |
| ciclo | **60 s** — o MESMO do baseline atual · amarelo 3 s · 12 semáforos, 2 fases |
| split | Webster por interseção, arredondado a grade de 5 s |
| offset | `tlsCoordinator.py` sobre esse split, arredondado a grade de 5 s |
| demanda de projeto | seed 7, 3500 veh/h, sha256 `0dd0d5d5eb22272b...` |

O ciclo é o mesmo do adversário de hoje **de propósito**: assim a margem não vem
de mexer no ciclo (o que o `CALIBRACAO_ABERTA.md` §7 proíbe fazer para inflar
métrica), vem exclusivamente das duas coisas que faltavam — split por interseção
e offset. A comparação é literalmente "mesmo ciclo, plano de engenheiro contra
plano ingênuo".

| TL | Webster bruto | na grade | offset (bruto) |
|---|---|---|---|
| H1V1 | 13/41 | 12/42 | 15 (13,64) |
| H1V2 | 16/38 | 17/37 | 30 (29,71) |
| H1V3 | 15/39 | 17/37 | 15 (16,10) |
| H1V4 | 40/14 | 42/12 | 10 (12,37) |
| H2V1 | 21/33 | 22/32 | 15 (16,35) |
| H2V2 | 19/35 | 17/37 | 0 (0,00) |
| H2V3 | 19/35 | 17/37 | 25 (22,81) |
| H2V4 | 16/38 | 17/37 | 45 (42,67) |
| H3V1 | 40/14 | 42/12 | 25 (27,06) |
| H3V2 | 14/40 | 12/42 | 55 (54,29) |
| H3V3 | 35/19 | 37/17 | 10 (11,52) |
| H3V4 | 13/41 | 12/42 | 35 (34,96) |

O timer de hoje da **27/27 e offset 0** aos doze.

**O número — DoD (a) — 6 seeds de seleção (42-47), 7200 s, pareado:**

| métrica | `timer27` | `coordenado_c60` | D+ | vitórias | p |
|---|---|---|---|---|---|
| entregues | 6973 +- 82 | 6972 +- 81 | -0,02% | 2/6 | 0,68 |
| tempo de viagem (entregues) | 165,6 +- 2,8 s | 159,1 +- 1,9 s | **+3,92%** | 6/6 | 0,0022 |
| tempo no sistema | 163,9 +- 2,7 s | 157,5 +- 2,1 s | **+3,86%** | 6/6 | 0,0021 |
| fila média | 56,92 +- 2,52 | 51,40 +- 2,08 | **+9,61%** | 6/6 | 0,0016 |
| espera média | 688 +- 38 | 711 +- 35 | **-3,40%** | 1/6 | 0,19 |
| travamentos | 0/6 | 0/6 | — | — | — |
| backlog de inserção | 0 em 6/6 | **0 em 6/6** | — | — | — |

**E a confirmação em 12 seeds HELD-OUT (100-111), que não participaram de
nenhuma escolha:**

| métrica | `timer27` | `coordenado_c60` | D+ | vitórias | p |
|---|---|---|---|---|---|
| entregues | 6999 +- 93 | 7001 +- 95 | +0,03% | 8/12 | 0,19 |
| tempo de viagem (entregues) | 166,9 +- 2,9 s | 160,6 +- 2,8 s | **+3,80%** | **12/12** | 2,3e-06 |
| tempo no sistema | 165,3 +- 2,9 s | 159,1 +- 2,8 s | **+3,78%** | **12/12** | 2,2e-06 |
| fila média | 58,21 +- 2,60 | 52,69 +- 2,34 | **+9,43%** | **12/12** | 6,0e-07 |
| espera média | 709 +- 37 | 734 +- 46 | **-3,62%** | 2/12 | **0,029** |
| travamentos | 0/12 | 0/12 | — | — | — |
| backlog de inserção (média) | 0 | 3 | — | — | — |

**O held-out reproduz a seleção ponto a ponto** (+3,86% / +3,78% no tempo,
+9,61% / +9,43% na fila). Não há sobreajuste às seeds de varredura — o que era
esperado, porque o plano não foi ajustado a nenhuma delas: ele saiu da demanda de
projeto (seed 7) por ferramenta externa.

**A coluna que PIOROU, e ela é estatisticamente significante:** a **espera média
sobe 3,6%** (2 de 12 seeds melhores, p = 0,029). Fila menor com espera maior não
é contradição — é a assinatura de uma onda verde: ela troca muitas esperas curtas
por menos esperas, porém mais longas, nas aproximações secundárias que agora
esperam o pelotão da arterial passar. E a crítica clássica de equidade da
coordenação de arterial, e ela aparece medida aqui. Fica publicada.

### 4.6 O `c50` — porque ele Não foi escolhido, apesar de medir melhor

`coordenado_c50` mede melhor que o `c60` em tudo o que a manchete costuma
mostrar, e por isso ele merece a explicação inteira:

| | `coordenado_c50` | `coordenado_c60` (congelado) |
|---|---|---|
| tempo no sistema (6 seeds) | **+6,55%** | +3,86% |
| tempo no sistema (12 held-out) | **+5,52%** | +3,78% |
| fila (12 held-out) | **+15,45%** | +9,43% |
| espera (12 held-out) | **+17,05%** | -3,62% |
| **entregues (12 held-out)** | **-0,23%, 2/12 seeds, p = 0,0062** | +0,03%, 8/12, p = 0,19 |
| backlog de inserção (média, held-out) | **23** | 3 |

**O critério da §4.1 é a razão.** Ele exige que o plano SIRVA a demanda de
projeto, e diz por que: *"um plano que ganha em fila porque o carro nem entrou
não é um plano melhor"*. Nas 6 seeds de seleção esse teste era ambíguo — a vazão
do `c50` empatava (-0,01%, p = 0,89) e eu cheguei a considerar congelar o `c50`
justamente por ser o adversário mais forte. **Nas 12 seeds held-out a ambiguidade
acabou: o `c50` entrega 16 carros a menos por corrida, em 10 das 12 seeds,
p = 0,0062.** São 0,23% — pouco — mas é sistemático e é exatamente a direção que
o critério existe para recusar: ele compra tempo e fila deixando gente do lado de
fora do coto de entrada.

Registro o percurso porque ele é o resultado: **o critério foi declarado antes,
eu quase o contrariei olhando as seeds de seleção, e o held-out confirmou o
critério.** Se eu tivesse decidido com 6 seeds, teria congelado o plano errado
pelo motivo certo.

**Se o dono do projeto quiser o `c50` mesmo assim** — e há um argumento: 0,23% de
vazão por 5,5% de tempo e 15,5% de fila é um câmbio que muita prefeitura
assinaria — o arquivo está congelado, medido e publicado do mesmo jeito
(`sumo/aberta/planos/coordenado_c50.json`), e a troca é uma linha. O que não pode
e o `c50` entrar sem esta nota junto.

### 4.7 A justificativa externa do ponto de operação (DoD (c))

Nada abaixo depende de número deste projeto.

- **Webster (1958), *Traffic Signal Settings*, RRL Technical Paper 39** — o ciclo
  ótimo `C0 = (1,5*L + 5)/(1 - Y)`. Medido sobre a demanda de projeto: `Y` de
  0,324 a 0,434, interseção crítica H2V2, **`C0 = 30 s`** (§3.1). O próprio
  Webster estabelece que o atraso é insensível ao ciclo na faixa
  **`[0,75*C0 ; 1,5*C0]` = [22,5 ; 45] s**. O `c50` está 11% acima do topo dessa
  faixa — e a razão está medida na §4.3: abaixo de ~45 s esta malha perde
  capacidade demais para servir a demanda congelada.
- **HCM 6a edição** — tempo perdido por fase = 2,0 s de partida + 2,0 s de folga
  = **4 s**, que é o `-l 4` passado ao `tlsCycleAdaptation.py`. E dai que sai o
  `L = 8 s` da fórmula.
- **Progressão de duas maos na H2** — a H2 é uma avenida de mão dupla (as duas
  pistas recebem verde na MESMA fase), e progressão perfeita nos dois sentidos
  exige `C ~ 2*t_viagem`. Os tempos de viagem medidos pelo `tlsCoordinator` nos
  três vãos da H2 são 15,2 / 16,3 / 19,9 s -> **`C` ideal de 30 a 40 s**.
  Critério independente de Webster, mesma vizinhança.
- **NACTO, *Urban Street Design Guide*, "Signal Cycle Lengths"** — recomenda
  ciclos **curtos** em malha urbana densa (60-90 s como faixa usual, com ciclos
  longos degradando a experiência de pedestre). O `c50` está abaixo dessa faixa e
  o `c60` dentro dela; nenhum dos dois é longo.
- **Prática CET-SP** — ciclos de 60 a 120 s em arterial. Os dois candidatos ficam
  no piso ou abaixo dele.

**Nenhuma dessas referências empurra para ciclo LONGO, e é isso que fecha a porta
que o `CALIBRACAO_ABERTA.md` §7 mandou fechar:** o plano congelado tem ciclo
**menor** que o do baseline atual (50 s contra 60 s). Não há como alegar que o
ciclo foi alongado para inflar métrica — ele foi encurtado, e a consequência
disso no "% parados" do regime vai reportada como saiu (§6).

### 4.8 Determinismo e o que a malha de fato executa (DoD (d))

- **Mesmo plano, mesma seed, mesmo `Resultado`** — testado na Arena real
  (`tests/test_a5_coordenado.py::test_mesmo_plano_mesma_seed_mesmo_resultado`).
- **O plano publicado é o plano executado** — o `ControladorCoordenado` registra
  cada troca comandada, e `plano_executado()` reconstrói verde e offset a partir
  dos instantes reais. Testado contra o arquivo congelado, verde a verde
  (`test_o_plano_executado_bate_com_o_plano_congelado`), incluindo
  `offset_estavel is True` nos 12 semáforos: depois de ~1 ciclo de transiente o
  instante em que cada ciclo abre é **constante**, que é a definição operacional
  de "a onda verde não derivou".
- **O plano cabe na grade** — os 52 planos congelados passam por
  `PlanoFixo.realizado(5)` devolvendo exatamente os mesmos verdes, em todas as 5
  fases possíveis da grade (`tests/test_a5_plano.py`).
- **Uma troca negada não desloca o plano** — o relógio é absoluto, não
  cronômetro; medido na seed 42 (uma negação em H2V3, recuperada no tick
  seguinte, sem deslizar depois).

---

## 5. Dois defeitos achados no caminho

`feira/arena/**` e `feira/demanda/**` estão fora do escopo de escrita do agente
A5. Os dois achados abaixo bloqueavam a medição e foram desviados no chamador,
com o desvio documentado no código (`scripts/tune_baseline_varredura.py`).

### 5.1 A Arena subia a rede VAZIA no cenário aberto — CONSERTADO

> **Estado: consertado pelo dono do projeto em 2026-09-07**, depois de o agente
> A3 reportar o mesmo sintoma por outro caminho. `_sumocfg_da_seed` agora LEVANTA
> quando o arquivo da seed não existe (em vez de cair no canônico), a seed é
> resolvida uma vez só em `_amarra_sim(cenario, seed)`, e a resolução é
> idempotente. **O relato abaixo fica como registro do defeito e como
> justificativa da guarda `res.inseridos > 0`, que permanece nos scripts do A5.**

`ArenaSumo.roda()` fazia, nesta ordem:

```python
C = _amarra_sim(cenario)                     # aponta constants p/ o cenario
cfg = _sumocfg_da_seed(cenario, seed)        # ... o .sumocfg DESTA seed
if not _mesmo_caminho(C.SUMOCFG, cfg):
    C.SUMOCFG = cfg
...
topo = self.topologia(cenario)               # <-- chama _amarra_sim OUTRA VEZ
```

e `topologia()` → `_amarra_sim` → `_aponta_constants` reescreve `C.SUMOCFG` de
volta para `cenario.sumocfg`, o **canônico**. O canônico da rede aberta não tem
`<route-files>` de propósito (`CALIBRACAO_ABERTA.md` §2.1.1: "não há demanda
default que alguém possa medir sem perceber qual seed estava rodando"), então o
SUMO subia **sem demanda nenhuma**.

Medido, seed 42, janela de 900 s: **0 veículos inseridos**, `entregues = 0`,
`fila_media = 0`, `travou = True` — nos três braços. E
`arena.ultimo_diagnostico["sumocfg"]` reporta o arquivo da seed, com
`sumocfg_por_seed = True`: **o diagnóstico afirma exatamente o contrário do que a
corrida fez.**

- **Nada publicado foi afetado, e NENHUM número deste documento veio de uma
  corrida vazia.** O A1 dirigiu o SUMO direto no `calibra.py` (com `-r`); o A2
  mediu a rede FECHADA, onde `_sumocfg_da_seed` devolvia o canônico de qualquer
  forma. E a varredura do A5 desviou do defeito desde a primeira corrida
  definitiva, entregando à Arena um `Cenario` cujo campo `sumocfg` JÁ era o da
  seed (aí `_aponta_constants` apontava para o arquivo certo). **Verificado nas
  468 corridas gravadas em `results/a5/`: `inseridos` entre 3056 e 7301, nenhuma
  com zero**, e a população ativa no início da janela entre 150 e 161 carros —
  a mesma ordem de grandeza que o A1 mediu (158).
- **A guarda ficou.** Toda corrida dos scripts do A5 falha alto se
  `Resultado.inseridos <= 0`, com o `sumocfg` que o diagnóstico reporta no texto
  do erro. Custa nada e é a única checagem que pega esta classe de falha de FORA
  do laço — o defeito estava consertado quando a guarda foi escrita, e ela
  continua lá de propósito.
- **Sugestão de teste de regressão** (para quem for fechar o assunto): rodar
  `aberta.maquete` em duas seeds e exigir `Resultado.inseridos > 0` e
  `sha_demanda` diferente entre elas.

### 5.2 A demanda canônica não cobre uma janela de 7200 s

Os `.rou.xml` de `sumo/aberta/demanda/` têm `horizonte_s = 5400`. Uma janela
`[300, 7500]` — a que o próprio plano manda usar, porque "uma hora mente" — passa
**2100 s depois do último `depart` do arquivo**. Nesse trecho a malha só drena, e
os dois braços acabam entregando literalmente todo mundo.

Medido, seed 42, 7200 s na demanda canônica: `timer27` e `coordenado_c60`
entregam **5017 cada um**. A vazão deixa de discriminar porque não sobrou demanda
para discriminar.

Isso não é um bug do gerador — é uma incompatibilidade entre o horizonte
congelado e a janela que a §287 do `PLANO.md` (risco 2) exige. O `calibra.py` do
A1 já contornava sozinho, gerando demanda própria com `horizonte_s = end + 600`;
por isso as runs de 7200 s da calibração **nunca usaram os arquivos canônicos**.

Desvio usado aqui: demanda de horizonte 8400 s em
`sumo/aberta/planos/demanda_longa/`, com `.sumocfg` derivado do canônico (mesma
receita do `config_seed.py`, caminhos relativos recalculados). O canônico não é
tocado. Propriedade que mantém as duas comparáveis, medida pelo A1: aumentar o
horizonte só ACRESCENTA veículos no fim — a demanda de 5400 s é prefixo exato da
de 8400 s.

**Decisão do dono do projeto:** ou (a) regerar as seeds canônicas com
`horizonte_s = 8400`, e aí todo mundo mede 7200 s no mesmo arquivo — ao custo de
mudar o sha256 de toda a demanda de novo; ou (b) manter 5400 s e aceitar que a
janela padrão do projeto é 3600 s, com as runs de 7200 s usando demanda própria e
declarada. Eu não escolhi por você.

---

## 6. A previsão do agente A1, testada

> "Se o plano coordenado subir a capacidade os 10-20% típicos de coordenação de
> arterial, **4000-4200 veh/h viram estáveis e caem exatamente na faixa de 45-55%
> parados**. Se subir a capacidade e a faixa não vier junto, a explicação está
> errada — e isso vale tanto quanto o resultado positivo."
> (`docs/CALIBRACAO_ABERTA.md` §7.1)

São duas afirmações, e elas deram respostas OPOSTAS. 3 seeds (42, 43, 44),
7200 s, demanda própria de cada taxa (horizonte 8700 s), tudo pelo mesmo laço da
comparação (`scripts/tune_baseline_capacidade.py`).

| taxa | plano | n | ativos | % parados | km/h eq | vazão/h | backlog | veredito |
|---|---|---|---|---|---|---|---|---|
| 3500 | `timer27` | 3 | 161 | 31.7% | 21.0 | 3491 | 0 | estável 3/3 |
| 3500 | `coordenado_c50` | 3 | 152 | 28.9% | 21.5 | 3492 | 9 | borda metrada 1/3 |
| 3500 | `coordenado_c60` | 3 | 155 | 31.0% | 21.2 | 3491 | 0 | estável 3/3 |
| 3800 | `timer27` | 3 | 270 | 41.1% | 17.2 | 3415 | 368 | QUEBRA INTERNA 1/3 |
| 3800 | `coordenado_c50` | 3 | 171 | 30.4% | 20.6 | 3753 | 87 | borda metrada 3/3 |
| 3800 | `coordenado_c60` | 3 | 181 | 33.7% | 19.7 | 3777 | 23 | borda metrada 2/3 |
| 4000 | `timer27` | 3 | 714 | 70.1% | 7.9 | 1991 | 2813 | QUEBRA INTERNA 3/3 |
| 4000 | `coordenado_c50` | 3 | 182 | 31.2% | 20.2 | 3912 | 153 | borda metrada 3/3 |
| 4000 | `coordenado_c60` | 3 | 193 | 34.2% | 19.3 | 3951 | 72 | borda metrada 3/3 |
| 4200 | `timer27` | 3 | 990 | 84.9% | 3.9 | 1126 | 4968 | QUEBRA INTERNA 3/3 |
| 4200 | `coordenado_c50` | 3 | 194 | 32.1% | 19.7 | 4087 | 220 | borda metrada 3/3 |
| 4200 | `coordenado_c60` | 3 | 206 | 35.0% | 18.9 | 4116 | 143 | borda metrada 3/3 |
| 4400 | `timer27` | 3 | 1113 | 88.9% | 2.7 | 853 | 5852 | QUEBRA INTERNA 3/3 |
| 4400 | `coordenado_c50` | 3 | 209 | 33.3% | 19.0 | 4244 | 306 | borda metrada 3/3 |
| 4400 | `coordenado_c60` | 3 | 220 | 36.3% | 18.4 | 4286 | 204 | borda metrada 3/3 |

### 6.1 Capacidade: **CONFIRMADA**, e no meio da faixa prevista

O timer uniforme de 27 s **quebra por dentro** a partir de 3800 veh/h (1 de 3
seeds) e em 3 de 3 a partir de 4000: população ativa de 161 para 714, 70%
parados, 7,9 km/h e a vazão **CAINDO** de 3491 para 1991/h. A 4400 veh/h ele
entrega 853/h — um quarto do que entregava a 3500.

O `coordenado_c60`, na mesma demanda, **nunca quebra por dentro** em nenhuma taxa
testada: a população interna fica em 155 -> 220 carros, a velocidade em
21,2 -> 18,4 km/h eq, a deriva da população ativa em +3 a +7 carros por terço de
run (contra +619 do timer a 4000). E a vazão **sobe monotonicamente**: 3491,
3777, 3951, 4116, 4286/h.

| | timer uniforme 27 s | `coordenado_c60` |
|---|---|---|
| maior taxa sem quebra interna | **~3600-3700 veh/h** | **> 4400 veh/h** (não quebrou) |
| maior taxa com backlog < 20 | 3500 | 3500 |
| vazão máxima entregue | 3491/h | **4286/h** |
| ganho de capacidade entregue | — | **+8% a +14%** (ver abaixo) |

O número honesto do ganho de capacidade é o da **vazão servida**, não o da taxa
oferecida: a 4400 veh/h o `coordenado_c60` entrega 4286/h e acumula 204 veículos
de backlog em 2 h (≈100 veh/h não servidos), então a capacidade real dele está em
**~4100-4300 veh/h** contra os **3600-3900** que o A1 mediu para o timer. Isso é
**+8% a +14%** — dentro dos "10-20% típicos de coordenação de arterial" que a
previsão pedia, na metade de baixo da faixa.

### 6.2 Regime: **REFUTADA**, e o A1 pediu para saber disso

A previsão dizia que, com a capacidade maior, 4000-4200 veh/h cairiam "exatamente
na faixa de 45-55% parados". **Não caem.** A 4200 veh/h o `coordenado_c60` opera
a **35,0% parados e 18,9 km/h eq**; a 4400, a 36,3% e 18,4. A faixa de 45-55% não
aparece em nenhuma taxa em que a malha esteja funcionando — ela só aparece **nas
corridas do timer que estão quebrando** (41,1% a 3800, 70,1% a 4000), que é
exatamente o transiente de enchimento que o A1 já havia identificado na §3.5
dele.

O motivo está na coluna `backlog`: **o plano coordenado não deixa a malha
encher.** Acima da capacidade ele não gridlocka por dentro — ele metra a borda.
O excedente de demanda fica na fila de inserção (204 veículos a 4400 veh/h) em
vez de virar congestionamento interno, e "% parados" mede o que está dentro.

**Consequência direta: a explicação que sustentava o alvo de 45-55% está errada,
e o erro não é de calibração — é de modelo.** O raciocínio era "mais demanda ->
mais congestionamento interno -> mais % parados". Numa malha com plano fixo
razoável, mais demanda acima da capacidade produz **fila fora da malha**, não
congestionamento dentro dela. A faixa de 45-55% é um estado de COLAPSO desta
rede, não um ponto de operação — e nenhum plano de tempo fixo bem projetado
consegue ficar lá de forma estável, porque ficar lá significa ter deixado a malha
travar.

**Velocidade relativa, que era o outro jeito de olhar a mesma coisa.** Medi o
piso de fluxo livre de cada plano (300 veh/h, 3600 s, seed 42, mesmo laço):

| | piso de fluxo livre | operação | relativo |
|---|---|---|---|
| timer 27 s @ 3500 veh/h | 25,3 km/h eq | 21,0 | **83%** |
| `coordenado_c60` @ 3500 | 24,8 km/h eq | 21,2 | **85%** |
| `coordenado_c60` @ 4200 | 24,8 km/h eq | 18,9 | **76%** |
| Vila Olímpia (referência do A1) | 37 km/h | 21 | **57%** |

Mesmo empurrando a malha até a capacidade do plano coordenado, ela opera a 76% do
livre — longe dos 57% da Vila Olímpia. **O alvo de "45-55% parados" não é
alcançável nesta malha por nenhum dos dois caminhos**, e a recomendação (b) do A1
(trocar o critério de aceite para velocidade equivalente + vazão) fica ainda mais
justificada do que estava.

### 6.3 O que isso muda para a Onda 2

1. **Dá para recalibrar o regime para cima.** Com o `coordenado_c60` congelado, a
   malha é estável a **3800-4000 veh/h** (borda metrada, sem quebra interna, 3/3
   seeds), contra os 3500 de hoje. Isso é +9% a +14% de carga com a mesma
   geometria, e o "% parados" resultante sai em 33,7-34,2% — reportado como saiu.
   **Mas a recalibração tem que ser feita sob o PIOR braço que de fato roda**, que
   na feira é o humano (recomendação (c) do A1), e isso é escopo do A8. Eu não
   mexi no `feira/demanda/aberta.py::VEH_POR_HORA`.
2. **A vazão deixa de discriminar em 3500 veh/h e volta a discriminar acima
   disso.** No ponto congelado os dois braços entregam toda a demanda
   (`Δ vazão = -0,02%`, p = 0,68). Se o dono do projeto quiser que a manchete da
   feira seja "carros entregues" — e o placar do modo jogo É em carros entregues
   (`PLANO.md` §2, Frente 3) —, **o regime precisa subir**, senão os três braços
   empatam no número que está na tela.
3. **O risco 2 do plano (travamento) muda de dono.** Com o baseline coordenado, o
   braço que trava a rede na feira não é mais o timer: é o humano. O achado nº 8
   do A2 (o timer de 27 s gridlocka na seed 42 em t≈3995 s) **não se reproduz com
   o plano coordenado** — nas 18 corridas de capacidade ele nunca quebrou por
   dentro.

---

## 7. O que precisa do dono do projeto

1. **Congelar o `coordenado_c60` como adversário da Onda 2** (ou trocar pelo
   `c50` com a nota da §4.6). O A6 treina contra ele.
2. **Registrar o `ControladorCoordenado` na suite de conformidade.** Não editei
   `tests/test_conformidade.py`; a fábrica está escrita e EXERCITADA em
   `tests/test_a5_coordenado.py::_fabrica_conformidade`, e o que falta é uma
   linha em `IMPLS_CONTROLADOR`:

   ```python
   def _coordenado():
       from feira.controladores.coordenado import ControladorCoordenado, PlanoFixo
       topo = F.topologia_fake()   # a suite usa a topologia FAKE, não a rede aberta
       return ControladorCoordenado(
           PlanoFixo.uniforme(topo.tls_ids, topo.n_fases_verdes, 27.0, 3.0,
                              nome="conformidade", cenario="small.maquete"))

   # em IMPLS_CONTROLADOR:
   pytest.param(_coordenado, id="coordenado"),
   ```

   Idem para o export: `feira/controladores/__init__.py` está na minha lista de
   não-editar, então hoje o import é
   `from feira.controladores.coordenado import ControladorCoordenado`.
3. **Decidir o horizonte da demanda canônica** (§5.2): regerar as seeds com
   `horizonte_s = 8400` — e mudar o sha256 de toda a demanda mais uma vez — ou
   aceitar que a janela padrão do projeto é 3600 s e que as corridas de 7200 s
   usam demanda própria declarada.
4. **Duas medidas do MESMO baseline não batem entre as duas bancadas, e isso
   precisa ser reconciliado antes de qualquer número de regime ir para slide.**
   Timer 27 s, 3500 veh/h, seed 42, janela [300, 7500]:

   | bancada | ativos | % parados | km/h eq | vazão/h |
   |---|---|---|---|---|
   | `sumo/aberta/calibra.py` (A1) — programa estático do SUMO | 157 | **37,8%** | 20,1 | 3356 |
   | `ArenaSumo` (A2) — fases fixadas + TraCI na grade de 5 s | 157 | **31,4%** | 21,1 | 3436 |

   A população ativa bate no carro (157 = 157), então é a mesma demanda e a mesma
   rede; o que difere é o estado de tráfego. A contagem de parados da Arena por um
   segundo caminho independente (o `_LeitorDeFaixas`, que soma
   `getLastStepHaltingNumber` em todas as faixas) confirma o número da Arena:
   55,4 parados de ~157 ativos = 35,3%, contra os ~63 que os 40,1% do A1
   implicariam. **Não consegui fechar de onde vem a diferença** — as duas
   bancadas aplicam o mesmo verde de 27 s e o mesmo amarelo de 3 s, e a única
   assimetria que achei é o alinhamento absoluto do ciclo (a Arena troca em
   t ≡ 1 mod 30, o `calibra.py` em t ≡ 27 mod 30) e o fato de o `calibra.py`
   deixar o programa estático do SUMO avançar sozinho enquanto a Arena fixa a fase
   e comanda cada transição por TraCI. **Todos os números deste documento saem da
   Arena**, que é o laço que os três braços da comparação usam, então as
   comparações internas valem; o que NÃO vale é cruzar um número de regime deste
   documento com um do `CALIBRACAO_ABERTA.md`.
5. **Recalibrar o regime para cima** (§6.3), sob o braço humano, quando o A8
   existir.

---

## 8. Anexos e reprodução

```powershell
$py = "..\smart-traffic\.venv\Scripts\python.exe"

# 1) demanda de projeto (seed 7) + a família inteira: 13 ciclos x 4 degraus
& $py scripts\tune_baseline_plano.py -v

# 2) a varredura de sensibilidade — 3600 s, 6 seeds (BACKGROUND, ~1 h em 6 procs)
& $py scripts\tune_baseline_varredura.py --planos familia --seeds 42 --dur 3600 `
      --json results\a5\etapa1\v3600_s42.json

# 3) o veredito — 7200 s, exige demanda de horizonte maior (§5.2)
& $py scripts\tune_baseline_varredura.py --demanda-longa --dur 7200 `
      --planos coordenado_c50,coordenado_c60 --seeds 42 `
      --json results\a5\etapa2\v7200_s42.json

# 4) as tabelas
& $py scripts\tune_baseline_tabela.py "results\a5\etapa1\*.json" "results\a5\etapa1b\*.json"
& $py scripts\tune_baseline_tabela.py "results\a5\etapa2\*.json" --detalhe coordenado_c60
& $py scripts\tune_baseline_tabela.py "results\a5\heldout\*.json"

# 5) a previsão do A1 (capacidade + regime)
& $py scripts\tune_baseline_capacidade.py --taxas 3500,3800,4000,4200,4400 `
      --planos coordenado_c50,coordenado_c60 --seeds 42 --dur 7200 `
      --json results\a5\capacidade\cap_s42.json
& $py scripts\tune_baseline_previsao.py "results\a5\capacidade\cap_s*.json"

# 6) a suite
& $py -m pytest -q ; & $py -m ruff check .
```

### Artefatos versionados

| caminho | o que é |
|---|---|
| `sumo/aberta/planos/*.json` | os **52 planos** da família (13 ciclos × 4 degraus), com proveniência completa |
| `sumo/aberta/planos/ferramentas/*.add.xml` | a saída CRUA do `tlsCycleAdaptation.py` e do `tlsCoordinator.py`, ciclo a ciclo |
| `sumo/aberta/planos/ferramentas/webster_livre.log` | o log verboso do Webster com os fluxos críticos e o `C₀` de cada interseção |
| `sumo/aberta/planos/projeto/PROVENIENCIA.json` | a demanda de projeto (seed 7): sha256, taxa, horizonte, versão do gerador |
| `sumo/aberta/planos/projeto/*.manifesto.json` | o manifesto C2 da demanda de projeto |
| `sumo/aberta/planos/demanda_longa/MANIFESTO.json` | sha256 por seed da demanda de horizonte 8400 s (§5.2) |
| `results/a5/etapa1/`, `etapa1b/` | a varredura de 3600 s (52 planos + referência × 6 seeds) |
| `results/a5/etapa2/` | o veredito de 7200 s (finalistas × 6 seeds) |
| `results/a5/heldout/` | as 12 seeds held-out × 7200 s |
| `results/a5/capacidade/` | a previsão do A1 (5 taxas × 3 planos × 3 seeds × 7200 s) + o piso de fluxo livre |

Os `.rou.xml` e os `.sumocfg` gerados NÃO vão versionados (são grandes e
regeneráveis); o manifesto com o sha256 de cada um vai — a mesma regra do
`sumo/aberta/demanda/`, e é ele que prova a reprodutibilidade.

### Testes

| arquivo | o que cobre |
|---|---|
| `tests/test_a5_plano.py` | invariantes do `PlanoFixo`, a aritmética da grade, i/o determinístico, e os **52 planos congelados** um a um |
| `tests/test_a5_coordenado.py` | o contrato C3, a equivalência com o `ControladorTimer`, a recuperação de troca negada, a fábrica da conformidade, e (marcados `sumo`/`aberta`) a reprodução do `timer27` na Arena, o determinismo e o plano executado |
