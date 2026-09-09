// paint.js — o PINTOR do mapa da projeção da feira.
//
// PORTADO de `smart-traffic-maquete/dashboard/frontend/projecao/js/paint.js`
// (commit `18ea6dd`). A linguagem visual é de lá e os motivos dela também: fundo preto
// (projetor soma luz e nunca subtrai), acúmulo em duas dimensões (cor = gravidade,
// comprimento = quanto da via já foi tomada), anel de pressão por cruzamento, carro
// colorido pela velocidade, zero `shadowBlur` (halos pré-renderizados + bloom por
// segundo traço).
//
// O QUE MUDOU NESTE REPO, E POR QUÊ
// ---------------------------------
// 1. PEGADA EXATA. O `/api/network` do maquete não exportava `minGap` e o pintor
//    chutava `foot = 1,7 x comprimento`. O `/api/rede` daqui exporta `minGap`, e a
//    pegada passou a ser `length + minGap` — o número que o SUMO de fato reserva.
//
// 2. O SPRITE DO CARRO FOI RE-RESOLVIDO (ver docs/PROJECAO.md §3). A regra do maquete
//    era `D = max(7, laneW·s·1,15)` e `L = D·2,9`. Nesta rede ela produz um sprite
//    DUAS VEZES mais comprido que a pegada — e aí a condição `footPx > L·1,15` que
//    manda desenhar a pegada nunca dispara, a pegada some, e carros parados passam a
//    se sobrepor: a fila vira um borrão que não dá para contar. A regra aqui é:
//
//        extensão longitudinal desenhada  ==  PEGADA (length + minGap), sempre
//        corpo sólido                     =   min(comprimento·mult, pegada)
//        resto da pegada                  =   rastro translúcido atrás (o da herança)
//        largura                          =   min(largura·mult, corpo·0,72)
//
//    Ou seja: o comprimento NUNCA é exagerado além do espaço que o modelo reserva, e
//    a largura é exagerada pelo MESMO fator com que a via já é exagerada (`mult`) — a
//    razão carro/faixa desenhada fica em 0,37, abaixo dos 0,44 reais, então o carro
//    também não invade lateralmente. É a mesma propriedade da herança ("sprite grande
//    + pegada verdadeira continua honesto"), só que válida nos DOIS sentidos da
//    desigualdade: ela conserta o sprite curto demais, esta versão conserta também o
//    comprido demais.
//
// 3. JUNÇÃO MAIS CLARA (`#708095`). O `#637183` media 1,37 contra a via na mesa de
//    1,30 m do maquete; na imagem de 1,82 m da feira o mesmo par cai para 1,26 —
//    abaixo do piso, só por causa do ponto de operação. Re-resolvido para 1,45.
//    Auditado em `scripts/projecao_contraste.py`.

const DEG = Math.PI / 180;

// ============================================================================
// PALETA — espelha `scripts/projecao_contraste.py`. Mudou aqui, muda lá.
// ============================================================================
export const COL = {
  road: '#4b5869',        // leito da via   L=0,095
  junction: '#708095',    // junção         L=0,211  (reajustada pelo A7)
  dash: 'rgba(156,188,223,.55)',
  green: '#2bea88', yellow: '#ffd23d', red: '#ff5245', off: '#55637a',
  sigCore: 'rgba(255,255,255,.92)',
  // Os três estados do carro são todos CLAROS, separados por TEMPERATURA de cor. O
  // carro parado fica EM CIMA da fila incandescente: escurecê-lo o dissolve justo
  // onde ele importa. Vermelho, nesta tela, só quer dizer farol fechado.
  carFree: '#f4fbff', carSlow: '#e6eef7', carStop: '#ffe2b8',
  carEdge: 'rgba(2,6,12,.75)',
  truth: 'rgba(6,10,16,.85)',   // contorno do carro REAL dentro do sprite (tecla V)
};

// Rampa do acúmulo, em dois canais: IDENTIDADE no matiz (âmbar -> vermelho) e
// GRAVIDADE no núcleo incandescente. Vermelho saturado tem luminância baixa por
// construção, então "mais vermelho" seria "mais escuro" e a rampa ficaria plana.
const RAMP = [
  [0.00, [224, 137, 26], 0.30],
  [0.33, [255, 122, 26], 0.55],
  [0.67, [255, 84, 36], 0.80],
  [1.00, [255, 47, 58], 0.95],
];

