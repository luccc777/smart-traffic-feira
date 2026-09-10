# A política RL na rede aberta — treino, seleção e held-out

Agente A6. Retreino da DDQN+GNN no cenário `aberta.maquete` contra o baseline
coordenado congelado (`docs/BASELINE_ABERTO.md` §4.5), e a validação nas 12 seeds
held-out.

---

## 0. TL;DR

- **A política nova vence o `coordenado_c60` nas três métricas em 12 de 12 seeds
  held-out**, com p entre 8,2e-08 e 5,2e-13, na janela de 7200 s. DoD (a)
  fechada com folga.
- **A política que está em produção hoje PERDE, e perde feio:** rodada na mesma
  bancada e na mesma janela, `maq30_ats_full_best.pt` entrega **3141 contra 7001**
  carros (−55,1%), **trava a rede em 3 de 12 seeds** e estrangula a borda em mais
  8. A medição do A3 ("93 e 82 contra 111 e 109") era o começo desse colapso,
  vista numa janela curta demais para mostrá-lo inteiro.
- **A alavanca que decidiu foi o retreino no cenário, não o warm start.** Partir
  dos pesos da rede fechada comprou ~50 episódios (≈70 min); a política treinada
  do zero chega ao mesmo lugar em 160 episódios (§5.1).
- **`queue` continua ganhando de `pressure`**, também na rede aberta. A hipótese
  de que max-pressure viraria o resultado aqui está **refutada** (§5.2).
- **5/7 continua sendo a grade certa, e o A/B tem uma ressalva grande**: mudar a
  grade muda o adversário junto (§1.5). Em números absolutos, 10/10 entrega
  MENOS (7016,5 contra 7025,7) com fila 28% pior — mesmo tendo o percentual mais
  bonito.
- A métrica que o baseline coordenado PIORAVA — a **espera média**, a crítica de
  equidade da onda verde (`BASELINE_ABERTO` §4.5) — melhora **+74,3%** com a RL.

| braço | grade | entregues | fila | tempo no sistema | travamentos |
|---|---|---|---|---|---|
| `coordenado_c60` | 5/7 | 7000,9 | 52,69 | 159,06 s | 0/12 |
| **`rl:aberta_v1_queue_di5`** | **5/7** | **7025,7** | **31,22** | **137,20 s** | **0/12** |
| `rl:aberta_v3_queue_mr60` | 5/7 | 7029,0 | 30,45 | 135,66 s | 0/12 |
| `rl:aberta_v5_queue_di10` | 10/10 | 7016,5 | 40,03 | 145,70 s | 0/12 |
| `coordenado_c60` | 10/10 | 6814,6 | 56,49 | 165,07 s | 0/12 |
| `maq30_ats_di5_full` (transferida) | 5/7 | 4391,8 | 435,05 | 745,22 s | **2/12** |
| `maq30_ats_full` (**em produção**) | 5/7 | 3140,8 | 667,81 | 1348,57 s | **3/12** |

---

## 1. O método — o que o loop do maquete não podia fazer aqui

O `sim.training.train` do maquete treina na rede FECHADA. Reaproveitá-lo direto
aqui produziria uma política inválida por quatro motivos independentes (§1.1 a
§1.4), e `feira/treino/loop.py` existe para fechar os quatro. A §1.5 é um achado
que saiu do caminho e muda como se LÊ o A/B de espaço de ação.

### 1.1 A demanda ROTACIONA por episódio

`train.py` faz `env = TrafficEnv(seed=cfg.seed, deterministic_demand=False)`
**uma vez** e depois `env.reset()` por episódio. Na rede fechada isso basta: a
frota persistente sorteia destinos novos a cada reset, então cada episódio é uma
realização diferente.

Na rede aberta a demanda não vem do controlador de frota — vem do `.rou.xml` que
o `constants.SUMOCFG` aponta, e esse ponteiro é **fixo na run inteira**. Todo
episódio veria a MESMA realização de 8400 s, e a política decoraria uma sequência
de pelotões em vez de aprender uma política.

O loop daqui reaponta `C.SUMOCFG` (e o `--seed` do SUMO) a cada episódio,
sorteando sem reposição de um pool de 24 seeds de treino. Verificado em
`tests/test_a6_treino.py::test_o_loop_troca_a_demanda_entre_episodios`: o
`.sumocfg` e o sha256 da demanda mudam entre episódios consecutivos.

