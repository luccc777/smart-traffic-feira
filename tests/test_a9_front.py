"""A9 — o front da gamificação, testado onde ele roda: no motor de JS.

Três decisões do front são funções PURAS de propósito, para serem provadas sem DOM
(docs/GAMIFICACAO.md §7, DoD (l)):

  (a) o SEXTO DESFECHO: `sinais` não vazio no placar (C7) vira `travou` — sem coroa,
      sem colocação, sem régua, e com precedência abaixo só da rodada não pareada;
  (b) o REDUTOR DO TECLADO (`reduzEntrada`): com o campo de nome aberto NENHUMA tecla
      vira botão nem START; com ele fechado, as 12 letras viram botão, espaço START e
      Escape ABORTAR;
  (c) a LINHA DO QUADRO e a COLOCAÇÃO: score com sinal, medalha, "VOCÊ FICOU EM 7º DE
      31", e a linha antiga (sem `score`) continua desenhando como antes.

Mesmo harness do `test_a7_front.py`: Node (v20+, ESM) importando os arquivos do repo.
Sem Node, pula.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

# O harness (`_node`, `_url`, `sem_node`) é o do test_a7_front.py — importado por
# arquivo, porque `tests/` não é pacote.
_A7 = Path(__file__).resolve().parent / "test_a7_front.py"
_spec = importlib.util.spec_from_file_location("test_a7_front", _A7)
_a7 = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("test_a7_front", _a7)
_spec.loader.exec_module(_a7)
_node, _url, sem_node = _a7._node, _a7._url, _a7.sem_node

# ============================================================ (a) travou
_TRAVOU = """
import { veredito, colocacoes } from %s;
const L = (b, e) => ({ braco: b, entregues: e });
const tres = [L('timer', 111), L('rl', 120), L('humano', 36)];
const sinal = 'acúmulo excedente +51,0 pp sobre timer:uniforme_27s > 20 pp';
const casos = {
  travou:      { fase: 'resultado', pareado: true, vencedor: null, rodada: 7,
                 motivo: 'o trânsito travou: ' + sinal, sinais: [sinal], linhas: tres },
  travou_e_nao_pareada: { fase: 'resultado', pareado: false, vencedor: null,
                 motivo: 'selo de t0 divergente', sinais: [sinal], linhas: tres },
  sao:         { fase: 'resultado', pareado: true, vencedor: 'rl', sinais: [], linhas: tres },
  antigo:      { fase: 'resultado', pareado: true, vencedor: 'rl', linhas: tres },
  em_curso:    { fase: 'jogando', pareado: true, vencedor: null, sinais: [sinal], linhas: tres },
  empate_sao:  { fase: 'resultado', pareado: true, vencedor: null, sinais: [],
                 linhas: [L('timer', 120), L('rl', 120), L('humano', 100)] },
};
const out = {};
for (const k in casos) {
  const v = veredito(casos[k]);
  out[k] = { ...v, colocacoes: v.compara ? colocacoes(casos[k].linhas) : {} };
}
console.log(JSON.stringify(out));
"""


@sem_node
def test_sinais_no_placar_viram_o_sexto_desfecho(tmp_path):
    r = _node(_TRAVOU % json.dumps(_url("placar.js")), tmp_path)
    t = r["travou"]
    assert t["estado"] == "travou"
    assert t["coroa"] is None, "coroou o timer numa rodada travada"
    assert t["compara"] is False and t["colocacoes"] == {}, "classificou uma rodada travada"
    assert t["sinais"] and "acúmulo excedente" in t["sinais"][0]
    assert "o trânsito travou" in t["motivo"]
    # a não pareada ganha: janela/estado errados invalidam antes de qualquer saúde
    assert r["travou_e_nao_pareada"]["estado"] == "nao_pareada"
    # `sinais: []` e `sinais` ausente são a rodada de sempre
    assert r["sao"]["estado"] == "vencedor" and r["sao"]["coroa"] == "rl"
    assert r["antigo"]["estado"] == "vencedor"
    # fora do resultado o campo não decide nada
    assert r["em_curso"]["estado"] == "em_curso"
    # e o empate legítimo continua empate — travou NÃO é o novo nome do empate
    assert r["empate_sao"]["estado"] == "empate"


# ============================================================ (b) o redutor
_REDUTOR = """
import { reduzEntrada, estadoInicial, aoMudarFase, textoOcioso, NOME_MAX } from %s;
const passos = (e, teclas) => {
  const acoes = [];
  for (const k of teclas) { const r = reduzEntrada(e, k); e = r.estado; acoes.push(...r.acoes); }
  return { e, acoes };
};
const out = {};
// 1. campo aberto: as letras do jogo viram NOME, nada sai para o jogo
let e = estadoInicial('ocioso');
let r = passos(e, ['a', 'n', 'a', 'q', ' ', 'w']);
out.nome_digitado = { nome: r.e.nome, acoes: r.acoes, campo: r.e.campo };
// 2. ENTER confirma e fecha o campo; vai para o POST, não para o WS
r = passos(r.e, ['Enter']);
out.confirmado = { nome: r.e.nome, acoes: r.acoes, campo: r.e.campo, confirmado: r.e.confirmado };
// 3. DURANTE A RODADA: `q` é botão, espaço é START, Escape é ABORTAR.
// A fase entra explícita porque ela MANDA no Escape: no `ocioso` com o campo fechado
// (nome confirmado, esperando o ESPAÇO) Esc é "desistir" e devolve a vez — ver
// `tests/test_a11_fluxo_visitante.py`. Abortar é da rodada em curso.
r = passos({ ...r.e, fase: 'jogando' }, ['q', 'V', ' ', 'Escape', 'Escape', 'Escape', 'h']);
// um Esc sozinho NÃO aborta (é a tecla do reflexo); três em 1,5 s, sim
out.esc_um = reduzEntrada({ campo: false, nome: '', escs: [] }, 'Escape', 1000).acoes;
out.esc_tres = passos({ campo: false, nome: '', escs: [] }, ['Escape', 'Escape', 'Escape']).acoes;
out.esc_lento = (() => { let e = { campo: false, nome: '', escs: [] }, ac = [];
  for (const t of [0, 1000, 2000]) { const r = reduzEntrada(e, 'Escape', t); e = r.estado; ac = ac.concat(r.acoes); }
  return ac; })();
