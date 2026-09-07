# Plano — rede aberta, margem honesta e modo jogo

Aprovado em 2026-09-07. Feira ≈ **2026-09-28** (3 semanas).

Três frentes: abrir a rede, ampliar a margem da RL honestamente, e um modo jogo em
que o público assume os semáforos.

---

## 0. O que já estava medido (base do plano)

| fato | fonte |
|---|---|
| grid 3×4, mão única por corredor, fechado por `ret_N`/`ret_S` | `sumo/small_network/network/*.edg.xml` do maquete |
| **`real`: 12 TLs, 8 controláveis. `maquete` e `maquete_sim` (os que rodam na feira): 10 TLs, só 6 controláveis** | `net_topology.TL_PHASES`, rodado nos três cenários |
| os 2 cantos (H1V4/H3V4) foram **des-semaforizados** na maquete: viraram junções de prioridade com U-turn interno, porque o carrinho não podia parar na curva de retorno | `scale_to_maquete.py`, cabeçalho |
| treino de 250 ep × 1800 s = **2511 s de parede (42 min, CPU)** | `experiments/maq30_ats_full/train_log.csv` |
| `BASELINE_GREEN=27`, `YELLOW=3`, `DI=10`, `MIN_GREEN=10`, `MAX_RED=0` | `sim/environment/constants.py` |
| demo roda `SEED=42`, que é uma das `eval_seeds=(42,43)` do treino | `dashboard/backend/config.py` + `train.py` |
| SUMO 1.27.0 com `tlsCoordinator.py`, `tlsCycleAdaptation.py`, `routeSampler.py` | `$SUMO_HOME/tools` |
| `pyserial` **não** está instalado no venv compartilhado | medido |
| geometria `maquete`: quarteirão 28 m, travessia 2,5 s, capacidade 242 carros | `docs/RESULTADOS_MAQUETE.md` §2.1 |
| similitude (`maquete_sim`): travessia 15,2 s, capacidade 1453 | idem |

---

## 1. Auditoria — os 7 achados que o agente A2 tem que verificar ou refutar

O número **offline** (+16,0% tempo / +34,4% fila / +19,5% vazão, 12 seeds held-out,
p ≤ 1e-11) é honesto e bem defendido. O número **da tela** é outro objeto.

| # | onde | o quê |
|---|---|---|
| 1 | `nn_runner.py` / `timer_runner.py` | dois processos, dois deadlines; ao atrasar fazem `deadline = perf_counter()` — o atraso some da vista e nunca volta |
| 2 | `projecao.js:366` | `updateVerdict` compara `completed` acumulado dos dois braços **sem olhar o `t`** de cada frame |
| 3 | `config.py:SEED=42` | a demo roda na seed usada para **escolher o checkpoint** — levemente in-sample |
| 4 | `projecao.js:tail()` | fila da tela = média dos últimos 20 **frames recebidos**, acumulada no cliente, zera ao recarregar. O paper usa média da run inteira |
| 5 | `snapshot.py:LaneStream` | `heat` ignora lanes internas de junção (`:`) — carro parado dentro do cruzamento não conta |
| 6 | `projecao.js:AQUECIMENTO=8` | gate de 8 viagens por lado; não corresponde a protocolo nenhum, e **quebra na rede aberta** (que começa vazia) |
| 7 | `metrics.py:coherence_gap` | assume frota fechada (`esperado ≈ N × T / tt`) — **morre na rede aberta**. É o único detector de artefato de sobrevivência do projeto |

**As duas ressalvas que precisam acompanhar o número publicado:**
1. o timer não tem **offset nem split por interseção** — plano que nenhum engenheiro
   instalaria numa arterial;
2. a geometria comprimida infla o ganho (verde curto rende demais num quarteirão de
   2,5 s de travessia).

A decisão de geometria (§2) corrige a (2); o agente A5 corrige a (1).

---

## 2. Decisões técnicas

### Frente 1 — cenário `aberta.maquete`