### 1.2 As três faixas de seed são disjuntas

| faixa | uso | quem gasta |
|---|---|---|
| 42-47 | varredura/calibração | o plano congelado saiu delas (`BASELINE_ABERTO` §4) |
| **200-223** | **treino** | 24 seeds novas, geradas para o A6 |
| **230-233** | **validação** | escolhe o checkpoint E escolhe a variante |
| 100-111 | **held-out** | gasto UMA vez, pelo vencedor |

`feira.treino.ambiente.checa_disjuncao` levanta `SeedContaminada` se qualquer uma
encostar na outra. Não é paranoia decorativa: treinar numa held-out não quebra
nada em tempo de execução — só devolve um número mais bonito e sem valor.

As seeds novas saíram do gerador canônico, com o mesmo horizonte de 8400 s:

```powershell
..\smart-traffic\.venv\Scripts\python.exe -m feira.demanda --seeds 200-223,230-233
```

As 18 seeds canônicas **não foram tocadas**.

### 1.3 A seleção é por VAZÃO, com porta de sanidade

DoD (c), e o motivo está medido no maquete (`docs/RESULTADOS_ATS.md` §5): o tempo
médio de viagem **só conta quem chegou**. Uma política que trava a rede melhora
essa métrica por seleção de amostra — foi assim que uma política que travava em
2 de 12 seeds virou "a melhor de todas" naquele repositório.

Aqui o checkpoint só concorre se as corridas de validação forem sãs; entre as
sãs, vence a maior `entregues`.

**E `Resultado.sane()` sozinho NÃO basta — isto foi medido nesta corrida.** A
variante `pressure`+`max_red` produziu, no episódio 10, uma validação com
**lacuna de sobrevivência de 94,1% e backlog de inserção de 660 carros** que o
`sane()` APROVOU: o backlog ficou em 9,8% dos agendados, um décimo de ponto
abaixo do teto de 10% do C5. A porta passou a exigir também
`feira.metricas.sinais_de_travamento` vazio (limiar de lacuna declarado pelo
chamador, como o C5 manda).

> **Ressalva honesta:** as 6 runs deste documento rodaram com a porta ANTIGA (só
> `sane()` + `travou`), porque o furo foi descoberto com elas em voo. A porta
> estrita entrou no código depois e vale daqui para a frente. O que protege os
> números publicados é que a rodada de seleção e a held-out reportam
> `sinais_de_travamento` seed a seed — e no vencedor eles vêm **vazios em 12 de
> 12** (§4).

### 1.4 A avaliação passa pela Arena, contra o plano coordenado

`evaluate_policy` e `FixedTimerSim` do maquete pressupõem a frota FECHADA, e não
há N numa rede aberta. Toda medida deste documento sai da `ArenaSumo`, com os
dois braços na mesma `Chave` (C5) — mesmo cenário, mesma seed, mesma janela,
mesmo sha de demanda e **mesma assinatura de espaço de ação**.

Toda corrida confere `res.inseridos > 0` (`feira/treino/avalia.py::CorridaVazia`).

**Conferência de proveniência:** o braço `coordenado_c60` medido aqui devolve
**7000,9 entregues e fila 52,69** nas 12 held-out — os mesmos 7001 e 52,69 que a
§4.5 do `BASELINE_ABERTO.md` publicou. A bancada reproduz o baseline do A5 no
dígito.

### 1.5 O A/B de espaço de ação NÃO é um A/B do mesmo adversário — medido

A alavanca 2 do escopo pede o A/B de 5/7 contra 10/10. Ele foi feito, e o
resultado tem uma ressalva que precisa vir ANTES do número: **mudar a grade
também muda o baseline**, porque as restrições de fase são as mesmas para os três
braços (C1) e o `coordenado_c60` passa a ser executado na grade nova.

`PlanoFixo.realizado()` diz exatamente o que a malha executa em cada grade:

