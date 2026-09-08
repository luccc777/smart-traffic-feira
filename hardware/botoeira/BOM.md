# Botoeira SmartTraffic — BOM em R$

Preços de varejo **Brasil, set/2026**, para compra unitária (não em lote — são 13
botões, não 13 mil). Fornecedores citados são os plausíveis para cada linha; o
projeto não tem cotação fechada.

> ⚠️ **Estes preços não passaram por cotação real.** Trate como estimativa sólida
> para dimensionar o pedido, e confirme no carrinho antes de comprar — a mesma
> ressalva que o guia dos carrinhos faz da sua §11. As duas linhas que mais
> mexem no total são os 12 botões iluminados e o Pico.

---

## 1. Total

| Cenário | Total |
|---|---:|
| **Botoeira funcional, alimentada pelo USB** | **R$ 432** |
| + fonte externa 5 V/3 A (obrigatória se o LED passar de 28 mA — ver ESQUEMA §6.2) | R$ 477 |
| + peças de reposição (§4) | R$ 497 |

Para comparação de escala: os 18 carrinhos que saíram de cena orçavam ~R$ 1.516.
A botoeira é **28 %** disso e é a única peça de hardware que sobrou no projeto.

---

## 2. BOM completa

| # | Item | Qtd | Unit. R$ | Total R$ | Fornecedor plausível |
|--:|---|--:|--:|--:|---|
| 1 | **Raspberry Pi Pico** (RP2040), sem headers | 1 | 45,00 | **45,00** | Curto Circuito · Eletrogate · MakerHero |
| 2 | **Botão arcade iluminado 30 mm**, LED 5 V com resistor embutido | 12 | 13,00 | **156,00** | Mercado Livre (kits de arcade) · Baú da Eletrônica |
| 3 | **Botão arcade iluminado 44 mm** (START) | 1 | 35,00 | **35,00** | Mercado Livre |
| 4 | 74HC595N (DIP-16) | 2 | 2,50 | 5,00 | Baú da Eletrônica · Eletrogate |
| 5 | ULN2803A (DIP-18) | 2 | 4,50 | 9,00 | Baú da Eletrônica |
| 6 | Soquete DIP-16 | 2 | 1,20 | 2,40 | — |
| 7 | Soquete DIP-18 | 2 | 1,50 | 3,00 | — |
| 8 | Placa padrão ilhada 10 × 15 cm | 1 | 14,00 | 14,00 | — |
| 9 | Barra de pinos macho 40 vias | 2 | 3,50 | 7,00 | — |
| 10 | Resistor 10 kΩ 1/4 W (pull-up do /OE) | 10 | 0,30 | 3,00 | — |
| 11 | Capacitor cerâmico 100 nF | 10 | 0,50 | 5,00 | — |
| 12 | Capacitor eletrolítico 470 µF / 16 V | 1 | 2,50 | 2,50 | — |
| 13 | Fio flexível 24 AWG, 4 cores × 5 m | 1 | 35,00 | 35,00 | — |
| 14 | Terminal faston fêmea 2,8 mm (pacote 100) | 1 | 25,00 | 25,00 | — |
| 15 | **Cabo USB A ↔ micro-B, 1,5 m, COM DADOS** | 1 | 22,00 | 22,00 | — |
| 16 | MDF 3 mm cortado 305 × 240 mm + 13 furos (corte a laser) | 1 | 25,00 | 25,00 | marcenaria / fablab |
| 17 | Sarrafo de pinus 15 × 30 mm, 1,2 m (moldura) | 1 | 18,00 | 18,00 | — |
| 18 | Parafusos, porcas, cola, pés de borracha | 1 | 20,00 | 20,00 | — |
| | **SUBTOTAL — botoeira alimentada pelo USB** | | | **431,90** | |
| 19 | Fonte chaveada 5 V / 3 A + jack P4 fêmea de painel | 1 | 45,00 | 45,00 | — |
| | **TOTAL com fonte externa** | | | **476,90** | |

### Notas por linha