function _ramp(t, idx) {
  t = t < 0 ? 0 : (t > 1 ? 1 : t);
  for (let i = 1; i < RAMP.length; i++) {
    if (t <= RAMP[i][0]) {
      const A = RAMP[i - 1], B = RAMP[i];
      const k = (t - A[0]) / (B[0] - A[0] || 1);
      if (idx === 2) return A[2] + (B[2] - A[2]) * k;
      return [Math.round(A[1][0] + (B[1][0] - A[1][0]) * k),
              Math.round(A[1][1] + (B[1][1] - A[1][1]) * k),
              Math.round(A[1][2] + (B[1][2] - A[1][2]) * k)];
    }
  }
  const L = RAMP[RAMP.length - 1];
  return idx === 2 ? L[2] : L[1];
}

export function heatRGB(t) { return _ramp(t, 1); }
export function heatAlpha(t) { return _ramp(t, 2); }

const CORE_ON = 0.30;
export const CORE_RGB = [255, 220, 172];
export function coreK(u) { return u <= CORE_ON ? 0 : (u - CORE_ON) / (1 - CORE_ON); }

const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a.toFixed(3)})`;

// Fila (carros parados numa aproximação) que satura a rampa.
export const Q_JAM = 5;

// Velocidade de fluxo livre para normalizar a cor do carro. NA REDE ABERTA DA FEIRA
// tudo está em SIMILITUDE K=6: a secundária de 40 km/h vira 11,11/6 = 1,852 m/s. Herdar
// os 11,11 do maquete classificaria a frota inteira como "parada" e a tela ficaria de
// uma cor só — por isso o valor sai do `/api/rede`, não de constante.
const V_FREE_PADRAO = 1.852;

// --- halos pré-renderizados (drawImage é ~10x mais barato que shadowBlur) --------
const _glow = new Map();
function glowSprite(hex, px) {
  const key = hex + '@' + px;
  let c = _glow.get(key);
  if (c) return c;
  c = document.createElement('canvas');
  c.width = c.height = px;
  const g = c.getContext('2d');
  const r = px / 2;
  const grad = g.createRadialGradient(r, r, 0, r, r, r);
  grad.addColorStop(0.00, hex);
  grad.addColorStop(0.28, hex);
  grad.addColorStop(1.00, 'rgba(0,0,0,0)');
  g.fillStyle = grad;
  g.globalAlpha = 0.55;
  g.beginPath(); g.arc(r, r, r, 0, 6.2832); g.fill();
  _glow.set(key, c);
  return c;
}

function blitGlow(ctx, hex, x, y, radius, alpha) {
  const s = glowSprite(hex, 64);
  ctx.globalAlpha = alpha;
  ctx.drawImage(s, x - radius, y - radius, radius * 2, radius * 2);
  ctx.globalAlpha = 1;
}

function poly(ctx, T, pts) {
  ctx.beginPath();
  for (let i = 0; i < pts.length; i++) {
    const x = T.X(pts[i][0]), y = T.Y(pts[i][1]);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
}

function rrect(ctx, x, y, w, h, r) {
  r = Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

// ---------------------------------------------------------------- sprite ----
// PISO ANTI-SUMIÇO, e só isso. A regra do sprite é "a extensão longitudinal desenhada
// É a pegada do SUMO" — sem exceção negociável. Este piso de 3 px existe apenas para o
// carro não desaparecer numa janela minúscula (uma prévia de 400 px, um monitor
// secundário), e quando ele morde `Board.spriteExcede` fica true e a régua de bancada
// (tecla I) denuncia por quanto.
//
// NÃO existe piso de LEGIBILIDADE aqui de propósito. Na montagem da feira a pegada de
// um carro mede ~6,1 px = 5,8 mm = 9,9' de arco a 2 m — está no limite do que se
// resolve individualmente, e esticar o sprite para "resolver" isso não resolveria: só
// faria os carros parados se sobreporem e a fila virar um borrão de comprimento certo
// e densidade errada. A leitura de longe é a BANDA da fila e o PLACAR; o carro
// individual é para quem chega perto. Ver docs/PROJECAO.md §3.
const PISO_PX = 3;

// ============================================================================
// Board — o mapa de UM braço. Guarda os índices derivados da rede (que não mudam),
// o transform e o estado suavizado do acúmulo.
// ============================================================================
export class Board {
  constructor(net) {
    this.net = net;
    this.laneW = net.defaultLaneWidth || 0.53;
    const veh = net.vehicle || {};
    this.vehLen = veh.length || 3.5;
    this.vehW = veh.width || 1.8;
    this.minGap = veh.minGap == null ? this.vehLen * 0.7 : veh.minGap;
    // A PEGADA: o espaço que o SUMO reserva por carro na fila. Exato, do `.add.xml`.
    this.foot = this.vehLen + this.minGap;
    this.vFree = net.vFree || V_FREE_PADRAO;

    this.lanes = net.lanes;
    this.edgeOf = {};
    this.lanesOfEdge = {};
    this.lenOf = {};
    for (const ln of this.lanes) {
      this.edgeOf[ln.id] = ln.edge;
      (this.lanesOfEdge[ln.edge] || (this.lanesOfEdge[ln.edge] = [])).push(ln);
      let L = 0;
      for (let i = 1; i < ln.shape.length; i++) {
        L += Math.hypot(ln.shape[i][0] - ln.shape[i - 1][0],
                        ln.shape[i][1] - ln.shape[i - 1][1]);
      }
      this.lenOf[ln.id] = L || 1;
    }

    // edge -> junção onde ele DESEMBOCA. Tolerância generosa (6 faixas): a ponta da
    // faixa para na borda do polígono da junção, não no centro dela.
    this.endJunctionOf = {};
    const tol = 6 * this.laneW;
    for (const eid in this.lanesOfEdge) {
      const sh = this.lanesOfEdge[eid][0].shape;
      const p = sh[sh.length - 1];
      let best = null, bd = Infinity;
      for (const j of net.junctions) {
        const d = Math.hypot(j.center[0] - p[0], j.center[1] - p[1]);
        if (d < bd) { bd = d; best = j; }
      }
      if (best && bd <= tol) this.endJunctionOf[eid] = best.id;
    }
    this.tlJunctions = net.junctions.filter(j => j.type === 'traffic_light');

    // BBOX DE DESENHO = a geometria de verdade, não o `convBoundary` (as faixas vazam
    // dele, e aqui a tela é full-bleed: a via encostaria na borda).
    const bb = { xmin: net.bbox.xmin, ymin: net.bbox.ymin,
                 xmax: net.bbox.xmax, ymax: net.bbox.ymax };
    const eat = pts => {
      for (const q of pts) {
        if (q[0] < bb.xmin) bb.xmin = q[0]; if (q[0] > bb.xmax) bb.xmax = q[0];
        if (q[1] < bb.ymin) bb.ymin = q[1]; if (q[1] > bb.ymax) bb.ymax = q[1];
      }
    };
    for (const ln of this.lanes) eat(ln.shape);
    for (const j of net.junctions) eat(j.shape);
    this.bbox = bb;

    this.ema = Object.create(null);
    for (const eid in this.lanesOfEdge) this.ema[eid] = 0;

    this.T = null;
    this.mult = 2.15;
    this.rect = { x: 0, y: 0, w: 0, h: 0 };
    this.netW = 0; this.netH = 0;
    this.queueTotal = 0;
    this.sprite = null;          // medidas do sprite no layout atual
    this.spriteExcede = false;   // true = o piso em px venceu a pegada (ver acima)
  }

  layout(rect, view = { zoom: 1, panX: 0, panY: 0 }) {
    this.rect = rect;
    const b = this.bbox;
    const bw0 = Math.max(1e-6, b.xmax - b.xmin), bh0 = Math.max(1e-6, b.ymax - b.ymin);
    const mult = this._multPara(Math.min(rect.w / bw0, rect.h / bh0));
    this.mult = mult;
    const m = this.laneW * mult;
    const bx0 = b.xmin - m, by0 = b.ymin - m;
    const bw = (b.xmax - b.xmin) + 2 * m, bh = (b.ymax - b.ymin) + 2 * m;
    const s = Math.min(rect.w / bw, rect.h / bh) * (view.zoom || 1);
    const cx = bx0 + bw / 2, cy = by0 + bh / 2;
    const ox = rect.x + rect.w / 2 - cx * s + (view.panX || 0);
    const oy = rect.y + rect.h / 2 + cy * s + (view.panY || 0);
    this.T = { s, X: x => ox + x * s, Y: y => oy - y * s };
    this.netW = bw * s; this.netH = bh * s;
    this._medeSprite();
    return this.T;
  }

  // Exagero transversal da via. Piso em PIXELS para a via nunca virar um fio de cabelo.
  _multPara(s) {
    const px = this.laneW * s;
    return px > 0 ? Math.max(2.15, Math.min(4.5, 15 / px)) : 2.15;
  }

  laneMult() { return this.mult || 2.15; }

  // ------------------------------------------------------------------ sprite
  // A regra do cabeçalho, resolvida uma vez por layout. Tudo em px de tela.
  _medeSprite() {
    const s = this.T ? this.T.s : 1, mult = this.laneMult();
    const footPx = this.foot * s;                      // o teto: a pegada do SUMO
    const corpoIdeal = this.vehLen * s * mult;
    let corpo = Math.min(corpoIdeal, footPx);
    this.spriteExcede = corpo < PISO_PX;
    if (this.spriteExcede) corpo = PISO_PX;           // piso anti-sumiço (denunciado)
    // Largura: exagerada pelo MESMO fator com que a via já é exagerada (`mult`), e
    // limitada a 0,72 do corpo para o sprite continuar lendo como veículo e não como
    // ponto. Nesta rede o limite de aspecto é quem manda, e o resultado é uma cápsula
    // de ~1,4:1 — mais curta que o carro real (2,5:1), mas ainda alongada.
    const largura = Math.max(PISO_PX, Math.min(this.vehW * s * mult, corpo * 0.72));
    this.sprite = {
      s, mult, corpo, largura,
      pegada: Math.max(footPx, corpo),                 // extensão longitudinal desenhada
      rastro: Math.max(0, Math.max(footPx, corpo) - corpo),
      realC: this.vehLen * s, realL: this.vehW * s, footPx,
      // os fatores que o documento cobra: exagero medido, não declarado
      exageroC: corpo / Math.max(1e-9, this.vehLen * s),
      exageroL: largura / Math.max(1e-9, this.vehW * s),
      excede: this.spriteExcede ? corpo / Math.max(1e-9, footPx) : 1,
    };
    return this.sprite;
  }

  // ------------------------------------------------------------------ asfalto
  // Estático: quem chama desenha isto UMA vez num canvas fora de tela.
  paintBase(ctx, { asphalt = true } = {}) {
    if (!asphalt || !this.T) return;
    const T = this.T, mult = this.laneMult();
    const w = this.laneW * T.s * mult;
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';

    ctx.strokeStyle = COL.road;
    ctx.lineWidth = w;
    for (const ln of this.lanes) { poly(ctx, T, ln.shape); ctx.stroke(); }

    ctx.fillStyle = COL.junction;
    for (const j of this.net.junctions) {
      if (j.shape.length >= 3) { poly(ctx, T, j.shape); ctx.closePath(); ctx.fill(); }
    }

    ctx.strokeStyle = COL.dash;
    ctx.lineWidth = Math.max(1.2, T.s * 0.035 * mult);
    ctx.setLineDash([Math.max(4, T.s * 0.75 * mult), Math.max(3, T.s * 0.55 * mult)]);
    for (const ln of this.lanes) { poly(ctx, T, ln.shape); ctx.stroke(); }
    ctx.setLineDash([]);
  }

  // ------------------------------------------------------- camada por quadro
  paint(ctx, snap, nowMs, dt, opts = {}) {
    if (!this.T || !snap) return;
    const { heat = true, signals = true, cars = true, footprint = true,
            verdade = false } = opts;
    this._advanceHeat(snap.heat, dt);
    if (heat) { this._paintHeat(ctx, nowMs); this._paintPressure(ctx, nowMs); }
    if (signals) this._paintSignals(ctx, snap.tls || {});
    if (cars) this._paintCars(ctx, snap.vehicles || [], footprint, verdade);
  }

  _advanceHeat(heat, dt) {
    const q = Object.create(null);
    let total = 0;
    if (heat) {
      for (const laneId in heat) {
        const e = this.edgeOf[laneId];
        const n = heat[laneId];
        total += n;
        if (e) q[e] = (q[e] || 0) + n;
      }
    }
    this.queueTotal = total;
    // TAU=0,55 s: acompanha o verde abrindo sem piscar junto com o passo de 1 Hz.
    const a = 1 - Math.exp(-Math.max(0, dt) / 0.55);
    for (const e in this.ema) this.ema[e] += ((q[e] || 0) - this.ema[e]) * a;
  }

  _paintHeat(ctx, nowMs) {
    const T = this.T, mult = this.laneMult();
    const w = this.laneW * T.s * mult;
    ctx.lineCap = 'butt';
    for (const eid in this.ema) {
      const q = this.ema[eid];
      if (q < 0.06) continue;
      const lanes = this.lanesOfEdge[eid];
      const u = Math.min(q / Q_JAM, 1);
      const c = heatRGB(u);
      const puls = u > 0.72 ? 1 + 0.18 * Math.sin(nowMs / 290) : 1;
      const aMax = Math.min(0.98, heatAlpha(u) * puls);
      const k = coreK(u);
      for (const ln of lanes) {
        const sh = ln.shape, n = sh.length;
        const hx = T.X(sh[n - 1][0]), hy = T.Y(sh[n - 1][1]);
        const cx = T.X(sh[0][0]), cy = T.Y(sh[0][1]);
        // alcance FÍSICO da fila: (parados / nº de faixas) × pegada / comprimento.
        // Com a pegada exata (length + minGap) este número deixou de ser estimativa.
        const reach = Math.max(0.14, Math.min(1,
          (q / lanes.length) * this.foot / this.lenOf[ln.id]));
        const faixa = (cor, alpha) => {
          const g = ctx.createLinearGradient(hx, hy, cx, cy);
          g.addColorStop(0, rgba(cor, alpha));
          g.addColorStop(Math.max(0.001, reach * 0.62), rgba(cor, alpha * 0.72));
          g.addColorStop(Math.min(0.999, reach), rgba(cor, 0));
          g.addColorStop(1, rgba(cor, 0));
          return g;
        };
        ctx.strokeStyle = faixa(c, aMax);
        ctx.lineWidth = w * 1.75;
        ctx.globalAlpha = 0.30;
        poly(ctx, T, ln.shape); ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.lineWidth = w * 0.92;
        poly(ctx, T, ln.shape); ctx.stroke();
        if (k > 0.01) {
          ctx.strokeStyle = faixa(CORE_RGB, Math.min(0.62, 0.55 * k * puls));
          ctx.lineWidth = w * (0.20 + 0.16 * k);
          poly(ctx, T, ln.shape); ctx.stroke();
        }
      }
    }
    ctx.lineCap = 'round';
  }

  _paintPressure(ctx, nowMs) {
    const T = this.T, w = this.laneW * T.s * this.laneMult();
    const acc = Object.create(null);
    for (const eid in this.ema) {
      const j = this.endJunctionOf[eid];
      if (j) acc[j] = (acc[j] || 0) + this.ema[eid];
    }
    for (const j of this.tlJunctions) {
      const q = acc[j.id] || 0;
      if (q < 1.2) continue;
      const u = Math.min(q / (Q_JAM * 2.2), 1);
      const base = heatRGB(u), k = coreK(u);
      const c = [Math.round(base[0] + (CORE_RGB[0] - base[0]) * k * 0.8),
                 Math.round(base[1] + (CORE_RGB[1] - base[1]) * k * 0.8),
                 Math.round(base[2] + (CORE_RGB[2] - base[2]) * k * 0.8)];
      const x = T.X(j.center[0]), y = T.Y(j.center[1]);
      const r = w * (0.75 + 0.75 * u);
      const puls = u > 0.7 ? 1 + 0.12 * Math.sin(nowMs / 340) : 1;
      blitGlow(ctx, `rgb(${c[0]},${c[1]},${c[2]})`, x, y, r * 1.7, 0.12 + 0.26 * u);
      ctx.beginPath();
      ctx.arc(x, y, r * puls, 0, 6.2832);
      ctx.strokeStyle = rgba(c, 0.30 + 0.62 * u);
      ctx.lineWidth = Math.max(1.6, w * (0.14 + 0.24 * u));
      ctx.stroke();
    }
  }

  _paintSignals(ctx, tls) {
    const T = this.T, mult = this.laneMult();
    const w = this.laneW * T.s * mult;
    for (const tl of this.net.tls) {
      const st = tls[tl.id];
      if (!st) continue;
      for (const lk of tl.links) {
        const ch = st[lk.linkIndex] || 'o';
        const col = (ch === 'G' || ch === 'g') ? COL.green
                  : (ch === 'y' || ch === 'Y') ? COL.yellow
                  : (ch === 'r' || ch === 'R') ? COL.red : COL.off;
        const h = (lk.heading || 0) * DEG;
        const px = Math.cos(h), py = -Math.sin(h);
        const half = this.laneW * mult * 0.5;
        const x0 = T.X(lk.stopLine[0] + px * half), y0 = T.Y(lk.stopLine[1] + py * half);
        const x1 = T.X(lk.stopLine[0] - px * half), y1 = T.Y(lk.stopLine[1] - py * half);
        const cx = T.X(lk.stopLine[0]), cy = T.Y(lk.stopLine[1]);
        blitGlow(ctx, col, cx, cy, w * 1.2, 0.45);
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
        ctx.lineWidth = Math.max(3.5, w * 0.46);
        ctx.strokeStyle = col;
        ctx.stroke();
        // NÚCLEO BRANCO dentro da barra: o vermelho é a cor de menor luminância que
        // existe e some sobre uma fila acesa (1,12 medido). O núcleo entrega a leitura
        // por luminância; o halo colorido em volta continua entregando o ESTADO.
        ctx.beginPath();
        ctx.moveTo(x0 * 0.62 + cx * 0.38, y0 * 0.62 + cy * 0.38);
        ctx.lineTo(x1 * 0.62 + cx * 0.38, y1 * 0.62 + cy * 0.38);
        ctx.lineWidth = Math.max(1.4, w * 0.17);
        ctx.strokeStyle = COL.sigCore;
        ctx.stroke();
      }
    }
  }

  _paintCars(ctx, vehicles, footprint, verdade) {
    const T = this.T;
    const sp0 = this.sprite || this._medeSprite();
    const L = sp0.corpo, D = sp0.largura, r = D * 0.42;
    const rastro = sp0.rastro;
    const vFree = this.vFree;

    for (const v of vehicles) {
      const sp = Math.max(0, v.speed == null ? vFree : v.speed);
      const f = Math.min(1, sp / vFree);
      const stopped = sp < vFree * 0.03;
      // 0,45 de fluxo livre classificava como "devagar" quase a frota inteira nesta
      // rede de quadras curtas — a tela ficava toda de uma cor só. 0,28 separa.
      const col = stopped ? COL.carStop : (f < 0.28 ? COL.carSlow : COL.carFree);
      const rad = v.angle * DEG;
      const a = Math.atan2(-Math.cos(rad), Math.sin(rad));   // náutico + flipY -> canvas
      const x = T.X(v.x), y = T.Y(v.y);

      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(a);

      // RASTRO DA PEGADA: só existe quando o corpo é MAIS CURTO que a pegada. Aqui ele
      // é o resto do espaço reservado, não uma invenção — e some quando o corpo já
      // cobre a pegada inteira. Só em quem está parando: no fluxo livre não há fila
      // para representar, e um rastro claro fora da via vira sujeira de render.
      if (footprint && rastro > 1.5 && f < 0.35) {
        const peso = 1 - f / 0.35;
        const g = ctx.createLinearGradient(-L, 0, -L - rastro, 0);
        g.addColorStop(0, col);
        g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.globalAlpha = 0.10 + 0.22 * peso;
        ctx.fillStyle = g;
        rrect(ctx, -L - rastro, -D * 0.42, rastro, D * 0.84, D * 0.2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      // Corpo: uma cápsula limpa (a posição do SUMO é o para-choque DIANTEIRO, então
      // o corpo recua de 0 a -L). Nesta escala, forma se faz com silhueta, não com
      // detalhe: um "teto" escuro por cima fazia o sprite ler como dominó.
      rrect(ctx, -L, -D / 2, L, D, r);
      const vol = ctx.createLinearGradient(0, 0, -L, 0);
      vol.addColorStop(0, col);
      vol.addColorStop(1, 'rgba(0,0,0,.30)');
      ctx.fillStyle = col; ctx.fill();
      ctx.fillStyle = vol; ctx.globalAlpha = 0.32; ctx.fill(); ctx.globalAlpha = 1;
      // Contorno escuro: sobre a fila incandescente o contraste global do carro cai,
      // mas o olho detecta forma por BORDA local muito antes de detectar por
      // luminância média. Custa um traço e salva a leitura.
      rrect(ctx, -L, -D / 2, L, D, r);
      ctx.lineWidth = Math.max(1.2, D * 0.15);
      ctx.strokeStyle = COL.carEdge; ctx.stroke();

      // MODO VERDADE (tecla V): o carro REAL, na escala real, dentro do sprite. Existe
      // para a foto de bancada — é a prova visual de que o exagero é só exagero, e de
      // quanto ele é. Não é modo de feira: a 2 m ninguém vê este contorno.
      if (verdade) {
        ctx.lineWidth = 1;
        ctx.strokeStyle = COL.truth;
        ctx.strokeRect(-sp0.realC, -sp0.realL / 2, sp0.realC, sp0.realL);
      }

      ctx.restore();

      if (stopped) blitGlow(ctx, COL.carStop, x, y, D * 1.7, 0.20);
    }
  }
}
