# Próximos passos — pronto para disparar

Estado em 2026-09-09. **Ondas 0, 1 e 2 concluídas.** Passo 0 executado e verificado
(§0); A6 e A7 entregues e conferidos. **Falta o A8** — e ele é a Onda 3 inteira.

Este documento existe para a próxima sessão começar disparando, sem redescobrir nada.

---

## 0. A demanda canônica — FEITO (2026-09-09)

**Decidido pelo dono do projeto, executado pelo coordenador.** O horizonte era
`HORIZONTE_S = 5400` e não sustentava a janela de 7200 s que a metaestabilidade exige:
medido na seed 42, a partir de t≈5700 a rede ficava **vazia**, e toda janela de 7200 s
promediava ~25% de rede deserta. Hoje `HORIZONTE_S = 8400` (300 de aquecimento + 7200 de
janela + 900 de folga), e as 18 seeds foram regeradas.

O que mudou: **o sha256 de toda demanda**, e portanto toda `Chave` (C5) já carimbada. Os
números medidos antes continuam válidos como medida — o que muda é a proveniência, e eles
precisam ser re-rodados para voltar a comparar. Cada seed passou de ~5138 para ~8100–8370
veículos. Vale a propriedade que o A1 mediu: o horizonte só ACRESCENTA no fim, então os
primeiros 5400 s de cada seed continuam byte a byte os de antes.

**Um defeito fechado no caminho.** `gera()` decidia não regerar comparando o sha do
arquivo com o manifesto — o que prova que o ARQUIVO bate com o MANIFESTO, mas não que o
manifesto bate com o CÓDIGO. Mudar `horizonte_s` deixaria em disco a demanda do regime
antigo, íntegra e com o sha certo, e o `gera()` a devolveria calada. É a mesma classe de
falha silenciosa que fez a Arena rodar a malha vazia, e é a razão pela qual o A5 teve de
carimbar o horizonte no nome da pasta em `tune_baseline_capacidade.py`. Agora
`GeradorDemandaAberta._divergencias()` compara os parâmetros que determinam o conteúdo
(taxa, horizonte, `od_weight`, `depart_lane`, `k_rotas`, ...) e regera, dizendo o motivo:

    seed  42 | 8053 veiculos | ... | horizonte_s 5400.0 -> 8400.0

Guardado por `tests/test_a1_demanda.py::test_parametro_mudado_regera_em_vez_de_devolver_o_disco`.

**Verificação (obrigatória, executada).** `scripts/divergencia_bancadas.py --seed 42
--ate 7200`, timer uniforme de 27 s:

| janela | ativos | % parados | km/h eq. (×6) |
|---|---|---|---|
| `[300, 900)` | 149,0 | 33,3% | 21,5 |
| `[300, 3900)` | 153,2 | 34,8% | 20,9 |
| `[300, 7500)` | **157,3** | **35,2%** | **20,6** |

6879 inseridos, 6871 entregues. **Nenhuma das 12 fatias de 600 s fica vazia** e a
população não deriva (141–170 em todas). O regime é estacionário na janela inteira — que
era exatamente o que o horizonte de 5400 não entregava.

**Confirmação independente:** o A5 já tinha gerado a demanda de 8400 s por conta própria,
em `sumo/aberta/planos/demanda_longa/`, para poder rodar 7200 s. Os arquivos batem **byte
a byte** com os canônicos de agora (seed 42: `5f89b4da…`, 1 889 734 bytes nos dois). Dois
caminhos independentes chegaram ao mesmo arquivo — é o invariante do C2 funcionando.

**O que NÃO mudou, e não deve mudar.** A demanda **de projeto** que alimentou o Webster
(`sumo/aberta/planos/projeto/demanda_projeto_s7.rou.xml`, seed 7) continua em 5400 s: o
horizonte dela é a constante própria `HORIZONTE_PROJETO` do
`scripts/tune_baseline_plano.py`, não o `HORIZONTE_S` do gerador. É separação correta e
deliberada — a demanda de projeto nunca é avaliada, só desenha o plano, e Webster só
precisa de taxas de fluxo. **Não "conserte" alinhando os dois horizontes:** isso
re-derivaria o plano congelado e invalidaria a comparação inteira do A5.

---

## 1. Agente A6 — Política RL no cenário aberto  ✅ **entregue**

**Fechou a DoD (a) em 12/12.** Checkpoint vencedor `results/rl/v1_queue_di5.pt` —
recompensa `queue`, grade do contrato (`di5/vm7/am3/mr0`), warm start de
`maq30_ats_di5_full_best.pt`. Held-out, 12 seeds (100–111), janela de 7200 s, pareado,
contra `coordenado_c60`:

| métrica | `coordenado_c60` | RL v1 | Δ+ | vitórias | p |
|---|---|---|---|---|---|
| entregues | 7000,9 | **7025,7** | +0,35% | 12/12 | 8,2e-08 |
| tempo no sistema | 159,06 s | **137,20 s** | +13,73% | 12/12 | 4,6e-12 |
| fila média | 52,69 | **31,22** | +40,71% | 12/12 | 5,2e-13 |
| espera média | 733,8 | **188,4** | +74,26% | 12/12 | 1,0e-13 |

Vitórias na **trinca** (as três na mesma seed): 12/12. Zero travamentos, `sane()` verde
12/12, `sinais_de_travamento` vazio em 12/12, lacuna de sobrevivência −1,14% a −0,68%
(faixa sã: −1,4% a −0,2%).

**Conferido fora da bancada do A6.** O coordenador rodou a seed 100 num script próprio,
sem importar nada de `feira/treino` nem ler `results/rl/*.json`: +0,27% / +13,49% /
+40,62% / +74,02%, chaves idênticas nos dois braços. E o braço `coordenado_c60` medido
pelo A6 devolve 7000,9 entregues e fila 52,69 — os mesmos 7001 e 52,69 do
`BASELINE_ABERTO.md` §4.5, no dígito.

**O "antes", na mesma bancada:** a política que estava em produção
(`maq30_ats_full_best.pt`) entrega 3140,8 contra 7001 (**−55,1%**), fila 667,8, e
**trava em 3 de 12 seeds**. O "93 e 82 contra 111 e 109" que o A3 mediu era o começo
desse colapso, numa janela curta demais para mostrá-lo inteiro.

### Variantes descartadas, com o número

| variante | resultado | por que caiu |
|---|---|---|
| v2 `pressure` | +0,39% / +35,94% / +11,66% | perde do `queue` (+0,44 / +41,55 / +14,11). **Max-pressure refutado também na rede aberta.** |
| v4 `pressure`+`max_red 60` | +0,37% / +34,86% / +10,95% | e instável: duas validações colapsadas |
| v5 grade 10/10 | +2,96% em percentual | perde em absoluto (7016,5 contra 7025,7; fila 40,03 contra 31,22). **`RESTRICOES_ABERTA` fica 5/7.** |
| v6 sem warm start | +0,43% / +38,47% / +12,81% | empata com o v1 — o warm start comprou ~70 min, não qualidade |
| v3 `queue`+`max_red 60` | held-out melhor: 7029,0 / 30,45 / 135,66 | **perdeu no critério declarado** (vazão, por 0,02 pp) na seleção. Não foi promovido de propósito: trocar por causa da held-out é escolher no conjunto de teste — o erro que o `BASELINE_ABERTO.md` §4.6 documenta para o `c50`. A troca é uma linha, se o dono quiser, com esta nota junto. |

### Dois achados do A6 que mudam leitura

1. **O A/B de grade não compara o mesmo adversário.** Em `di10` o `coordenado_c60` perde
   6 dos 12 splits e a onda verde quebra: ele cai de 7000,9 para 6814,6 entregues. Os
   +2,96% do braço 10/10 mediam o adversário **mutilado**. Foi o que salvou a grade 5/7
   de ser trocada por um número que não existia.
2. **`sane()` sozinho não pega o colapso** — uma validação com lacuna de 94,1% e backlog
   de 660 passou, porque o backlog ficou em 9,8% dos agendados, um décimo de ponto abaixo
   do teto do C5. É o mesmo achado que `test_sane_e_estrutural_e_nao_ve_gridlock_sozinho`
   já guarda: `sane()` é **estrutural**, e o veredito de saúde é do
   `sinais_de_travamento`, onde quem chama declara o limiar. A porta de seleção do A6
   passou a exigir os dois.

### Consertado pelo coordenador ao integrar

**O cache de fantasmas não sabia QUEM o gerou.** `Fantasma.confere()` compara a `Chave`
(C5) — cenário, seed, janela, demanda, restrições —, que descreve a **condição** e
deliberadamente não diz quem jogou. Duas políticas na mesma condição produzem fantasmas
de chave idêntica. Consequência concreta: trocar `CKPT_PADRAO` para a política nova
reaproveitaria **em silêncio** o fantasma da velha, e o projetor exibiria a RL antiga —
perdendo — com o nome da nova. O nome do controlador já viajava no arquivo desde sempre
(`rl:maq30_ats_full_best`); só nunca era comparado. Provado ao vivo nos fantasmas reais
em disco. No mesmo lugar, o subprocesso do prefetch não recebia `--ckpt` e caía no
default. Guardado por dois testes em `tests/test_a3_jogo.py`.

