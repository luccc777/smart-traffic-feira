// projecao.js — a PROJEÇÃO do modo jogo. Cliente do servidor `feira.jogo.web`.
//
// O que vai no chão, por fase da rodada (as cinco de `FASES`, no C7):
//
//   ocioso      a RL rodando ao vivo, o TIMER como régua, e o convite para jogar
//   preparando  "calculando a rodada" — pode demorar 9 s (fantasma da RL sem cache)
//   contagem    3 · 2 · 1 gigantes por cima do mapa congelado
//   jogando     as TRÊS barras vivas em carros entregues + o mapa do braço humano
//   resultado   o placar em tela cheia, com as linhas vindas do `Resultado` (C5)
//
// TRÊS PROPRIEDADES QUE NÃO PODEM CAIR
// ------------------------------------
// (a) OBSERVADOR PASSIVO. Este front nunca manda nada que o jogo espere. O WS só
//     recebe; o `send` existe apenas para o keep-alive do protocolo.
// (b) SE O JOGO CAIR, A PROJEÇÃO VOLTA SOZINHA para RL × timer em <= 3 s. Há DOIS
//     vigias: o do servidor (`feira/jogo/web.py`, rédea por fase) e o daqui, que
//     cobre o caso de o servidor inteiro morrer — sem ele, "o jogo caiu" e "a rede
//     caiu" teriam desfechos diferentes na tela, e para a plateia é a mesma coisa.
// (c) JANELA DIVERGENTE SE DENUNCIA. A `Chave`/`janela` viaja no frame porque a
//     projeção antiga comparava contadores de simulações derivadas. Se dois braços
//     chegarem com janelas diferentes, esta tela mostra a DENÚNCIA no lugar das
//     barras. Não desenha "mais ou menos certo".
//
// ESTADO PERSISTIDO (localStorage): rotação/espelho, zoom/pan e o tamanho do texto.
// Fechar e reabrir a janela do projetor não perde o alinhamento do chão.

import { FrameBuffer } from './interp.js';
import { Board } from './paint.js';
import { Placar, veredito } from './placar.js';

const $ = id => document.getElementById(id);
const BRACOS = ['timer', 'rl', 'humano'];
const STORE = 'st-feira-projecao-v1';

// Vigia do FRONT. O do servidor tem rédea 2,0 s + tique 0,25 s; este é o backstop
// para o servidor inteiro morrer, e fica abaixo dos 3 s da DoD com folga.
const QUEDA_MS = 2500;
// Altura da tarja do placar a 1080p. Tem que bater com `--h-placar` no CSS: é ela
// que decide o retângulo do mapa, e portanto a escala do sprite.
const H_PLACAR = 344;
const RECONECTA_MS = 800;

// --------------------------------------------------------------------- estado
const st = {
  rot: 0, mirror: false, zoom: 1, panX: 0, panY: 0,
  texto: 1, hud: true, asfalto: true, pegada: true, verdade: false,
  grade: false, diag: false,
};
try { Object.assign(st, JSON.parse(localStorage.getItem(STORE)) || {}); } catch (e) { /**/ }
(() => {
  const q = new URLSearchParams(location.search);
  const bool = (k, campo) => {
    if (q.has(k)) st[campo] = !['0', 'false', 'nao', 'não'].includes(q.get(k).toLowerCase());
  };
  bool('hud', 'hud'); bool('asfalto', 'asfalto'); bool('pegada', 'pegada');
  bool('verdade', 'verdade'); bool('espelho', 'mirror'); bool('diag', 'diag');
  if (q.has('rot')) st.rot = ((parseInt(q.get('rot'), 10) || 0) % 360 + 360) % 360;
  if (q.has('zoom')) st.zoom = Math.max(0.35, Math.min(3, parseFloat(q.get('zoom')) || 1));
  if (q.has('texto')) st.texto = Math.max(0.7, Math.min(2, parseFloat(q.get('texto')) || 1));
})();
const BENCH = (() => {
  const n = parseInt(new URLSearchParams(location.search).get('bench') || '0', 10);
  return isFinite(n) && n > 0 ? n : 0;
})();
// `?demo=<fase>` desenha uma fase com dados sintéticos, SEM WebSocket. Existe para a
// foto de bancada e para o `scripts/projecao_telas.py`: um navegador headless com
// `--screenshot` dispara o instantâneo assim que o orçamento de tempo VIRTUAL acaba, e
// uma conexão WS de verdade não cabe nessa janela — a foto sairia sempre na tela de
// "conectando". Os dados entram pelo MESMO `recebe()` do fio, então a foto mostra o
// código real, não uma maquete dele.
const DEMO = new URLSearchParams(location.search).get('demo') || '';
// `?quadros=N` para o laço de render depois de N quadros. Só o
// `scripts/projecao_telas.py` usa: o `--screenshot` do Chrome headless espera o
// orçamento de tempo VIRTUAL acabar, e um laço de `requestAnimationFrame` que nunca
// para faz esse orçamento levar minutos de tempo real com 180 carros na tela.
const LIMITE_QUADROS = (() => {
  const n = parseInt(new URLSearchParams(location.search).get('quadros') || '0', 10);
  return isFinite(n) && n > 0 ? n : 0;
})();
function salva() { try { localStorage.setItem(STORE, JSON.stringify(st)); } catch (e) { /**/ } }

