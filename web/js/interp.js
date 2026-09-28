// interp.js — buffer de interpolação com RENDER-DELAY, indexado pela linha-do-tempo
// da SIMULAÇÃO (frame.t, em segundos simulados).
//
// PORTADO de `smart-traffic-maquete/dashboard/frontend/js/interp.js` (commit `18ea6dd`),
// com `lerpAngle` embutido (o `transform.js` de lá não veio junto). A lógica é a de lá,
// e o comentário de lá vale aqui inteiro:
//
//   O lerp ingênuo "pulava" porque fazia k=(now-prevT)/span com span = intervalo entre
//   os 2 últimos frames, e renderizava SEMPRE >= a chegada do frame novo: k saturava em
//   1, o carro teleportava e congelava até o próximo. Aqui mantemos um BUFFER e
//   renderizamos ~1 frame ATRÁS do mais novo, sempre interpolando entre DOIS frames que
//   JÁ temos. O relógio de playback anda em tempo real e é puxado por TAXA (não por
//   salto) para (mais_novo - DELAY), absorvendo o jitter sem nunca extrapolar.
//
// O QUE MUDA NA FEIRA: o backend aqui é a `ArenaSumo` com `step-length=1.0` e ritmo
// 1:1 (`Marcapasso`), então `speed=1` e um frame por segundo simulado — as mesmas
// premissas do original. O `status` do C7 é `"ok"`; qualquer outro valor não entra na
// interpolação, porque não traz posições em que se possa confiar.

const DEG = Math.PI / 180;

function lerpAngle(a, b, k) {
  const d = ((b - a + 540) % 360) - 180;
  return a + d * k;
}

// Posição por spline de HERMITE entre dois samples do SUMO, usando a VELOCIDADE na
// direção do heading como tangente: o carro segue a CURVA da conversão em vez de cortar
// caminho em reta. A tangente é escalada por TENSION uniforme -> velocidade contínua na
// fronteira entre segmentos; e limitada a uma fração da CORDA -> não estoura em curva
// fechada (o artefato em que o carro saía da via).
const TENSION = 0.85;
const TAN_MAX = 0.9;

function hermite(p, v, dt, k) {
  const r0 = p.angle * DEG, r1 = v.angle * DEG;   // náutico: dir mundo = (sin, cos)
  const chord = Math.hypot(v.x - p.x, v.y - p.y);
  const cap = chord * TAN_MAX;
  const s = TENSION * dt;
  let g0 = p.speed * s, g1 = v.speed * s;
  if (g0 > cap) g0 = cap;
  if (g1 > cap) g1 = cap;
  const m0x = Math.sin(r0) * g0, m0y = Math.cos(r0) * g0;
  const m1x = Math.sin(r1) * g1, m1y = Math.cos(r1) * g1;
  const k2 = k * k, k3 = k2 * k;
  const h00 = 2 * k3 - 3 * k2 + 1, h10 = k3 - 2 * k2 + k;
  const h01 = -2 * k3 + 3 * k2, h11 = k3 - k2;
  const d00 = 6 * k2 - 6 * k, d10 = 3 * k2 - 4 * k + 1;
  const d01 = -6 * k2 + 6 * k, d11 = 3 * k2 - 2 * k;
  return {
    x: h00 * p.x + h10 * m0x + h01 * v.x + h11 * m1x,
    y: h00 * p.y + h10 * m0y + h01 * v.y + h11 * m1y,
    vx: d00 * p.x + d10 * m0x + d01 * v.x + d11 * m1x,
    vy: d00 * p.y + d10 * m0y + d01 * v.y + d11 * m1y,
  };
}

export const DELAY = 1.15;      // s simulados atrás do frame mais novo (>1 step: sempre há par)
const DRIFT_GAIN = 0.5;
const RATE_MIN = 0.85, RATE_MAX = 1.15;
const MAX_DT = 0.25;     // passo real (s) acima disto = gap (aba inativa) -> re-sincroniza
const KEEP_BEHIND = 2.0;
const MAX_BUF = 16;