- **#1 Pico.** O Pico **W** custa ~R$ 20 a mais e traz Wi-Fi que não usamos —
  pior: no Pico W a GP25 é do módulo Wi-Fi, e o LED de heartbeat da placa some.
  Compre o **Pico normal**. Sem headers: os 17 fios vão soldados direto, e sem
  header a placa fica 3 mm mais baixa dentro da caixa.
- **#2 Botões.** A linha mais cara e a que sustenta o contrato: o C6 exige
  `feedback()` porque *"sem retorno visual o visitante conclui que o botão quebrou
  e para de jogar"*. **Confirme a tensão do LED antes de comprar** — 12 V é comum
  no mercado brasileiro de arcade e muda o §6 do ESQUEMA (fonte externa
  obrigatória, mas o ULN2803A já aguenta).
- **#3 START.** Precisa ser **visivelmente outro botão**: maior e separado. Se
  achar de 60 mm por preço parecido, melhor ainda — o furo muda no `gabarito.py`
  (`FURO_START_MM`), o teste refaz a folga e o SVG sai novo.
- **#15 Cabo USB.** ⚠️ **Cabo só-carga não enumera nada.** É o erro clássico e o
  sintoma é idêntico ao de firmware morto: `SerialInput` levanta
  `BotoeiraAusente: sem HELLO em 2.0 s`. Compre um cabo declaradamente de dados e
  teste **antes** de montar a caixa.
- **#16 MDF 3 mm.** Botão arcade genérico aceita painel de 1,5 a 6 mm; 3 mm é o
  ponto onde a porca ainda pega bastante rosca. A placa de 3 mm flexiona sob o
  dedo — daí a moldura (#17), que também vira a caixa.

---

## 3. O que **não** cortar (e o que dá)

| Corte tentador | Economia | Veredito |
|---|--:|---|
| Botão **sem** luz + LED de 5 mm ao lado | ~R$ 80 | ❌ **Não.** O LED tem que estar *no botão*: é o retorno que diz "ouvi você". Um LED ao lado vira decoração e o visitante não associa |
| Trocar os 12 arcade por táteis de 12 mm | ~R$ 120 | ❌ **Não.** Botão de 12 mm não é apertável por criança de pé, e o painel deixa de ser um mapa legível a 1 m |
| Cortar um dos ULN2803A | R$ 6 | ❌ Não fecha: 13 LEDs > 8 canais |
| Cortar o segundo 595 | R$ 4 | ❌ Não fecha: 13 > 8 saídas |
| MDF cru pintado à mão em vez de corte a laser | ~R$ 15 | ✅ Se você tiver serra copo de 28 mm e paciência. O `gabarito_painel.svg` impresso 1:1 é feito para isso |
| Caixa impressa em 3D em vez de moldura de pinus | ~R$ 18 | ✅ Só filamento. 305 × 240 não cabe numa Ender de uma vez — imprima em 4 cantoneiras |
| **Modo corredor** (4 botões da arterial, os outros 8 no plano fixo) | ~R$ 104 | ⚠️ É mitigação do **risco 8** do plano, não corte de custo. Se virar a decisão de produto, o painel encolhe — mas aí é um painel diferente, com o gabarito refeito |

---

## 4. Reposição — a linha que ninguém lembra e faz falta no sábado

| Item | Qtd | R$ |
|---|--:|--:|
| Botão arcade iluminado 30 mm | 1 | 13,00 |
| 74HC595N | 1 | 2,50 |
| ULN2803A | 1 | 4,50 |
| **Total** | | **20,00** |

Com soquete DIP (#6, #7) a troca de um CI queimado é sem ferro de solda, no meio
do evento. É por isso que os soquetes estão na BOM.

---

## 5. Custos que não são compra

| Item | Custo |
|---|---|
| Firmware MicroPython | livre — `.uf2` oficial da Raspberry Pi |
| `SerialInput` + `SerialFalso` | já entregues |
| Gabarito de furação | gerado (`gabarito_painel.svg`), imprimir em A3 |
| `pyserial` no venv | `pip install pyserial` (o jogo roda sem ele) |
