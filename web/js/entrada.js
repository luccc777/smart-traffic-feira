// entrada.js — o TECLADO JUNTO DO PROJETOR, lido pela página projetada.
//
// Os recursos da feira são um notebook, um projetor no chão e um teclado. O visitante
// digita o próprio apelido e joga olhando para o chão — então o foco tem de estar na
// página projetada, e quem recebe as teclas é o NAVEGADOR. Este módulo é o lado da
// página da `FonteWeb` (`feira/entrada/web.py`): captura `keydown`, decide o que cada
// tecla significa e manda para o servidor por um WebSocket `/entrada`. O feedback (os
// 12 LEDs) volta pelo `/ws` normal, junto de tudo o mais, e é desenhado aqui sobre os
// cruzamentos: o painel da botoeira, projetado para a plateia.
//
// DOIS MODOS, E A DECISÃO É UMA FUNÇÃO PURA (`reduzEntrada`), testável sem navegador:
//
//   NOME  (fase `ocioso`, campo aberto)  letras/dígitos viram texto, ENTER confirma,
//         Backspace apaga, Escape limpa. NENHUMA tecla vira botão nem START enquanto
//         o campo está aberto — por construção, não por filtro: o servidor nunca vê
//         letra de nome. ESPAÇO com o campo VAZIO começa a rodada sem nome
//         (`Visitante N`); com texto digitado, é ignorado (apelido não tem espaço).
//   JOGO  (qualquer outra situação)  `q w e r / a s d f / z x c v` viram botão,
//         ESPAÇO vira START, Escape vira ABORTAR (o servidor só aborta se o
//         operador ligou esse modo; a página não pergunta — é o operador que aperta).
//
// SÓ LIGA QUANDO O SERVIDOR DIZ (`entrada_web: true` no status). Sem isso a página
// não captura tecla nenhuma e se comporta exatamente como antes — as teclas do
// operador (`H`, `G`, `I`, `F`...) continuam com o `projecao.js`. Com a entrada ligada,
// as teclas do JOGO ganham das do operador (`d`, `v`, `r`, `f` são botões): o listener
// mora na fase de CAPTURA e para a propagação do que consumiu. Com Ctrl/Alt a tecla
// passa direto, para o operador ainda alcançar as dele.
//
// A LINGUAGEM DA PLACA (pedido do dono, 2026-09-14: "vendo de fora não sei o porquê
// daquelas cores"). Cada cruzamento tem uma placa com a letra do botão, e a placa fala
// a MESMA língua do farol que está embaixo dela — verde/amarelo/vermelho da paleta
// auditada — em cinco estados (`estadoDaPlaca`, função pura):
//
//   LIVRE      placa escura, letra branca. Pode apertar.
//   BLOQUEADO  o farol acabou de trocar (está no amarelo, ou o verde tem menos que o
//              verde mínimo): a placa escurece e um ANEL ESVAZIA, com os segundos que
//              faltam. É a resposta a "apertar várias vezes para abrir mais rápido":
//              a pessoa VÊ que está travado, e por quanto tempo. É estimativa da
//              página (`observaTls`/`faltaParaTrocar`), a partir do estado do farol
//              nos frames; quem decide é o servidor, no tick.
//   PEDIDO     apertou: placa AMARELA (transição pedida) com um ANEL ENCHENDO até o
//              próximo tick da grade — a "bolinha de carregamento".
//   TROCOU     o tick aceitou: placa VERDE por 1,2 s, depois volta ao calculado.
//   NEGADO     o tick recusou (cedo demais): placa VERMELHA piscando "CEDO" por 1,2 s,
//              depois cai para BLOQUEADO com o anel e os segundos.
//
// O servidor deixa `on`/`deny` acesos até o tick seguinte (5 s simulados); a DURAÇÃO
// VISUAL é da página, porque 5 s de placa verde lê como "travou no verde".

const LETRAS = ['q', 'w', 'e', 'r', 'a', 's', 'd', 'f', 'z', 'x', 'c', 'v'];
export const MAPA_TECLAS = Object.fromEntries(LETRAS.map((k, i) => [k, i]));
export const NOME_MAX = 12;
export const ESC_VEZES = 3;          // Esc 3x em 1,5 s = abortar (só o operador faz isso de propósito)
export const ESC_JANELA_MS = 1500;
const RECONECTA_MS = 800;

// A grade da RL, em segundos SIMULADOS (`RESTRICOES_ABERTA`: di5/vm7/am3). O servidor
// manda a dele em `grade` no status; isto é o fallback para servidor antigo.
export const GRADE_PADRAO = { di: 5, min_green: 7, yellow: 3 };