const bufs = {}; const boards = {};
for (const b of BRACOS) bufs[b] = new FrameBuffer();

let rede = null, placar = null;
let cv, ctx, base, bctx, SW = 0, SH = 0, U = 1, dpr = 1;
let baseSujo = true, ultimoNow = 0, lacoVivo = false;
let fase = 'ocioso', degradado = false, motivo = '';
let ultimaMsgMs = 0, ws = null;
const janelaDe = Object.create(null);      // braco|placar -> "t0,t1"
let denuncia = '';
// O `motivo` que veio DO MOTOR na última mensagem `placar`. Tem precedência sobre o
// texto que o servidor infere: o motor sabe *por que* a rodada está degradada (qual
// fantasma faltou, qual exceção subiu); o servidor só sabe que ninguém publicou.
let motivoDoMotor = '';
let naoPareada = false;
// O mesmo `motivo` não pode aparecer duas vezes na tela. Ele tem TRÊS lugares
// possíveis — a denúncia em tela cheia, a linha embaixo do veredito e a tarja do
// operador — e a regra é: quem está mais perto do olho do público ganha, a tarja é
// a última opção.
let motivoJaNaTela = false;

// telemetria da DoD (b): quadro perdido é gap no `t` simulado, não impressão
const tele = {
  quadros: 0, gaps: 0, fora: 0, ultimoT: Object.create(null),
  fps: 0, pior: 0, amostras: [], desenhados: 0,
};

// ---------------------------------------------------------------------- palco
const palco = () => $('palco');

function aplicaPalco() {
  const vw = window.innerWidth, vh = window.innerHeight;
  const troca = (st.rot === 90 || st.rot === 270);
  SW = troca ? vh : vw;
  SH = troca ? vw : vh;
  const p = palco();
  p.style.width = SW + 'px';
  p.style.height = SH + 'px';
  p.style.transform =
    `translate(-50%,-50%) rotate(${st.rot}deg) scale(${st.mirror ? -1 : 1},1)`;
}

