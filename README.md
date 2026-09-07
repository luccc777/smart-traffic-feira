# smart-traffic-feira — rede aberta, comparação auditada e modo jogo

O terceiro repo do SmartTraffic (IC FIAP). Os dois primeiros continuam donos do que
sempre foram; este é o da **feira**:

| repo | é dono de |
|---|---|
| `smart-traffic-maquete` | o ambiente de RL (`sim/`), a rede fechada e os resultados dela |
| `smart-traffic-rl` | a linha de pesquisa na rede grande (Vila Olímpia) |
| **`smart-traffic-feira`** | **a rede de bordas abertas, a bancada de comparação auditada e o modo jogo** |

## A regra que barateia tudo: aqui não se copia ambiente

Este repo **não reimplementa** `TrafficEnv`, `FixedTimerSim`, a GNN nem as métricas.
Ele consome o pacote `sim` do maquete, em modo editável:

```powershell
# uma vez, no venv COMPARTILHADO (o do smart-traffic; este repo não tem .venv próprio)
..\smart-traffic\.venv\Scripts\python.exe -m pip install -e ..\smart-traffic-maquete --no-deps
..\smart-traffic\.venv\Scripts\python.exe -m pip install -e . --no-deps
```

Assim os números da rede fechada seguem reproduzíveis **no repo deles**, e aqui não
existe uma segunda cópia para divergir. `tests/test_pacote_sim.py` guarda essa
fronteira: se algo que este repo consome sumir do maquete, quebra num teste, não na
feira.

## Como rodar

```powershell
.\run_testes.ps1              # a suíte inteira (não precisa de SUMO)
.\run_testes.ps1 -Lint        # + ruff
```

## Estado

**Onda 0 concluída: os contratos estão congelados.** Nenhuma implementação ainda —
é de propósito: a regra do projeto é contrato antes de código, para os agentes
poderem trabalhar em paralelo sem se atropelar.

| # | contrato | módulo | congela |
|---|---|---|---|
| C1 | `Cenario` | `feira/contratos/cenario.py` | rede + demanda + **restrições de fase iguais para os três braços** |
| C2 | `Demanda` | `feira/contratos/demanda.py` | mesma seed → mesmo `.rou.xml`, provado por sha256 |
| C3 | `Controlador` | `feira/contratos/controlador.py` | a única superfície de RL, timer e humano |
| C4 | `Arena` | `feira/contratos/arena.py` | **um laço só** roda os três; a cadência é do laço |
| C5 | `Resultado` | `feira/contratos/resultado.py` | o que se mediu + a `Chave` sem a qual não se compara |
| C6 | `FonteEntrada` | `feira/contratos/entrada.py` | teclado / botoeira / replay, plugáveis |
| C7 | fio | `feira/contratos/frame.py` | frames e placar até a projeção |
| C8 | `Fantasma` | `feira/contratos/fantasma.py` | trajetória pré-computada, carimbada com a `Chave` |

Cada módulo abre com o *porquê* — quase todo invariante aqui existe por causa de um
bug real, do histórico do projeto ou da auditoria do sistema de comparação atual.

`feira/_fakes.py` traz implementações de referência: elas são o alvo de
`tests/test_conformidade.py`, a suíte parametrizada que **toda** implementação real
vai ter que passar. Quando o agente A6 entregar o `ControladorRL`, ele entra na mesma
lista e é cobrado pelos mesmos testes.

## Mapa

```
feira/contratos/   C1..C8 — congelados na Onda 0
feira/_fakes.py    implementações de referência (alvo da conformidade)
sumo/aberta/       rede de bordas abertas + demanda por seed      (A1, Onda 1)
web/               projeção com o placar da rodada                (A7, Onda 2)
docs/PLANO.md      o plano aprovado: agentes, ondas, riscos
experiments/       uma pasta por run
results/           campeões + fantasmas pré-computados
```

## O que este repo NÃO faz

Não reabre a rede fechada, não mexe nos pesos treinados do maquete, e não enfraquece
baseline. O timer é tunado honestamente (Webster + splits + **offsets**, que hoje não
existem) mesmo que isso encolha a margem publicada — ver `docs/PLANO.md`, §"Onde eu
discordo".
