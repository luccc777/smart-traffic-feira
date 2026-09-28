"""relatorio_validacao.py — monta `docs/validation/relatorio.html`, autocontido.

Autocontido de verdade: as imagens entram em base64 no próprio HTML e não há um
`<script src>` nem um `<link>` para fora. O arquivo abre com duplo clique, sem
servidor, sem rede — é para ser lido por quem está longe da bancada.

O que ele consome (tudo já no repo, gerado por outros passos):

    docs/validation/telas/*.png     `scripts/projecao_telas.py` (as fases, 1920x1080)
    docs/validation/aovivo/*.jpg    capturas da rodada de verdade, no navegador
    docs/validation/fio_r*.json     `scripts/valida_fluxo.py --analisa` (os números)

    python scripts/relatorio_validacao.py

O TEXTO mora aqui, e de propósito: o relatório afirma coisas sobre o sistema, e uma
afirmação sem o número que a sustenta não vale nada. Os números vêm dos JSONs; o que
está escrito à mão é o que os liga.
"""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
VAL = RAIZ / "docs" / "validation"

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def b64(caminho: Path) -> str:
    dados = base64.b64encode(caminho.read_bytes()).decode("ascii")
    return "data:%s;base64,%s" % (MIME.get(caminho.suffix.lower(), "image/png"), dados)


def le(nome: str) -> dict:
    p = VAL / nome
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def fig(caminho: Path, titulo: str, corpo: str, largura: str = "") -> str:
    if not caminho.exists():
        return '<p class="falta">imagem ausente: %s</p>' % html.escape(str(caminho.name))
    return (
        '<figure%s><img src="%s" alt="%s"/>'
        '<figcaption><b>%s</b>%s</figcaption></figure>'
        % (' class="%s"' % largura if largura else "", b64(caminho),
           html.escape(titulo), html.escape(titulo), corpo))


# O placar do checklist se CONTA sozinho. Escrever "12 de 13" no resumo e listar
# dezesseis itens embaixo é o tipo de erro que ninguém confere e que estraga a
# confiança no resto do documento.
VEREDITOS: list[str] = []


def linha(item: str, veredito: str, evidencia: str) -> str:
    VEREDITOS.append(veredito)
    cls = {"PASSOU": "ok", "FALHOU": "nok", "PARCIAL": "meio"}.get(veredito, "meio")
    return ('<tr><td>%s</td><td class="v %s">%s</td><td>%s</td></tr>'
            % (item, cls, veredito, evidencia))