function layout() {
  aplicaPalco();
  // A imagem projetada tem a mesma largura FÍSICA em qualquer painel, então escalar o
  // tipo com a resolução mantém o texto do MESMO tamanho no chão: 720p e 1080p ficam
  // iguais para quem assiste. O que a conta não sabe é a distância da plateia — isso é
  // `st.texto`, nas teclas , e .
  U = Math.max(0.55, Math.min(1.9, Math.min(SW / 1920, SH / 1080))) * st.texto;
  document.documentElement.style.setProperty('--u', U);

  dpr = Math.min(window.devicePixelRatio || 1, 2);
  for (const c of [cv, base]) {
    c.width = Math.round(SW * dpr);
    c.height = Math.round(SH * dpr);
    c.style.width = SW + 'px';
    c.style.height = SH + 'px';
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  bctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  // O mapa nunca entra embaixo do placar: o retângulo dele é o que sobra. O retângulo
  // NÃO muda na fase `resultado` (onde o placar toma a tela) de propósito: ali o mapa
  // simplesmente não é desenhado — encolher o retângulo faria o sprite do carro cair
  // abaixo da pegada do SUMO e o pintor teria que esticá-lo, quebrando a honestidade
  // numa tela em que o mapa nem aparece.
  const topo = 56 * U;
  const r = { x: 0, y: topo, w: SW, h: Math.max(120, SH - topo - H_PLACAR * U) };
  for (const b of BRACOS) {
    if (boards[b]) boards[b].layout(r, { zoom: st.zoom, panX: st.panX, panY: st.panY });
  }
  baseSujo = true;
  // ver `garanteLaco`: o canvas acabou de ser apagado por ter mudado de tamanho.
  if (LIMITE_QUADROS) tele.desenhados = 0;
  garanteLaco();
  atualizaDiag();
}

// ------------------------------------------------------------------ desenho
function bracoDoMapa() {
  // Quem o mapa mostra: durante a rodada é o HUMANO (é a corrida dele que está
  // acontecendo); no ocioso é a RL, que é o que a exibição normal mostra. Se o braço
  // preferido não tem frame, cai para o que houver — a tela nunca fica preta sem
  // explicação.
  const pref = (fase === 'jogando' || fase === 'contagem' || fase === 'resultado')
    ? ['humano', 'rl', 'timer'] : ['rl', 'timer', 'humano'];
  for (const b of pref) if (boards[b] && !bufs[b].vazio) return b;
  return null;
}

// O laço é RE-ARMÁVEL, e isso não é firula de teste. `layout()` reatribui
// `canvas.width`, e reatribuir a largura de um canvas APAGA o conteúdo dele — então
// todo redimensionamento (ou troca de fase, ou zoom do operador) deixa a tela preta
// até o próximo quadro. Com o laço correndo a 60 Hz isso dura 16 ms e ninguém vê; com
// `?quadros=N` (a foto de bancada) o laço já parou, e a foto sairia PRETA. Descoberto
// exatamente assim: a foto de `jogando` saía sem mapa nenhum.
function garanteLaco() {
  if (lacoVivo) return;
  lacoVivo = true;
  requestAnimationFrame(desenha);
}

function desenha(now) {
  lacoVivo = false;
  if (!LIMITE_QUADROS || tele.desenhados < LIMITE_QUADROS) garanteLaco();
  const dt = ultimoNow ? Math.min(0.25, (now - ultimoNow) / 1000) : 0.016;
  ultimoNow = now;

  // No RESULTADO o mapa some: a comparação É a mensagem, e um mapa parado atrás do
  // placar só joga luz no chão de graça (e custa quadro justo quando a plateia está
  // lendo número).
  const braco = fase === 'resultado' ? null : bracoDoMapa();
  const board = braco ? boards[braco] : null;
  if (board && baseSujo) {
    bctx.clearRect(0, 0, SW, SH);
    board.paintBase(bctx, { asphalt: st.asfalto });
    baseSujo = false;
  }
  ctx.clearRect(0, 0, SW, SH);
  if (board) {
    ctx.drawImage(base, 0, 0, SW, SH);
    const snap = bufs[braco].sample(now);
    if (snap) {
      board.paint(ctx, snap, now, dt,
                  { footprint: st.pegada, verdade: st.verdade });
    }
  }

  // fps: média móvel curta + pior quadro da janela (é o número da DoD (b))
  tele.desenhados++;
  tele.amostras.push(dt * 1000);
  if (tele.amostras.length > 120) tele.amostras.shift();
  if (tele.desenhados % 15 === 0) {
    const a = [...tele.amostras].sort((x, y) => x - y);
    tele.fps = a.length ? 1000 / a[Math.floor(a.length / 2)] : 0;
    tele.pior = a.length ? a[a.length - 1] : 0;
    if (st.diag || BENCH) atualizaDiag();
  }

  const agora = performance.now();
  if (!DEMO && !BENCH && ultimaMsgMs && agora - ultimaMsgMs > QUEDA_MS
      && (fase === 'contagem' || fase === 'jogando')) {
    cai(`sem mensagem do servidor há ${((agora - ultimaMsgMs) / 1000).toFixed(1)} s`);
  }
}

// ------------------------------------------------------------------- fases
function poeFase(nova) {
  if (!nova || nova === fase) return;
  const antes = fase;
  fase = nova;
  document.documentElement.dataset.fase = fase;
  // A escala da barra é por RODADA: `preparando` é onde a rodada nova começa.
  if (fase === 'preparando' && antes !== 'preparando' && placar) placar.reinicia();
  // A denúncia de pareamento é sobre UMA rodada. Ao sair do `resultado` ela vai junto,
  // senão a tela ociosa da rodada seguinte abriria acusando a rodada anterior.
  if (antes === 'resultado' && fase !== 'resultado' && naoPareada) {
    naoPareada = false;
    motivoDoMotor = '';
    motivoJaNaTela = false;      // senão a tarja do vigia ficaria muda depois
    poeAlerta();
    mostraAviso();
  }
  $('fase-nome').textContent = fase.toUpperCase();
}

function cai(porque) {
  if (degradado) return;
  degradado = true;
  motivo = porque;
  // O motivo do MOTOR é o da última rodada, e o motor sumiu: ele deixou de descrever o
  // estado de agora. A precedência "motor ganha do servidor" vale enquanto o motor
  // está vivo; na queda, quem sabe o que houve é o vigia.
  motivoDoMotor = '';
  motivoJaNaTela = false;
  naoPareada = false;
  poeAlerta();
  poeFase('ocioso');
  // Os buffers do humano param de valer: a rodada dele acabou (ou nunca terminou).
  bufs.humano.limpa();
  mostraAviso();
}

function volta() {
  if (!degradado) return;
  degradado = false;
  motivo = '';
  mostraAviso();
}

// A tarja de aviso tem DUAS fontes e uma regra de precedência: o texto do MOTOR
// (`Placar.motivo`, C7) ganha do que o servidor infere pelo relógio. "modo degradado:
// sem fantasma de rl" diz o que quebrou; "sem publicação há 2,3 s" só diz que alguém
// calou. Quando não há motivo do motor, o do servidor ainda é melhor que nada.
function mostraAviso() {
  // Se o motivo já está na denúncia (tela cheia) ou embaixo do veredito, a tarja fica
  // vazia: repetir seria dizer duas vezes a mesma coisa, e a segunda vez em corpo
  // menor — que é a pior das duas.
  const texto = motivoJaNaTela ? '' : (motivoDoMotor || (degradado ? motivo : ''));
  document.documentElement.dataset.degradado = texto ? '1' : '0';
  $('degradado-msg').textContent = texto;
}

// -------------------------------------------------------------- divergência
// A ARMADILHA (b) do C7. Dois braços em janelas diferentes NÃO se comparam: é o erro
// que a auditoria do A2 catalogou e a razão pela qual a janela viaja no frame.
function confereJanela() {
  const vistas = new Map();
  for (const k in janelaDe) {
    if (!janelaDe[k]) continue;
    if (!vistas.has(janelaDe[k])) vistas.set(janelaDe[k], []);
    vistas.get(janelaDe[k]).push(k);
  }
  if (vistas.size <= 1) { denuncia = ''; }
  else {
    denuncia = [...vistas.entries()]
      .map(([j, ks]) => `${ks.join('/')} = [${j}]`).join('   ·   ');
  }
  poeAlerta();
  return denuncia;
}

// UMA camada de denúncia, dois motivos. Os dois tiram o placar da tela pela MESMA
// razão: se a comparação não vale, não há primeiro nem segundo lugar para mostrar.
// A janela ganha da não-pareada quando as duas acontecem — janela diferente é a
// condição errada, e nem os números isolados significam a mesma coisa.
const ALERTAS = {
  janela: {
    titulo: 'JANELAS DIFERENTES — ESTA COMPARAÇÃO NÃO VALE',
    nota: 'os braços não estão na mesma condição. o placar foi retirado da tela de '
        + 'propósito: comparar contadores de simulações derivadas é exatamente o '
        + 'defeito que a janela no frame existe para pegar.',
  },
  pareamento: {
    titulo: 'RODADA NÃO PAREADA — SEM VENCEDOR E SEM COLOCAÇÃO',
    nota: 'os braços partiram de estados diferentes no início da janela, então os '
        + 'números não se comparam. não há primeiro nem segundo lugar: uma rodada '
        + 'que não é pareada não tem classificação, só tem os números soltos de '
        + 'cada braço — que ficam no log da rodada.',
  },
};

function poeAlerta() {
  const qual = denuncia ? 'janela' : (naoPareada ? 'pareamento' : '');
  document.documentElement.dataset.alerta = qual;
  if (!qual) return;
  $('denuncia-titulo').textContent = ALERTAS[qual].titulo;
  $('denuncia-nota').textContent = ALERTAS[qual].nota;
  $('denuncia-corpo').textContent = qual === 'janela' ? denuncia : motivoDoMotor;
}

// -------------------------------------------------------------------- rede WS
function conecta() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    ultimaMsgMs = performance.now();
    $('live-txt').textContent = 'ao vivo';
    document.documentElement.dataset.live = '1';
  };
  ws.onclose = () => {
    $('live-txt').textContent = 'reconectando';
    document.documentElement.dataset.live = '0';
    setTimeout(conecta, RECONECTA_MS);
  };
  ws.onerror = () => { try { ws.close(); } catch (e) { /**/ } };
  ws.onmessage = ev => {
    ultimaMsgMs = performance.now();
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    recebe(m);
  };
}

