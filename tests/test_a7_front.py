"""A7 — o front, testado onde ele roda: no motor de JS.

Duas propriedades do front são exatamente as duas armadilhas nomeadas do agente, e
nenhuma delas se prova lendo o código:

  (a) A ESCALA DA BARRA NÃO PODE SE ANCORAR NA RL. Quando este teste foi escrito a
      política PERDIA para o timer na rede aberta (93 e 82 contra 111 e 109); depois
      do retreino do A6 ela GANHA (120 e 126 contra 111 e 109). Os dois regimes já
      aconteceram neste mesmo front, o que é a prova de que a tela tem que continuar
      correta com a RL em primeiro, em último ou empatada. Escala chumbada em valor
      absoluto também quebra quando o regime mudar de novo.

  (b) O SPRITE NÃO PODE EXAGERAR ALÉM DA PEGADA. A regra herdada do maquete
      (`D = max(7, laneW·s·1,15)`, `L = D·2,9`) produz, NESTA rede, um sprite duas
      vezes mais comprido que o espaço que o SUMO reserva — e a condição que manda
      desenhar a pegada (`footPx > L·1,15`) nunca dispara. O teste mede os dois e
      compara.

O harness roda no Node (v20+, ESM), importando os arquivos do repo direto. Sem Node,
pula: é ferramenta de bancada, não requisito da suíte.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "web" / "js"
NODE = shutil.which("node")
sem_node = pytest.mark.skipif(NODE is None, reason="requer Node (ferramenta de bancada)")
TEM_SUMO = bool(os.environ.get("SUMO_HOME"))

# O cenário `aberta.maquete`, nos números que estão no disco: bbox do `<location>` do
# `.net.xml`, largura de faixa e o vType em similitude K=6 do `.add.xml`. Ter isto
# explícito é de propósito — o teste `test_a_rede_sintetica_bate_com_a_de_verdade`
# confere contra a geometria real quando o SUMO existe.
REDE = {
    "cenario": "aberta.maquete",
    "bbox": {"xmin": 0.0, "ymin": 0.0, "xmax": 153.33, "ymax": 90.0},
    "defaultLaneWidth": 0.53,
    "vehicle": {"length": 0.583, "width": 0.233, "minGap": 0.292},
    "vFree": 1.852,
    "lanes": [{"id": "l1", "edge": "e1", "street": "a|b", "index": 0, "width": 0.53,
               "type": "sec", "shape": [[0.0, 0.0], [153.33, 90.0]]}],
    "junctions": [{"id": "j1", "type": "traffic_light", "center": [76.0, 45.0],
                   "shape": [[75.0, 44.0], [77.0, 44.0], [77.0, 46.0], [75.0, 46.0]]}],
    "tls": [{"id": "j1", "index": 0, "links": []}],
}


def _node(script: str, tmp_path: Path) -> dict:
    arq = tmp_path / "harness.mjs"
    arq.write_text(script, encoding="utf-8")
    env = dict(os.environ)
    saida = subprocess.run([NODE, str(arq)], capture_output=True, text=True,
                           encoding="utf-8", env=env, timeout=90)
    if saida.returncode != 0:
        pytest.fail("node falhou:\n%s\n%s" % (saida.stdout, saida.stderr))
    return json.loads(saida.stdout.strip().splitlines()[-1])


def _url(nome: str) -> str:
    return (WEB / nome).resolve().as_uri()


# ============================================================ (a) a escala
@sem_node
def test_a_escala_da_barra_nao_se_ancora_num_braco(tmp_path):
    script = """