**Geometria:** base = a maquete de hoje, **alterada para similitude** (`x'=x/6,
v'=v/6, a'=a/6, t'=t`), para o ganho da RL vir da política e não do quarteirão curto.
Consequência: capacidade sobe para ~1453 carros — "mais veículos" sai de graça
(~180 ativos na mesma densidade relativa de hoje) — e o carro fica 6× menor na
projeção, exigindo fator de exagero de sprite (a arte já é desacoplada: `vehLen` vem
do net export, e `paint.js` desenha a pegada real do SUMO por baixo).

**Bordas:** remover `ret_N`/`ret_S`; cotos de origem/sorvedouro nos términos de cada
corredor de mão única → **9 fontes, 9 sorvedouros**. Mão única é realista para aquele
quarteirão (Al. Santos e Pamplona são mão única no OSM). Escolha de rota preservada:
descer de H1 para H3 tem três caminhos (V1, V3, V4S) além do par H2E/H2W.

**Demanda: arquivo de rotas pré-gerado por seed, não Poisson in-process.**
- reprodutibilidade na forma mais forte (sha256), e **provadamente** independente do
  controlador — não "quase";
- os três braços leem literalmente o mesmo arquivo;
- **a Frente 3 depende disso**: com rotas em arquivo a demanda vive no estado do SUMO,
  então o replay determinístico do warm-up funciona. Com injeção in-process, não.
- OD ponderado por capacidade (`od_weight="capacity"`, pow=1 — pow ≥ 1,5 colapsa,
  medido na large), H2 com participação dominante, `reroute_period=60`.
- calibração **por população ativa alvo**, não por taxa (taxa fixa foi o que prendeu
  a Vila Olímpia em fluxo livre).

### Frente 2 — baseline honesto e margem

Baseline = plano de tempo fixo **bem projetado**: ciclo por Webster + splits por
interseção + **offsets (onda verde)** em H2 via `tlsCoordinator.py`.
`FixedTimerSim.offset_seconds` já existe e nunca foi usado.

Alavancas da RL, em ordem de aposta: espaço de ação 5/7 (verde mínimo alcançável cai
de 17 s para 7 s), `MAX_RED > 0` (starvation nas aproximações de borda), recompensa
`pressure` vs `queue` (max-pressure é derivado para redes **abertas**), 12 alavancas
em vez de 8, e demanda direcional (plano fixo é ótimo para uma hora de projeto).

### Frente 3 — modo jogo

| decisão | valor | motivo |
|---|---|---|
| semáforos controlados | **12** (todos, após abrir) — contra **6** úteis hoje | ninguém acompanha 12 cruzamentos: protege a margem sem trapaça. Hoje o jogo teria 6 botões com efeito e 4 mortos |
| rodada | **120 s simulados, 1:1 → 2 min** | ~270 viagens (média estável) e teto de atenção em pé |
| botão | enfileira intenção, aplicada no **próximo tick** da grade, sujeita a MIN_GREEN/YELLOW/MAX_RED | idêntico bit-a-bit à ação da RL; aplicar na hora daria ao humano grade mais fina |
| feedback | LED: pulsando = armado · aceso = aceito · piscando = negado | sem isso o visitante acha que o botão quebrou |
| placar | 3 barras: TIMER / RL / VOCÊ, em **carros entregues** | tempo de viagem como manchete seria exploitável: quem trava a rede ganha na média dos sobreviventes |
| RL e timer na rodada | **fantasmas pré-computados** (durante a rodada anterior) | início instantâneo, pareamento exato, um SUMO só ao vivo |

**Desvio consciente do enunciado:** a rodada parte de um **estado neutro canônico**
da seed (warm-up com o plano fixo, igual para os três), não do estado que a RL
produziu. O visual é o mesmo (a tela congela, conta, o público joga), mas o timer não
herda uma rede arrumada pelo concorrente.

**Botoeira:** Pi Pico + 13 botões arcade iluminados (12 em painel 3×4 espelhando a
geometria da rede + START), LEDs por 2× 74HC595, protocolo ASCII por USB CDC
(`feira/contratos/entrada.py`). Teclado equivalente: `Q W E R / A S D F / Z X C V`
+ Espaço.

---

## 3. Agentes

Escopo · **fora** · depende de · entrega · DoD.

