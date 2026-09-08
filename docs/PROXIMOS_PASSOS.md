# Próximos passos — pronto para disparar

Estado em 2026-09-08. **534 testes verdes, `ruff` limpo.** Ondas 0 e 1 concluídas,
Onda 2 com o baseline (A5) fechado. Falta A6 (treino), A7 (projeção) e A8 (adversários).

Este documento existe para a próxima sessão começar disparando, sem redescobrir nada.

---

## 0. Antes de qualquer agente — regerar a demanda canônica

**Decidido pelo dono do projeto.** O horizonte atual (`HORIZONTE_S = 5400`) não sustenta
a janela de 7200 s que a metaestabilidade exige: medido na seed 42, a partir de t≈5700 a
rede fica **vazia**, e toda janela de 7200 s promedia ~25% de rede deserta.

```powershell
# regerar as 18 seeds canônicas com horizonte 8400
..\smart-traffic\.venv\Scripts\python.exe -m feira.demanda --horizonte 8400 --todas --forcar
```

O que muda: **o sha256 de toda demanda**, e portanto toda `Chave` (C5) já carimbada. Os
números medidos continuam válidos como medida — o que muda é a proveniência, e eles têm
que ser re-rodados para voltar a comparar. O A1 mediu que a demanda de horizonte menor é
**prefixo exato** da maior, então o conteúdo dos primeiros 5400 s não muda.

**Verificação obrigatória depois:** rodar `scripts/divergencia_bancadas.py --seed 42
--ate 7200` e conferir que nenhuma fatia de 600 s termina com 0 ativos.

Quem faz: pode ser o coordenador (é mecânico) ou entrar como passo 1 do agente A6.

---

## 1. Agente A6 — Política RL no cenário aberto  ← **caminho crítico**

**O que é.** Retreinar a DDQN+GNN no `aberta.maquete` contra o baseline coordenado
congelado, e validar em held-out.

**Por que é urgente.** Medido pelo A3: a política atual **perde** para o timer na rede
aberta — 93 e 82 entregues contra 111 e 109. Esperado (o checkpoint foi treinado na rede
fechada, grade 10/10), mas até isto rodar **não existe Frente 2, e o jogo mostraria a RL
perdendo no projetor**.

**Depende de:** passo 0, A1 (rede+demanda ✅), A2 (Arena ✅), A5 (baseline congelado ✅).

**Escreve só em:** `feira/treino/**`, `scripts/treina*.py`, `experiments/**`,
`results/rl/**`, `tests/test_a6_*.py`, `docs/RESULTADOS_ABERTA.md`.
**Não edita:** `feira/contratos/**`, `feira/arena/**`, `feira/metricas.py`,
`feira/demanda/**`, `feira/controladores/{timer,coordenado,humano,rl}.py`,
`sumo/aberta/{network,demanda,config,planos}/**`, `tests/test_{contratos,conformidade,pacote_sim}.py`,
`docs/PLANO.md`, `README.md`.

**Alavancas, em ordem de aposta** (todas com o porquê já medido):
1. **Warm start** dos pesos de `results/maq30_ats_full_best.pt` — a GNN é N-agnóstica e
   os pesos transferem. Treino do zero custou 42 min na rede fechada; aqui espere 2–4 h.
2. **Espaço de ação 5/7** (já é o default do cenário; verde mínimo alcançável 7 s contra
   17 s). A/B contra 10/10 — se 10/10 vencer, o `RESTRICOES_ABERTA` do C1 muda **e o jogo
   herda a grade mais grossa**, porque as restrições são as mesmas para os três braços.
3. **`MAX_RED > 0`** — agora há aproximações de borda com starvation real. O shield já
   existe no `TrafficEnv`; o C1 valida que `max_red > min_green + yellow`.
4. **Recompensa `pressure` contra `queue`** — max-pressure é derivado para redes
   **abertas** com demanda exógena. `queue` venceu na rede fechada; a chance de virar
   aqui é real.