| grade | interseções com split distorcido | offset |
|---|---|---|
| **5 s** (o default do C1) | **0 de 12** — o plano é executado EXATO | +3 s em todos os 12 (é o amarelo; a onda verde fica intacta) |
| **10 s** | **6 de 12** — 12/42→7/47, 42/12→47/7, 22/32→17/37, 42/12→37/17, 12/42→7/47 (×2) | +3 s em 5 e +8 s em 7 — a onda verde QUEBRA |

E isso aparece no número: o mesmo `coordenado_c60`, nas mesmas 12 held-out e na
mesma janela, cai de **7000,9 para 6814,6 entregues**, com a fila subindo de
52,69 para 56,49 e o tempo no sistema de 159,1 s para 165,1 s.

**Consequência para a leitura do A/B:** uma vitória percentual da RL em 10/10 é,
em parte, vitória sobre um adversário mutilado pela própria grade. Por isso a
comparação entre variantes é feita em **número absoluto**, e por isso a rodada de
seleção só deixa concorrer as variantes na grade do contrato.

---

## 2. As seis variantes treinadas

Todas: 160 episódios × 3600 s simulados, aquecimento de 300 s sob o timer de 27 s
antes de o agente assumir, estado `ats` (26 dims), DDQN+GNN sem dueling,
`lr=3e-4`, `γ=0,99`, buffer 50k, batch 64, target a cada 1000 passos. Um processo
por variante (`constants` é singleton de processo). 16 CPUs, ~3,3 h em paralelo.

| # | nome | recompensa | grade | `max_red` | warm start | ε |
|---|---|---|---|---|---|---|
| v1 | `v1_queue_di5` | queue | 5/7 | 0 | `maq30_ats_di5_full` | 0,20 → 0,01 em 40k |
| v2 | `v2_pressure_di5` | pressure | 5/7 | 0 | `maq30_ats_di5_full` | idem |
| v3 | `v3_queue_mr60` | queue | 5/7 | **60 s** | `maq30_ats_di5_full` | idem |
| v4 | `v4_pressure_mr60` | pressure | 5/7 | **60 s** | `maq30_ats_di5_full` | idem |
| v5 | `v5_queue_di10` | queue | **10/10** | 0 | `maq30_ats_full` | 0,20 → 0,01 em 20k |
| v6 | `v6_queue_semwarm` | queue | 5/7 | 0 | **nenhum** | 1,00 → 0,01 em 60k |

**Warm start — a escolha do checkpoint.** `maq30_ats_di5_full_best.pt` é o único
do maquete treinado em `decision_interval=5 / min_green=7`, que é exatamente a
grade de `RESTRICOES_ABERTA` (conferido no `env_scenario` do `config.json` da run
dele). Isso importa mais do que parece: `traffic_env._NORM_WAIT` é
`max(30, 6·(MIN_GREEN+YELLOW))` — a normalização do estado MUDA com a grade, e um
checkpoint de 10/10 vê as features de espera em outra escala. O braço 10/10 do
A/B partiu do `maq30_ats_full_best.pt` pelo mesmo motivo.

**O `global_step` do checkpoint é zerado no warm start.** Carregá-lo (20601 e
44001) deixaria o ε no piso e o fine-tuning começaria 100% guloso. O cronograma
de exploração é da run, não herança.

**`max_red = 60 s`** não é chute: é o ciclo do plano congelado. Sob o `c60` toda
fase recebe verde uma vez a cada 60 s, então `max_red=60` iguala a pior
starvation da RL à do adversário. (O C1 já recusa `max_red ≤ min_green+yellow`.)

---

## 3. A rodada de seleção — 4 seeds de validação (230-233), 7200 s

O critério foi declarado no código antes de qualquer corrida held-out
(`scripts/treina_aberta_selecao.py`): **maior vazão, entre as variantes na grade
do contrato**; empate desempata pela trinca.