out.jogo = { acoes: r.acoes };
// 4. campo aberto e VAZIO: espaço começa (Visitante N); Escape limpa; Backspace apaga
e = estadoInicial('ocioso');
out.vazio_espaco = passos(e, [' ']).acoes;
r = passos(e, ['x', 'y', 'Backspace', 'Escape']);
out.limpa = { nome_apos_backspace: passos(e, ['x', 'y', 'Backspace']).e.nome, nome_apos_escape: r.e.nome };
// 5. ENTER com nome vazio não confirma
out.enter_vazio = passos(e, ['Enter']).e.campo;
// 6. teto de 12
out.teto = passos(e, 'abcdefghijklmnop'.split('')).e.nome.length;
out.teto_max = NOME_MAX;
// 7. voltar ao ocioso REABRE o campo vazio; sair fecha
let f = aoMudarFase({ ...estadoInicial('ocioso'), nome: 'ANA', campo: false, confirmado: true }, 'preparando');
out.saiu = { campo: f.campo };
f = aoMudarFase(aoMudarFase(f, 'resultado'), 'ocioso');
out.voltou = { campo: f.campo, nome: f.nome, confirmado: f.confirmado };
// 8. teclas do operador não são consumidas com o campo fechado (setas, i)
const ec = { ...estadoInicial('jogando'), campo: false };
out.passa = { i: reduzEntrada(ec, 'i').consumida, seta: reduzEntrada(ec, 'ArrowLeft').consumida,
              d: reduzEntrada(ec, 'd').consumida };
// 9. o texto do ocioso
out.texto_aberto = textoOcioso(estadoInicial('ocioso'), { anonimo: 'Visitante 27' },
                               { seed: 107, rotulo: 'DIFÍCIL', hoje: { jogaram: 4, bateram: 0 } });