// Durações VISUAIS, em ms de parede — são da página, não do jogo.
export const MOSTRA_MS = 1200;        // quanto TROCOU/NEGADO ficam na tela
export const PULSO_MS = 150;          // a borda engrossa ao ver a tecla de novo
export const DEBOUNCE_TECLA_MS = 120; // 1 mensagem por tecla por 120 ms
export const DEBOUNCE_START_MS = 500; // o botão grande, mais folgado

// ------------------------------------------------------------------ o redutor
export function estadoInicial(fase = 'ocioso') {
  return { fase, campo: fase === 'ocioso', nome: '', confirmado: false };
}

// Uma letra "de nome": letra (com acento), dígito. Sem espaço, sem pontuação — a
// fonte do projetor não tem glifo para tudo, e nome que vira caixa vazia na tela é
// pior que nome cortado (é a mesma regra de `normaliza_nome` no servidor).
const DE_NOME = /^[\p{L}\p{N}]$/u;

/**
 * `(estado, tecla) -> { estado, acoes }`. `tecla` é `KeyboardEvent.key`.
 *
 * `acoes` é o que sai da página: `{tipo:'tecla',k}` / `{tipo:'start'}` /
 * `{tipo:'abortar'}` vão para o WS `/entrada`; `{tipo:'nome', nome}` vai por
 * `POST /api/jogador`. `consumida` diz se a tecla foi do jogo (e não deve chegar ao
 * operador).
 */
export function reduzEntrada(estado, tecla, agora = 0) {
  const k = String(tecla || '');
  const kl = k.toLowerCase();
  const e = { ...estado };
  const acoes = [];
  if (e.campo) {
    if (k === 'Enter') {
      if (e.nome) {
        acoes.push({ tipo: 'nome', nome: e.nome });
        e.campo = false;
        e.confirmado = true;
      }
      return { estado: e, acoes, consumida: true };
    }
    if (k === 'Escape') { e.nome = ''; return { estado: e, acoes, consumida: true }; }
    if (k === 'Backspace') { e.nome = e.nome.slice(0, -1); return { estado: e, acoes, consumida: true }; }
    if (k === ' ') {
      if (!e.nome) acoes.push({ tipo: 'start' });
      return { estado: e, acoes, consumida: true };
    }
    if (DE_NOME.test(k)) {
      if (e.nome.length < NOME_MAX) e.nome += k.toUpperCase();
      return { estado: e, acoes, consumida: true };
    }
    // setas, F-keys, sinais: não são do jogo nem do nome — passam ao operador
    return { estado: e, acoes, consumida: false };
  }
  if (kl in MAPA_TECLAS) { acoes.push({ tipo: 'tecla', k: kl }); return { estado: e, acoes, consumida: true }; }
  if (k === ' ') { acoes.push({ tipo: 'start' }); return { estado: e, acoes, consumida: true }; }
  if (k === 'Escape') {
    // ABORTAR é do operador, mas o teclado é o MESMO do visitante — e Esc é a tecla
    // que todo mundo aperta por reflexo (sair da tela cheia, "cancelar"). Um Esc
    // sozinho não faz nada; três em 1,5 s abortam. Deliberado, nunca por acidente.
    const escs = (estado.escs || []).filter(t => agora - t < ESC_JANELA_MS).concat(agora);
    if (escs.length >= ESC_VEZES) {
      e.escs = [];
      acoes.push({ tipo: 'abortar' });
    } else {
      e.escs = escs;
    }
    return { estado: e, acoes, consumida: true };
  }
  return { estado: e, acoes, consumida: false };
}

/** A fase da rodada mudou. Voltar ao `ocioso` REABRE o campo, vazio. */
export function aoMudarFase(estado, fase) {
  const e = { ...estado, fase };
  if (fase === 'ocioso' && estado.fase !== 'ocioso') {
    e.campo = true; e.nome = ''; e.confirmado = false;
  } else if (fase !== 'ocioso') {
    e.campo = false;
  }
  return e;
}

// ------------------------------------------------------------------ anti-spam
/**
 * Tecla SEGURADA gera `keydown` repetido (`ev.repeat`). No jogo isso é o visitante
 * "apertando várias vezes para abrir mais rápido" em versão automática — e não
 * adianta: a intenção é um booleano por tick no servidor. Ignorar aqui poupa o fio e,
 * mais importante, poupa a placa de piscar sem motivo. No modo nome o repeat só vale
 * para Backspace (segurar para apagar é o gesto que todo mundo espera).
 */
export function aceitaEvento(estado, ev) {
  if (!ev || !ev.repeat) return true;
  return !!(estado && estado.campo && ev.key === 'Backspace');
}