| variante | entregues | Δ+ | fila | Δ+ | t. sistema | Δ+ | trincas | travam. |
|---|---|---|---|---|---|---|---|---|
| `coordenado_c60` (5/7) | 7063,5 | — | 53,67 | — | 159,5 s | — | — | 0/4 |
| **v1 `queue` 5/7** | **7094,5** | **+0,44%** | 31,34 | +41,55% | 136,9 s | +14,11% | **4/4** | 0/4 |
| v6 `queue` s/ warm | 7093,8 | +0,43% | 33,01 | +38,47% | 139,0 s | +12,81% | 4/4 | 0/4 |
| v3 `queue` mr60 | 7093,0 | +0,42% | **30,87** | **+42,45%** | **135,6 s** | **+14,92%** | 4/4 | 0/4 |
| v2 `pressure` 5/7 | 7091,0 | +0,39% | 34,39 | +35,94% | 140,9 s | +11,66% | 4/4 | 0/4 |
| v4 `pressure` mr60 | 7090,0 | +0,37% | 34,95 | +34,86% | 142,0 s | +10,95% | 4/4 | 0/4 |
| v5 `queue` 10/10 † | 7087,8 | +3,03% | 40,59 | +28,61% | 145,8 s | +11,52% | 4/4 | 0/4 |

† fora de concurso: o baseline dele é o `coordenado_c60` executado na grade de
10 s, que entrega 6879,2 em vez de 7063,5 (§1.5). **Em número absoluto v5 é a
PIOR das seis** — o percentual dele é maior porque o adversário é menor.

**Vencedor declarado: `v1_queue_di5`.** As cinco variantes de 5/7 estão dentro de
0,07 pp umas das outras na vazão — é um empate técnico, e o desempate foi o
critério declarado, não o olho.

---

## 4. O held-out — 12 seeds (100-111), 7200 s, pareado

### 4.1 O veredito — DoD (a) e (b)

`rl:aberta_v1_queue_di5` contra `timer:coordenado_c60`, janela `[300, 7500)`,
grade `di5/vm7/am3/mr0`:

| métrica | `coordenado_c60` | **RL (v1)** | Δ+ | vitórias | p |
|---|---|---|---|---|---|
| **entregues** | 7000,9 | **7025,7** | **+0,35%** | **12/12** | **8,2e-08** |
| **tempo no sistema** | 159,06 s | **137,20 s** | **+13,73%** | **12/12** | **4,6e-12** |
| **fila média** | 52,69 | **31,22** | **+40,71%** | **12/12** | **5,2e-13** |
| tempo de viagem (entregues) | 160,57 s | 138,31 s | +13,85% | 12/12 | 4,8e-12 |
| espera média | 733,8 | 188,4 | **+74,26%** | 12/12 | 1,0e-13 |
| travamentos | 0/12 | **0/12** | — | — | — |
| `sane()` | 12/12 | **12/12** | — | — | — |
| backlog de inserção | 0 em 12/12 | **0 em 12/12** | — | — | — |
| perdidos | 0 em 12/12 | **0 em 12/12** | — | — | — |

**Vitórias na trinca (as três ao mesmo tempo, na mesma seed): 12/12.**

**DoD (b) — a lacuna de sobrevivência, seed a seed:**

| | mínimo | máximo | faixa sã declarada |
|---|---|---|---|
| `coordenado_c60` | −1,31% | −0,85% | −1,4% a −0,2% |
| **RL (v1)** | **−1,14%** | **−0,68%** | **dentro** |

`sinais_de_travamento` vem **vazio nas 12 seeds** do braço RL.

### 4.2 Seed a seed

| seed | c60 ent | RL ent | Δ | c60 fila | RL fila | c60 t.sis | RL t.sis | ativos_fim c60 → RL |
|---|---|---|---|---|---|---|---|---|
| 100 | 6942 | 6961 | +19 | 49,61 | 29,46 | 155,9 | 134,9 | 144 → 125 |
| 101 | 6966 | 6992 | +26 | 51,41 | 31,58 | 157,7 | 138,2 | 153 → 127 |
| 102 | 6978 | 7011 | +33 | 55,29 | 30,59 | 163,0 | 137,2 | 152 → 119 |
| 103 | 7058 | 7096 | +38 | 57,72 | 33,46 | 164,5 | 139,9 | 171 → 160 |
| 104 | 7222 | 7241 | +19 | 54,37 | 33,02 | 159,9 | 138,8 | 149 → 130 |
| 105 | 6941 | 6969 | +28 | 51,58 | 29,71 | 158,4 | 135,5 | 140 → 112 |
| 106 | 6854 | 6876 | +22 | 53,84 | 29,86 | 161,8 | 136,1 | 163 → 141 |
| 107 | 7088 | 7112 | +24 | 52,01 | 31,16 | 157,4 | 136,4 | 147 → 123 |
| 108 | 6999 | 7024 | +25 | 52,83 | 32,12 | 159,2 | 138,5 | 159 → 140 |
| 109 | 6917 | 6948 | +31 | 49,79 | 30,11 | 155,8 | 135,6 | 164 → 133 |
| 110 | 6991 | 7006 | +15 | 52,89 | 31,03 | 158,7 | 136,6 | 171 → 156 |
| 111 | 7055 | 7072 | +17 | 50,97 | 32,49 | 156,5 | 138,6 | 136 → 119 |