### A0 · Fundação & Contratos — Onda 0 ✅ **concluído**
Repo novo, `sim` como pacote editável, C1–C8 + suíte de conformidade, ponto de
retorno nos repos. **DoD:** pytest verde, `import sim` de fora do maquete, commit de
baseline. **Resultado:** 58 testes, lint limpo.

### A1 · Rede Aberta & Demanda — Onda 1
`.nod/.edg/.con` com 9 fontes / 9 sorvedouros + similitude + `netconvert`; gerador de
`.rou.xml` por seed; calibração de população ativa; warm-up medido; replay
determinístico. **Fora:** treino, baseline, jogo, projeção.
**DoD:** (a) `netconvert` sem warning; (b) **os 12 TLs controláveis** (contra 6 de 10
hoje — abrir a borda devolve os cantos H1V4/H3V4 à semaforização, já que o U-turn de
retorno deixa de existir, e dá uma segunda aproximação a H1V1/H1V3/H3V1/H3V2);
(c) mesma seed 2× → mesmo sha256; (d) 3600 s a 45–55% parados, estável, sem travamento em 6 seeds;
(e) replay de t=0 a t0 reproduz estado idêntico em 3 seeds. **Preenche
`Cenario.warmup_s`, hoje `None` — a Arena recusa rodar sem isso.**

### A2 · Bancada de Medição & Auditoria — Onda 1
Implementa a `Arena` (C4) e as métricas de rede aberta (C5); substitui o
`coherence_gap`; verifica ou refuta os 7 achados da §1 (inclui medir a deriva
`t_timer − t_nn` por 10 min na demo atual). **Depende:** A0 (mede a demo de hoje sem
esperar A1).
**DoD:** (a) a Arena reproduz o `evaluate.py` atual na rede fechada dentro de 0,5%;
(b) o detector novo denuncia travamento injetado e não acusa política sã; (c) cada
achado com número medido ou marcado *refutado*; (d) comparação entre janelas
diferentes levanta.

### A3 · Motor do Jogo & Input — Onda 1
`ControladorHumano` + `KeyboardInput` + máquina de estados da rodada + orquestração
dos fantasmas. **Roda em paralelo à A1** — só precisa dos contratos; desenvolve sobre
`small.maquete`. **Fora:** hardware, arte, política.
**DoD:** (a) rodada jogável só com teclado, sem `pyserial` instalado; (b) a intenção
do humano respeita as mesmas restrições, provado contra a mesma sequência aplicada à
RL; (c) `ReplayInput` reproduz rodada gravada com o mesmo `Resultado`; (d) fantasma
com hash divergente é recusado.

### A4 · Botoeira Física — Onda 1→3 (paralela)
Firmware MicroPython, esquema, painel, BOM, `SerialInput`. **Depende:** só do
protocolo C6, congelado.
**DoD:** (a) `SerialInput` passa a mesma suíte do teclado contra um serial falso;
(b) 13 botões/LEDs verificados na bancada; (c) **desconectar o USB no meio da rodada
não derruba o jogo**; (d) latência botão→evento < 50 ms medida.

### A5 · Baseline Honesto — Onda 2
Webster + splits + offsets; varredura como sensibilidade; congela **um** plano.
**Depende:** A1, A2.
**DoD:** (a) o plano coordenado bate o timer uniforme de 27 s na rede aberta — se não
bater, o tuning está errado, não o baseline; (b) varredura publicada com a mesma
tabela desconfortável do Apêndice A; (c) escolha justificada por fora do projeto.

### A6 · Política RL no Cenário Aberto — Onda 2
Warm start dos pesos atuais; A/B de espaço de ação, recompensa e `MAX_RED`; held-out
12 seeds. **Depende:** A1, A2, A5 (o baseline congelado é o adversário).
**DoD:** (a) vence o **baseline coordenado** nas três métricas em ≥10 de 12 seeds
held-out, p<0,01; (b) zero travamentos, conservação sã em 12/12; (c) seleção de
checkpoint por vazão; (d) toda variante descartada documentada com o motivo.
**Se (a) falhar, reporta como está** e dispara a decisão de discurso (risco 4).