/**
 * O teclado é UM SÓ, e é do visitante. Os atalhos do OPERADOR (`h` esconde o placar,
 * `g` apaga o asfalto, `r` gira o mapa, `f` tela cheia, `v`/`d`/`t`/`i` modos de
 * desenho) moram nas mesmas letras que o jogo e o nome. Com a entrada web ligada,
 * um visitante que aperta `g` e `h` no meio da rodada apaga as ruas e a tarja — e
 * a página ainda GRAVA isso no localStorage, então o estrago sobrevive ao F5
 * (aconteceu: 2026-09-14, "quebrou a simulação"). Regra: com a entrada ligada, o
 * atalho do operador exige `Ctrl+Alt`; sem entrada (bancada, fotos), continua a
 * tecla solta de sempre.
 */
export function passaAoOperador(ev, entradaLigada) {
  if (!ev) return false;
  if (!entradaLigada) return true;
  return !!(ev.ctrlKey && ev.altKey);
}

/**
 * O que a PLATEIA tem que ver, sempre: placar, asfalto e a pegada dos carros; nada
 * de diagnóstico, grade ou "modo verdade". Aplicado ao ligar a entrada web — o
 * localStorage pode ter guardado um estado de bancada, ou o estrago de um
 * visitante em outra sessão.
 */
export const PLATEIA = { hud: true, asfalto: true, pegada: true, verdade: false, grade: false, diag: false };

/**
 * Debounce por tecla, puro: `(memo, acao, agoraMs) -> { envia, memo }`.
 *
 * Duas mensagens `tecla:q` em menos de `DEBOUNCE_TECLA_MS` são a mesma intenção (o
 * servidor já as trataria como uma; aqui nem saem). START tem a folga maior porque
 * ele tem consequência — e o visitante que martela o botão grande no `ocioso` só
 * quer começar uma vez.
 */
export function filtraSpam(memo, acao, agoraMs) {
  const m = { ...(memo || {}) };
  if (!acao) return { envia: false, memo: m };
  let chave = null, janela = 0;
  if (acao.tipo === 'tecla') { chave = 'k:' + acao.k; janela = DEBOUNCE_TECLA_MS; }
  else if (acao.tipo === 'start') { chave = 'start'; janela = DEBOUNCE_START_MS; }
  if (chave === null) return { envia: true, memo: m };
  const ultima = m[chave];
  if (ultima != null && agoraMs - ultima < janela) return { envia: false, memo: m };
  m[chave] = agoraMs;
  return { envia: true, memo: m };
}

// ------------------------------------------------------------------ o texto
/** O que a faixa do `ocioso` mostra, a partir do estado + o que o servidor sabe. */
export function textoOcioso(estado, jogador, proxima) {
  const linhas = { convite: '', sub: '', nivel: '' };
  if (estado.campo) {
    linhas.convite = `QUAL O SEU APELIDO?  ${estado.nome}`;
    // A SEQUÊNCIA INTEIRA, em toda linha. Quem chega no meio da fila não viu o passo
    // anterior: dizer só "ENTER confirma" deixa a pessoa no campo confirmado sem saber
    // que ainda falta o ESPAÇO. As duas linhas terminam no mesmo lugar.
    linhas.sub = estado.nome
      ? 'ENTER confirma → depois ESPAÇO para jogar · Backspace apaga'
      : `DIGITE O NOME → ENTER → ESPAÇO · ou só ESPAÇO, como ${(jogador && jogador.anonimo) || 'Visitante'}`;
  } else {
    const nome = (jogador && jogador.nome) || estado.nome || (jogador && jogador.anonimo) || '';
    linhas.convite = `${nome ? nome + ' · ' : ''}APERTE ESPAÇO PARA COMEÇAR`;
    linhas.sub = '12 semáforos · 120 segundos · a mesma hora de trânsito para os três';
  }
  if (proxima && proxima.seed != null) {
    linhas.nivel = `HORA DE TRÂNSITO ${proxima.seed} · NÍVEL ${proxima.rotulo || '—'}`;
    if (proxima.hoje) {
      linhas.nivel += ` · hoje ${proxima.hoje.bateram} de ${proxima.hoje.jogaram} bateram a IA`;
    }
  }
  return linhas;
}

/** A legenda das placas, uma linha, para o `ocioso` com a entrada web ligada. */
export const LEGENDA = [
  { cor: 'amarelo', texto: 'pedido registrado — vale no próximo ciclo' },
  { cor: 'verde', texto: 'trocou' },
  { cor: 'vermelho', texto: 'descartado: cedo demais — placa apagada = espere o anel' },
];