### 4.3 De onde vem a vazão — e por que ela é a métrica de baixa resolução

Nesta rede, a 3500 veh/h, **a vazão está quase saturada por construção**: o
`inseridos` é praticamente idêntico nos dois braços (idêntico ao veículo em 10 de
12 seeds; o backlog é zero nos dois), então a identidade de balanço do C5 se
reduz a

    entregues_RL − entregues_c60  =  ativos_fim_c60 − ativos_fim_RL

e a coluna da direita da tabela acima fecha a conta seed a seed (seed 100:
144 − 125 = 19 = +19 entregues). **A vazão não mede "quanto o controlador serve";
mede quanta gente ele deixou presa às 7500 s.** É por isso que o teto dela é da
ordem de +0,4% e não de +14% como o tempo.

Isso tem uma consequência para a DoD, e ela precisa ser dita: **a mesma DoD
aplicada ao `coordenado_c60` contra o `timer27` teria REPROVADO o plano que hoje
é o baseline congelado** — 8/12 vitórias em entregues, p = 0,19
(`BASELINE_ABERTO.md` §4.5). O critério "vencer nas três com p<0,01" é exigente
justamente na métrica de menor resolução do regime. Aqui ele passou (12/12,
p = 8,2e-08), então a questão é acadêmica **nesta corrida** — mas ela volta a
valer se alguém reusar o mesmo critério em outro ponto de operação, e por isso
fica registrada. Ver §7.

---

## 5. As alavancas, uma a uma

### 5.1 Alavanca 1 — warm start: **comprou tempo, não qualidade**

Curva da fila na validação (Δ+ contra o `coordenado_c60`, 2 seeds, 7200 s):

| episódio | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 | 160 |
|---|---|---|---|---|---|---|---|---|---|
| **v1 (warm start)** | +20,1% | +22,6% | +25,0% | +25,3% | +31,6% | +32,4% | +32,6% | +33,3% | +43,1% |
| **v6 (do zero)** | −1285% | −1304% | −263% | +8,9% | +18,8% | +24,3% | +27,7% | +27,9% | +37,5% |

O warm start **já entrega uma política melhor que o baseline no episódio 10** e
adianta o do-zero em ~50 episódios (≈70 min de parede). Na seleção final, porém,
os dois empatam dentro do ruído: +0,44% contra +0,43% na vazão, +41,6% contra
+38,5% na fila. **Conclusão: o que decide é retreinar NO CENÁRIO; a origem dos
pesos decide o custo, não o resultado.** É o mesmo achado do maquete
(`RESULTADOS_ATS.md` §4: "empatou: retreinar no regime de produção"), agora na
direção contrária — lá a transferência bastava, aqui ela é obrigatória.

### 5.2 Alavanca 4 — `pressure` contra `queue`: **`queue` ganha, hipótese refutada**

A aposta registrada no escopo era que max-pressure, sendo derivado para redes
ABERTAS com demanda exógena, pudesse virar o resultado da rede fechada. Não virou:

| | vazão | fila | tempo no sistema |
|---|---|---|---|
| v1 `queue` | **+0,44%** | **+41,55%** | **+14,11%** |
| v2 `pressure` | +0,39% | +35,94% | +11,66% |
| v3 `queue` + mr60 | +0,42% | +42,45% | +14,92% |
| v4 `pressure` + mr60 | +0,37% | +34,86% | +10,95% |

`queue` ganha nos dois pares, nas três métricas. A margem é pequena na vazão
(0,05 pp) e grande na fila (5,6 pp). Uma leitura possível: a informação de
jusante que o max-pressure traria **já está no estado** desde a v2 do maquete (a
dimensão de pressão do `ats`), então usá-la também como recompensa é redundante e
só adiciona variância.