out.texto_fechado = textoOcioso({ campo: false, nome: 'ANA' }, { nome: 'ANA' }, null);
console.log(JSON.stringify(out));
"""


@sem_node
def test_com_o_campo_de_nome_aberto_nenhuma_tecla_vira_botao(tmp_path):
    r = _node(_REDUTOR % json.dumps(_url("entrada.js")), tmp_path)
    # as letras do jogo viraram nome (em caixa alta), e NENHUMA ação saiu
    assert r["nome_digitado"]["nome"] == "ANAQW"
    assert r["nome_digitado"]["acoes"] == [], "tecla de nome vazou para o jogo"
    assert r["nome_digitado"]["campo"] is True
    # ENTER: o nome vai para o POST, o campo fecha
    assert r["confirmado"]["acoes"] == [{"tipo": "nome", "nome": "ANAQW"}]
    assert r["confirmado"]["campo"] is False and r["confirmado"]["confirmado"] is True
    # campo fechado: botão, botão, START, ABORTAR — e `h` não é nada
    assert r["jogo"]["acoes"] == [{"tipo": "tecla", "k": "q"}, {"tipo": "tecla", "k": "v"},
                                  {"tipo": "start"}, {"tipo": "abortar"}]
    # Esc: um só não faz nada; três seguidos abortam; três espaçados de 1 s, não
    assert r["esc_um"] == [] and r["esc_tres"] == [{"tipo": "abortar"}] and r["esc_lento"] == []


@sem_node
def test_espaco_com_o_campo_vazio_comeca_e_o_resto_das_regras_do_nome(tmp_path):
    r = _node(_REDUTOR % json.dumps(_url("entrada.js")), tmp_path)
    assert r["vazio_espaco"] == [{"tipo": "start"}], "ESPAÇO sem nome tem de começar (Visitante N)"
    assert r["limpa"]["nome_apos_backspace"] == "X"
    assert r["limpa"]["nome_apos_escape"] == ""
    assert r["enter_vazio"] is True, "ENTER sem nome não pode fechar o campo"
    assert r["teto"] == r["teto_max"] == 12
    assert r["saiu"]["campo"] is False
    assert r["voltou"] == {"campo": True, "nome": "", "confirmado": False}
    # as teclas do operador passam quando não são do jogo; `d` É do jogo
    assert r["passa"] == {"i": False, "seta": False, "d": True}
    t = r["texto_aberto"]
    assert t["convite"].startswith("QUAL O SEU APELIDO?")
    assert "Visitante 27" in t["sub"]
    assert t["nivel"] == "HORA DE TRÂNSITO 107 · NÍVEL DIFÍCIL · hoje 0 de 4 bateram a IA"
    assert r["texto_fechado"]["convite"] == "ANA · APERTE ESPAÇO PARA COMEÇAR"
    assert r["texto_fechado"]["nivel"] == ""


# ============================================================ (c) quadro e colocação
_QUADRO = """
import { linhaRecorde, textoColocacao, formataScore } from %s;
const out = {};
out.scores = [15, -4, 0, null].map(formataScore);
out.v2 = linhaRecorde({ id: 'm3', nome: 'Ana', rotulo: 'Ana', entregues: 104, seed: 107,
                        venceu: true, rl: 101, timer: 89, score: 15, delta_rl: 3,
                        medalha: 'ouro', degradada: false, hora: '14:22' });
out.v2_sem = linhaRecorde({ rotulo: 'Visitante 4', score: -12, medalha: '', entregues: 60 });
out.v1 = linhaRecorde({ entregues: 143, seed: 111, venceu: true, rl: 131, hora: '14:22' });
out.col = textoColocacao({ posicao: 7, pessoas: 31, medalha: 'prata', score: 11, recorde: false });
out.rec = textoColocacao({ posicao: 1, pessoas: 31, medalha: 'ouro', score: 15, recorde: true });
out.deg = textoColocacao({ posicao: 3, pessoas: 5, medalha: 'bronze', score: 4, degradada: true });
out.deg_sem_medalha = textoColocacao({ posicao: 4, pessoas: 5, medalha: '', score: -1, degradada: true });
out.nada = textoColocacao(null);
out.sem_pos = textoColocacao({ posicao: null, pessoas: 5 });
console.log(JSON.stringify(out));
"""


@sem_node
def test_a_linha_do_quadro_e_a_colocacao_sao_derivadas_da_marca(tmp_path):
    r = _node(_QUADRO % json.dumps(_url("placar.js")), tmp_path)
    assert r["scores"] == ["+15", "−4", "0", "—"]
    v2 = r["v2"]
    assert v2["v2"] is True and v2["rotulo"] == "Ana" and v2["score"] == "+15"
    assert v2["medalha"] == "ouro" and v2["letra"] == "O"
    assert r["v2_sem"]["v2"] is True and r["v2_sem"]["score"] == "−12" and r["v2_sem"]["letra"] == ""
    # a marca antiga (sem score/rotulo) NÃO é v2: a tela desenha como antes
    assert r["v1"]["v2"] is False
    c = r["col"]
    assert c["titulo"] == "VOCÊ FICOU EM 7º DE 31" and c["sub"] == "" and c["letra"] == "P"
    rec = r["rec"]
    assert rec["titulo"] == "NOVO RECORDE DA FEIRA" and rec["sub"] == "VOCÊ FICOU EM 1º DE 31"
    assert rec["recorde"] is True and rec["medalha"] == "ouro"
    assert r["deg"]["medalhaTexto"].startswith("BRONZE")
    assert r["deg_sem_medalha"]["medalhaTexto"] == "sem IA nesta rodada"
    assert r["nada"] is None and r["sem_pos"] is None


@sem_node
def test_os_modulos_do_front_carregam_e_o_operador_nao_depende_de_rede(tmp_path):
    """`entrada.js` e `placar.js` importam sem DOM (é o que os testes acima usam), e a
    página do operador não carrega nada de fora do repo."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    op = (raiz / "web" / "operador.html").read_text(encoding="utf-8")
    assert "http://" not in op and "https://" not in op, "a página do operador puxa algo da rede"
    assert "/api/abortar" in op and "/api/pular" in op and "/api/jogador" in op
    idx = (raiz / "web" / "index.html").read_text(encoding="utf-8")
    for el in ("colocacao", "nivel", "foco", "legenda"):
        assert 'id="%s"' % el in idx, "o index.html perdeu #%s" % el