// ------------------------------------------------------------------ o bloqueio
/**
 * O estimador de BLOQUEIO, a partir do que o farol mostra nos frames.
 *
 * `hist[id] = { state, tMudanca }`: o estado SUMO do farol e o `t` simulado em que
 * ele mudou pela última vez. `observaTls(hist, tls, t)` devolve o histórico novo —
 * puro, um frame de cada vez. `tls` aceita o array do frame (`[{id, state}]`) ou o
 * mapa `{id: state}` do interpolador.
 */
export function observaTls(hist, tls, t) {
  const h = { ...(hist || {}) };
  const pares = Array.isArray(tls) ? tls.map(x => [x.id, x.state]) : Object.entries(tls || {});
  for (const [id, state] of pares) {
    const ant = h[id];
    if (!ant || ant.state !== state) h[id] = { state, tMudanca: +t };
  }
  return h;
}

/**
 * Quanto falta (em s SIMULADOS) para o farol `id` poder trocar. A regra é a do
 * `pode_trocar` da Arena: não está no amarelo E o verde atual já dura `min_green`.
 *
 * Devolve `{ bloqueado, faltam, total }`; `total` é o tamanho da espera inteira (para
 * o anel esvaziar proporcionalmente): `yellow + min_green` se pegou o amarelo,
 * `min_green` se pegou o verde nascendo. Sem histórico do farol: LIVRE — a página não
 * inventa bloqueio que não viu.
 */
export function faltaParaTrocar(entrada, t, grade = GRADE_PADRAO) {
  const g = { ...GRADE_PADRAO, ...(grade || {}) };
  if (!entrada || entrada.tMudanca == null) return { bloqueado: false, faltam: 0, total: 0, amarelo: false };
  const desde = Math.max(0, +t - entrada.tMudanca);
  const amarelo = /y/i.test(entrada.state || '');
  if (amarelo) {
    const total = g.yellow + g.min_green;
    return { bloqueado: true, faltam: Math.max(0, total - desde), total, amarelo: true };
  }
  const faltam = Math.max(0, g.min_green - desde);
  return { bloqueado: faltam > 0, faltam, total: g.min_green, amarelo: false };
}

// ------------------------------------------------------------------ a placa
/**
 * O estado VISUAL da placa, puro: `{ estado, fracao, segundos, pisca }`.
 *
 *   led         'off' | 'armed' | 'on' | 'deny'   (o último quadro `leds` deste farol)
 *   tLed        ms de parede em que esse led foi visto pela primeira vez
 *   agora       ms de parede
 *   bloqueio    `faltaParaTrocar(...)` deste farol, ou null
 *   proximoTick ms de parede do próximo tick da grade (null = ainda não se sabe)
 *   tickMs      período do tick em parede (di / ritmo, em ms)
 *   ritmo       s simulados por s de parede (para converter `faltam`)
 *
 * `fracao` é o preenchimento do anel: ENCHENDO no PEDIDO (0 → 1 até o tick),
 * ESVAZIANDO no BLOQUEADO (1 → 0 até liberar). `null` = spinner indeterminado.
 */
export function estadoDaPlaca({ led = 'off', tLed = 0, agora = 0, bloqueio = null,
                                proximoTick = null, tickMs = 5000, ritmo = 1 } = {}) {
  const r = ritmo > 0 ? ritmo : 1;
  const seg = b => (b && b.bloqueado) ? Math.max(1, Math.ceil(b.faltam / r)) : null;
  const idade = agora - (tLed || 0);
  if (led === 'on' && idade < MOSTRA_MS) {
    return { estado: 'trocou', fracao: 1 - idade / MOSTRA_MS, segundos: null, pisca: false };
  }
  if (led === 'deny' && idade < MOSTRA_MS) {
    // duas piscadas em 1,2 s: aceso nos terços 1 e 3. `progresso` (0..1) é o relógio
    // da animação de DESCARTE: o anel do pedido se desfaz, a placa treme e um X cruza
    // a letra — a pessoa tem que ver que AQUELE aperto morreu e precisa apertar de novo.
    const pisca = Math.floor(idade / (MOSTRA_MS / 4)) % 2 === 0;
    return { estado: 'negado', fracao: null, segundos: seg(bloqueio), pisca,
             progresso: Math.min(1, Math.max(0, idade / MOSTRA_MS)) };
  }
  if (led === 'armed') {
    // O anel enche até o TICK — o instante exato em que a intenção é julgada — e a
    // pílula conta os segundos até lá. `cedo` avisa que, pelo farol que a tela
    // mostra, o tick vai chegar antes de o bloqueio acabar: o pedido vai ser negado.
    let fracao = null, ateTick = null;
    if (proximoTick != null && tickMs > 0) {
      fracao = Math.min(1, Math.max(0, 1 - (proximoTick - agora) / tickMs));
      ateTick = Math.max(0, (proximoTick - agora) / 1000);
    }
    const bloq = seg(bloqueio);
    const cedo = bloq != null && ateTick != null && bloq > ateTick + 0.5;
    return { estado: 'pedido', fracao, pisca: false, cedo,
             segundos: ateTick == null ? null : Math.max(1, Math.ceil(ateTick)) };
  }
  if (bloqueio && bloqueio.bloqueado) {
    const fracao = bloqueio.total > 0 ? Math.min(1, Math.max(0, bloqueio.faltam / bloqueio.total)) : 0;
    return { estado: 'bloqueado', fracao, segundos: seg(bloqueio), pisca: false,
             amarelo: !!bloqueio.amarelo };
  }
  return { estado: 'livre', fracao: null, segundos: null, pisca: false };
}