### 5.3 Alavanca 3 — `MAX_RED > 0`: **neutro a levemente positivo, e instável com `pressure`**

`v3` (`queue`+mr60) mede um fio melhor que `v1` na fila e no tempo — e, na
held-out, um fio melhor em tudo (§6). Mas:

- na rodada de seleção `v3` perdeu de `v1` no critério declarado (vazão, por
  0,02 pp) — empate técnico;
- com `pressure` a guarda foi **desestabilizadora**: `v4` produziu validações
  colapsadas no episódio 10 (lacuna 94%, backlog 660) e de novo no episódio 160
  (−19,2% de vazão, fila 232, não-sã), embora o melhor checkpoint dela (ep 130)
  seja perfeitamente são.

**Veredito: a guarda não é necessária nesta rede** — as políticas sem ela têm
lacuna de sobrevivência entre −1,14% e −0,68% e zero travamento em 12 seeds. Ela
fica documentada como disponível e barata (o shield já é do `TrafficEnv`, o C1 já
valida), não como parte da configuração recomendada.

### 5.4 Alavanca 2 — 5/7 contra 10/10: **5/7 vence, e o percentual mente**

| braço | grade | entregues | fila | tempo no sistema |
|---|---|---|---|---|
| RL v1 | **5/7** | **7025,7** | **31,22** | **137,20 s** |
| RL v5 | 10/10 | 7016,5 | 40,03 | 145,70 s |
| `coordenado_c60` | 5/7 | 7000,9 | 52,69 | 159,06 s |
| `coordenado_c60` | 10/10 | 6814,6 | 56,49 | 165,07 s |

Em percentual, v5 parece o melhor de todos (**+2,96%** de vazão contra os +0,35%
de v1, p = 1,1e-10, 12/12). Em número absoluto ele é **pior**: entrega 9 carros a
menos, com fila 28% maior e 8,5 s a mais no sistema. Os +2,96% medem o adversário
mutilado pela grade grossa (§1.5), não a política.

**`RESTRICOES_ABERTA` fica como está: 5/7/3, verde mínimo alcançável de 7 s.** O
resultado é consistente com o motivo (b) pelo qual o C1 escolheu 5/7 — o tato do
jogo — e agora tem também o motivo de desempenho.

> **Nota para o A8 e para o jogo:** o interesse do braço 10/10 não é ganhar a
> comparação, é que ele mostra que a RL **também** vence numa grade em que o
> plano de engenheiro não cabe. Isso é um argumento de robustez, e é só isso.

---

## 6. Variantes descartadas — o motivo e o número

Nenhuma variante foi descartada por não terminar; as seis rodaram os 160
episódios e produziram checkpoint. "Descartada" = não é a política recomendada.

| variante | motivo | o número que sustenta |
|---|---|---|
| **`maq30_ats_full` (a de produção)** | colapsa a rede aberta; foi treinada na fechada, grade 10/10 | held-out 12 seeds: **3140,8 entregues contra 7001 (−55,1%)**, fila 667,8 (−1163%), **3/12 travamentos**, 8/12 com borda estrangulada (backlog 18–56%), 0/12 vitórias em tudo |
| **`maq30_ats_di5_full` (transferida, grade certa)** | idem, mesmo com a grade casada | held-out: **4391,8 entregues (−37,1%)**, fila 435,1 (−722%), **2/12 travamentos**, 7/12 com borda estrangulada |
| **v2 `pressure`** | perde de `queue` nas três métricas | seleção: +0,39% / +35,94% / +11,66% contra +0,44% / +41,55% / +14,11% |
| **v4 `pressure` + `max_red 60`** | pior das cinco de 5/7 **e** instável no treino | seleção: +0,37% / +34,86% / +10,95%; validações colapsadas em ep 10 (lacuna 94,1%, backlog 660) e ep 160 (−19,2% vazão, fila 232,3, não-sã) |
| **v5 `queue` 10/10** | vence em percentual, perde em absoluto; e o percentual vem de um adversário mutilado pela grade | held-out: 7016,5 entregues contra os 7025,7 de v1; fila 40,03 contra 31,22; §1.5 e §5.4 |
| **v6 `queue` sem warm start** | empata com v1 e custa ~50 episódios a mais para chegar lá | seleção: +0,43% / +38,47% / +12,81%; curva da §5.1 |
| **v3 `queue` + `max_red 60`** | **não é bem um descarte** — mede um fio melhor que v1 na held-out, mas perdeu no critério declarado (vazão) na seleção | held-out: +0,40% / +14,70% / +42,19%, 12/12, p ≤ 1,1e-07, 0 travamentos |