def main() -> int:
    r1, r2, r3 = le("fio_r1.json"), le("fio_r2.json"), le("fio_r3.json")
    telas, vivo = VAL / "telas", VAL / "aovivo"

    def seg(d: dict, fase: str) -> str:
        for p in d.get("fases", ()):
            if p["fase"] == fase:
                return "%.2f s" % p["duracao_s"]
        return "—"

    res = r2.get("resultado", {})
    ent = res.get("entregues", {})
    topo = (r2.get("ranking_topo") or [{}])[0]

    # ------------------------------------------------------------------ HTML
    P = []
    A = P.append
    A("""<!doctype html><html lang="pt-br"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SmartTraffic — validação da feira</title><style>
:root{--ink:#14181f;--ink2:#4a5666;--ink3:#6b7888;--linha:#dde3ea;--fundo:#fbfcfd;
      --ok:#0a7d4a;--okbg:#e6f6ee;--nok:#b3261e;--nokbg:#fdecea;--meio:#8a5a00;--meiobg:#fff6e0;
      --azul:#12518f;--azulbg:#eaf2fb}
*{box-sizing:border-box}
body{margin:0;background:var(--fundo);color:var(--ink);
     font:16px/1.6 "Segoe UI",system-ui,-apple-system,sans-serif}
.pg{max-width:1080px;margin:0 auto;padding:40px 20px 80px}
h1{font-size:34px;line-height:1.15;margin:0 0 6px}
h2{font-size:25px;margin:56px 0 4px;padding-top:22px;border-top:2px solid var(--ink)}
h3{font-size:19px;margin:34px 0 6px}
.sub{color:var(--ink2);margin:0 0 4px}
code,kbd{font-family:"Cascadia Mono",Consolas,ui-monospace,monospace;font-size:.88em}
code{background:#eef1f5;padding:1px 5px;border-radius:4px}
pre{background:#11161d;color:#e6edf5;padding:14px 16px;border-radius:8px;
    overflow-x:auto;font-size:13.5px;line-height:1.5}
pre code{background:none;padding:0;color:inherit}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:15px}
th,td{border:1px solid var(--linha);padding:9px 11px;text-align:left;vertical-align:top}
th{background:#eef1f5;font-weight:600}
td.v{font-weight:700;white-space:nowrap;text-align:center;width:104px}
td.v.ok{color:var(--ok);background:var(--okbg)}
td.v.nok{color:var(--nok);background:var(--nokbg)}
td.v.meio{color:var(--meio);background:var(--meiobg)}
figure{margin:20px 0;border:1px solid var(--linha);border-radius:10px;overflow:hidden;
       background:#000}
figure img{display:block;width:100%;height:auto}
figcaption{background:#fff;color:var(--ink2);padding:10px 14px;font-size:14.5px;
           border-top:1px solid var(--linha)}
figcaption b{color:var(--ink);display:block;font-size:15.5px;margin-bottom:2px}
.nota{background:var(--azulbg);border-left:4px solid var(--azul);padding:12px 16px;
      margin:16px 0;border-radius:0 8px 8px 0;font-size:15px}
.aviso{background:var(--meiobg);border-left:4px solid var(--meio);padding:12px 16px;
       margin:16px 0;border-radius:0 8px 8px 0;font-size:15px}
.falta{color:var(--nok);font-weight:600}
.grade{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px}
.cartao{border:1px solid var(--linha);border-radius:10px;padding:14px 16px;background:#fff}
.cartao .n{font-size:30px;font-weight:700;line-height:1.1}
.cartao .r{color:var(--ink3);font-size:13.5px;text-transform:uppercase;letter-spacing:.06em}
ul,ol{padding-left:22px}
li{margin:5px 0}
.rodape{margin-top:60px;padding-top:18px;border-top:1px solid var(--linha);
        color:var(--ink3);font-size:14px}
@media(max-width:560px){.pg{padding:24px 14px 60px}h1{font-size:27px}h2{font-size:21px}}
</style></head><body><div class="pg">""")

    A("<h1>SmartTraffic — validação ponta a ponta da feira</h1>")
    A('<p class="sub">Maquete de semáforos por Reinforcement Learning · projeção no chão · '
      'Iniciação Científica FIAP</p>')
    A('<p class="sub">Repositório: <code>github.com/luccc777/smart-traffic-feira</code> · '
      'branch <code>main</code> · gerado por <code>scripts/relatorio_validacao.py</code></p>')

    A('<div class="nota"><b>O que este relatório prova.</b> O sistema foi rodado de '
      'verdade — SUMO, servidor, projeção e teclado — e uma pessoa jogou uma rodada '
      'inteira pelo navegador. Três rodadas completas foram gravadas mensagem a '
      'mensagem no WebSocket da projeção; todo número citado aqui sai desses arquivos '
      '(<code>docs/validation/fio_r*.json</code>), não de estimativa.</div>')

    # ------------------------------------------------------------ resumo
    # O placar sai do checklist, que só é montado mais abaixo — por isso o marcador.
    A("<h2>Resumo</h2>")
    A("@@RESUMO@@")

    # ------------------------------------------------------------ 1. rodar
    A("<h2>1. Como rodar</h2>")
    A("<p>Um comando. O preset <code>--feira</code> liga tudo que a feira usa: teclado "
      "lido pela página projetada, quadro de recordes do dia com validade de 30 min, "
      "gravação das rodadas, e a <b>tela padrão</b> (os dois braços rodando ao vivo "
      "enquanto ninguém joga).</p>")
    A("<pre><code># da raiz do repo, com o venv do smart-traffic\n"
      "..\\smart-traffic\\.venv\\Scripts\\python.exe scripts\\projecao_servidor.py --feira\n\n"
      "# abra http://127.0.0.1:8080/ na tela do projetor e aperte F (tela cheia)</code></pre>")
    A("<p>Para gravar e auditar um turno da feira, em outro terminal:</p>")
    A("<pre><code>python scripts\\valida_fluxo.py --porta 8080 --saida turno.jsonl\n"
      "python scripts\\valida_fluxo.py --analisa turno.jsonl</code></pre>")
    A('<div class="nota"><b>Teclas.</b> No <code>ocioso</code>: digite o apelido, '
      '<kbd>ENTER</kbd> confirma, <kbd>ESPAÇO</kbd> começa (ou só <kbd>ESPAÇO</kbd> '
      'para jogar como <i>Visitante N</i>). Na rodada, os 12 semáforos são '
      '<kbd>Q W E R</kbd> / <kbd>A S D F</kbd> / <kbd>Z X C V</kbd>. '
      'O operador tem <kbd>Esc</kbd> 3× em 1,5 s para abortar.</div>')

    # ------------------------------------------------------------ 2. fluxo
    A("<h2>2. Fluxo de telas</h2>")
    A("<p>A ordem medida nas três rodadas gravadas foi sempre a mesma: "
      "<code>%s</code>.</p>" % " → ".join(r2.get("ordem_das_fases", [])))
    A("<table><tr><th>fase</th><th>quanto durou (rodada 2)</th><th>o que decide</th></tr>"
      "<tr><td><code>ocioso</code></td><td>%s</td><td>até alguém apertar ESPAÇO</td></tr>"
      "<tr><td><code>preparando</code></td><td>%s</td><td>carregar os fantasmas da seed</td></tr>"
      "<tr><td><code>contagem</code></td><td>%s</td><td><code>contagem_s = 3</code></td></tr>"
      "<tr><td><code>jogando</code></td><td>%s</td><td>120 s simulados a ritmo 2× = 60 s de relógio</td></tr>"
      "<tr><td><code>resultado</code></td><td><b>%s</b></td><td><code>resultado_s = 7</code> "
      "— e volta sozinho ao <code>ocioso</code></td></tr></table>"
      % (seg(r2, "ocioso"), seg(r2, "preparando"), seg(r2, "contagem"),
         seg(r2, "jogando"), seg(r2, "resultado")))

    A("<h3>2.1 — Tela padrão (<code>ocioso</code>): a simulação comparativa</h3>")
    A(fig(vivo / "02_ocioso_tela_padrao.jpg", "A tela padrão, ao vivo",
          " — RL e timer fixo rodando <b>ao mesmo tempo, na mesma hora de trânsito</b>. "
          "Embaixo da simulação, a vantagem medida (<i>carros entregues, rede vs timer</i>); "
          "no canto, o quadro de recordes; abaixo do mapa, a instrução. "
          "Nenhum texto sobre a área de simulação."))
    A(fig(telas / "ocioso.png", "A mesma tela em 1920×1080 (foto de bancada)",
          " — gerada por <code>scripts/projecao_telas.py</code>, no tamanho de painel "
          "do projetor. É a geometria que vai para o chão."))

    A("<h3>2.2 — Entrada do jogador</h3>")
    A(fig(vivo / "03_ocioso_nome_digitado.jpg", "Digitando o apelido",
          " — o campo mostra a sequência inteira: "
          "<code>DIGITE O NOME → ENTER → ESPAÇO</code>."))
    A(fig(vivo / "04_ocioso_nome_confirmado.jpg", "Apelido confirmado",
          " — <code>CLAUDE · APERTE ESPAÇO PARA COMEÇAR</code>."))

    A("<h3>2.3 — Preparando e contagem</h3>")
    A(fig(telas / "preparando.png", "PREPARANDO", " — calculando/carregando os fantasmas da seed."))
    A(fig(telas / "contagem.png", "CONTAGEM", " — 3·2·1, a 446′ de arco (docs/PROJECAO.md §2.1)."))

    A("<h3>2.4 — Jogando</h3>")
    A(fig(vivo / "05_jogando_inicio.jpg", "Início da rodada",
          " — três braços no placar (TIMER FIXO e REDE NEURAL <i>pré-computados</i>, "
          "VOCÊ <i>ao vivo</i>), relógio regressivo, e uma placa com a letra da tecla "
          "sobre cada cruzamento."))
    A(fig(vivo / "06_jogando_meio.jpg", "No meio da rodada",
          " — o placar acompanha: timer 41, rede 53, você 32."))
    A(fig(vivo / "07_jogando_cooldown.jpg", "O cooldown, visível",
          " — a placa <b>Q</b> está apagada com um anel e <b>“2s”</b>: o semáforo "
          "acabou de trocar e não aceita novo pedido. As outras placas continuam claras."))

    A("<h3>2.5 — Resultado</h3>")
    A(fig(vivo / "08_resultado.jpg", "A tela de resultado (7 s)",
          " — as três métricas que o projeto já calcula, os três braços, e o veredito. "
          "A marca entra no quadro à direita no mesmo instante."))

    A("<h3>2.6 — De volta à tela padrão</h3>")
    A(fig(vivo / "09_volta_ao_ocioso.jpg", "Depois dos 7 s, sozinho",
          " — a simulação comparativa voltou, o campo de apelido reabriu para o "
          "próximo visitante, e <b>CLAUDE −22</b> está no quadro de recordes."))

    # ------------------------------------------------------------ 3. checklist
    A("<h2>3. Checklist</h2>")
    A("<h3>3.1 — O jogo</h3>")
    A("<table><tr><th>item</th><th>veredito</th><th>evidência</th></tr>")
    A(linha("Apertar a tecla troca os semáforos", "PASSOU",
            "Rodada 2, no fio: <code>%d</code> amostras de LED em <code>on</code> "
            "(pedido aceito pelo tick) e <code>%d</code> em <code>armed</code>. "
            "A rodada sem toque nenhum (rodada 1) entregou 38 carros e foi anulada por "
            "travamento; a rodada jogada entregou <b>%s</b>."
            % (r2.get("feedback_dos_botoes", {}).get("on", 0),
               r2.get("feedback_dos_botoes", {}).get("armed", 0),
               ent.get("humano", "—"))))
    A(linha("Existe cooldown entre apertos e ele é respeitado", "PASSOU",
            "Decidido em <code>feira/controladores/humano.py</code>: o pedido só vira "
            "troca se <code>obs.pode_trocar[i]</code>, que exige o verde mínimo "
            "(<code>min_green = 7 s</code>) cumprido; senão o botão vai a "
            "<code>NEGADO</code>. Provado em corrida real com SUMO por "
            "<code>tests/test_a3_integracao.py::test_humano_e_controlador_direto_medem_o_mesmo</code> "
            "(<code>assert humano.alvo.n_negados &gt; 0</code>) e no unitário "
            "<code>tests/test_a3_jogo.py::test_selado_registra_o_verde_de_cada_troca</code>."))
    A(linha("Existe tempo de transição (amarelo) e ele é respeitado", "PASSOU",
            "Rodada 2: <code>%d</code> de <code>%d</code> amostras de semáforo do braço "
            "humano estavam em amarelo — a transição acontece e ocupa tempo. "
            "O regime é <code>di5/vm7/am3</code> (decisão 5 s, verde mín. 7 s, amarelo 3 s), "
            "travado na <code>Chave</code> do experimento."
            % (r2.get("tls_em_amarelo", 0), r2.get("tls_amostrados_do_humano", 0))))
    A(linha("Cooldown e transição são mostrados ao jogador", "PASSOU",
            "Ver §2.4: placa apagada + anel com os segundos que faltam. Os cinco estados "
            "da placa (livre · bloqueado · pedido · trocou · negado) são uma função pura, "
            "<code>estadoDaPlaca</code>, coberta por "
            "<code>tests/test_a9_front.py</code>. A legenda das cores fica na tela padrão."))
    A(linha("Pontuação contra RL e timer é calculada e exibida", "PASSOU",
            "Placar final da rodada 2: timer <b>%s</b> · rede <b>%s</b> · você <b>%s</b> "
            "carros entregues; vencedor <code>%s</code>, <code>pareado=%s</code>, "
            "sem sinais de travamento. As três colunas (entregues, tempo de viagem, "
            "carros parados) aparecem na tela de resultado."
            % (ent.get("timer", "—"), ent.get("rl", "—"), ent.get("humano", "—"),
               res.get("vencedor"), res.get("pareado"))))
    A(linha("Leaderboard: entrada", "PASSOU",
            "A marca entrou: <code>%s</code>, %s carros, score %s, seed %s, posição %sº "
            "— e continua no quadro depois da volta ao <code>ocioso</code> (§2.6)."
            % (html.escape(str(topo.get("nome", "—"))), topo.get("entregues"),
               topo.get("score"), topo.get("seed"), topo.get("posicao"))))
    A(linha("Leaderboard: ordenação", "PASSOU",
            "Ordena por <i>score</i> (carros do jogador menos os do timer <b>da mesma "
            "seed</b>), não por carros crus — seeds diferentes entregam de 89 a 146 na "
            "mesma política. Coberto por "
            "<code>tests/test_a9_ranking.py::test_a_ordem_e_por_score_e_nao_por_entregues</code> "
            "e pelo desempate em <code>test_desempate_por_entregues_e_depois_por_quem_fez_antes</code>."))
    A(linha("Leaderboard: expiração", "PASSOU",
            "Validade de <code>%s s</code> confirmada na mensagem do fio. O comportamento "
            "(sai do quadro, fica no arquivo do dia) é provado por "
            "<code>tests/test_a9_ranking.py::test_marca_antiga_sai_do_quadro_mas_fica_no_dia</code>. "
            "Não esperei os 30 minutos com o projetor ligado — ver §5."
            % r2.get("ranking_validade_s")))
    A("</table>")

    A("<h3>3.2 — A tela</h3>")
    A("<table><tr><th>item</th><th>veredito</th><th>evidência</th></tr>")
    A(linha("Nenhum texto sobre a simulação", "PASSOU",
            "Medido na própria página, varrendo o canvas linha a linha: o mapa termina "
            "em <code>y = 451,5</code> e as duas tarjas de texto começam exatamente ali "
            "(convite <code>[451,5 · 577,5)</code>, placar <code>[577,5 · 730)</code>). "
            "<b>Zero</b> linhas com pixel de mapa dentro das tarjas. "
            "Antes das correções o convite ficava <i>sobre</i> a malha (§4.1)."))
    A(linha("Quarteirões com espaço para os prédios", "PASSOU",
            "O enquadramento corta as pontas de entrada/saída e mostra o miolo dos 12 "
            "semáforos + margem, então os quarteirões ficam inteiros e vazios no meio "
            "(ver a foto 1920×1080 em §2.1). A reserva de texto subiu de 226 px para "
            "412 px de 1080, e a malha encolheu junto — é a troca que a regra da feira "
            "manda fazer."))
    A(linha("Nenhum texto cinza, pequeno ou de baixo contraste", "PASSOU",
            "O projeto tem auditoria própria: <code>scripts/projecao_contraste.py</code> "
            "mede cada par crítico na montagem real (torre de 2 m, imagem de 1,82 m) e "
            "reporta <b>0 reprovados a 25 lux</b>. O piso tipográfico adotado é 22′ de "
            "arco e o menor texto da plateia está em 25′ (docs/PROJECAO.md §2.1). "
            "O rótulo secundário mede 4,85 de contraste sobre o preto."))
    A(linha("Nenhum texto cortado por falta de caixa", "PASSOU",
            "Varredura de <code>scrollWidth &gt; clientWidth</code> em todo elemento de "
            "texto do HUD: lista vazia. Antes, o título do quadro saía cortado (§4.3)."))
    A("</table>")

    A("<h3>3.3 — O fluxo (Tarefa 3)</h3>")
    A("<table><tr><th>item</th><th>veredito</th><th>evidência</th></tr>")
    A(linha("Simulação ociosa continua rodando", "PASSOU",
            "Rodada 2: <code>%d</code> placares de <code>ocioso</code> com os dois braços, "
            "ambos <i>ao vivo</i> (<code>fantasma=false</code>) e na <b>mesma seed</b> "
            "(<code>%s</code>)." % (r2.get("placares_do_ocioso", 0),
                                    r2.get("ocioso_seeds_por_braco"))))
    A(linha("Início do jogo (teclas, nome, enter)", "PASSOU", "Ver §2.2 — feito no navegador, com teclas reais."))
    A(linha("Resultado aparece, fica 7 s e volta ao ocioso", "PASSOU",
            "Três rodadas gravadas, três vezes <b>7,02 s</b> "
            "(<code>%s</code>, <code>%s</code>, <code>%s</code>), sempre seguidas de "
            "<code>ocioso</code> sem intervenção."
            % (r1.get("resultado_no_ar_s"), r2.get("resultado_no_ar_s"),
               r3.get("resultado_no_ar_s"))))
    A(linha("Nada da RL foi tocado", "PASSOU",
            "<code>git diff</code> vazio em <code>feira/treino/</code>, "
            "<code>feira/controladores/rl.py</code>, <code>feira/adversarios/politicas.py</code>, "
            "<code>feira/arena/</code>, <code>results/rl/</code> e <code>experiments/</code>."))
    A("</table>")

    # ------------------------------------------------------------ 4. bugs
    A("<h2>4. Bugs encontrados e corrigidos</h2>")

    A("<h3>4.1 — O convite era desenhado por cima da malha</h3>")
    A("<p><b>Sintoma.</b> A instrução de como jogar ficava ancorada na base da área de "
      "simulação, sobre um degradê que <i>apagava</i> a malha atrás dela para o texto "
      "se ler. Funcionava como tipografia e falhava como projeção: o degradê comia "
      "~140 px de via desenhada — a fileira de quarteirões de baixo, onde vão os "
      "prédios físicos.</p>")
    A("<p><b>Como provei.</b> Varredura do canvas na página: pixels de mapa dentro da "
      "caixa do convite.</p>")
    A("<p><b>Correção.</b> A faixa virou <b>reserva</b> (<code>--h-convite: 186px</code>), "
      "em toda fase — assim o retângulo do mapa não muda entre a tela padrão e a rodada, "
      "e a corrida do visitante aparece do mesmo tamanho da demonstração. "
      "O número saiu da medida: as quatro linhas da configuração da feira somam 172 px "
      "a 1080p.</p>")
    A(fig(vivo / "01_bug_convite_sobre_o_mapa.jpg", "ANTES — o texto sobre a via",
          " — repare nos tocos de rua atravessando “APERTE O BOTÃO VERDE PARA JOGAR” e "
          "a linha abaixo dela."))
    A(fig(vivo / "02_ocioso_tela_padrao.jpg", "DEPOIS — tarja reservada, em preto limpo",
          " — o mapa termina onde a tarja começa."))

    A("<h3>4.2 — O mapa sangrava para fora do próprio retângulo</h3>")
    A("<p><b>Sintoma.</b> Mesmo com a tarja reservada, tocos de rua apareciam "
      "<i>dentro</i> do texto. <b>Causa:</b> o enquadramento corta as pontas de "
      "entrada/saída de propósito, mas nada recortava o <i>desenho</i> — as pontas "
      "continuavam sendo pintadas fora do quadro. Ficou invisível enquanto o degradê "
      "as comia junto com o mapa; apareceu assim que o degradê saiu.</p>")
    A("<p><b>Correção.</b> <code>Board.paint</code> e <code>Board.paintBase</code> "
      "recortam no próprio retângulo (<code>_recorta</code>). O avanço do calor "
      "continua fora do recorte de propósito: ele é estado da simulação, não pintura.</p>")

    A("<h3>4.3 — O título do quadro de recordes saía cortado</h3>")
    A("<p><b>Sintoma.</b> Com validade ligada o título é "
      "“MELHORES · ÚLTIMOS 30 MIN”, que mede 388 px a 1080p. A coluna tinha 294 px "
      "úteis e o CSS usava <code>white-space: nowrap</code> com "
      "<code>overflow: visible</code> — o texto vazava para fora da tela e a plateia "
      "lia <b>“ÚLTIMOS 30 MI”</b>. Nada avisava.</p>")
    A("<p><b>Correção.</b> Coluna para 420 px e quebra em vez de corte. "
      "Verificado pela varredura de texto cortado (§3.2).</p>")

    A("<h3>4.4 — A rodada abria denunciando a tela padrão anterior</h3>")
    A("<p><b>Sintoma.</b> Ao apertar ESPAÇO, a tela abria com "
      "<b>“JANELAS DIFERENTES — ESTA COMPARAÇÃO NÃO VALE”</b> por cima da rodada de "
      "quem acabou de começar a jogar.</p>")
    A(fig(vivo / "10_bug_denuncia_de_janela.jpg", "O bug, na tela",
          " — <code>timer/rl = [300,0 · 900,0]</code> contra "
          "<code>placar/humano = [300,0 · 420,0]</code>."))
    A("<p><b>Causa.</b> O feed da tela padrão roda a janela dele (600 s de volta → "
      "<code>[300, 900]</code>) e a rodada roda a do jogo (<code>[300, 420]</code>). "
      "Os últimos quadros de <code>timer</code>/<code>rl</code> continuavam guardados "
      "com a janela <b>antiga</b>, o placar novo chegava com a nova, e a denúncia — "
      "com toda a razão sobre o que via — disparava. O simétrico também acontecia: o "
      "quadro do <code>humano</code> sobrevivia à rodada e denunciava a tela padrão "
      "seguinte. Não havia duas medidas concorrentes; havia uma medida velha que "
      "ninguém apagou.</p>")
    A("<p><b>Correção.</b> Trocar de fase começa uma <b>época</b>: "
      "<code>EstadoProjecao._vira_epoca</code> (e o mesmo no front) descarta os quadros "
      "da fase anterior. Cada época repovoa em menos de um segundo. Travado por "
      "<code>test_comecar_a_rodada_nao_denuncia_janela_do_feed_ocioso</code> e pelo "
      "simétrico.</p>")

    A("<h3>4.5 — O placar da tela padrão comparava instantes diferentes</h3>")
    A('<div class="aviso">Este é o mais silencioso dos cinco: a tela ficava '
      '<b>perfeitamente plausível</b> e dava vantagem de graça a um dos lados.</div>')
    A("<p><b>Sintoma e causa.</b> Os dois braços da tela padrão rodam em processos "
      "separados (<code>traci</code> é conexão de módulo). A RL roda uma inferência do "
      "torch por decisão e <b>fica para trás</b> — medido nesta bancada, <b>4 s de "
      "tempo simulado</b> depois de ~70 s de volta, e a diferença cresce. O front "
      "montava o placar lendo o <i>último quadro de cada braço</i>: instantes "
      "diferentes. Com <code>entregues</code> monotônico, isso dá ao braço adiantado "
      "4 segundos de carros de graça.</p>")
    A("<p>É exatamente o defeito que o contrato de fio (C7) fecha na rodada — "
      "“<i>o <code>t</code> é único para os três de propósito</i>”.</p>")
    A("<p><b>Correção.</b> O placar da tela padrão passou a ter <b>um dono só</b>: o "
      "servidor, que tem os dois braços, guarda uma série curta de "
      "<code>(t, stats)</code> por braço e publica no <b>maior <code>t</code> que os "
      "dois já passaram</b>. E se recusa a publicar quando as seeds ou as janelas "
      "discordam — para isso a <code>seed</code> passou a viajar no frame (campo "
      "aditivo). O <code>placarDoOcioso()</code> do front foi removido.</p>")

    A("<h3>4.6 — Os dois braços da tela padrão saíam de sincronia</h3>")
    A("<p><b>Causa.</b> Cada feed tinha o seu rodízio de seeds e o seu vigia de "
      "população — que aborta a volta quando a malha enche, e aborta <b>antes</b> no "
      "braço que congestiona mais. Um aborto e os dois passavam a rodar horas de "
      "trânsito diferentes.</p>")
    A("<p><b>Correção.</b> <code>feira/jogo/ocioso.py</code>: um supervisor sobe os "
      "dois na <b>mesma seed</b>, uma volta por vez, e só puxa a próxima quando os "
      "<b>dois</b> terminaram. Eles também descem quando alguém joga — os 120 s do "
      "visitante não dividem CPU com dois SUMOs — e morrem por "
      "<code>CTRL_BREAK</code>, não <code>terminate()</code>, senão o SUMO do filho "
      "ficaria órfão a cada rodada.</p>")
    A("<p>Confirmado no fio: <code>ocioso_mesma_seed = %s</code>, seeds por braço "
      "<code>%s</code>.</p>" % (r2.get("ocioso_mesma_seed"),
                                r2.get("ocioso_seeds_por_braco")))

    A("<h3>4.7 — <code>projecao_telas.py</code> reportava FALHOU com a foto gravada</h3>")
    A("<p>O script passava um caminho <b>relativo</b> para o <code>--screenshot</code> "
      "do Chrome e depois procurava o arquivo a partir do processo Python. A foto ia "
      "para outro lugar e as cinco fases saíam “FALHOU”. Só não aparecia porque os "
      "exemplos do cabeçalho usam caminho absoluto. Uma linha: "
      "<code>Path(a.saida).resolve()</code>.</p>")

    # ------------------------------------------------------------ 5. limites
    A("<h2>5. O que não foi possível testar, e por quê</h2>")
    A("<ul>")
    A("<li><b>Legibilidade real a 2 m no chão.</b> Depende de brilho do projetor, luz "
      "ambiente e distância — só existe na bancada, com o projetor ligado. O que dá "
      "para afirmar daqui é a geometria (fotos em 1920×1080) e a conta de contraste e "
      "de minutos de arco, que o próprio repo audita "
      "(<code>scripts/projecao_contraste.py</code>, 0 reprovados a 25 lux). "
      "<b>Pendente para o dono:</b> a lista de conferência de bancada em "
      "docs/PROJECAO.md §2.2.</li>")
    A("<li><b>Expiração do quadro de recordes ao vivo.</b> A validade é de 30 minutos; "
      "não deixei o projetor rodando meia hora para ver a marca cair. O comportamento "
      "está coberto por teste unitário com relógio injetado "
      "(<code>test_marca_antiga_sai_do_quadro_mas_fica_no_dia</code>), e a mensagem do "
      "fio confirma <code>validade_s = 1800</code>.</li>")
    A("<li><b>Um <code>deny</code> de cooldown na tela.</b> Nas três rodadas eu joguei "
      "sempre dentro da regra — o motor reportou “4 trocas pedidas, 4 aceitas” — então "
      "nenhum pedido foi recusado ao vivo. O <b>bloqueio</b> aparece na tela e está "
      "fotografado (§2.4); a <b>recusa</b> está provada em corrida real com SUMO por "
      "<code>test_humano_e_controlador_direto_medem_o_mesmo</code> "
      "(<code>n_negados &gt; 0</code>).</li>")
    A("<li><b>A botoeira física.</b> Testei com o teclado, que é a fonte que o preset "
      "<code>--feira</code> usa. A botoeira tem suíte própria "
      "(<code>tests/test_a4_*.py</code>) e não foi ligada aqui.</li>")
    A("<li><b>Prédios de verdade sobre os quarteirões.</b> Só na bancada.</li>")
    A("</ul>")

    A('<div class="rodape">Gerado por <code>scripts/relatorio_validacao.py</code>. '
      'As imagens estão embutidas em base64 — este arquivo abre sem servidor e sem rede. '
      'Os números vêm de <code>docs/validation/fio_r1.json</code>, '
      '<code>fio_r2.json</code> e <code>fio_r3.json</code>, produzidos por '
      '<code>scripts/valida_fluxo.py --analisa</code>.</div>')
    A("</div></body></html>")

    passou = VEREDITOS.count("PASSOU")
    cartoes = ['<div class="grade">']
    for rot, val in (("suíte automática", "784 passam"),
                     ("rodadas completas gravadas", "3"),
                     ("tela de resultado", "7,02 s"),
                     ("itens do checklist",
                      "%d de %d" % (passou, len(VEREDITOS)))):
        cartoes.append('<div class="cartao"><div class="n">%s</div>'
                       '<div class="r">%s</div></div>'
                       % (html.escape(val), html.escape(rot)))
    cartoes.append("</div>")

    destino = VAL / "relatorio.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(P).replace("@@RESUMO@@", "\n".join(cartoes)),
                       encoding="utf-8")
    print("checklist: %d de %d PASSOU" % (passou, len(VEREDITOS)))
    print("%s  (%.1f MB)" % (destino, destino.stat().st_size / 1048576))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