function recebe(m) {
  // O C7 usa `tipo` no placar e `type` no frame. Aceitamos os dois e seguimos.
  const tipo = m.tipo || m.type;
  if (tipo === 'frame') return recebeFrame(m);
  if (tipo === 'placar') return recebePlacar(m);
  if (tipo === 'projecao') return recebeEstado(m);
}

function recebeFrame(m) {
  const b = m.braco;
  if (!BRACOS.includes(b)) return;
  tele.quadros++;
  const ant = tele.ultimoT[b];
  if (ant != null) {
    const passos = Math.round(m.t - ant);
    if (passos > 1) tele.gaps += passos - 1;      // quadro perdido no caminho
    if (passos <= 0) tele.fora++;
  }
  tele.ultimoT[b] = m.t;
  janelaDe[b] = m.janela ? m.janela.map(v => (+v).toFixed(1)).join(', ') : '';
  confereJanela();
  bufs[b].push(m);
  if (!boards[b] && rede) boards[b] = novoBoard();
  if (boards[b] && !boards[b].T) layout();
  volta();
  // No ocioso o placar sai do PRÓPRIO frame (não há mensagem `placar` fora da rodada):
  // são os `stats` que a Arena já mede, com os mesmos nomes do C5.
  if (fase === 'ocioso') placarDoOcioso();
}

function placarDoOcioso() {
  const linhas = [];
  for (const b of ['timer', 'rl']) {
    const f = bufs[b].newestFrame;
    if (!f || !f.stats) continue;
    linhas.push({
      braco: b, rotulo: b === 'timer' ? 'TIMER FIXO' : 'REDE NEURAL',
      entregues: f.stats.entregues || 0,
      fila: f.stats.fila_media || 0,
      tempo_medio: f.stats.tempo_medio_entregue || 0,
      fantasma: false,
    });
  }
  if (linhas.length && placar) placar.atualiza(linhas, { fase: 'ocioso' });
}