**Sobre o v3, explicitamente:** ele foi levado à held-out junto do vencedor, e o
número dele é marginalmente melhor (7029,0 contra 7025,7 entregues; fila 30,45
contra 31,22). **Trocar o vencedor por causa disso seria escolher no conjunto de
teste** — exatamente o erro que a §4.6 do `BASELINE_ABERTO.md` documenta para o
plano `c50`. A recomendação é ficar com **v1**, que foi escolhido antes, no
conjunto de validação, pelo critério declarado. Se o dono do projeto preferir o
v3, a troca é uma linha e o arquivo está medido e publicado do mesmo jeito — mas
**esta nota vai junto**.

---

## 7. Onde eu discordo de uma decisão já tomada

**A DoD (a) exige `p < 0,01` na vazão, e a vazão é a métrica de menor resolução
deste regime.** A §4.3 mostra o mecanismo: com a demanda exógena servida quase
integralmente por qualquer plano são, `entregues` só consegue variar pelo saldo
de população presa no instante `t1`. O teto útil da métrica é da ordem de +0,4%.

Isso não é opinião: **o próprio `coordenado_c60`, o baseline que a DoD manda
bater, reprovaria nessa cláusula** — 8/12 vitórias e p = 0,19 contra o timer27,
na mesma janela e nas mesmas seeds (`BASELINE_ABERTO.md` §4.5). O plano foi
congelado assim mesmo, e com razão: a vazão ali era um **critério de recusa** (um
plano que ganha tempo deixando carro fora não presta), não um critério de mérito.

**Minha discordância, com a correção que proponho:** a vazão deveria entrar na
DoD como *porta* (não pode cair, e o backlog de inserção tem que ficar em zero) e
não como uma das três métricas que precisam de `p<0,01`. As métricas de mérito
seriam tempo no sistema e fila — que é onde há resolução para medir controle.

**Isto não muda nada nesta entrega:** o critério como está foi cumprido, 12/12 e
p = 8,2e-08. Registro porque o mesmo critério vai ser reusado — pelo A8, e no dia
em que o ponto de operação subir para 3800–4000 veh/h (pendência 4 do
`PROXIMOS_PASSOS.md` §4). Num regime mais carregado a vazão ganha resolução e a
cláusula volta a fazer sentido; num regime mais leve ela fica ainda mais cega.

---

## 8. O que ficou aberto

1. **Nenhuma varredura de hiperparâmetro.** `lr`, `γ`, `batch`, arquitetura e
   `dueling` ficaram nos valores do maquete. As seis variantes gastaram o
   orçamento nas quatro alavancas do escopo, que eram as que tinham porquê medido.
2. **Um seed de treino só por variante** (`semente_torch=7`). A diferença entre
   as cinco variantes de 5/7 (0,07 pp de vazão) é menor que o que uma re-run com
   outra semente provavelmente produziria — ou seja, **o ranking interno delas
   não é confiável, só o ranking contra o baseline é**. Isso é uma limitação real
   do §3, e a §6 já a leva em conta ao não trocar o vencedor pelo v3.
3. **Episódio de 3600 s, avaliação de 7200 s.** O regime é estacionário na janela
   inteira (a medida de referência do coordenador), e a validação de 7200 s pega
   metaestabilidade na hora de escolher o checkpoint — foi ela que reprovou o v4.
   Treinar em episódios de 7200 s não foi testado.
4. **O ponto de operação continua 3500 veh/h.** Nada aqui foi medido acima disso.
5. **`espera_media` melhorou +74,3%** e esse número é grande demais para não ser
   olhado com desconfiança. Ele é consistente (12/12, p = 1e-13) e o mecanismo é
   plausível — a espera acumulada cresce de forma superlinear com a fila, e a fila
   caiu 41% —, mas ninguém auditou essa métrica na rede aberta como o A2 auditou
   as outras. **Não usar como manchete até alguém conferir.**