export class FrameBuffer {
  constructor() {
    this.buf = [];
    this.playClock = null;
    this.lastReal = null;
    this.newestFrame = null;
    this.speed = 1;
    this.recebidos = 0;
    this.perdidos = 0;     // frames que chegaram fora de ordem / duplicados
  }

  get vazio() { return this.buf.length === 0; }

  push(frame) {
    if (!frame || (frame.status && frame.status !== 'ok')) return;
    const t = frame.t;
    const last = this.buf[this.buf.length - 1];
    if (last && t <= last.t) {
      // t voltou MUITO atrás => a rodada reiniciou: zera e aceita o frame novo.
      if (t < last.t - 1.0) {
        this.buf = []; this.playClock = null; this.lastReal = null; this.newestFrame = null;
      } else { this.perdidos++; return; }
    }
    const tlsMap = {};
    for (const tl of (frame.tls || [])) tlsMap[tl.id] = tl.state;
    this.buf.push({
      t, vehicles: frame.vehicles || [], tlsMap,
      heat: frame.heat || null, raw: frame,
    });
    this.newestFrame = frame;
    this.recebidos++;
    if (this.buf.length > MAX_BUF) this.buf.shift();
  }

  limpa() {
    this.buf = []; this.playClock = null; this.lastReal = null; this.newestFrame = null;
  }

  sample(nowMs) {
    if (this.buf.length === 0) return null;
    if (this.buf.length === 1) {
      const f = this.buf[0];
      return { vehicles: f.vehicles, tls: f.tlsMap, heat: f.heat, t: f.t };
    }
    const newest = this.buf[this.buf.length - 1].t;
    const oldest = this.buf[0].t;
    const target = newest - DELAY;

    if (this.playClock === null) { this.playClock = target; this.lastReal = nowMs; }
    let dt = (nowMs - this.lastReal) / 1000;
    this.lastReal = nowMs;
    if (dt < 0) dt = 0;

    if (dt > MAX_DT) {
      this.playClock = target;
    } else {
      const err = target - this.playClock;
      let rate = 1 + err * DRIFT_GAIN;
      if (rate < RATE_MIN) rate = RATE_MIN; else if (rate > RATE_MAX) rate = RATE_MAX;
      this.playClock += dt * rate * this.speed;
    }
    if (this.playClock > newest) this.playClock = newest;
    if (this.playClock < oldest) this.playClock = oldest;

    while (this.buf.length > 2 && this.buf[1].t < this.playClock - KEEP_BEHIND) {
      this.buf.shift();
    }

    let a = this.buf[0], b = this.buf[this.buf.length - 1];
    for (let i = 0; i < this.buf.length - 1; i++) {
      if (this.buf[i].t <= this.playClock && this.playClock <= this.buf[i + 1].t) {
        a = this.buf[i]; b = this.buf[i + 1]; break;
      }
    }
    const k = b.t > a.t ? (this.playClock - a.t) / (b.t - a.t) : 0;

    const am = {};
    for (const v of a.vehicles) am[v.id] = v;
    const segDt = b.t - a.t;
    const vehicles = b.vehicles.map(v => {
      const p = am[v.id];
      if (!p) return { id: v.id, x: v.x, y: v.y, angle: v.angle, speed: v.speed };
      const pos = hermite(p, v, segDt, k);
      const moving = Math.hypot(pos.vx, pos.vy) > 0.05;
      const angle = moving ? Math.atan2(pos.vx, pos.vy) / DEG
                           : lerpAngle(p.angle, v.angle, k);
      return { id: v.id, x: pos.x, y: pos.y, angle,
               speed: p.speed + (v.speed - p.speed) * k };
    });
    // faróis e fila são estado DISCRETO válido em [a.t, b.t): usa o de `a`. Fila por
    // faixa não se interpola — inventar meio carro parado é inventar dado.
    return { vehicles, tls: a.tlsMap, heat: a.heat, t: this.playClock };
  }
}