function recebePlacar(m) {
  poeFase(m.fase);
  volta();
  const v = veredito(m);
  motivoDoMotor = v.motivo;
  naoPareada = v.estado === 'nao_pareada';
  const k = m.chave || {};
  janelaDe.placar = k.janela ? k.janela.map(x => (+x).toFixed(1)).join(', ') : '';
  confereJanela();                                 // já chama poeAlerta()
  $('chip-chave').textContent = `${k.cenario || '?'} · seed ${k.seed} · demanda ${k.demanda || '?'}`;
  $('chip-janela').textContent = k.janela ? `janela [${(+k.janela[0]).toFixed(0)}, ${(+k.janela[1]).toFixed(0)}] s` : '';
  $('relogio').textContent = (m.t_restante || 0).toFixed(0);
  $('contagem-num').textContent = String(Math.max(0, Math.round(m.t_restante || 0)));
  if (placar) {
    placar.atualiza(m.linhas || [],
                    { vencedor: v.coroa, fase: m.fase, compara: v.compara });
  }
  poeVeredito(m, v);
  mostraAviso();          // depois do veredito: ele é quem decide se sobrou motivo
}

// O veredito não é "tem vencedor ou não tem": são quatro estados, e o `veredito()` do
// placar.js já os separou. Aqui só viram texto.
const VENCEU = { timer: 'O TIMER FIXO VENCEU', rl: 'A REDE NEURAL VENCEU',
                 humano: 'VOCÊ VENCEU' };

function poeVeredito(m, v) {
  const el = $('veredito');
  el.textContent = '';
  el.dataset.quem = '';
  el.dataset.estado = '';
  motivoJaNaTela = false;
  if (m.fase !== 'resultado') return;
  // Na rodada não pareada quem fala é a denúncia, em tela cheia — e o placar (com o
  // veredito dentro) nem está visível.
  if (v.estado === 'nao_pareada') { motivoJaNaTela = !!v.motivo; return; }
  el.dataset.estado = v.estado;
  if (v.estado === 'vencedor') {
    el.textContent = VENCEU[v.coroa] || v.coroa;
    el.dataset.quem = v.coroa;
    return;
  }
  el.textContent = v.estado === 'empate' ? 'EMPATE' : 'RODADA NÃO CONCLUÍDA';
  if (v.motivo) {
    const n = document.createElement('span');
    n.className = 'motivo';
    n.textContent = v.motivo;
    el.appendChild(n);
    motivoJaNaTela = true;
  }
}

function recebeEstado(m) {
  if (m.evento === 'queda') cai(m.motivo || 'o jogo parou de publicar');
  if (m.evento === 'retomada') volta();
  if (m.fase) poeFase(m.fase);
  if (m.divergencia) {
    janelaDe.servidor = '';                     // o servidor já compôs a denúncia
    denuncia = m.divergencia;
    poeAlerta();
  }
}

// ------------------------------------------------------------------ diagnóstico
// A "régua de bancada": o proxy MENSURÁVEL da legibilidade a 2 m. Nenhum agente pode
// verificar "legível a 2 m" sem o projetor e uma foto — o que dá para entregar é o
// tamanho ANGULAR de cada elemento, com a conta à vista, para o dono conferir com o
// projetor ligado. Ver docs/PROJECAO.md §2.
const MONTAGEM = { larguraM: 2.00 / 1.10, distanciaM: 2.0 };   // torre 2 m, TR 1,10

function mmPorPx() { return (MONTAGEM.larguraM * 1000) / (SW || 1920); }
function arcmin(px) { return (px * mmPorPx() / (MONTAGEM.distanciaM * 1000)) * 3437.75; }

function capDe(sel) {
  const el = document.querySelector(sel);
  if (!el) return 0;
  const fs = parseFloat(getComputedStyle(el).fontSize) || 0;
  return fs * 0.72;                      // cap-height ~0,72 em, para a família em uso
}

function atualizaDiag() {
  const el = $('diag');
  if (!el) return;
  const b = boards[bracoDoMapa()] || boards.rl || boards.timer || boards.humano;
  const sp = b && b.sprite;
  const linhas = [
    `palco ${SW}x${SH} px · dpr ${dpr} · u ${U.toFixed(2)}`,
    `montagem: imagem ${MONTAGEM.larguraM.toFixed(2)} m · ${mmPorPx().toFixed(3)} mm/px · plateia a ${MONTAGEM.distanciaM} m`,
    `render: ${tele.fps.toFixed(1)} fps (mediana) · pior quadro ${tele.pior.toFixed(1)} ms`,
    `frames: ${tele.quadros} recebidos · ${tele.gaps} buracos no t · ${tele.fora} fora de ordem`,
    `mapa: braço ${bracoDoMapa() || '—'} · buffers ` +
      BRACOS.map(b => `${b}=${bufs[b].buf.length}`).join(' '),
  ];
  if (sp) {
    linhas.push(
      `escala do mapa: ${sp.s.toFixed(2)} px/m · exagero transversal da via x${sp.mult.toFixed(2)}`,
      `carro REAL: ${sp.realC.toFixed(1)}x${sp.realL.toFixed(1)} px = ${(sp.realC * mmPorPx()).toFixed(2)}x${(sp.realL * mmPorPx()).toFixed(2)} mm = ${arcmin(sp.realC).toFixed(1)}'x${arcmin(sp.realL).toFixed(1)}'`,
      `SPRITE:     ${sp.corpo.toFixed(1)}x${sp.largura.toFixed(1)} px = ${(sp.corpo * mmPorPx()).toFixed(2)}x${(sp.largura * mmPorPx()).toFixed(2)} mm = ${arcmin(sp.corpo).toFixed(1)}'x${arcmin(sp.largura).toFixed(1)}'`,
      `exagero: comprimento x${sp.exageroC.toFixed(2)} · largura x${sp.exageroL.toFixed(2)} · pegada ${sp.footPx.toFixed(1)} px${b.spriteExcede ? ` — SPRITE EXCEDE A PEGADA x${sp.excede.toFixed(2)}` : ' (o sprite NÃO passa da pegada)'}`);
  }
  for (const [rot, sel] of [['número do placar', '.pl-num b'], ['rótulo do braço', '.pl-rot'],
                            ['secundária', '.pl-sec'], ['cromo do operador', '.chip']]) {
    const cap = capDe(sel);
    if (cap) linhas.push(`texto ${rot}: cap ${cap.toFixed(0)} px = ${(cap * mmPorPx()).toFixed(1)} mm = ${arcmin(cap).toFixed(0)}' de arco`);
  }
  el.textContent = linhas.join('\n');
}