# ============================================================ (d) a placa
_PLACA = """
import { estadoDaPlaca, PainelLeds, observaTls, faltaParaTrocar, aceitaEvento, passaAoOperador, PLATEIA, filtraSpam,
         MOSTRA_MS, DEBOUNCE_TECLA_MS, DEBOUNCE_START_MS } from %s;
const out = {};
const B = (bloqueado, faltam, total) => ({ bloqueado, faltam, total });
// (i) o estado visual, puro
out.livre = estadoDaPlaca({ led: 'off', agora: 1000 });
out.pedido = estadoDaPlaca({ led: 'armed', tLed: 900, agora: 1000, proximoTick: 3000, tickMs: 4000 });
out.pedido_spinner = estadoDaPlaca({ led: 'armed', tLed: 900, agora: 1000, proximoTick: null });
out.pedido_bloq = estadoDaPlaca({ led: 'armed', agora: 1000, bloqueio: B(true, 4.2, 7), ritmo: 1.5, proximoTick: 3000, tickMs: 4000 });
out.pedido_cedo = estadoDaPlaca({ led: 'armed', agora: 1000, bloqueio: B(true, 9, 10), ritmo: 1.5, proximoTick: 3000, tickMs: 4000 });
out.trocou = estadoDaPlaca({ led: 'on', tLed: 1000, agora: 1000 + MOSTRA_MS - 1 });
out.trocou_caiu = estadoDaPlaca({ led: 'on', tLed: 1000, agora: 1000 + MOSTRA_MS + 1 });
out.trocou_caiu_bloq = estadoDaPlaca({ led: 'on', tLed: 1000, agora: 1000 + MOSTRA_MS + 1,
                                       bloqueio: B(true, 6, 7) });
out.negado = estadoDaPlaca({ led: 'deny', tLed: 1000, agora: 1000 + 50, bloqueio: B(true, 3, 7) });
out.negado_piscadas = [0, 350, 650, 950].map(d => estadoDaPlaca({ led: 'deny', tLed: 1000, agora: 1000 + d }).pisca);
out.negado_caiu = estadoDaPlaca({ led: 'deny', tLed: 1000, agora: 1000 + MOSTRA_MS + 1, bloqueio: B(true, 3, 7) });
out.negado_progresso = [0, MOSTRA_MS / 2, MOSTRA_MS - 1].map(d => estadoDaPlaca({ led: 'deny', tLed: 1000, agora: 1000 + d }).progresso);
out.bloqueado = estadoDaPlaca({ led: 'off', agora: 1000, bloqueio: B(true, 3.5, 7) });
// (ii) o estimador de bloqueio, grade 5/7/3: verde nasce em t=100, amarelo em t=130
let h = observaTls({}, [{ id: 'H1V1', state: 'GGrr' }], 100);
h = observaTls(h, { H1V1: 'GGrr' }, 103);            // sem mudança: tMudanca fica
out.verde_3s = faltaParaTrocar(h.H1V1, 103);
out.verde_7s = faltaParaTrocar(h.H1V1, 107);
h = observaTls(h, [{ id: 'H1V1', state: 'yyrr' }], 130);
out.amarelo_1s = faltaParaTrocar(h.H1V1, 131);
h = observaTls(h, [{ id: 'H1V1', state: 'rrGG' }], 133);
out.verde_novo_2s = faltaParaTrocar(h.H1V1, 135);
out.sem_historico = faltaParaTrocar(h.H2V2, 135);
out.grade_outra = faltaParaTrocar({ state: 'GGrr', tMudanca: 100 }, 104, { di: 5, min_green: 10, yellow: 3 });
// o painel: tick detectado, próximo tick projetado, pulso
const p = new PainelLeds(12);
p.recebe({ tipo: 'leds', estados: ['armed', ...new Array(11).fill('off')], start: 'on' }, 1000);
out.painel_armed = p.estado(0, 1200, { tickMs: 2500 });
p.recebe({ tipo: 'leds', estados: ['on', 'deny', ...new Array(10).fill('off')] }, 3000);
out.painel_tick = p.ultimoTick;
out.painel_prox = p.proximoTick(3100, 2500);
out.painel_prox_rolou = p.proximoTick(9000, 2500);
p.recebe({ tipo: 'leds', estados: ['armed', ...new Array(11).fill('off')] }, 3500);
out.painel_pedido = p.estado(0, 4000, { tickMs: 2500 });
p.pulsa(0, 4000);
out.painel_pulso = [p.estado(0, 4050).pulso, p.estado(0, 4400).pulso];
// com ATRASO (o render-delay do mapa): o resultado do tick só aparece `atrasoMs` depois;
// o aperto (armed) aparece na hora; um aperto DEPOIS do tick não é engolido pelo tick
const q = new PainelLeds(12, { atrasoMs: 600 });
q.recebe({ tipo: 'leds', estados: ['armed', ...new Array(11).fill('off')] }, 1000);
q.recebe({ tipo: 'leds', tick: true, t: 305, estados: ['on', 'deny', ...new Array(10).fill('off')] }, 2000);
out.atraso_antes = [q.estado(0, 2100).estado, q.estado(1, 2100).estado, q.ultimoTick];
out.atraso_depois = [q.estado(0, 2650).estado, q.estado(1, 2650).estado, q.ultimoTick, q.tTick];
q.recebe({ tipo: 'leds', tick: true, t: 310, estados: ['off', 'off', ...new Array(10).fill('off')] }, 4500);
q.recebe({ tipo: 'leds', estados: ['armed', 'off', ...new Array(10).fill('off')] }, 4700);
out.atraso_aperto_vence = [q.estado(0, 5200).estado, q.estado(1, 5200).estado, q.ticks];
// (iii) anti-spam
out.operador = { solto_sem_entrada: passaAoOperador({ key: 'g' }, false),
                 solto_com_entrada: passaAoOperador({ key: 'g' }, true),
                 ctrl_alt_com_entrada: passaAoOperador({ key: 'g', ctrlKey: true, altKey: true }, true),
                 so_ctrl: passaAoOperador({ key: 'g', ctrlKey: true }, true) };
out.plateia = PLATEIA;
out.repeat = { jogo: aceitaEvento({ campo: false }, { repeat: true, key: 'q' }),
               nome_bs: aceitaEvento({ campo: true }, { repeat: true, key: 'Backspace' }),
               nome_letra: aceitaEvento({ campo: true }, { repeat: true, key: 'a' }),
               normal: aceitaEvento({ campo: false }, { repeat: false, key: 'q' }) };
let memo = {};
const sp = [];
for (const [t, a] of [[0, { tipo: 'tecla', k: 'q' }], [50, { tipo: 'tecla', k: 'q' }], [80, { tipo: 'tecla', k: 'w' }],
                      [130, { tipo: 'tecla', k: 'q' }], [200, { tipo: 'start' }], [600, { tipo: 'start' }],
                      [750, { tipo: 'start' }], [800, { tipo: 'abortar' }]]) {
  const r = filtraSpam(memo, a, t); memo = r.memo; sp.push(r.envia);
}
out.spam = sp;
out.janelas = [DEBOUNCE_TECLA_MS, DEBOUNCE_START_MS];
console.log(JSON.stringify(out));
"""


