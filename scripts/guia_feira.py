"""guia_feira.py — monta o GUIA DA FEIRA: quem vai apresentar lê isto e opera sozinho.

Duas saidas do mesmo conteudo, como o `relatorio_validacao.py`:

    docs/GUIA_DA_FEIRA.html            autocontido (base64), abre do disco sem rede
    docs/GUIA_DA_FEIRA.artifact.html   so o conteudo, para publicar como Artifact

    python scripts/guia_feira.py

As imagens saem de `docs/validation/` — as mesmas telas que a validacao usou, que sao
as telas que a feira mostra. Se elas mudarem, rode
`python scripts/projecao_telas.py --saida docs/validation/telas --sem-diag` antes.
"""
from __future__ import annotations

import base64
import html
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
VAL = RAIZ / "docs" / "validation"
TELAS, VIVO = VAL / "telas", VAL / "aovivo"

BR = chr(10)
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

# A familia e a paleta sao as da PROJECAO (`web/css/projecao.css`), auditadas por
# `scripts/projecao_contraste.py`. O guia fala da mesma tela, entao veste o mesmo.
SANS = '"IBM Plex Sans","Segoe UI",system-ui,-apple-system,sans-serif'
MONO = '"IBM Plex Mono","Cascadia Mono",Consolas,ui-monospace,monospace'