**E o ponteiro foi trocado:** `feira/jogo/fantasmas.py::CKPT_PADRAO` aponta agora para
`results/rl/v1_queue_di5.pt`.

### Onde o A6 discorda de decisão já tomada — e ele tem razão

**A DoD exigia `p<0,01` na vazão, que é a métrica de MENOR resolução deste regime.** Com
`inseridos` idêntico nos dois braços e backlog zero, a identidade do C5 reduz a diferença
de vazão a `ativos_fim` — o teto útil é ~+0,4%. A prova é direta: **o próprio
`coordenado_c60` reprovaria nessa cláusula** (8/12, p = 0,19 contra o timer27, mesmas
seeds e mesma janela), e ele já foi aceito como melhoria por este projeto.

**Adotado para o A8:** a vazão entra como **porta** (não pode cair, backlog zero) e não
como uma das três com `p<0,01`. Não muda nada no A6, que passou 12/12 com p = 8,2e-08.
Fica registrado porque o critério vai ser reusado, e porque é decisão que o dono pode
querer rever se o regime subir para 3800–4000.

### Aberto no A6

- sem varredura de hiperparâmetro; **uma semente de treino por variante** — o ranking
  *interno* das cinco variantes de 5/7 (dentro de 0,07 pp) não é confiável; só o ranking
  contra o baseline é;
- `espera_media` **+74,3%** é grande demais para virar manchete sem alguém auditar a
  métrica na rede aberta. **Não use esse número em slide antes disso.**
- lixo de fumaça que o sandbox não deixou apagar: `experiments/_smoke_a6/`,
  `experiments/_smoke2/`, `results/rl/smoke_a6.pt`, `results/rl/smoke2.pt`.

Documento completo, com tabela seed a seed e reprodução: [`docs/RESULTADOS_ABERTA.md`](RESULTADOS_ABERTA.md).

---

## 2. Agente A7 — Projeção & Placar  ✅ **entregue**

Ver [`docs/PROJECAO.md`](PROJECAO.md) e a triagem de contratos no §5 deste documento.

---

## 3. Agente A8 — Adversários & Calibração de Dificuldade  ← **o que falta**

**Depende de:** A3 ✅, A5 ✅, A6 ✅ — **está desbloqueado.** O adversário é a política
`results/rl/v1_queue_di5.pt`, e o critério de vazão entra como porta, não como cláusula
de `p<0,01` (ver §1).

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
- o **horizonte da demanda não era a causa** (medido no passo 0): com a demanda de 8400 s
  o reprodutor dá 35,0% em `[300, 5700)`, o MESMO número de antes — como manda a
  propriedade de prefixo. O que a regeração conserta é outra coisa: a janela de 7200 s
  passou a medir rede com carro dentro em vez de cauda deserta;
- sobra como candidato a **ordem de agregação**: `média(parados)/média(ativos)` contra
  `média(parados/ativos)` divergem bastante quando a cauda drena.

**O que o passo 0 acrescentou ao caso.** Há hoje quatro leituras da mesma condição:

| leitura | % parados |
|---|---|
| `sumo/aberta/calibra.py` (A1) | 37,8% |
| `_LeitorDeFaixas` do A5 — segundo caminho, independente | 35,3% |
| `scripts/divergencia_bancadas.py` — observador da Arena, `[300, 7500)` | 35,2% |
| manchete do `Resultado` da Arena (A2) | 31,4% |

As **duas leituras independentes ao nível de observador batem** (35,3% e 35,2%), e ficam
entre as duas publicadas. Isso desloca a suspeita: o número fora da curva é a **manchete
do `Resultado` da Arena**, não o do `calibra.py`. **Ainda é hipótese** — quem fecha é
comparar as duas ordens de agregação sobre a MESMA série, que é uma tarde de trabalho e
não precisa de agente.

Reprodutor: `scripts/divergencia_bancadas.py`.

> **Enquanto não fechar: não cruze número de regime entre `CALIBRACAO_ABERTA.md` e
> `BASELINE_ABERTO.md`.** Cada documento é internamente consistente; a comparação entre
> eles é que não vale.

### Triagem dos contratos reportados pelo A7 (2026-09-09)

O A7 reportou cinco pontos e não consertou nenhum, como manda a regra. Veredito do
coordenador:

| # | reportado | veredito |
|---|---|---|
| 2 | C7 mistura `tipo` (placar) e `type` (frame) | **procede, corrigido.** `type` é herdado do `snapshot.frame` do maquete e não pode ser renomeado sem quebrar a projeção que já roda; `tipo` é do placar novo. `Placar.json()` passou a emitir **os dois**, com o mesmo valor — o cliente despacha por um nome só e a mensagem para de poder sumir sem erro. |
| 3 | `Placar` não carrega `motivo` | **procede, e era pior do que ele descreveu — corrigido.** `vencedor=None` tinha dois significados opostos no fio: empate e **rodada não pareada** (selos de t0 divergentes). O motor já escrevia o texto detalhado em `ResultadoRodada.motivo` e o jogava fora. `Placar` ganhou `motivo` e `pareado`; o front foi devolvido ao A7 para denunciar em vez de coroar. Guardado por `test_placar_distingue_empate_de_rodada_nao_pareada` e pela ponta a ponta em `test_selo_divergente_nao_coroa_vencedor`. **Ver a nota abaixo — são quatro desfechos, não três.** |
| 1 | o motor não expõe gancho de frame | **procede, mas não vou consertar.** O contorno dele — `ArenaPublicada`, decorador do `Arena` (C4), entrando pelo `arena=` que o motor já aceita — é **melhor** que o `MotorDoJogo(ao_quadro=...)` que ele sugeriu: frame é assunto da Arena, não da rodada, e o decorador é testável sozinho. Fica como está. |
| 4 | `Placar` não anuncia a próxima seed | procede, cosmético. Entra se e quando a tela de `ocioso` precisar. |
| 5 | `frame_wire` levanta em braço desconhecido | **não é defeito** — é a guarda fazendo o trabalho dela. O nome do controlador é `familia:variante` por convenção dos controladores, e normalizar para o braço é do consumidor, onde o A7 pôs (`braco_do_controlador()`). Se um terceiro consumidor precisar, aí sim sobe para o C7. |

**`vencedor: null` são QUATRO desfechos, não três.** Ao devolver a tarefa eu instruí o
A7 que "`pareado=true` e `vencedor=null` ⇒ empate". **Estava errado, e ele recusou com
razão:** rodada abortada pelo operador e rodada em que o SUMO caiu também chegam
`pareado=true` e sem vencedor, e chamá-las de empate daria ao visitante um resultado que
ele não fez. Os dois casos já se distinguem no fio, sem campo novo — **uma rodada que não
aconteceu não tem linha do humano**: `res` só é atribuído numa corrida bem-sucedida, e
tanto o `RodadaAbortada` quanto a exceção genérica deixam `humano=None`, que o
`_placar_final` não anexa. Os quatro:

| fio | desfecho | tela |
|---|---|---|
| `pareado: false` | não pareada | denúncia + `motivo`, sem coroa e **sem colocação** |
| `vencedor: "x"` | vencedor | coroa |
| sem linha do humano | rodada não concluída | "RODADA NÃO CONCLUÍDA" + `motivo` |
| resto | empate | "EMPATE", neutro |

E `motivo` não vazio **não** invalida sozinho: "modo degradado: sem fantasma de rl" é uma
rodada boa de dois braços, e ela coroa normalmente.

**A DoD (a) do A7 não é verificável por agente nenhum** — exige o projetor e uma foto.
Ele tem razão em pedir que o documento separe **DoD do agente** e **DoD do dono**; daqui
para frente, escreva as duas listas separadas ao abrir uma trilha.

**Outros pontos vivos:**
- `ArenaSumo` mede a janela em `[t0+1, t1+1)`, não `[t0, t1)` — o `TrafficEnv.reset()` já
  dá um sim-step. Mesma duração, deslocada, **idêntica nos três braços** (pareamento
  intacto), mas a `Chave` rotula outra coisa.
- `feira/jogo/estado.py::cenario_da_seed()` é contorno do bug da Arena que já foi
  consertado — hoje é redundante. Simplificar quando alguém encostar no arquivo.
- `sumo/aberta/planos/demanda_longa/` (34 MB, 56 arquivos) virou **cópia byte a byte** da
  demanda canônica com o passo 0. Duas fontes de verdade para o mesmo arquivo é como se
  mede a coisa errada sem perceber. Apagar a pasta e fazer o `--demanda-longa` do
  `scripts/tune_baseline_varredura.py` apontar para a canônica — pequeno, mas é do A5, e
  ninguém deve mexer enquanto o A6 estiver medindo.
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