@sem_node
def test_a_placa_fala_a_lingua_do_farol_e_a_duracao_visual_e_da_pagina(tmp_path):
    r = _node(_PLACA % json.dumps(_url("entrada.js")), tmp_path)
    assert r["livre"]["estado"] == "livre"
    p = r["pedido"]
    assert p["estado"] == "pedido" and abs(p["fracao"] - 0.5) < 1e-9, "o anel enche até o tick"
    assert r["pedido_spinner"]["fracao"] is None, "sem tick conhecido o anel gira"
    # a pílula do PEDIDO conta até o TICK (2 s de parede), e avisa "cedo" só quando o
    # bloqueio (4,2 s sim / 1,5 = 2,8 s -> 3) passa do tick por mais de meio segundo
    assert r["pedido_bloq"]["segundos"] == 2 and r["pedido_bloq"]["cedo"] is True
    assert r["pedido_cedo"]["cedo"] is True and r["pedido_cedo"]["segundos"] == 2
    assert r["trocou"]["estado"] == "trocou"
    assert r["trocou_caiu"]["estado"] == "livre", "verde não pode ficar até o tick seguinte"
    assert r["trocou_caiu_bloq"]["estado"] == "bloqueado"
    n = r["negado"]
    assert n["estado"] == "negado" and n["segundos"] == 3 and n["pisca"] is True
    assert r["negado_piscadas"] == [True, False, True, False], "duas piscadas em 1,2 s"
    assert r["negado_caiu"]["estado"] == "bloqueado", "depois do DESCARTADO a placa mostra o anel"
    p0, p1, p2 = r["negado_progresso"]
    assert p0 == 0 and abs(p1 - 0.5) < 0.01 and 0.99 < p2 <= 1, "o relógio da animação de descarte"
    b = r["bloqueado"]
    assert b["estado"] == "bloqueado" and b["segundos"] == 4 and abs(b["fracao"] - 0.5) < 1e-9