**DoD:**
- (a) vence o **`coordenado_c60`** (não o uniforme de 27 s) nas três métricas em ≥10 de
  12 seeds held-out, p<0,01, janela de 7200 s;
- (b) zero travamentos e `sane()` verde em 12/12; lacuna de sobrevivência na faixa sã
  (política sã fica entre −1,4% e −0,2%; ver `metricas.sinais_de_travamento`);
- (c) seleção de checkpoint **por vazão**, nunca por tempo de viagem — é a métrica que o
  artefato de sobrevivência não engana;
- (d) toda variante descartada documentada com o motivo;
- (e) `pytest -q` verde, `ruff` limpo.

**Se (a) falhar, reporta como está.** Dispara a decisão de discurso do risco 4 do plano:
"a RL iguala um plano coordenado sem precisar ser projetada para esta demanda" é um
resultado verdadeiro e defensável — mas é outro roteiro, e precisa de tempo para mudar.

**Vigiar:** treinar em regime metaestável produz política que não reproduz. O ponto de
operação congelado é 3500 veh/h; **não subir sem medir 7200 s**.

---

## 2. Agente A7 — Projeção & Placar

**Depende de:** A3 (motor do jogo ✅). Melhor **depois** do A6, para não calibrar a arte
contra números que vão mudar.

**Escreve só em:** `web/**`, `feira/jogo/web*.py`, `tests/test_a7_*.py`,
`docs/PROJECAO.md`.

**Escopo:** a rodada na projeção (congelamento, contagem, três barras vivas em carros
entregues, tela de resultado), o **fator de exagero de sprite** (sob similitude o carro
mede ~7 mm na mesa) e o modo degradado.

**DoD:**
- (a) legível a 2 m da mesa, em foto do projetor real;
- (b) 180+ carros a 1 Hz sem perder frame no notebook da feira, **medido**;
- (c) contraste ≥ o piso de `smart-traffic-maquete/scripts/projecao/contraste.py` para
  todos os elementos novos;
- (d) se o jogo cair, a projeção volta sozinha para RL × timer em ≤3 s.

**Herança:** a projeção atual vive em `smart-traffic-maquete/dashboard/frontend/projecao/`
(commit `18ea6dd`). `paint.js` já desenha a pegada real do SUMO por baixo do sprite —
sprite exagerado + pegada verdadeira continua honesto.

---

## 3. Agente A8 — Adversários & Calibração de Dificuldade

**Depende de:** A3 ✅, A5 ✅, A6.

**Escreve só em:** `feira/adversarios/**`, `scripts/adversarios*.py`,
`results/a8/**`, `tests/test_a8_*.py`, `docs/DIFICULDADE.md`.

**Escopo:** políticas "humanas" scriptadas rodadas headless em massa sobre o protocolo de
rodada, para estimar **P(humano vence a RL)** sem precisar de público.

Classes mínimas: aleatória · **martelo** (todo TROCAR) · tudo-verde-na-arterial ·
gulosa de maior fila · alternada fixa · humano-com-lag.

**Duas perguntas que só o A8 responde:**

1. **Martelar ainda vence?** Medido pelo A3: martelar todos os botões bate o timer
   **uniforme** de 27 s em 6/6 seeds (+7,1%). Contra o `coordenado_c60` isso deve parar de
   funcionar — mas é hipótese, não medida. Se martelar continuar vencendo o baseline
   coordenado, é achado sobre o baseline; se vencer a RL, é achado sobre a RL, e **vai
   para o documento de resultados, não para debaixo do tapete**.
2. **120 s aguenta?** O A3 mediu: dp do número absoluto 10–12 carros, dp da **diferença**
   contra o timer 2,8–4,0, sinal de habilidade +15,7 (S/R ≈ 4,6). Diferenças ≤3,4 carros
   viram moeda. **Se a margem humano-vs-RL cair nessa ordem, a duração da rodada volta à
   mesa — com dado, não com opinião.** Foi a ressalva registrada quando o dono do projeto
   escolheu 120 s contra a recomendação de 180 s.

**DoD:** ≥200 rodadas por adversário, ≥12 seeds, estimativa com intervalo de confiança, e
a duração da rodada escolhida a partir deste dado com o número publicado.