import { escalaPara, colocacoes, PASSO } from %s;
const cenas = {
  rl_ultimo:  [{braco:'timer',entregues:111},{braco:'rl',entregues:82},{braco:'humano',entregues:95}],
  rl_lider:   [{braco:'timer',entregues:82},{braco:'rl',entregues:140},{braco:'humano',entregues:95}],
  humano_lider:[{braco:'timer',entregues:82},{braco:'rl',entregues:95},{braco:'humano',entregues:160}],
  empate:     [{braco:'timer',entregues:100},{braco:'rl',entregues:100},{braco:'humano',entregues:100}],
  zerado:     [{braco:'timer',entregues:0},{braco:'rl',entregues:0},{braco:'humano',entregues:0}],
  regime_novo:[{braco:'timer',entregues:1110},{braco:'rl',entregues:820},{braco:'humano',entregues:950}],
};
const out = {};
for (const k in cenas) {
  out[k] = { escala: escalaPara(cenas[k]), pos: colocacoes(cenas[k]),
             maior: Math.max(...cenas[k].map(l => l.entregues)) };
}
// monotonicidade dentro da rodada: entregues só cresce, a escala nunca encolhe
let esc = PASSO; const trilha = [];
for (const n of [3, 20, 55, 91, 91, 120]) {
  esc = escalaPara([{braco:'humano',entregues:n}], esc);
  trilha.push(esc);
}
out.trilha = trilha;
// e uma rodada nova começa do zero
out.reinicio = escalaPara([{braco:'humano',entregues:5}], PASSO);
console.log(JSON.stringify(out));
""" % json.dumps(_url("placar.js"))
    r = _node(script, tmp_path)

    for cena in ("rl_ultimo", "rl_lider", "humano_lider", "regime_novo"):
        d = r[cena]
        # a escala acompanha QUEM LIDERA, seja ele quem for
        assert d["maior"] < d["escala"], cena
        assert d["escala"] <= d["maior"] * 1.35, cena
    # a escala do regime novo é ~10x a do velho: nada de absoluto chumbado
    assert r["regime_novo"]["escala"] >= 9 * r["rl_ultimo"]["escala"]
    # empate não inventa desempate
    assert set(r["empate"]["pos"].values()) == {1}
    # RL em último é 3º, e o placar continua desenhável
    assert r["rl_ultimo"]["pos"]["rl"] == 3
    assert r["rl_lider"]["pos"]["rl"] == 1
    # placar zerado não divide por zero nem some
    assert r["zerado"]["escala"] > 0
    # nunca encolhe dentro da rodada
    assert r["trilha"] == sorted(r["trilha"])
    # e a rodada seguinte recomeça pequena
    assert r["reinicio"] < r["trilha"][-1]


# ============================================================ (b) o sprite
_SPRITE = """
import { Board } from %s;
const rede = %s;
const layouts = %s;
const out = [];
for (const [w, h, rodape] of layouts) {
  const b = new Board(JSON.parse(JSON.stringify(rede)));
  b.layout({ x: 0, y: 56, w, h: Math.max(120, h - 56 - rodape) });
  const s = b.sprite;
  // A REGRA HERDADA DO MAQUETE, para comparação: D = max(7, laneW*s*1.15), L = D*2.9
  const Dm = Math.max(7, b.laneW * s.s * 1.15);
  const Lm = Dm * 2.9;
  out.push({
    palco: [w, h], escala_px_por_m: s.s, mult: s.mult,
    corpo: s.corpo, largura: s.largura, pegada: s.footPx,
    real: [s.realC, s.realL], exageroC: s.exageroC, exageroL: s.exageroL,
    spriteExcede: b.spriteExcede, excede: s.excede,
    maquete_L: Lm, maquete_D: Dm,
    maquete_excesso: Lm / s.footPx,
    maquete_desenha_pegada: s.footPx > Lm * 1.15,
    razao_carro_faixa_desenhada: s.largura / (b.laneW * s.s * s.mult),
    razao_real: b.vehW / b.laneW,
  });
}
console.log(JSON.stringify(out));
"""


@sem_node
def test_carro_parado_nunca_monta_em_carro_parado(tmp_path):
    """A propriedade que manda no sprite, e a única que a plateia consegue verificar
    olhando: **o desenho nunca passa do espaço que o modelo reserva**.

    ESTE TESTE JÁ COBROU OS DOIS EXTREMOS, e o histórico é o argumento. Primeiro o
    corpo era a pegada CHEIA (`corpo = min(comprimento·mult, pegada)`): honesto, e um
    carro de 6,3 × 4,6 px que ninguém enxerga. Depois foi adotada a regra da projeção
    do maquete (`D = max(7 px, laneW·s·1,15)`, `L = D·2,9`): 20,3 × 7,0 px, legível — e
    **2,5 sprites por vaga**, ou seja, em qualquer fila os carros parados montavam uns
    nos outros. Um mapa que existe para mostrar trânsito não pode desenhar o trânsito
    errado para o carro ficar bonito.

    A regra que ficou resolve o conflito onde ele de fato estava, que não era o carro:

        corpo   = min(comprimento·mult, pegada · 0,88)   -> nunca monta, e sobra costura
        largura = min(largura·mult,     corpo  · 0,66)   -> silhueta ~1,5:1
        faixa desenhada = 11,5 px (antes 15)             -> ver `_multPara`

    Baixar o exagero da VIA é o que faz o carro caber como carro: a razão
    carro/faixa desenhada volta para ~0,40, contra os 0,42 reais. O carro não cresceu;
    a rua parou de ser grande demais para ele.
    """
    layouts = [[1920, 1080, 226], [1600, 900, 190], [1280, 720, 151],
               [3840, 2160, 452], [1904, 985, 206]]
    r = _node(_SPRITE % (json.dumps(_url("paint.js")), json.dumps(REDE),
                         json.dumps(layouts)), tmp_path)
    for d in r:
        # 1. A PROPRIEDADE CENTRAL: carro parado não monta em carro parado. Em
        #    resolução nenhuma, e com folga de costura — a 0,88 da vaga sobra ~1 px de
        #    preto entre um carro e o próximo, que é o que faz a fila PARECER fila.
        assert d["corpo"] <= d["pegada"] + 1e-6, d
        assert d["excede"] <= 0.89, d
        # 2. o único piso é anti-sumiço (3 px), e ele é quem liga a denúncia
        if d["excede"] > 0.881:
            assert d["corpo"] == pytest.approx(3.0), d
            assert d["spriteExcede"] is True, d
        else:
            assert d["spriteExcede"] is False, d
        # 3. O CARRO NUNCA É MAIS LARGO QUE UM CARRO. A razão real é
        #    `vehW/laneW` (0,42 nesta rede), e a desenhada não passa disso em
        #    resolução nenhuma — se passasse, o veículo estaria invadindo a faixa
        #    vizinha no desenho sem invadir na simulação.
        assert d["razao_carro_faixa_desenhada"] <= d["razao_real"] + 1e-9, d
        # 4. silhueta de carro, não de dado: o comprimento manda na largura
        assert 1.3 <= d["corpo"] / d["largura"] <= 2.6, d

    # E na resolução DA FEIRA a razão tem de ser EXATAMENTE a real — não "abaixo dela",
    # não "perto dela". É o caso em que nenhum dos dois tetos morde: o carro é exagerado
    # pelo mesmo `mult` com que a via já é, e ocupa na faixa desenhada a mesma fração
    # que ocupa na faixa de verdade. Foi para chegar aqui que o enquadramento cortou as
    # pontas (§3.4) e o exagero da via caiu de 15 px para 11,5 (§3.3); se esta linha
    # começar a falhar, um dos dois regrediu.
    #
    # Abaixo de 1080p o piso em PIXELS da faixa passa a mandar (a via não pode virar um
    # fio de cabelo), a via fica proporcionalmente mais larga e a razão cai — é
    # conhecido, está coberto pelo teto do laço acima, e é o preço de projetar numa
    # resolução menor.
    feira = r[0]
    assert feira["palco"] == [1920, 1080]
    assert feira["razao_carro_faixa_desenhada"] == pytest.approx(feira["razao_real"],
                                                                 rel=1e-6), feira


@sem_node
def test_a_regra_do_maquete_estouraria_a_pegada_nesta_rede(tmp_path):
    """O contraponto do teste acima: a regra herdada NÃO serve aqui, e o número diz por
    quanto. NÃO é defeito do maquete — lá a rede é outra e a regra deles produz um
    sprite MAIS CURTO que a pegada, que é o caso que o rastro foi feito para consertar.
    Aqui a desigualdade inverte, e aplicá-la produz 2,5 carros desenhados por vaga."""
    r = _node(_SPRITE % (json.dumps(_url("paint.js")), json.dumps(REDE),
                         json.dumps([[1920, 1080, 300]])), tmp_path)
    d = r[0]
    assert d["maquete_excesso"] > 1.8, (
        "a regra herdada não estoura mais a pegada — refazer a conta do docs/PROJECAO.md")
    assert d["maquete_desenha_pegada"] is False, (
        "com o sprite herdado a condição `footPx > L*1.15` nunca dispara: a pegada "
        "verdadeira simplesmente não seria desenhada")


@sem_node
def test_o_diagnostico_publica_os_numeros_que_o_documento_cobra(tmp_path):
    """O fator de exagero tem que ser MEDIDO na tela, não declarado no documento."""
    r = _node(_SPRITE % (json.dumps(_url("paint.js")), json.dumps(REDE),
                         json.dumps([[1920, 1080, 300]])), tmp_path)
    d = r[0]
    for chave in ("escala_px_por_m", "mult", "corpo", "largura", "pegada",
                  "exageroC", "exageroL"):
        assert isinstance(d[chave], (int, float)) and d[chave] > 0, chave


# ====================================== (c) o veredito: `vencedor: null` NÃO é um estado
# O C7 ganhou `pareado` e `motivo` porque `vencedor: null` juntava coisas opostas:
# empate (resultado legítimo) e rodada NÃO PAREADA (os braços partiram de estados
# diferentes em t0 — a comparação não vale). A tela mostrava as duas idênticas.
_VEREDITO = """
import { veredito, colocacoes } from %s;
const L = (b, e) => ({ braco: b, entregues: e });
const tres = [L('timer', 111), L('rl', 93), L('humano', 104)];
const casos = {
  nao_pareada: { fase: 'resultado', pareado: false, vencedor: null,
                 motivo: 'selo de t0 divergente (humano=8f3a fantasmas={rl: b71d})',
                 linhas: tres },
  vencedor:    { fase: 'resultado', pareado: true, vencedor: 'timer', motivo: '',
                 linhas: tres },
  empate:      { fase: 'resultado', pareado: true, vencedor: null, motivo: '',
                 linhas: [L('timer', 104), L('rl', 93), L('humano', 104)] },
  abortada:    { fase: 'resultado', pareado: true, vencedor: null,
                 motivo: 'abortada pelo operador',
                 linhas: [L('timer', 111), L('rl', 93)] },
  degradado:   { fase: 'resultado', pareado: true, vencedor: 'humano',
                 motivo: 'modo degradado: sem fantasma de rl',
                 linhas: [L('timer', 111), L('humano', 120)] },
  jogando:     { fase: 'jogando', pareado: true, vencedor: null, motivo: '',
                 linhas: tres },
  antigo:      { fase: 'resultado', vencedor: 'rl',
                 linhas: [L('rl', 120), L('humano', 100)] },
};
const out = {};
for (const k in casos) {
  const v = veredito(casos[k]);
  out[k] = { ...v, colocacoes: v.compara ? colocacoes(casos[k].linhas) : {} };
}
console.log(JSON.stringify(out));
"""


@sem_node
def test_vencedor_nulo_se_separa_em_quatro_desfechos(tmp_path):
    r = _node(_VEREDITO % json.dumps(_url("placar.js")), tmp_path)

    # 1. NÃO PAREADA: sem coroa E sem colocação. Se a comparação não vale, segundo
    #    lugar também não existe — é o ponto inteiro do campo `pareado`.
    d = r["nao_pareada"]
    assert d["estado"] == "nao_pareada"
    assert d["coroa"] is None
    assert d["compara"] is False
    assert d["colocacoes"] == {}, "rodada não pareada não pode ter classificação"
    assert "selo de t0 divergente" in d["motivo"]

    # 2. EMPATE é resultado legítimo e tem que ler como empate, não como "sem placar".
    #    Empate no TOPO: timer e humano dividem o 1º, a RL fica em 3º (não em 2º —
    #    inventar o 2º seria fabricar uma ordem que os números não têm).
    assert r["empate"]["estado"] == "empate"
    assert r["empate"]["coroa"] is None
    assert r["empate"]["colocacoes"] == {"timer": 1, "humano": 1, "rl": 3}

    # 3. Rodada que não terminou (abortada / SUMO caiu): NÃO é empate. Ninguém empatou
    #    — o humano nem aparece nas linhas.
    assert r["abortada"]["estado"] == "sem_placar"
    assert r["abortada"]["motivo"] == "abortada pelo operador"

    # 4. Vencedor com motivo (modo degradado: faltou um fantasma) continua coroando.
    #    `motivo` não vazio não quer dizer "rodada inválida".
    assert r["degradado"]["estado"] == "vencedor"
    assert r["degradado"]["coroa"] == "humano"

    assert r["vencedor"]["estado"] == "vencedor" and r["vencedor"]["coroa"] == "timer"
    assert r["jogando"]["estado"] == "em_curso"
    # mensagem antiga, de antes do campo existir: assume pareada (o campo só some
    # para trás, nunca para frente)
    assert r["antigo"]["estado"] == "vencedor" and r["antigo"]["compara"] is True


@sem_node
def test_a_barra_perde_regua_e_colocacao_quando_nao_pareada(tmp_path):
    """A régua ("você está à direita do timer") e o selo de colocação são AFIRMAÇÕES
    DE COMPARAÇÃO. Numa rodada não pareada as duas mentem, e `atualiza()` as desliga.
    Aqui a prova é sobre a decisão pura; a prova sobre o DOM está no teste do Chrome."""
    script = """
