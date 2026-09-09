"""A7 — o front, testado onde ele roda: no motor de JS.

Duas propriedades do front são exatamente as duas armadilhas nomeadas do agente, e
nenhuma delas se prova lendo o código:

  (a) A ESCALA DA BARRA NÃO PODE SE ANCORAR NA RL. Hoje a política PERDE para o timer
      na rede aberta (93 e 82 entregues contra 111 e 109), o A6 está retreinando em
      paralelo, e a tela tem que continuar correta com a RL em primeiro, em último ou
      empatada. Escala chumbada em valor absoluto também quebra quando o regime mudar.

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
    excede: b.spriteExcede, razao_excesso: s.excede,
    maquete_L: Lm, maquete_D: Dm,
    maquete_excesso: Lm / s.footPx,
    maquete_desenha_pegada: s.footPx > Lm * 1.15,
    razao_carro_faixa_desenhada: s.largura / (b.laneW * s.s * s.mult),
  });
}
console.log(JSON.stringify(out));
"""


@sem_node
def test_o_sprite_nunca_passa_da_pegada_do_sumo(tmp_path):
    layouts = [[1920, 1080, 300], [1600, 900, 250], [1280, 720, 200],
               [3840, 2160, 600], [1904, 985, 274]]
    r = _node(_SPRITE % (json.dumps(_url("paint.js")), json.dumps(REDE),
                         json.dumps(layouts)), tmp_path)
    for d in r:
        # A propriedade central: o comprimento desenhado É a pegada, nunca mais.
        assert d["corpo"] <= d["pegada"] + 1e-6 or d["excede"], d
        if d["excede"]:
            # só o piso anti-sumiço pode ter mordido, e ele é de 3 px
            assert d["corpo"] == pytest.approx(3.0), d
        # O carro nunca invade lateralmente MAIS do que já invade na realidade: a
        # razão carro/faixa DESENHADA nunca passa da razão real (0,44). Quando o
        # limite de aspecto morde ela fica abaixo; quando não morde, ela É a razão
        # real — que é o caso ideal, porque aí a largura foi exagerada exatamente
        # pelo mesmo fator com que a via já é exagerada.
        assert d["razao_carro_faixa_desenhada"] <= 0.233 / 0.53 + 1e-9, d
        # e o exagero longitudinal é modesto e conhecido
        assert 1.0 <= d["exageroC"] <= 1.6, d


@sem_node
def test_a_regra_do_maquete_estouraria_a_pegada_nesta_rede(tmp_path):
    """O achado que motivou re-resolver o sprite. NÃO é defeito do maquete: lá a rede
    é outra e a regra deles produz um sprite MAIS CURTO que a pegada, que é o caso que
    o rastro da pegada foi feito para consertar. Aqui a desigualdade inverte."""
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


def _dom(fase: str, porta: int) -> str:
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
                     "http://127.0.0.1:%d/?demo=%s&carros=20&quadros=8" % (porta, fase)],
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
    # e nenhum selo de colocação
    assert "1º" not in dom and "2º" not in dom, "classificou uma rodada não pareada"


@pytest.mark.sumo
@pytest.mark.aberta
@pytest.mark.skipif(not TEM_SUMO or _chrome() is None,
                    reason="requer SUMO_HOME + Chrome (prova de bancada)")
def test_dom_do_resultado_normal_continua_coroando():
    """O contraponto: sem ele, o teste acima passaria com a tela quebrada."""
    dom = _dom("resultado", 8613)
    if not dom.strip():
        pytest.skip("o Chrome não devolveu DOM")
    assert "VENCEU" in dom
    assert re.search(r'class="pl-linha[^"]*venceu', dom), "o vencedor não foi marcado"
    assert re.search(r'id="veredito"[^>]*data-quem="timer"', dom)
    assert "1º" in dom
    assert 'data-alerta="pareamento"' not in dom


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