/**
 * O painel: guarda o último `leds`, QUANDO cada LED mudou (para a duração visual),
 * os pulsos de tecla e o relógio dos ticks. Sem DOM, sem canvas — só o tempo que o
 * chamador passa.
 *
 * O TICK é detectado, não suposto: uma mensagem `leds` em que algum farol passa a
 * `on`/`deny` é um tick (é só ali que o servidor decide). Os ticks são periódicos em
 * parede (`di / ritmo`), então o próximo é o último mais o período — e enquanto não
 * houve nenhum, o anel do PEDIDO gira sem número (spinner).
 */
export class PainelLeds {
  /**
   * `atrasoMs`: quanto a placa deve ATRASAR o que o servidor decidiu no tick, para
   * coincidir com o farol que o mapa está mostrando. O mapa anda `DELAY` s simulados
   * atrás do frame mais novo (render-delay do `interp.js`); a mensagem `leds` do tick
   * chega na hora. Sem o atraso a placa fica verde e o farol só amarela ~1 s depois —
   * era o "demora mais um pouco, aí sim começa o amarelo" que o dono viu.
   *
   * O que é do VISITANTE (o `armed` do aperto, o pulso) aparece na hora: é a mão
   * dele, não o mundo. O que é do TICK (on/deny/off e o relógio) espera o atraso.
   */
  constructor(n = 12, { atrasoMs = 0 } = {}) {
    this.n = n;
    this.atrasoMs = Math.max(0, +atrasoMs || 0);
    this.estados = new Array(n).fill('off');
    this.tLed = new Array(n).fill(0);
    this.tArmado = new Array(n).fill(-1e9);   // quando a pessoa apertou pela última vez
    this.pulsos = new Array(n).fill(-1e9);
    this.pendentes = [];                       // quadros de tick esperando o atraso
    this.ultimoTick = null;
    this.tTick = null;                         // t simulado do último tick anunciado
    this.ticks = 0;
    this.start = 'off';
  }

  /** É um quadro de TICK? Anunciado (`tick: true`), ou — servidor antigo — algum
   *  farol passando a on/deny, que só acontece no tick. */
  _eTick(msg) {
    if (msg.tick) return true;
    for (let i = 0; i < this.n; i++) {
      const novo = msg.estados[i] || 'off';
      if ((novo === 'on' || novo === 'deny') && novo !== this.estados[i]) return true;
    }
    return false;
  }

  recebe(msg, agoraMs) {
    if (!msg || !msg.estados) return;
    if (this._eTick(msg)) {
      this.pendentes.push({ msg, chegouEm: agoraMs, aplicaEm: agoraMs + this.atrasoMs });
      this.avanca(agoraMs);
      return;
    }
    // quadro de APERTO (armed) ou de limpeza fora do tick: vale agora
    for (let i = 0; i < this.n; i++) {
      const novo = msg.estados[i] || 'off';
      if (novo === 'armed') this.tArmado[i] = agoraMs;
      if (novo !== this.estados[i]) { this.estados[i] = novo; this.tLed[i] = agoraMs; }
    }
    if (msg.start) this.start = msg.start;
  }

  /** Aplica os quadros de tick cujo atraso já passou. */
  avanca(agoraMs) {
    while (this.pendentes.length && this.pendentes[0].aplicaEm <= agoraMs) {
      const { msg, chegouEm, aplicaEm } = this.pendentes.shift();
      for (let i = 0; i < this.n; i++) {
        const novo = msg.estados[i] || 'off';
        // a pessoa apertou DEPOIS deste tick: o pedido dela vale mais que o
        // resultado atrasado do tick anterior
        if (this.estados[i] === 'armed' && this.tArmado[i] > chegouEm) continue;
        if (novo !== this.estados[i]) { this.estados[i] = novo; this.tLed[i] = aplicaEm; }
      }
      if (msg.start) this.start = msg.start;
      this.ultimoTick = aplicaEm;
      this.ticks++;
      if (msg.t != null) this.tTick = +msg.t;
    }
  }