ESTILO = """<style>
:root{
  --fundo:#f5f7f9; --papel:#ffffff; --tinta:#0d1217; --tinta2:#44525f; --tinta3:#6b7a88;
  --linha:#d7e0e8; --forte:#0d1217; --campo:#e8eef4;
  --rl:#0d4d8a; --rl-fraco:#e8f1fa; --timer:#8a4e05; --timer-fraco:#fbf1e2;
  --ok:#0a6b41; --ok-fundo:#e5f4ec; --alerta:#a3241c; --alerta-fundo:#fbeceb;
  --aviso:#7a4f00; --aviso-fundo:#fdf2df;
  --pre-fundo:#0d1217; --pre-tinta:#e6edf5;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --fundo:#0a0e13; --papel:#131a21; --tinta:#e9eff6; --tinta2:#a4b3c2; --tinta3:#7b8a99;
    --linha:#222d37; --forte:#3a4855; --campo:#1b232b;
    --rl:#7fcbfa; --rl-fraco:#132030; --timer:#cb7a18; --timer-fraco:#241a0d;
    --ok:#4fd894; --ok-fundo:#0e2a1f; --alerta:#ff8a7e; --alerta-fundo:#2c1614;
    --aviso:#ffc861; --aviso-fundo:#2a2011;
    --pre-fundo:#05080b; --pre-tinta:#dbe5ef;
  }
}
:root[data-theme="dark"]{
  --fundo:#0a0e13; --papel:#131a21; --tinta:#e9eff6; --tinta2:#a4b3c2; --tinta3:#7b8a99;
  --linha:#222d37; --forte:#3a4855; --campo:#1b232b;
  --rl:#7fcbfa; --rl-fraco:#132030; --timer:#cb7a18; --timer-fraco:#241a0d;
  --ok:#4fd894; --ok-fundo:#0e2a1f; --alerta:#ff8a7e; --alerta-fundo:#2c1614;
  --aviso:#ffc861; --aviso-fundo:#2a2011;
  --pre-fundo:#05080b; --pre-tinta:#dbe5ef;
}
*{box-sizing:border-box}
body{margin:0;background:var(--fundo);color:var(--tinta);
     font:16px/1.65 SANS_;-webkit-text-size-adjust:100%}
img{max-width:100%}
.pg{max-width:940px;margin:0 auto;padding-block:36px 80px;padding-left:20px;padding-right:20px}
h1{font-size:clamp(28px,6vw,40px);line-height:1.1;margin:0 0 10px;letter-spacing:-.02em;
   text-wrap:balance}
h2{font-size:clamp(21px,4.4vw,27px);margin:64px 0 6px;padding-top:20px;
   border-top:3px solid var(--forte);text-wrap:balance;letter-spacing:-.01em}
h3{font-size:clamp(17px,3.2vw,20px);margin:32px 0 6px;text-wrap:balance}
p{margin:12px 0} ul,ol{padding-left:22px} li{margin:6px 0}
.chapeu{font:600 13px/1 MONO_;letter-spacing:.18em;text-transform:uppercase;
        color:var(--rl);margin:0 0 10px}
.lead{font-size:clamp(17px,3vw,19px);color:var(--tinta2);margin:0 0 6px}
code,kbd{font-family:MONO_;font-size:.87em}
code{background:var(--campo);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
kbd{display:inline-block;background:var(--papel);border:1px solid var(--linha);
    border-bottom-width:3px;border-radius:6px;padding:2px 8px;font-size:.84em;
    font-weight:600;white-space:nowrap;color:var(--tinta)}
pre{background:var(--pre-fundo);color:var(--pre-tinta);padding:16px 18px;border-radius:10px;
    overflow-x:auto;font-size:13.5px;line-height:1.6}
pre code{background:none;padding:0;color:inherit}
.rolagem{overflow-x:auto;margin:16px 0;border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:15px;min-width:460px}
th,td{border:1px solid var(--linha);padding:10px 12px;text-align:left;vertical-align:top}
th{background:var(--campo);font-weight:600}
figure{margin:20px 0;border:1px solid var(--linha);border-radius:12px;overflow:hidden;
       background:#000}
figure img{display:block;width:100%;height:auto}
figcaption{background:var(--papel);color:var(--tinta2);padding:11px 15px;font-size:14.5px;
           border-top:1px solid var(--linha)}
figcaption b{color:var(--tinta);display:block;font-size:15.5px;margin-bottom:2px}
.passo{display:flex;gap:18px;align-items:flex-start;margin:22px 0}
.passo .n{flex:none;width:38px;height:38px;border-radius:50%;background:var(--rl);
          color:var(--papel);display:flex;align-items:center;justify-content:center;
          font:700 19px/1 MONO_}
.passo .c{flex:1;min-width:0}
.passo .c h3{margin:4px 0 4px}
.fala{background:var(--rl-fraco);border-left:5px solid var(--rl);padding:16px 20px;
      margin:16px 0;border-radius:0 10px 10px 0;font-size:clamp(16px,3vw,18px);
      line-height:1.6}
.fala b{color:var(--rl)}
.nota{background:var(--papel);border:1px solid var(--linha);border-left:5px solid var(--ok);
      padding:14px 18px;margin:16px 0;border-radius:0 10px 10px 0;font-size:15px}
.aviso{background:var(--aviso-fundo);border-left:5px solid var(--aviso);padding:14px 18px;
       margin:16px 0;border-radius:0 10px 10px 0;font-size:15px}
.grade{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));
       gap:14px;margin:18px 0}
.cartao{border:1px solid var(--linha);border-radius:12px;padding:16px 18px;
        background:var(--papel)}
.cartao .n{font:700 32px/1.05 MONO_;font-variant-numeric:tabular-nums;color:var(--rl)}
.cartao .r{color:var(--tinta3);font-size:12.5px;text-transform:uppercase;
           letter-spacing:.08em;margin-top:6px}
.placa{display:inline-block;width:15px;height:15px;border-radius:4px;vertical-align:-2px;
       margin-right:7px;border:1px solid rgba(128,128,128,.45)}
.faq{border-top:1px solid var(--linha);padding-top:14px;margin-top:14px}
.faq p:first-child{font-weight:600;margin-top:0}
.rodape{margin-top:64px;padding-top:18px;border-top:1px solid var(--linha);
        color:var(--tinta3);font-size:14px}
@media(max-width:560px){
  .pg{padding-block:24px 56px;padding-left:16px;padding-right:16px}
  .passo{gap:12px} .passo .n{width:32px;height:32px;font-size:16px}
}
</style>""".replace("SANS_", SANS).replace("MONO_", MONO)


def b64(p: Path) -> str:
    return "data:%s;base64,%s" % (MIME.get(p.suffix.lower(), "image/png"),
                                  base64.b64encode(p.read_bytes()).decode("ascii"))