// ---------------------------------------------------------------------- teclas
const TECLAS = {
  h: () => { st.hud = !st.hud; document.documentElement.dataset.hud = st.hud ? '1' : '0'; },
  g: () => { st.asfalto = !st.asfalto; baseSujo = true; },
  d: () => { st.pegada = !st.pegada; },
  v: () => { st.verdade = !st.verdade; },
  i: () => { st.diag = !st.diag; document.documentElement.dataset.diag = st.diag ? '1' : '0'; atualizaDiag(); },
  t: () => { st.grade = !st.grade; document.documentElement.dataset.grade = st.grade ? '1' : '0'; },
  r: () => { st.rot = (st.rot + 90) % 360; layout(); },
  m: () => { st.mirror = !st.mirror; aplicaPalco(); },
  '+': () => { st.zoom = Math.min(3, st.zoom * 1.04); layout(); },
  '=': () => { st.zoom = Math.min(3, st.zoom * 1.04); layout(); },
  '-': () => { st.zoom = Math.max(0.35, st.zoom / 1.04); layout(); },
  ',': () => { st.texto = Math.max(0.7, st.texto - 0.05); layout(); },
  '.': () => { st.texto = Math.min(2, st.texto + 0.05); layout(); },
  '0': () => { st.zoom = 1; st.panX = 0; st.panY = 0; st.texto = 1; st.rot = 0; st.mirror = false; layout(); },
  arrowleft: () => { st.panX -= 4; layout(); },
  arrowright: () => { st.panX += 4; layout(); },
  arrowup: () => { st.panY -= 4; layout(); },
  arrowdown: () => { st.panY += 4; layout(); },
  f: () => { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen(); },
};

window.addEventListener('keydown', ev => {
  const k = ev.key.toLowerCase();
  const fn = TECLAS[k];
  if (!fn) return;
  ev.preventDefault();
  fn();
  salva();
});

// ------------------------------------------------------------------- arranque
function novoBoard() {
  const b = new Board(rede);
  b.layout({ x: 0, y: 56 * U, w: SW, h: Math.max(120, SH - 56 * U - H_PLACAR * U) },
           { zoom: st.zoom, panX: st.panX, panY: st.panY });
  return b;
}

async function iniciar() {
  cv = $('cv'); ctx = cv.getContext('2d');
  base = document.createElement('canvas'); bctx = base.getContext('2d');
  placar = new Placar($('placar-linhas'));
  document.documentElement.dataset.fase = fase;
  document.documentElement.dataset.hud = st.hud ? '1' : '0';
  document.documentElement.dataset.diag = st.diag ? '1' : '0';
  document.documentElement.dataset.degradado = '0';
  document.documentElement.dataset.alerta = '';
  window.addEventListener('resize', layout);
  layout();

  try {
    const r = await fetch('/api/rede', { cache: 'no-store' });
    rede = await r.json();
    $('chip-rede').textContent =
      `${rede.lanes.length} faixas · ${rede.tls.length} semáforos · carro ${rede.vehicle.length} x ${rede.vehicle.width} m`;
    // O cromo da chave começa com o que a REDE sabe. No `ocioso` não há mensagem
    // `placar`, então sem isto o chip ficaria em "…" a feira inteira.
    if ($('chip-chave').textContent === '…') $('chip-chave').textContent = rede.cenario;
    for (const b of BRACOS) boards[b] = novoBoard();
    layout();
  } catch (e) {
    $('espera-msg').textContent = 'sem geometria: /api/rede não respondeu';
  }

  if (BENCH) { bench(BENCH); return; }
  if (DEMO) { demo(DEMO); garanteLaco(); return; }
  conecta();
  garanteLaco();
}

// ------------------------------------------------------------------------ demo
// Números plausíveis com a REDE NEURAL EM ÚLTIMO de propósito: é o regime medido hoje
// na rede aberta (93 e 82 entregues contra 111 e 109 do timer), o A6 está retreinando
// em paralelo, e a tela tem que ficar correta exatamente nesse caso — não só quando a
// RL ganha.
const DEMO_LINHAS = [
  { braco: 'timer', rotulo: 'TIMER FIXO', entregues: 111, fila: 12.4, tempo_medio: 63, fantasma: true },
  { braco: 'rl', rotulo: 'REDE NEURAL', entregues: 93, fila: 14.1, tempo_medio: 68, fantasma: true },
  { braco: 'humano', rotulo: 'VOCÊ', entregues: 104, fila: 13.0, tempo_medio: 65, fantasma: false },
];