  pulsa(i, agoraMs) { if (i >= 0 && i < this.n) this.pulsos[i] = agoraMs; }

  proximoTick(agoraMs, tickMs) {
    if (this.ultimoTick == null || !(tickMs > 0)) return null;
    let p = this.ultimoTick + tickMs;
    while (p < agoraMs) p += tickMs;
    return p;
  }

  /** O estado visual do farol `i` agora. `bloqueio` vem de `faltaParaTrocar`. */
  estado(i, agoraMs, { bloqueio = null, tickMs = 5000, ritmo = 1 } = {}) {
    this.avanca(agoraMs);
    return {
      ...estadoDaPlaca({ led: this.estados[i], tLed: this.tLed[i], agora: agoraMs, bloqueio,
                         proximoTick: this.proximoTick(agoraMs, tickMs), tickMs, ritmo }),
      pulso: agoraMs - this.pulsos[i] < PULSO_MS,
    };
  }
}

// ------------------------------------------------------------------ o desenho
// Posição de cada semáforo na tela: o índice do LED é o índice em `rede.tls`, que o
// servidor entrega ORDENADO por id (`H1V1..H3V4`, linha a linha — a mesma ordem de
// `tls_ids` e do painel 3x4). O centro vem da junção de mesmo id.
export function centrosDosTls(rede, board) {
  if (!rede || !board || !board.T) return [];
  const ids = rede.tls.map(t => t.id).sort();
  return ids.map((id, i) => {
    const j = rede.junctions.find(x => x.id === id);
    if (!j) return null;
    return { i, id, x: board.T.X(j.center[0]), y: board.T.Y(j.center[1]) };
  }).filter(Boolean);
}

// Cores da paleta auditada (`scripts/projecao_contraste.py` / `paint.js::COL`): as
// TRÊS do farol, para a placa falar a língua do sinal que está embaixo dela; `off` é a
// cor do farol apagado, `borda`/`placa` os pretos de separação. Nada novo aqui.
const COR = {
  verde: '#2bea88', amarelo: '#ffd23d', vermelho: '#ff5245', off: '#55637a',
  borda: 'rgba(3,7,13,.88)', placa: 'rgba(6,10,16,.86)', texto: '#ffffff',
};

function anel(ctx, x, y, r, fracao, cor, lw, nowMs) {
  ctx.beginPath();
  if (fracao == null) {
    // spinner: um quarto de volta girando — "esperando o próximo ciclo"
    const a0 = (nowMs / 400) % (Math.PI * 2);
    ctx.arc(x, y, r, a0, a0 + Math.PI / 2);
  } else {
    ctx.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * fracao);
  }
  ctx.lineWidth = lw;
  ctx.strokeStyle = cor;
  ctx.lineCap = 'round';
  ctx.stroke();
}

function pilula(ctx, x, y, texto, f, fundo, cor) {
  const w = texto.length * f * 0.66 + f * 0.6, h = f * 1.25;
  ctx.fillStyle = fundo;
  ctx.beginPath();
  ctx.roundRect(x - w / 2, y - h / 2, w, h, h / 2);
  ctx.fill();
  ctx.fillStyle = cor;
  ctx.fillText(texto, x, y + f * 0.05);
}

/**
 * A PLACA de cada cruzamento: a letra do botão, sempre, e o estado por cima.
 *
 * A tecla fica escrita NO PRÓPRIO SINAL, em todas as fases, para o visitante se
 * localizar — quem olha para o chão e vê a fila crescer no cruzamento de cima à
 * direita precisa ler ali "R". No `ocioso` (`painel` null) é só o manual; na rodada,
 * a placa mostra o estado do `PainelLeds` na língua do farol (cabeçalho do módulo).
 *
 * `bloqueioDe(i)` devolve o `faltaParaTrocar` do farol `i` (ou null); `tickMs` e
 * `ritmo` convertem tempo simulado em parede. Luz contida (PROJECAO.md §3.6): placa
 * escura, anel fino, nada de halo.
 */