**Fora do escopo:** mudar a rodada para a RL ganhar.

---

## 4. Pendências do dono do projeto

| # | pendência | recomendação |
|---|---|---|
| 1 | rodada parte do **estado neutro canônico** ou da leitura literal "continua de onde a RL parou"? | o neutro (implementado assim); a literal faria o timer herdar uma rede arrumada pelo concorrente |
| 2 | **modo corredor** (jogador controla só os 4 da arterial) entra como plano B ou já nasce? | plano B, decidido com o dado do A8 |
| 3 | a demo roda em **seed 42, onde o timer trava em 1h35** | seed held-out (100–111) + reinício horário, ou manchete no número held-out com a rodada corrente rotulada "esta rodada" |
| 4 | recalibrar o regime para cima (3800–4000 agora é estável com o plano coordenado) | só depois do A8, e sob o **braço humano** — que é o pior que de fato roda na feira |

---

## 5. Aberto, e não pode ser esquecido

**As duas bancadas discordam sobre a mesma condição.** Timer 27 s, 3500 veh/h, seed 42:
`sumo/aberta/calibra.py` diz **37,8%** parados; a Arena diz **31,4%** — com população
ativa idêntica (157).

Investigado até aqui:
- hipótese "subconjunto de faixas" **refutada por medição** (aproximação e todas as
  faixas dão o mesmo número: 49,55 em [300, 900));
- a **duração da janela** explica ~1,7 pp (33,3% em 600 s → 35,0% em 5400 s);
- sobra como candidato a **ordem de agregação**: `média(parados)/média(ativos)` contra
  `média(parados/ativos)` divergem bastante quando a cauda drena.

Reprodutor: `scripts/divergencia_bancadas.py`.

> **Enquanto não fechar: não cruze número de regime entre `CALIBRACAO_ABERTA.md` e
> `BASELINE_ABERTO.md`.** Cada documento é internamente consistente; a comparação entre
> eles é que não vale.

**Outros pontos vivos:**
- `ArenaSumo` mede a janela em `[t0+1, t1+1)`, não `[t0, t1)` — o `TrafficEnv.reset()` já
  dá um sim-step. Mesma duração, deslocada, **idêntica nos três braços** (pareamento
  intacto), mas a `Chave` rotula outra coisa.
- `feira/jogo/estado.py::cenario_da_seed()` é contorno do bug da Arena que já foi
  consertado — hoje é redundante. Simplificar quando alguém encostar no arquivo.
- Falha transitória de TraCI (`Connection closed by SUMO` no aquecimento) vista **1 vez em
  30+ corridas**. O motor degrada e o jogo segue; vigiar no ensaio com público.
- **Limpeza pendente que o sandbox nega:** `Remove-Item -Recurse -Force
  sumo\aberta\calibracao\taxa*` (73 MB de `.rou.xml` de varredura, gitignorados e
  regeneráveis; os `.json` ao lado são o dado e ficam).

---

## 6. Como disparar

As três trilhas têm pastas de escrita disjuntas. Regras que valeram nas ondas anteriores e
devem continuar valendo:

- nenhum agente edita `feira/contratos/**` — se achar um contrato errado, **reporta com
  motivo técnico, não conserta**;
- nenhum agente edita `feira/controladores/__init__.py`, `tests/test_contratos.py`,
  `tests/test_conformidade.py`, `tests/test_pacote_sim.py`, `docs/PLANO.md`, `README.md` —
  o coordenador liga os exports e registra na conformidade;
- nenhum agente roda `git`;
- nenhum agente escreve dentro de `smart-traffic-maquete/` ou `smart-traffic-rl/`;
- rodadas longas vão em **background**;
- toda corrida nova checa `res.inseridos > 0` — é barato e pega a classe de falha que
  custou uma trilha inteira de retrabalho.

**Recomendação de sequência:** passo 0 → **A6 sozinho** (é o caminho crítico e A7/A8
dependem do resultado dele) → A7 ‖ A8.