function demoFrame(braco, t, n, janela) {
  const lanes = rede.lanes;
  const veic = [];
  for (let i = 0; i < n; i++) {
    const sh = lanes[i % lanes.length].shape;
    const u = ((i * 0.37 + t * 0.11) % 1) * (sh.length - 1);
    const k = Math.min(sh.length - 2, Math.floor(u)), f = u - k;
    const a = sh[k], b = sh[k + 1];
    veic.push({ id: 'd' + i, x: a[0] + (b[0] - a[0]) * f, y: a[1] + (b[1] - a[1]) * f,
                angle: (Math.atan2(b[0] - a[0], b[1] - a[1]) * 180 / Math.PI + 360) % 360,
                speed: i % 3 === 0 ? 0 : 1.4 });
  }
  const heat = {};
  lanes.forEach((ln, i) => { heat[ln.id] = (i * 3) % 9; });
  const tls = rede.tls.map((tl, i) => ({
    id: tl.id,
    state: ((i + Math.floor(t)) % 2 ? 'G' : 'r').repeat(Math.max(1, tl.links.length)),
  }));
  return { type: 'frame', braco, status: 'ok', t, janela, decision: Math.floor(t),
           substep: 0, policy: braco, tls, vehicles: veic, heat,
           stats: { entregues: 40, ativos: n, tempo_medio_entregue: 63, fila_media: 12.4 } };
}

function demo(qual) {
  const q = new URLSearchParams(location.search);
  const n = parseInt(q.get('carros') || '180', 10) || 180;
  const J = [300, 420];
  const FIM = ['resultado', 'nao_pareada', 'empate', 'sem_placar'];
  const frac = FIM.includes(qual) ? 1 : (qual === 'jogando' ? 0.6 : 0);
  const linhas = DEMO_LINHAS.map(l => ({ ...l, entregues: Math.round(l.entregues * frac) }));
  const pl = (fase, extra = {}) => ({
    tipo: 'placar', fase, t: J[0] + (J[1] - J[0]) * frac,
    t_restante: (1 - frac) * (J[1] - J[0]), chave: {
      cenario: rede.cenario, seed: 100, janela: J, demanda: '9f2c1ab77e04',
    }, linhas, ...extra,
  });
  ultimaMsgMs = performance.now();
  document.documentElement.dataset.live = '1';       // a foto não é da tela de espera
  if (qual === 'denuncia') {
    // A ARMADILHA (b) em imagem: dois braços em janelas diferentes.
    recebe(demoFrame('timer', 372, n, J));
    recebe(demoFrame('rl', 372, n, [300, 900]));
    recebe(pl('jogando'));
    return;
  }
  if (qual === 'ocioso') {
    // Sem mensagem `placar`: no ocioso de verdade ela não existe, e as linhas saem dos
    // `stats` que a Arena já mede. O demo faz igual para a foto não mentir.
    recebe({ ...demoFrame('rl', 372, n, J), stats: { entregues: 93, ativos: n, tempo_medio_entregue: 68, fila_media: 14.1 } });
    recebe({ ...demoFrame('timer', 372, n, J), stats: { entregues: 111, ativos: n, tempo_medio_entregue: 63, fila_media: 12.4 } });
  } else if (qual === 'preparando') {
    // `linhas: []` porque é o que o motor publica em PREPARANDO e em CONTAGEM
    // (`_placar(fase, t, {}, None)`): ainda não há fantasma carregado nem humano
    // correndo, e uma linha com zero seria número inventado.
    recebe({ ...pl('preparando'), linhas: [] });
  } else if (qual === 'contagem') {
    recebe(demoFrame('humano', 300, n, J));
    recebe({ ...pl('contagem'), linhas: [], t_restante: 2 });
  } else if (qual === 'jogando') {
    recebe(demoFrame('humano', 371, n, J));
    recebe(demoFrame('humano', 372, n, J));
    recebe(pl('jogando'));
  } else if (qual === 'resultado') {
    recebe(pl('resultado', { vencedor: 'timer' }));
  } else if (qual === 'nao_pareada') {
    // `pareado: false` — os braços partiram de estados diferentes em t0. A tela não
    // pode coroar ninguém NEM ordenar: é a denúncia inteira que aparece.
    recebe(pl('resultado', {
      vencedor: null, pareado: false,
      motivo: 'selo de t0 divergente (humano=8f3a1c2e… fantasmas={timer: 8f3a1c2e…, '
            + 'rl: b71d40aa…}): a rodada não é pareada e o vencedor fica em branco',
    }));
  } else if (qual === 'empate') {
    recebe(pl('resultado', {
      vencedor: null,
      linhas: linhas.map(l => ({ ...l, entregues: 104 })),
    }));
  } else if (qual === 'sem_placar') {
    // Abortada pelo operador: não há linha do humano. Não é empate — ninguém empatou.
    recebe(pl('resultado', {
      vencedor: null, motivo: 'abortada pelo operador',
      linhas: linhas.filter(l => l.braco !== 'humano'),
    }));
  } else if (qual === 'degradado') {
    recebe(demoFrame('rl', 372, n, J));
    cai('o jogo parou de publicar (demonstracao)');
  }
}