export function pintaTeclas(ctx, centros, U = 1, painel = null, nowMs = 0,
                            { bloqueioDe = null, tickMs = 5000, ritmo = 1 } = {}) {
  const f = Math.max(14, 26 * U);
  const fp = Math.max(10, 13 * U);              // a pílula dos segundos / "CEDO"
  ctx.save();
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const c of centros) {
    const letra = (LETRAS[c.i] || '?').toUpperCase();
    const w = f * 1.5, h = f * 1.35;
    const rAnel = Math.max(w, h) * 0.78;
    let v = { estado: 'livre', fracao: null, segundos: null, pisca: false, pulso: false };
    if (painel) {
      const bloqueio = bloqueioDe ? bloqueioDe(c.i, c.id) : null;
      v = painel.estado(c.i, nowMs, { bloqueio, tickMs, ritmo });
    }
    let fundo = COR.placa, borda = COR.off, texto = COR.texto, alfaTexto = 1;
    let lw = 1.5, corAnel = null, fracao = null, rotulo = null;
    // `alfa` é a opacidade da PLACA INTEIRA: bloqueado fica translúcido — "não dá
    // para apertar agora" tem que se ver de longe, antes de a pessoa tentar.
    let alfa = 1, dx = 0, xis = 0;
    switch (v.estado) {
      case 'bloqueado':
        alfa = 0.38; corAnel = COR.off; fracao = v.fracao; lw = 1.5;
        // no amarelo a placa DIZ que é o amarelo: é a transição que a pessoa pediu
        // acontecendo, não uma demora sem nome
        rotulo = v.segundos != null ? (v.amarelo ? `AMARELO ${v.segundos}s` : `${v.segundos}s`) : null;
        break;
      case 'pedido':
        fundo = COR.amarelo; borda = COR.amarelo; texto = COR.borda; lw = 2.5;
        corAnel = COR.amarelo; fracao = v.fracao;
        // a pílula conta até o CICLO (o tick), que é quando o pedido é julgado; se o
        // farol ainda vai estar travado nessa hora, avisa antes — "CEDO" é previsão
        rotulo = v.segundos != null ? (v.cedo ? `CEDO · ${v.segundos}s` : `CICLO ${v.segundos}s`) : 'CICLO…';
        break;
      case 'trocou':
        fundo = COR.verde; borda = COR.verde; texto = COR.borda; lw = 2.5;
        break;
      case 'negado': {
        // A animação do DESCARTE, em três gestos sobre `progresso` (0..1 em 1,2 s):
        //  1. o anel do pedido, que estava enchendo, DESENROLA até zero no primeiro
        //     quarto — o carregamento foi jogado fora;
        //  2. a placa TREME (3 oscilações que morrem) e pisca em vermelho;
        //  3. um X cruza a letra e some no fim, quando a placa cai para BLOQUEADO
        //     translúcido com o anel de espera — "apertou cedo; espere isto".
        const p = v.progresso == null ? 0 : v.progresso;
        fundo = v.pisca ? COR.vermelho : COR.placa; borda = COR.vermelho; lw = 2.5;
        texto = v.pisca ? COR.borda : COR.texto;
        corAnel = COR.vermelho; fracao = Math.max(0, 1 - p / 0.25);
        dx = Math.sin(p * Math.PI * 6) * (1 - p) * w * 0.14;
        xis = p < 0.85 ? 1 : (1 - p) / 0.15;
        rotulo = 'DESCARTADO';
        break;
      }
      default:
        break;
    }
    if (v.pulso) lw += 2.5;                       // "vi a tecla" — e nada mais muda
    const cx = c.x + dx;
    // o anel: fora da placa, fino, na cor do estado
    if (corAnel && (fracao == null || fracao > 0)) {
      ctx.globalAlpha = 0.95 * alfa;
      anel(ctx, cx, c.y, rAnel, fracao, corAnel, Math.max(2, 3 * U), nowMs);
    }
    ctx.globalAlpha = alfa;
    ctx.fillStyle = fundo;
    ctx.beginPath();
    ctx.roundRect(cx - w / 2, c.y - h / 2, w, h, f * 0.22);
    ctx.fill();
    ctx.lineWidth = Math.max(1, lw * U);
    ctx.strokeStyle = borda;
    ctx.stroke();
    ctx.globalAlpha = alfaTexto * alfa;
    ctx.fillStyle = texto;
    ctx.font = `700 ${f}px "IBM Plex Mono", Consolas, monospace`;
    ctx.fillText(letra, cx, c.y + f * 0.04);
    if (xis > 0) {
      // o X do descarte: duas diagonais grossas, na cor da borda escura sobre o
      // vermelho (ou vermelho sobre a placa escura), cobrindo a letra
      ctx.globalAlpha = xis;
      ctx.strokeStyle = v.pisca ? COR.borda : COR.vermelho;
      ctx.lineWidth = Math.max(3, 4 * U);
      ctx.lineCap = 'round';
      const k = f * 0.42;
      ctx.beginPath();
      ctx.moveTo(cx - k, c.y - k); ctx.lineTo(cx + k, c.y + k);
      ctx.moveTo(cx + k, c.y - k); ctx.lineTo(cx - k, c.y + k);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    if (rotulo) {
      // a pílula fica ABAIXO do anel, para não cobrir a letra
      ctx.font = `700 ${fp}px "IBM Plex Mono", Consolas, monospace`;
      const corP = v.estado === 'negado' ? COR.vermelho : (v.estado === 'pedido' ? COR.amarelo : COR.texto);
      ctx.globalAlpha = v.estado === 'bloqueado' ? 0.85 : 1;
      pilula(ctx, cx, c.y + rAnel + fp * 0.9, rotulo, fp, COR.borda, corP);
      ctx.globalAlpha = 1;
    }
  }
  ctx.restore();
}