6. **Sobra de faxina:** `experiments/_smoke_a6/`, `experiments/_smoke2/`,
   `results/rl/smoke_a6.pt` e `results/rl/smoke2.pt` são lixo de fumaça do
   desenvolvimento; o sandbox deste agente não pode apagar arquivo. São
   regeneráveis e podem ir embora.

---

## 9. Como reproduzir

```powershell
# 0) as seeds novas (as 18 canônicas NÃO são tocadas)
..\smart-traffic\.venv\Scripts\python.exe -m feira.demanda --seeds 200-223,230-233

# 1) as seis variantes, uma por processo, em BACKGROUND (~3,3 h em 16 CPUs)
#    (um processo por variante: `sim.environment.constants` é singleton de processo)
$w5  = "..\smart-traffic-maquete\results\maq30_ats_di5_full_best.pt"
$w10 = "..\smart-traffic-maquete\results\maq30_ats_full_best.pt"
python scripts/treina_aberta.py --nome v1_queue_di5     --episodios 160 --recompensa queue    --warm-start $w5
python scripts/treina_aberta.py --nome v2_pressure_di5  --episodios 160 --recompensa pressure --warm-start $w5
python scripts/treina_aberta.py --nome v3_queue_mr60    --episodios 160 --recompensa queue    --warm-start $w5  --max-red 60
python scripts/treina_aberta.py --nome v4_pressure_mr60 --episodios 160 --recompensa pressure --warm-start $w5  --max-red 60
python scripts/treina_aberta.py --nome v5_queue_di10    --episodios 160 --recompensa queue    --warm-start $w10 --decision-interval 10 --min-green 10 --epsilon-decay 20000
python scripts/treina_aberta.py --nome v6_queue_semwarm --episodios 160 --recompensa queue    --sem-warm-start --epsilon-start 1.0 --epsilon-decay 60000

# 2) a rodada de seleção (4 seeds de validação; ~15 min)
..\smart-traffic\.venv\Scripts\python.exe scripts/treina_aberta_selecao.py --procs 4 --saida results/rl/selecao.json

# 3) a held-out do vencedor (12 seeds; ~5 min)
..\smart-traffic\.venv\Scripts\python.exe -m feira.treino.avalia --ckpt results/rl/v1_queue_di5.pt `
    --seeds 100-111 --janela 7200 --procs 4 --saida results/rl/heldout_v1_queue_di5.json

# 4) o "antes" — a política que está em produção, na mesma bancada
..\smart-traffic\.venv\Scripts\python.exe -m feira.treino.avalia `
    --ckpt ..\smart-traffic-maquete\results\maq30_ats_full_best.pt `
    --seeds 100-111 --janela 7200 --procs 4 --saida results/rl/antes_maq30_ats_full.json

# 5) a suíte
..\smart-traffic\.venv\Scripts\python.exe -m pytest -q
..\smart-traffic\.venv\Scripts\python.exe -m ruff check .
```

### Artefatos

| arquivo | o que é |
|---|---|
| `results/rl/v1_queue_di5.pt` | **a política recomendada** (grade `di5/vm7/am3/mr0`, estado `ats`) |
| `results/rl/v3_queue_mr60.pt` | a alternativa com `max_red=60` (§6) |
| `results/rl/v5_queue_di10.pt` | o braço 10/10 do A/B — só roda em `di10/vm10` |
| `results/rl/heldout_*.json` | as tabelas held-out, seed a seed, com p-valor |
| `results/rl/selecao.json` | a rodada de seleção das 6 variantes |
| `results/rl/antes_*.json` | as duas políticas transferidas, na mesma bancada |
| `experiments/v*/` | `config.json`, `train_log.csv`, `eval_log.csv`, checkpoints |

### Testes

`tests/test_a6_treino.py` — 26 testes: as faixas de seed disjuntas, a variante de
espaço de ação que não vaza para o C1, a recusa de corrida vazia, o round-trip do
`Resultado` entre processos, a trinca da DoD, e (com SUMO) a rotação de demanda
entre episódios mais o pipeline inteiro ponta a ponta.