// ---------------------------------------------------------------------- bench
// DoD (b): 180+ carros a 1 Hz sem perder quadro, MEDIDO NO NOTEBOOK DA FEIRA. Só o
// dono pode rodar isto no notebook certo com o projetor certo, então o medidor mora
// aqui: `?bench=250` sintetiza N carros andando na rede real, empurra um frame por
// segundo pelo MESMO caminho de um frame do WS, e mostra o percentil do tempo de
// quadro. Não é simulação de tráfego: é carga de RENDER, que é o que a DoD cobra.
function bench(n) {
  document.documentElement.dataset.fase = 'jogando';
  document.documentElement.dataset.diag = '1';
  st.diag = true;
  const lanes = rede.lanes;
  const carros = [];
  for (let i = 0; i < n; i++) {
    const ln = lanes[i % lanes.length];
    carros.push({ ln, u: Math.random(), v: 0.4 + Math.random() * 1.4 });
  }
  const pontoEm = (ln, u) => {
    const sh = ln.shape;
    const k = Math.min(sh.length - 2, Math.floor(u * (sh.length - 1)));
    const f = u * (sh.length - 1) - k;
    const a = sh[k], b = sh[k + 1];
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f,
            (Math.atan2(b[0] - a[0], b[1] - a[1]) * 180 / Math.PI + 360) % 360];
  };
  let t = 0;
  const emite = () => {
    t += 1;
    const veic = carros.map((c, i) => {
      c.u = (c.u + c.v * 0.02) % 1;
      const [x, y, ang] = pontoEm(c.ln, c.u);
      return { id: 'b' + i, x, y, angle: ang, speed: c.v };
    });
    const heat = {};
    for (let i = 0; i < lanes.length; i += 3) heat[lanes[i].id] = (i % 11);
    const tls = rede.tls.map(tl => ({
      id: tl.id, state: 'G'.repeat(Math.max(1, tl.links.length)),
    }));
    recebe({ type: 'frame', braco: 'humano', status: 'ok', t, janela: [300, 420],
             decision: t, substep: 0, policy: 'bench', tls, vehicles: veic, heat,
             stats: { entregues: t * 2, ativos: n, tempo_medio_entregue: 40, fila_media: 9 } });
    recebe({ tipo: 'placar', fase: 'jogando', t, t_restante: 120 - t,
             chave: { cenario: rede.cenario, seed: 0, janela: [300, 420], demanda: 'bench' },
             linhas: [
               { braco: 'timer', rotulo: 'TIMER FIXO', entregues: Math.round(t * 1.8), fila: 11, tempo_medio: 55, fantasma: true },
               { braco: 'rl', rotulo: 'REDE NEURAL', entregues: Math.round(t * 1.9), fila: 9, tempo_medio: 50, fantasma: true },
               { braco: 'humano', rotulo: 'VOCÊ', entregues: t * 2, fila: 8, tempo_medio: 48, fantasma: false },
             ] });
  };
  emite(); emite();
  setInterval(emite, 1000);
  garanteLaco();
  // Publica o resultado num lugar que um browser headless consegue ler com --dump-dom.
  window.__bench = tele;
  setInterval(() => {
    const a = [...tele.amostras].sort((x, y) => x - y);
    if (!a.length) return;
    const p = q => a[Math.min(a.length - 1, Math.floor(a.length * q))];
    const b = boards[bracoDoMapa()];
    const dados = {
      carros: n, quadros_render: tele.desenhados,
      ms_p50: +p(0.5).toFixed(2), ms_p95: +p(0.95).toFixed(2),
      ms_max: +a[a.length - 1].toFixed(2),
      fps_p50: +(1000 / p(0.5)).toFixed(1),
      fps_p05: +(1000 / p(0.95)).toFixed(1),
      buracos_no_t: tele.gaps, fora_de_ordem: tele.fora,
      palco: [SW, SH], dpr,
      sprite_px: b && b.sprite ? [+b.sprite.corpo.toFixed(2), +b.sprite.largura.toFixed(2)] : null,
      sprite_arcmin: b && b.sprite ? [+arcmin(b.sprite.corpo).toFixed(1), +arcmin(b.sprite.largura).toFixed(1)] : null,
      sprite_excede_pegada: b ? !!b.spriteExcede : null,
      ua: navigator.userAgent,
    };
    const el = $('bench-out');
    if (el) el.textContent = JSON.stringify(dados, null, 1);
    // Manda para o servidor: o número da DoD (b) tem que sair do notebook da feira, e
    // ninguém deve transcrevê-lo à mão de uma tela projetada.
    if (tele.desenhados > 30) {
      fetch('/api/bench', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(dados) }).catch(() => {});
    }
  }, 500);
}

iniciar();