// ------------------------------------------------------------------ o fio
/**
 * A ligação viva: teclado -> redutor -> WS `/entrada` (+ POST do nome). Só existe
 * quando `entrada_web` é true; `liga()` é chamado uma vez pelo `projecao.js`.
 *
 * `aoTecla(i)` avisa que um botão foi apertado (para a placa pulsar), inclusive
 * quando o debounce não deixou a mensagem sair — a pessoa apertou, a placa responde.
 */
export class EntradaWeb {
  constructor({ aoMudar = () => {}, aoTecla = () => {}, fetchFn = (u, o) => fetch(u, o),
                agora = () => performance.now() } = {}) {
    this.estado = estadoInicial('ocioso');
    this.aoMudar = aoMudar;
    this.aoTecla = aoTecla;
    this.fetchFn = fetchFn;
    this.agora = agora;
    this.ws = null;
    this.ligada = false;
    this.enviadas = 0;
    this.perdidas = 0;
    this.descartadas = 0;              // repeat + debounce: teclas que não viraram fio
    this._memo = {};
    this._h = ev => this._tecla(ev);
  }

  liga() {
    if (this.ligada) return;
    this.ligada = true;
    window.addEventListener('keydown', this._h, true);       // CAPTURA: antes do operador
    this._conecta();
  }

  desliga() {
    if (!this.ligada) return;
    this.ligada = false;
    window.removeEventListener('keydown', this._h, true);
    try { if (this.ws) this.ws.close(); } catch (e) { /**/ }
    this.ws = null;
  }

  fase(f) {
    const antes = this.estado;
    this.estado = aoMudarFase(this.estado, f);
    if (antes.campo !== this.estado.campo || antes.nome !== this.estado.nome) this.aoMudar(this.estado);
  }

  _conecta() {
    if (!this.ligada) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/entrada`);
    this.ws = ws;
    ws.onclose = () => { if (this.ligada) setTimeout(() => this._conecta(), RECONECTA_MS); };
    ws.onerror = () => { try { ws.close(); } catch (e) { /**/ } };
  }

  _envia(msg) {
    if (this.ws && this.ws.readyState === 1) {
      this.ws.send(JSON.stringify(msg));
      this.enviadas++;
    } else {
      this.perdidas++;         // sem fio não há fila: a tecla de agora não vale depois
    }
  }

  _tecla(ev) {
    if (ev.ctrlKey || ev.altKey || ev.metaKey) return;       // as do operador passam
    if (!aceitaEvento(this.estado, ev)) {
      // tecla segurada: no jogo não vale nada — e não pode rolar a página nem, pior,
      // VAZAR para os atalhos do operador (um `r` segurado girava o mapa 90° a cada
      // repetição, um `f` segurado entrava e saía da tela cheia).
      ev.preventDefault();
      ev.stopImmediatePropagation();
      this.descartadas++;
      return;
    }
    const t = this.agora();
    const { estado, acoes, consumida } = reduzEntrada(this.estado, ev.key, t);
    const mudou = estado.nome !== this.estado.nome || estado.campo !== this.estado.campo;
    this.estado = estado;
    for (const a of acoes) {
      if (a.tipo === 'nome') {
        this.fetchFn('/api/jogador', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ nome: a.nome }),
        }).catch(() => {});
        continue;
      }
      if (a.tipo === 'tecla') this.aoTecla(MAPA_TECLAS[a.k], t);
      const { envia, memo } = filtraSpam(this._memo, a, t);
      this._memo = memo;
      if (envia) this._envia(a); else this.descartadas++;
    }
    if (consumida) {
      ev.preventDefault();               // espaço rola a página; as letras nunca devem vazar
      ev.stopImmediatePropagation();
    }
    if (mudou || acoes.length) this.aoMudar(this.estado);
  }
}