@sem_node
def test_o_bloqueio_e_estimado_do_farol_com_a_regra_do_pode_trocar(tmp_path):
    r = _node(_PLACA % json.dumps(_url("entrada.js")), tmp_path)
    assert r["verde_3s"] == {"bloqueado": True, "faltam": 4, "total": 7, "amarelo": False}
    assert r["verde_7s"] == {"bloqueado": False, "faltam": 0, "total": 7, "amarelo": False}
    assert r["amarelo_1s"] == {"bloqueado": True, "faltam": 9, "total": 10, "amarelo": True}, "amarelo + verde mínimo"
    assert r["verde_novo_2s"] == {"bloqueado": True, "faltam": 5, "total": 7, "amarelo": False}
    assert r["sem_historico"]["bloqueado"] is False, "a página não inventa bloqueio que não viu"
    assert r["grade_outra"] == {"bloqueado": True, "faltam": 6, "total": 10, "amarelo": False}
    # o painel
    assert r["painel_armed"]["estado"] == "pedido" and r["painel_armed"]["fracao"] is None
    assert r["painel_tick"] == 3000 and r["painel_prox"] == 5500 and r["painel_prox_rolou"] == 10500
    assert r["painel_pedido"]["estado"] == "pedido" and abs(r["painel_pedido"]["fracao"] - 0.4) < 1e-9
    assert r["painel_pulso"] == [True, False]
    assert r["atraso_antes"] == ["pedido", "livre", None], "antes do atraso a placa ainda mostra o pedido"
    assert r["atraso_depois"] == ["trocou", "negado", 2600, 305], "depois do atraso o tick aparece, no instante atrasado"
    assert r["atraso_aperto_vence"] == ["pedido", "livre", 2], "o aperto feito depois do tick não é engolido"


@sem_node
def test_tecla_segurada_e_martelada_nao_viram_fio(tmp_path):
    r = _node(_PLACA % json.dumps(_url("entrada.js")), tmp_path)
    assert r["repeat"] == {"jogo": False, "nome_bs": True, "nome_letra": False, "normal": True}
    # os atalhos do operador (h, g, r, f...) só com Ctrl+Alt quando o teclado é do visitante
    assert r["operador"] == {"solto_sem_entrada": True, "solto_com_entrada": False,
                             "ctrl_alt_com_entrada": True, "so_ctrl": False}
    assert r["plateia"] == {"hud": True, "asfalto": True, "pegada": True, "verdade": False,
                            "grade": False, "diag": False}
    # q, q(50ms: cai), w, q(130ms: passa), start, start(400ms: cai), start(550ms: passa), abortar
    assert r["spam"] == [True, False, True, True, True, False, True, True]
    assert r["janelas"] == [120, 500]