### A7 · Projeção & Placar — Onda 2
Rodada na projeção, 3 barras vivas, tela de resultado, exagero de sprite, modo
degradado. **Depende:** A3.
**DoD:** (a) legível a 2 m em foto do projetor real; (b) 180+ carros a 1 Hz sem
perder frame no notebook da feira, medido; (c) contraste ≥ o piso do `contraste.py`;
(d) se o jogo cair, a projeção volta sozinha para RL × timer em ≤3 s.

### A8 · Adversários & Calibração de Dificuldade — Onda 3
Políticas "humanas" scriptadas (aleatória, tudo-verde-na-arterial, gulosa de maior
fila, alternada, humano-com-lag) rodadas headless em massa. **Fora:** mudar a rodada
para a RL ganhar.
**DoD:** (a) ≥200 rodadas por adversário, ≥12 seeds; (b) estimativa com intervalo de
confiança de **P(humano vence a RL)**; (c) **se a gulosa vencer a RL, é achado sobre
a RL e vai para o documento de resultados**; (d) a duração da rodada sai deste dado e
o número escolhido é publicado.

> A8 responde à pergunta real — *"alguém do público vai derrubar minha RL em
> público?"* — **sem precisar de público**, e antes da feira.

---

## 4. Ondas

```
ONDA 0  D1–D2    A0                                    ✅ concluída
ONDA 1  D2–D8    A1 ║ A2 ║ A3 ║ A4
        gate: 12 TLs controláveis · demanda com hash estável ·
              malha congestionada e estável em 3600 s · jogo rodando no teclado
              ▸ se a rede aberta não congestionar, PARAR e recalibrar (risco 1)
ONDA 2  D8–D15   A5 → A6 (encadeados) ║ A7
        gate D13: a RL vence o baseline coordenado?
              ▸ NÃO → muda o discurso agora, com 2 semanas de folga
ONDA 3  D15–D19  A8 ║ integração
ONDA 4  D19–D21  ensaio com pessoas · congelamento · docs · roteiro
```

**Caminho crítico:** A0 → A1 → A5 → A6 → A8. A4 (botoeira) é a única trilha que pode
atrasar sem afetar a feira — o teclado sempre joga.

---

## 5. Riscos

| # | risco | mitigação | gate |
|---|---|---|---|
| 1 | **rede aberta não congestiona** (aconteceu na Vila Olímpia: presa em 250–650 carros) | calibrar por população ativa alvo; medir % parados e velocidade em 3600 s antes de treinar | Onda 1 |
| 2 | **travamento irreversível** — backlog de inserção sem teto | `reroute_period=60` + detector de conservação novo | Onda 1 |
| 3 | **replay determinístico não fecha** (RNG do SUMO, `weights.random-factor=2.0`, fila de inserção) | fallback: replay de t=0 headless a ~100× | Onda 1 |
| 4 | **o baseline honesto encolhe a margem** | decidir o discurso no gate D13, não na véspera | Onda 2 |
| 5 | **retreino não converge no calendário** | warm start; 3 variantes em paralelo em background, nunca em série | Onda 2 |
| 6 | **similitude quebra a leitura visual** (carro de 7 mm na mesa) | exagero de sprite + pegada real do SUMO por baixo | Onda 2 |
| 7 | **um operador só na feira** | modo degradado automático, watchdog, botão de abortar | Onda 3 |
| 8 | **12 botões frustram uma pessoa sozinha** | medir com A8; se preciso, **modo corredor** (4 da arterial; os outros 8 no plano fixo **para os três braços**) — pareado, mas rotulado como modo separado | Onda 3 |
| 9 | **repo novo custa dias** | `pip install -e` do maquete + venv compartilhado (feito: meio dia) | Onda 0 |

---

## 6. Fora de escopo

Carrinhos físicos · re-import da Paulista do OSM como malha (o `.osm` é referência de
pesos de OD e material de slide) · multiplayer em rede · dashboard novo · refazer o
resultado da rede fechada (fica congelado e reproduzível no maquete) · qualquer
mudança que enfraqueça o baseline.

## 7. Pendências do dono do projeto

- rodada partindo do **estado neutro canônico** (proposto) ou da leitura literal
  "continua de onde a RL parou"?
- **modo corredor** entra como plano B ou já nasce?