import { veredito } from %s;
const m = { fase: 'resultado', pareado: false, vencedor: 'humano',
            motivo: 'selo de t0 divergente',
            linhas: [{braco:'timer',entregues:111},{braco:'humano',entregues:200}] };
const v = veredito(m);
// mesmo com `vencedor` preenchido no fio, a tela não pode coroar: `pareado` manda.
console.log(JSON.stringify({ coroa: v.coroa, compara: v.compara, estado: v.estado }));
""" % json.dumps(_url("placar.js"))
    r = _node(script, tmp_path)
    assert r["coroa"] is None, "coroou numa rodada não pareada"
    assert r["compara"] is False
    assert r["estado"] == "nao_pareada"


# ------------------------------------------ a prova no DOM de verdade (Chrome)
def _chrome():
    import shutil as _sh

    for c in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if Path(c).exists():
            return c
    return _sh.which("chrome") or _sh.which("msedge")


def _dom(fase: str, porta: int, extra: str = "") -> str:
    """Renderiza `?demo=<fase>` no Chrome headless e devolve o DOM depois do JS."""
    import os as _os
    import shutil as _sh
    import subprocess as _sp

    sys.path.insert(0, str(RAIZ))
    from feira.contratos import cenario as resolve
    from feira.jogo.web import EstadoProjecao, ServidorProjecao, geometria

    cen = resolve("aberta.maquete")
    est = EstadoProjecao(cenario=cen)
    est._rede = geometria(cen)
    srv = ServidorProjecao(est, porta=porta)
    assert srv.sobe()
    perfil = Path(_os.environ.get("TEMP", ".")) / ("st-dom-%d" % porta)
    try:
        r = _sp.run([_chrome(), "--user-data-dir=%s" % perfil, "--no-first-run",
                     "--no-default-browser-check", "--headless=new", "--disable-gpu",
                     "--window-size=1920,1080", "--dump-dom",
                     "--virtual-time-budget=6000",
                     "http://127.0.0.1:%d/?demo=%s&carros=20&quadros=8%s"
                     % (porta, fase, extra)],
                    capture_output=True, text=True, encoding="utf-8", timeout=180)
    finally:
        srv.desce()
        _sh.rmtree(perfil, ignore_errors=True)
    return r.stdout or ""


@pytest.mark.sumo
@pytest.mark.aberta
@pytest.mark.skipif(not TEM_SUMO or _chrome() is None,
                    reason="requer SUMO_HOME + Chrome (prova de bancada)")
def test_dom_da_rodada_nao_pareada_nao_coroa_ninguem_e_mostra_o_motivo():
    """A prova que o coordenador pediu, no DOM de verdade: `pareado: false` ->
    a tela não coroa ninguém, não classifica, e o motivo do motor aparece."""
    dom = _dom("nao_pareada", 8611)
    if not dom.strip():
        pytest.skip("o Chrome não devolveu DOM")

    assert 'data-alerta="pareamento"' in dom, "a denúncia de pareamento não subiu"
    assert "SEM VENCEDOR E SEM COLOCAÇÃO" in dom
    assert "selo de t0 divergente" in dom, "o motivo do motor não apareceu na tela"
    # ninguém coroado, em lugar nenhum: nem no texto, nem na classe da barra, nem no
    # `data-quem` do veredito
    assert "VENCEU" not in dom, "coroou alguém numa rodada não pareada"
    assert not re.search(r'class="pl-linha[^"]*venceu', dom), "marcou uma barra vencedora"
    assert not re.search(r'id="veredito"[^>]*data-quem="[a-z]', dom), "coroou no veredito"
    # e nenhum selo de colocação NO PLACAR. A busca era por "1º" no documento inteiro,
    # e passou a falhar quando o quadro de recordes entrou na tela — ele numera os
    # recordes, e com razão: aquela é outra disputa, e ela vale. O que não pode existir
    # é colocação nas LINHAS do placar, que é o que `.pl-pos` carrega.
    assert not re.search(r'class="pl-pos">\s*\d', dom), (
        "classificou uma rodada não pareada")
    assert re.search(r'class="pl-pos">\s*—', dom), "as linhas perderam o traço de '—'"


@pytest.mark.sumo
@pytest.mark.aberta
@pytest.mark.skipif(not TEM_SUMO or _chrome() is None,
                    reason="requer SUMO_HOME + Chrome (prova de bancada)")
def test_dom_do_resultado_normal_continua_coroando():
    """O contraponto: sem ele, o teste acima passaria com a tela quebrada.

    Este teste já chumbou `data-quem="timer"` e quebrou quando a RL passou a ganhar —
    estava medindo o REGIME, não o front. O que ele mede agora é que a coroa SEGUE o
    número: `&perde=1` espelha os dois braços pré-computados e a coroa tem de ir junto.
    """
    for extra, quem in (("", "rl"), ("&perde=1", "timer")):
        dom = _dom("resultado", 8613, extra)
        if not dom.strip():
            pytest.skip("o Chrome não devolveu DOM")
        assert "VENCEU" in dom
        assert re.search(r'class="pl-linha[^"]*venceu', dom), "o vencedor não foi marcado"
        assert re.search(r'id="veredito"[^>]*data-quem="%s"' % quem, dom), (
            "coroou outro braço com %r" % (extra or "o demo padrão"))
        assert "1º" in dom
        assert 'data-alerta="pareamento"' not in dom


@pytest.mark.sumo
@pytest.mark.aberta
@pytest.mark.skipif(not TEM_SUMO or _chrome() is None,
                    reason="requer SUMO_HOME + Chrome (prova de bancada)")
def test_a_regua_de_bancada_nao_perde_nenhum_texto_da_plateia():
    """A régua mede o tamanho ANGULAR de cada texto por SELETOR CSS — e um seletor que
    para de casar some da auditoria calado. Foi o que aconteceu com `.pl-num b` quando
    o placar virou cartão: o MAIOR texto da plateia ficou fora da conta e ninguém viu.
    Agora a régua imprime `NÃO CASA`, e este teste lê a régua de verdade na tela.
    """
    dom = _dom("jogando", 8614, "&diag=1")
    if not dom.strip():
        pytest.skip("o Chrome não devolveu DOM")
    assert "de arco" in dom, "a régua não desenhou"
    assert "NÃO CASA" not in dom, "algum seletor da régua parou de casar"
    # e os textos que o §2 do documento cobra continuam todos na lista
    for rot in ("número do placar", "rótulo do braço", "selo pré-computado",
                "secundária", "cromo do operador"):
        assert ("texto %s:" % rot) in dom, "%r saiu da régua" % rot


# ============================================ (d) o delta contra a régua
# Ele é DERIVADO na tela (o C7 não manda delta nenhum), e é uma afirmação de
# COMPARAÇÃO: tem de sumir onde a colocação some, e não pode existir para o próprio
# timer — "o timer está 0 à frente do timer" é ruído ocupando o lugar de informação.
_DELTA = """
import { deltaContraRegua, deltaPercentual } from %s;
const L = (b, e) => ({ braco: b, entregues: e });
const tres = [L('timer', 111), L('rl', 120), L('humano', 104)];
const zerada = [L('timer', 0), L('rl', 4)];
console.log(JSON.stringify({
  pct_rl: deltaPercentual(tres, 'rl'),
  pct_humano: deltaPercentual(tres, 'humano'),
  pct_timer: deltaPercentual(tres, 'timer'),
  pct_regua_zerada: deltaPercentual(zerada, 'rl'),
  delta_regua_zerada: deltaContraRegua(zerada, 'rl'),
  rl_ganhando: deltaContraRegua(tres, 'rl'),
  humano_perdendo: deltaContraRegua(tres, 'humano'),
  o_proprio_timer: deltaContraRegua(tres, 'timer'),
  empatado: deltaContraRegua([L('timer', 111), L('rl', 111)], 'rl'),
  sem_regua: deltaContraRegua([L('rl', 120), L('humano', 104)], 'rl'),
  braco_ausente: deltaContraRegua(tres, 'ninguem'),
  lista_vazia: deltaContraRegua([], 'rl'),
}));
"""


@sem_node
def test_o_delta_contra_a_regua_e_derivado_e_nunca_aponta_para_si(tmp_path):
    r = _node(_DELTA % json.dumps(_url("placar.js")), tmp_path)
    # A PORCENTAGEM é o que vai grande na tela, e ela existe porque o absoluto sozinho
    # mente por omissão: +11,6 carros da RL sobre o timer em 120 s (a média das 12
    # seeds held-out do A8) é +10,3% de vazão. "Dez carros" soa a ruído; "10%" é o
    # resultado do projeto. Mesmo dado.
    assert abs(r["pct_rl"] - (9 / 111 * 100)) < 0.01
    assert abs(r["pct_humano"] - (-7 / 111 * 100)) < 0.01
    assert r["pct_timer"] is None, "o timer não tem porcentagem contra si mesmo"
    # E a divisão por zero: no primeiro segundo da rodada a régua ainda está em 0.
    assert r["pct_regua_zerada"] is None, "dividiu pela régua zerada"
    assert r["delta_regua_zerada"] == 4, "o ABSOLUTO continua valendo com a régua em 0"
    assert r["rl_ganhando"] == 9, "120 contra 111 tem de dar +9"
    assert r["humano_perdendo"] == -7
    assert r["empatado"] == 0, "empate é 0, não é ausência"
    # Os quatro casos em que o delta NÃO EXISTE. `0` e `null` são coisas diferentes:
    # 0 é "empatou com a régua", null é "não há delta a mostrar".
    assert r["o_proprio_timer"] is None, "o timer não tem delta contra si mesmo"
    assert r["sem_regua"] is None, "sem a linha do timer não há régua"
    assert r["braco_ausente"] is None
    assert r["lista_vazia"] is None


# ------------------------------------------------- a rede sintética é a de verdade
@pytest.mark.sumo
@pytest.mark.aberta
@pytest.mark.skipif(not TEM_SUMO, reason="requer SUMO_HOME")
def test_a_rede_sintetica_bate_com_a_de_verdade():
    """Se o `.net.xml` ou o `.add.xml` mudarem, os números do documento e do teste
    acima param de valer — e é melhor descobrir aqui do que na feira."""
    sys.path.insert(0, str(RAIZ))
    from feira.contratos import cenario as resolve
    from feira.jogo.web import geometria

    cen = resolve("aberta.maquete")
    if not cen.disponivel():
        pytest.skip("a rede aberta não está construída")
    g = geometria(cen)
    assert g["defaultLaneWidth"] == pytest.approx(REDE["defaultLaneWidth"], abs=1e-3)
    for k in ("length", "width", "minGap"):
        assert g["vehicle"][k] == pytest.approx(REDE["vehicle"][k], abs=1e-3), k
    for k in ("xmax", "ymax"):
        assert g["bbox"][k] == pytest.approx(REDE["bbox"][k], abs=0.01), k
    assert g["vFree"] == pytest.approx(REDE["vFree"], abs=0.01)
    # e a geometria de verdade tem o que o pintor precisa
    assert len(g["lanes"]) >= 80 and len(g["tls"]) == 12
    assert all(t["links"] for t in g["tls"])