def fig(caminho: Path, titulo: str, corpo: str = "") -> str:
    if not caminho.exists():
        return '<p style="color:var(--alerta)"><b>imagem ausente: %s</b></p>' % html.escape(
            caminho.name)
    return ('<figure><img src="%s" alt="%s"/><figcaption><b>%s</b>%s</figcaption></figure>'
            % (b64(caminho), html.escape(titulo), html.escape(titulo), corpo))


def passo(n: str, titulo: str, corpo: str) -> str:
    return ('<div class="passo"><div class="n">%s</div><div class="c">'
            '<h3>%s</h3>%s</div></div>' % (n, html.escape(titulo), corpo))


def main() -> int:
    P: list[str] = []
    A = P.append
    A(ESTILO)
    A('<div class="pg">')

    # ------------------------------------------------------------------ capa
    A('<p class="chapeu">Guia de quem apresenta</p>')
    A("<h1>SmartTraffic na feira</h1>")
    A('<p class="lead">Como a simulação funciona, como o jogo funciona, e o que dizer '
      'para a pessoa que parou na frente da maquete.</p>')
    A('<p class="lead" style="font-size:15px">Iniciação Científica · FIAP · '
      'leia uma vez antes de abrir a feira; depois consulte pelo índice.</p>')

    A('<div class="grade">')
    for val, rot in (("12", "semáforos que o visitante controla"),
                     ("120 s", "de rodada, em 60 s de relógio"),
                     ("3", "braços comparados no mesmo trânsito"),
                     ("30 min", "que um recorde dura no quadro")):
        A('<div class="cartao"><div class="n">%s</div><div class="r">%s</div></div>'
          % (html.escape(val), html.escape(rot)))
    A("</div>")

    # ------------------------------------------------------------ 1. a proposta
    A("<h2>1. A proposta, em trinta segundos</h2>")
    A("<p>Todo semáforo de esquina funciona no <b>relógio</b>: abre e fecha em tempo "
      "fixo, não importa se tem fila de um lado e rua vazia do outro. A pergunta do "
      "projeto é simples: <b>e se ele olhasse o trânsito antes de decidir?</b></p>")
    A("<p>Treinamos uma <b>rede neural</b> para fazer exatamente isso — ela vê quantos "
      "carros estão parados em cada aproximação e escolhe a hora de trocar. Depois a "
      "colocamos para correr <b>lado a lado</b> com o semáforo de tempo fixo, na mesma "
      "hora de trânsito, na mesma rede, partindo do mesmo instante. O que a projeção "
      "no chão mostra é essa corrida acontecendo.</p>")
    A('<div class="fala">Para falar com o visitante:<br>'
      '“Esses prédios são um bairro. Os carrinhos de luz são o trânsito de verdade, '
      'simulado. De um lado, semáforo comum, no relógio. Do outro, uma '
      '<b>inteligência artificial</b> que olha a fila antes de abrir. Os '
      'números embaixo mostram quem está ganhando. <b>E você pode tentar ganhar dos dois.</b>”'
      '</div>')

    A("<h3>Por que “carros entregues” é o número que manda</h3>")
    A("<p>É o número grande da tarja, e é ele porque é o mais difícil de enganar. "
      "Tempo médio de viagem só conta <i>quem chegou</i> — quem trava a rede inteira "
      "fica com a média dos poucos sobreviventes e parece ótimo. <b>Carros entregues "
      "desaba quando a malha trava</b>, então não dá para fingir.</p>")

    # ------------------------------------------------------------ 2. abrir
    A("<h2>2. Abrir a feira</h2>")
    A("<p>Um comando, no notebook, com o projetor já ligado e apontado:</p>")
    A("<pre><code>.\\run_feira.ps1</code></pre>")
    A("<p>Ele imprime um endereço. Abra <b>na tela do projetor</b> e aperte "
      "<kbd>F</kbd> para tela cheia. Pronto — a tela padrão já está rodando.</p>")
    A('<div class="nota"><b>Alinhe a imagem com a maquete.</b> Com as setas '
      '<kbd>↑</kbd><kbd>↓</kbd><kbd>←</kbd><kbd>→</kbd> você desloca, com '
      '<kbd>+</kbd> <kbd>−</kbd> dá zoom, e <kbd>R</kbd> / <kbd>M</kbd> giram e '
      'espelham (para projetor de cabeça para baixo). O ajuste fica salvo: fechar e '
      'reabrir a janela não perde o alinhamento.</div>')
    A('<div class="aviso"><b>Duas regras para o dia inteiro.</b> '
      '(1) O notebook é só da projeção — não use para outra coisa, porque a janela '
      'precisa do foco para o teclado chegar. '
      '(2) <b>Não minimize</b> a janela: o navegador congela a animação em aba '
      'escondida.</div>')

    # ------------------------------------------------------------ 3. as telas
    A("<h2>3. O fluxo, tela por tela</h2>")
    A("<p>São cinco telas e elas se sucedem sozinhas. Você não precisa apertar nada "
      "entre uma rodada e a seguinte.</p>")

    A(passo("1", "Tela padrão — a corrida rodando sozinha",
            "<p>É o que fica no ar quando ninguém está jogando. A rede neural e o "
            "semáforo comum correm <b>ao mesmo tempo</b>, na mesma hora de trânsito. "
            "Embaixo do mapa, a vantagem medida; no canto, o quadro de recordes; e a "
            "instrução de como começar.</p>"))
    A(fig(TELAS / "ocioso.png", "A tela padrão",
          " — o mapa em cima, os números e o convite embaixo. Texto nunca fica sobre a "
          "simulação: os quarteirões ficam livres para os prédios."))

    A(passo("2", "O visitante digita o apelido",
            "<p>Ele digita direto no teclado, olhando para o chão. <kbd>ENTER</kbd> "
            "confirma. Quem não quiser dar nome aperta <kbd>ESPAÇO</kbd> direto e "
            "entra como <i>Visitante N</i>.</p>"))
    A(fig(VIVO / "03_ocioso_nome_digitado.jpg", "Digitando o apelido",
          " — a linha abaixo mostra a sequência inteira, para quem chegou no meio da "
          "fila não ficar perdido."))
    A('<div class="nota">Se a pessoa desistir depois de confirmar, <kbd>Esc</kbd> '
      'cancela e devolve a vez. E se ela simplesmente for embora, o apelido expira '
      'sozinho em 90 s — o próximo da fila nunca joga com o nome do anterior.</div>')

    A(passo("3", "Contagem regressiva",
            "<p>Três segundos para a pessoa pôr a mão no teclado. Quem martelar o "
            "botão aqui não ganha nada: o jogo descarta o que for apertado durante a "
            "contagem.</p>"))
    A(fig(TELAS / "contagem.png", "3 · 2 · 1"))

    A(passo("4", "A rodada — 120 segundos",
            "<p>Agora os três correm juntos: o <b>timer fixo</b>, a <b>rede neural</b> "
            "e <b>você</b>. As barras crescem ao vivo e o relógio desce. Cada "
            "cruzamento ganha uma placa com a letra da tecla dele.</p>"))
    A(fig(TELAS / "jogando.png", "Durante a rodada",
          " — a tarja mostra os três braços e a diferença contra o timer, ao vivo."))

    A(passo("5", "Resultado, sete segundos",
            "<p>As três métricas do projeto, os três braços, quem venceu, e a "
            "colocação da pessoa no quadro — com medalha, se ela merecer. Depois disso "
            "a tela volta sozinha para a tela padrão.</p>"))
    A(fig(TELAS / "resultado.png", "A tela de resultado",
          " — <b>carros entregues</b> é a manchete; tempo de viagem e carros parados "
          "são o contexto."))

    # ------------------------------------------------------------ 4. as regras
    A("<h2>4. As regras do jogo (e como explicá-las)</h2>")
    A("<p>O visitante controla <b>12 semáforos</b> por 120 segundos simulados. As "
      "teclas estão na mesma posição do mapa:</p>")
    A("<pre><code>Q  W  E  R        ← fileira de cima" + BR
      + "A  S  D  F        ← fileira do meio" + BR
      + "Z  X  C  V        ← fileira de baixo</code></pre>")

    A("<h3>Não dá para abrir tudo o tempo todo</h3>")
    A("<p>Duas regras limitam o jogador — e são as <b>mesmas</b> que limitam a rede "
      "neural, senão a comparação não valeria:</p>")
    A('<div class="rolagem"><table>'
      "<tr><th>regra</th><th>quanto</th><th>o que significa na prática</th></tr>"
      "<tr><td><b>verde mínimo</b></td><td>7 s simulados</td>"
      "<td>um semáforo que acabou de abrir não fecha de novo na hora. Apertar antes "
      "disso é recusado.</td></tr>"
      "<tr><td><b>amarelo</b></td><td>3 s simulados</td>"
      "<td>toda troca passa pelo amarelo. Ele custa tempo — trocar demais também "
      "atrapalha.</td></tr>"
      "<tr><td><b>ciclo de decisão</b></td><td>5 s simulados</td>"
      "<td>o pedido não vale na hora: ele entra no próximo ciclo.</td></tr>"
      "</table></div>")

    A("<h3>A placa de cada cruzamento diz tudo</h3>")
    A("<p>Ela fala a mesma língua do farol embaixo dela. Se o visitante perguntar "
      "“por que não abriu?”, a resposta está na placa:</p>")
    A('<div class="rolagem"><table>'
      "<tr><th>placa</th><th>estado</th><th>o que dizer</th></tr>"
      '<tr><td><i class="placa" style="background:#e8eef4"></i><b>clara</b></td>'
      "<td>livre</td><td>“pode apertar”</td></tr>"
      '<tr><td><i class="placa" style="background:#ffd23d"></i><b>amarela</b></td>'
      "<td>pedido registrado</td><td>“anotou — vale no próximo ciclo”</td></tr>"
      '<tr><td><i class="placa" style="background:#2bea88"></i><b>verde</b></td>'
      "<td>trocou</td><td>“abriu agora”</td></tr>"
      '<tr><td><i class="placa" style="background:#ff5245"></i><b>vermelha “CEDO”</b></td>'
      "<td>recusado</td><td>“cedo demais, o verde mínimo não fechou”</td></tr>"
      '<tr><td><i class="placa" style="background:#39434d"></i><b>apagada com anel</b></td>'
      "<td>bloqueado</td><td>“espere o anel esvaziar — ele mostra os segundos”</td>"
      "</tr></table></div>")
    A(fig(VIVO / "07_jogando_cooldown.jpg", "A placa bloqueada, com o anel e os segundos",
          " — repare no <b>Q</b> apagado com “2s” embaixo: acabou de trocar e ainda não "
          "aceita pedido. As outras continuam claras."))

    A("<h3>O conselho que muda o resultado</h3>")
    A('<div class="fala"><b>Incentive a pessoa a apertar.</b> Quem aperta pouco '
      'trava a malha e vê a rodada ser anulada. Nas dez rodadas que medimos, todas as '
      'válidas vieram de quem trocava bastante; as anuladas tiveram de 0 a 11 trocas '
      'em 24 ciclos. Diga: <b>“não tenha medo de errar — mexa nos semáforos”</b>.</div>')

    A(passo("6", "E quando a rodada é anulada",
            "<p>Se a malha travar no braço do visitante e não no de referência, o jogo "
            "<b>não publica vencedor</b> e a rodada não entra no quadro. Não é bug: é "
            "o sistema se recusando a comparar uma corrida em que o trânsito parou. "
            "Explique assim: <i>“travou de vez — nem dá para comparar. Quer tentar de "
            "novo?”</i></p>"))

    # ------------------------------------------------------------ 5. quadro
    A("<h2>5. O quadro de recordes</h2>")
    A("<p>Entra no quadro quem <b>jogou uma rodada válida</b>. A ordem é pelo "
      "<b>score</b>, que é a diferença de carros entre a pessoa e o <b>timer da mesma "
      "hora de trânsito</b> — não pelo número cru. Isso é de propósito: umas seeds são "
      "mais fáceis que outras, e comparar número cru premiaria quem pegou trânsito "
      "leve.</p>")
    A('<div class="rolagem"><table>'
      "<tr><th>medalha</th><th>quando</th></tr>"
      "<tr><td><b>ouro</b></td><td>bateu a rede neural</td></tr>"
      "<tr><td><b>prata</b></td><td>chegou perto da rede neural</td></tr>"
      "<tr><td><b>bronze</b></td><td>bateu o timer fixo</td></tr>"
      "</table></div>")
    A('<div class="nota"><b>O quadro expira em 30 minutos</b> — de propósito, para o '
      'campeão mudar ao longo do dia. Uma marca antiga sai do quadro mas continua no '
      'arquivo do dia. Se o quadro aparecer vazio numa hora parada, não é defeito.</div>')
    A(fig(VIVO / "09_volta_ao_ocioso.jpg", "De volta à tela padrão, com o quadro atualizado",
          " — a simulação voltou e o campo já está aberto para o próximo."))

    # ------------------------------------------------------------ 6. perguntas
    A("<h2>6. O que responder</h2>")
    A('<div class="faq"><p>“A inteligência artificial sempre ganha?”</p>'
      "<p>Do semáforo comum, praticamente sempre — e é esse o resultado do projeto. "
      "De uma pessoa, quase sempre, mas <b>não é impossível</b>: já teve visitante "
      "batendo a rede. É por isso que o quadro existe.</p></div>")
    A('<div class="faq"><p>“Isso é um vídeo? É de verdade?”</p>'
      "<p>É simulação de trânsito de verdade, rodando agora — o mesmo motor que "
      "urbanistas usam (SUMO). Cada carrinho tem posição, velocidade e destino. "
      "Nada é gravado.</p></div>")
    A('<div class="faq"><p>“Por que o percentual muda tanto?”</p>'
      "<p>Porque é um contador que acumula. A vantagem é ganha nos primeiros "
      "segundos de cada volta; depois os dois entregam em ritmo parecido e a "
      "porcentagem se dilui. <b>O número que não dilui é a fila</b>: a rede neural "
      "segura cerca de um quarto menos de carros parados, a volta inteira.</p></div>")
    A('<div class="faq"><p>“Por que minha rodada não entrou no quadro?”</p>'
      "<p>Porque o trânsito travou no seu braço. O sistema se recusa a declarar "
      "vencedor de uma corrida em que a malha parou.</p></div>")
    A('<div class="faq"><p>“Vocês treinaram aqui nessa maquete?”</p>'
      "<p>A pesquisa começou numa rede grande, de verdade, e a maquete é a versão que "
      "cabe na mesa — em escala, com a física reduzida junto. Os semáforos, a demanda "
      "e as regras são os mesmos.</p></div>")

    # ------------------------------------------------------------ 7. problemas
    A("<h2>7. Quando algo dá errado</h2>")
    A('<div class="rolagem"><table>'
      "<tr><th>na tela</th><th>o que é</th><th>o que fazer</th></tr>"
      "<tr><td><b>CLIQUE NA TELA DO NOTEBOOK</b></td>"
      "<td>o navegador perdeu o foco e o teclado não chega</td>"
      "<td>clique na janela projetada</td></tr>"
      "<tr><td><b>MODO DEGRADADO</b></td><td>o jogo parou de publicar</td>"
      "<td>a tela volta sozinha; se ficar, reinicie o comando</td></tr>"
      "<tr><td><b>JANELAS DIFERENTES</b></td>"
      "<td>a projeção se recusa a comparar coisas diferentes</td>"
      "<td>no uso normal não deve aparecer — reinicie e avise a equipe</td></tr>"
      "<tr><td>tela preta, “conectando”</td><td>a simulação não subiu</td>"
      "<td>olhe o terminal; provavelmente o SUMO não abriu</td></tr>"
      "<tr><td>teclas do visitante não respondem</td><td>faltou o preset</td>"
      "<td>suba com <code>.\\run_feira.ps1</code>, não com o script direto</td></tr>"
      "</table></div>")
    A('<div class="nota"><b>A fila está grande?</b> Na página do operador '
      '(<code>/operador.html</code>, na tela do notebook) dá para <b>pular o '
      'resultado</b> e <b>abortar</b> uma rodada. Também dá para digitar o apelido '
      'por lá, quando a pessoa não quiser ou não conseguir digitar.</div>')

    # ------------------------------------------------------------ 8. teclas
    A("<h2>8. Teclas, de relance</h2>")
    A('<div class="rolagem"><table>'
      "<tr><th>quem</th><th>tecla</th><th>faz</th></tr>"
      "<tr><td>visitante</td><td><kbd>letras</kbd></td>"
      "<td>digita o apelido</td></tr>"
      "<tr><td>visitante</td><td><kbd>ENTER</kbd></td><td>confirma o apelido</td></tr>"
      "<tr><td>visitante</td><td><kbd>ESPAÇO</kbd></td><td>começa a rodada</td></tr>"
      "<tr><td>visitante</td><td><kbd>Esc</kbd></td><td>cancela / devolve a vez</td></tr>"
      "<tr><td>visitante</td>"
      "<td><kbd>Q</kbd><kbd>W</kbd><kbd>E</kbd><kbd>R</kbd> <kbd>A</kbd><kbd>S</kbd>"
      "<kbd>D</kbd><kbd>F</kbd> <kbd>Z</kbd><kbd>X</kbd><kbd>C</kbd><kbd>V</kbd></td>"
      "<td>os 12 semáforos</td></tr>"
      "<tr><td>operador</td><td><kbd>F</kbd></td><td>tela cheia</td></tr>"
      "<tr><td>operador</td><td><kbd>I</kbd></td>"
      "<td>régua de bancada (escala, seed, sha)</td></tr>"
      "<tr><td>operador</td><td><kbd>↑</kbd><kbd>↓</kbd><kbd>←</kbd><kbd>→</kbd> "
      "<kbd>+</kbd> <kbd>−</kbd></td><td>alinhar e dar zoom na imagem</td></tr>"
      "<tr><td>operador</td><td><kbd>R</kbd> <kbd>M</kbd></td>"
      "<td>girar · espelhar</td></tr>"
      "<tr><td>operador</td><td><kbd>Esc</kbd> ×3 em 1,5 s</td>"
      "<td>aborta a rodada em curso</td></tr>"
      "</table></div>")
    A('<div class="aviso"><b>Um <kbd>Esc</kbd> sozinho nunca aborta.</b> São '
      'necessários três seguidos, de propósito: Esc é a tecla que todo mundo aperta '
      'por reflexo.</div>')

    A('<div class="rodape">Gerado por <code>scripts/guia_feira.py</code>. '
      'As imagens são as telas reais do sistema, embutidas no arquivo — ele abre sem '
      'servidor e sem rede. Detalhes técnicos e a validação ponta a ponta estão em '
      '<code>docs/validation/relatorio.html</code>; a operação e os parâmetros, no '
      '<code>README.md</code>.</div>')
    A("</div>")

    corpo = "\n".join(P)
    corpo = corpo.replace("<table>", '<table>')  # as tabelas ja vem em .rolagem

    VAL.parent.mkdir(parents=True, exist_ok=True)
    conteudo = corpo[len(ESTILO):]

    disco = RAIZ / "docs" / "GUIA_DA_FEIRA.html"
    disco.write_text(
        '<!doctype html>\n<html lang="pt-br">\n<head>\n<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        "<title>SmartTraffic na feira — guia de quem apresenta</title>\n"
        + ESTILO + "\n</head>\n<body>\n" + conteudo + "\n</body>\n</html>\n",
        encoding="utf-8")

    art = RAIZ / "docs" / "GUIA_DA_FEIRA.artifact.html"
    art.write_text(
        "<title>SmartTraffic na feira</title>\n"
        '<link rel="preconnect" href="https://fonts.googleapis.com"/>\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        "family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600;700"
        '&display=swap"/>\n' + corpo + "\n", encoding="utf-8")

    for p in (disco, art):
        print("%s  (%.1f MB)" % (p, p.stat().st_size / 1048576))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
