// paint.js — o PINTOR do mapa da projeção da feira.
//
// PORTADO de `smart-traffic-maquete/dashboard/frontend/projecao/js/paint.js`
// (commit `18ea6dd`). De lá vêm o fundo preto (projetor soma luz e nunca subtrai), o
// acúmulo em duas dimensões (cor = gravidade, comprimento = quanto da via já foi
// tomada) e o carro colorido pela velocidade.
//
// O QUE NÃO VEIO JUNTO: o ESPALHAMENTO. A projeção do maquete desenha calor com halo
// — bloom de 1,75x a largura da via na fila, disco em volta de cada farol, anel de
// pressão por cruzamento, halo por carro parado. Lá isso se defende: o alvo é um
// painel de 300 lm e o que espalha luz é o que sobrevive ao ambiente. Aqui os quatro
// se SOMAVAM, e a malha lia como lente suja em vez de trânsito. A regra desta tela é
// TODA LUZ É CONTIDA — nada é aceso fora do asfalto, e o que precisa se separar do
// fundo se separa por BORDA escura, não por brilho.
//
// O QUE MUDOU NESTE REPO, E POR QUÊ
// ---------------------------------
// 1. PEGADA EXATA. O `/api/network` do maquete não exportava `minGap` e o pintor
//    chutava `foot = 1,7 x comprimento`. O `/api/rede` daqui exporta `minGap`, e a
//    pegada passou a ser `length + minGap` — o número que o SUMO de fato reserva.
//
// 2. O SPRITE DO CARRO NÃO É O DO MAQUETE (ver docs/PROJECAO.md §3.3). A regra de lá
//    (`D = max(7 px, laneW·s·1,15)`, `L = D·2,9`) produz nesta rede um sprite 2,5x
//    mais comprido que a pegada — e o efeito na tela é direto: em qualquer fila os
//    carros parados montam uns nos outros. Aqui o desenho NUNCA passa do espaço que o
//    modelo reserva, e ainda deixa ~1 px de costura entre um carro e o próximo:
//
//        corpo   = min(comprimento·mult, pegada·0,88)
//        largura = min(largura·mult,     corpo·0,60)
//
//    O carro individual fica pequeno (7,1 x 4,2 px a 1080p) porque a rede é grande —
//    e é para ficar. Quem carrega a leitura de longe é a BANDA DE ACÚMULO, cujo
//    comprimento sai do `reach` físico, e o placar.
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
  // A moldura escura do farol. Ela é o que substituiu o halo: a barra do farol cai em
  // cima da banda de acúmulo, e `farol vermelho sobre a banda` mede 1,12 de contraste
  // (§4) — ou seja, some. Um traço quase-preto mais largo por baixo devolve a leitura
  // por BORDA local, sem acender um pixel a mais. Não é cor de informação: é vedação,
  // e por isso não entra na auditoria de paleta.
  sigEdge: 'rgba(3,7,13,.88)',
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
//
// AS ALFAS BAIXARAM (era 0,30 .. 0,95). A 0,95 a banda saturada é um TIJOLO VERMELHO
// OPACO: ela apaga o asfalto embaixo, some com a marcação da faixa, e passa a disputar
// no olho com a barra do farol fechado, que é o outro vermelho da tela — e é o que
// mais importa ler. A 0,80 a banda é uma LAVAGEM: a via continua aparecendo por baixo,
// o farol continua sendo o único vermelho SÓLIDO, e a escada de gravidade não muda de
// forma (0,34 -> 0,80 é a mesma progressão, um degrau mais baixa).
//
// Elas espelham `RAMPA` em `scripts/projecao_contraste.py`: mudou aqui, muda lá, e o
// auditor mede a banda que a tela de fato desenha.
const RAMP = [
  [0.00, [224, 137, 26], 0.34],
  [0.33, [255, 122, 26], 0.50],
  [0.67, [255, 84, 36], 0.66],
  [1.00, [255, 47, 58], 0.80],
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
// alfa do núcleo no topo da rampa — espelha `NUCLEO_A` do auditor
export const CORE_A = 0.46;
export function coreK(u) { return u <= CORE_ON ? 0 : (u - CORE_ON) / (1 - CORE_ON); }

const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a.toFixed(3)})`;

// Fila (carros parados numa aproximação) que satura a rampa.
export const Q_JAM = 5;

// Quanto de APROXIMAÇÃO fica no quadro além do semáforo mais externo, em metros de
// mundo. Ver o bloco ENQUADRAMENTO no construtor do Board: 12 m são ~14 vagas de fila,
// quase o triplo do `Q_JAM` que já satura a rampa.
export const MARGEM_M = 12;

// Velocidade de fluxo livre para normalizar a cor do carro. NA REDE ABERTA DA FEIRA
// tudo está em SIMILITUDE K=6: a secundária de 40 km/h vira 11,11/6 = 1,852 m/s. Herdar
// os 11,11 do maquete classificaria a frota inteira como "parada" e a tela ficaria de
// uma cor só — por isso o valor sai do `/api/rede`, não de constante.
const V_FREE_PADRAO = 1.852;

// NÃO EXISTE MAIS UM `blitGlow` NESTE ARQUIVO, e por isso não existe mais o cache de
// sprites de halo que ele exigia. O que os quatro halos custavam, em números: 48 bolas
// coloridas de 36 px nas linhas de parada (12 cruzamentos x 4 aproximações), 12 discos
// nos cruzamentos, um disco por carro PARADO — e carro parado anda em fila, então eles
// se somavam até a fila inteira virar névoa — e um bloom de 1,75x a largura da via
// vazando para fora do asfalto em toda aproximação carregada.
//
// Borda custa um stroke, sobrevive à mesma distância que o halo, e é o único recurso
// que um projetor tem de verdade: ele soma luz e nunca subtrai, então o preto é o
// único valor garantidamente abaixo de qualquer coisa desenhada em cima dele.

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
// O ÚNICO piso desta tela, e ele é anti-sumiço, não de legibilidade: 3 px de corpo
// para o carro não desaparecer numa janela minúscula. Não existe piso de LEGIBILIDADE
// de propósito — esticar o sprite para o carro "aparecer" é exatamente o que faz os
// carros parados se sobreporem, e uma fila de comprimento certo com densidade errada
// mente sobre a única coisa que este mapa existe para mostrar. Ver `_medeSprite`.
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

    // ================== ENQUADRAMENTO: a rede não é o quadro ==================
    // A rede aberta mede 153,3 × 90 m, mas os 12 semáforos ocupam 103,3 × 40 m. Os
    // 25 m que sobram em CADA UM dos quatro lados são as pontas de entrada e saída —
    // rua por onde o carro chega e some, e que fica vazia quase o tempo todo.
    //
    // Enquadrar pela rede inteira custava caro, e custava no lugar errado: o quadro
    // ficava 1,70:1 numa tela de 2,25:1, encaixava pela ALTURA, e 55% dessa altura era
    // ponta vazia. Tudo o que é informação — via, carro, fila, farol — era desenhado na
    // escala que sobrava: 9,2 px/m, com o carro em 7,1 × 4,7 px.
    //
    // O quadro agora é o MIOLO + `MARGEM_M` de aproximação. Em 12 m cabem ~14 vagas de
    // fila em cada entrada, quase o triplo do `Q_JAM`: uma fila que estoure isso já
    // saturou a rampa há muito tempo e está gritando em vermelho dentro do quadro. O
    // que se perde é ver o carro nos últimos metros antes de sumir — e ele some no
    // enquadramento, não na simulação: nada aqui toca no que o SUMO calcula.
    //
    // O que se ganha: o quadro vira 2,0:1, a escala sobe ~44%, e via, carro e fila
    // sobem junto. É a única alavanca de tamanho que ainda existia — a tarja já foi de
    // 388 px para 226, e o exagero da via já está no ponto em que o carro cabe na
    // faixa na proporção real (ver `_multPara`).
    const tls = net.junctions.filter(j => j.type === 'traffic_light');
    const eq = { xmin: bb.xmin, ymin: bb.ymin, xmax: bb.xmax, ymax: bb.ymax };
    if (tls.length) {
      const xs = tls.map(j => j.center[0]), ys = tls.map(j => j.center[1]);
      // nunca mostra MAIS do que existe: o recorte só pode apertar
      eq.xmin = Math.max(bb.xmin, Math.min(...xs) - MARGEM_M);
      eq.xmax = Math.min(bb.xmax, Math.max(...xs) + MARGEM_M);
      eq.ymin = Math.max(bb.ymin, Math.min(...ys) - MARGEM_M);
      eq.ymax = Math.min(bb.ymax, Math.max(...ys) + MARGEM_M);
    }
    this.enquadre = eq;
    // quanto de ponta ficou de fora, em metros — a régua de bancada publica
    this.cortado = {
      esq: eq.xmin - bb.xmin, dir: bb.xmax - eq.xmax,
      baixo: eq.ymin - bb.ymin, cima: bb.ymax - eq.ymax,
    };

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
    const b = this.enquadre || this.bbox;
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

  // Exagero transversal da via: quanto a pista é desenhada mais larga do que é, para
  // não virar um fio de cabelo num projetor. O alvo era 15 px de faixa desenhada, e
  // ele foi para 11,5.
  //
  // POR QUE BAIXAR. O exagero da via é lateral e livre; o do CARRO não é — o
  // comprimento dele está preso à pegada do SUMO (`_medeSprite`), senão carro parado
  // monta em carro parado. Com a via a 15 px e o carro a 7 x 4, o carro ocupava 0,28
  // da faixa desenhada contra 0,42 na realidade: a pista parecia larga demais e o
  // trânsito, ralo. Não era o carro que estava pequeno, era a rua que estava grande.
  // A 11,5 px a razão volta para ~0,41 — a proporção real — sem tocar no sprite.
  //
  // 11,5 px = 10,9 mm no chão = 19' de arco a 2 m: continua sendo uma rua, com folga.
  _multPara(s) {
    const px = this.laneW * s;
    return px > 0 ? Math.max(2.0, Math.min(4.5, 11.5 / px)) : 2.0;
  }

  laneMult() { return this.mult || 2.15; }

  // ------------------------------------------------------------------ sprite
  // A REGRA, resolvida uma vez por layout. Tudo em px de tela.
  //
  //     corpo   = min(comprimento · mult,  pegada · 0,88)
  //     largura = min(largura     · mult,  corpo  · 0,60)
  //
  // A PRIMEIRA LINHA É A REGRA INTEIRA: o carro desenhado NUNCA passa do espaço que o
  // modelo reserva para ele. Consequência direta e visível — carro parado não se
  // sobrepõe a carro parado, nunca, em escala nenhuma. Uma fila desenhada tem o mesmo
  // comprimento E a mesma contagem que a fila simulada, e dá para contar os carros.
  //
  // O 0,88 é a costura. Com `corpo = pegada` cheia os carros parados se ENCOSTAM, e
  // uma fila carregada vira uma barra clara contínua em que não se distingue um
  // veículo do seguinte — tecnicamente não é sobreposição, visualmente é o mesmo
  // defeito. Os 12% que sobram são ~1 px de preto entre um carro e o próximo: é o
  // menor vão que ainda se lê, e é o que faz a fila PARECER uma fila de carros.
  // (O modelo reserva 33% de vão: `minGap`/pegada = 0,292/0,875. O desenho usa 12%
  // porque abaixo disso o carro fica menor que a costura; ele exagera o veículo dentro
  // do próprio slot, nunca para fora dele.)
  //
  // O 0,66 na largura é ASPECTO, não espaço: com o comprimento preso à pegada, deixar
  // a largura ir até `vehW·s·mult` produziria um sprite quase QUADRADO, e quadrado não
  // lê como carro. O teto de 0,66 do corpo segura a silhueta em ~1,5:1.
  //
  // Quem faz o carro CABER na faixa como carro é o exagero da VIA, não o dele: ver
  // `_multPara`. Com a faixa desenhada a 11,5 px, este sprite ocupa ~0,41 da largura
  // dela — a proporção real (0,42). Antes a faixa ia a 15 px e a razão caía para 0,28:
  // o carro parecia pequeno porque a rua estava grande.
  //
  // ESTA SEÇÃO JÁ DISSE O CONTRÁRIO. A regra da projeção do maquete
  // (`D = max(7 px, laneW·s·1,15)`, `L = D·2,9`) foi adotada aqui para consertar um
  // carro que media 6,3 × 4,6 px — e consertou, entregando 20,3 × 7,0. O preço era
  // 2,5 carros desenhados por vaga: em qualquer fila os sprites montavam uns nos
  // outros. Um mapa que mostra trânsito não pode desenhar o trânsito errado para o
  // carro ficar bonito. O carro individual é pequeno porque a rede é grande; quem
  // carrega a leitura de longe é a BANDA DE ACÚMULO e o placar (ver docs/PROJECAO.md
  // §3.4).
  _medeSprite() {
    const s = this.T ? this.T.s : 1, mult = this.laneMult();
    const footPx = this.foot * s;                      // a pegada do SUMO
    let corpo = Math.min(this.vehLen * s * mult, footPx * 0.88);
    // PISO ANTI-SUMIÇO, e só isso: o carro não pode desaparecer numa janela minúscula
    // (uma prévia de 400 px, um monitor secundário). Quando ele morde, `spriteExcede`
    // fica true e a régua de bancada (tecla I) denuncia por quanto. Nas resoluções de
    // feira (720p e 1080p) ele NÃO morde.
    this.spriteExcede = corpo < PISO_PX;
    if (this.spriteExcede) corpo = PISO_PX;
    const largura = Math.min(this.vehW * s * mult, corpo * 0.66);
    this.sprite = {
      s, mult, corpo, largura,
      pegada: Math.max(footPx, corpo),
      rastro: Math.max(0, footPx - corpo),
      realC: this.vehLen * s, realL: this.vehW * s, footPx,
      exageroC: corpo / Math.max(1e-9, this.vehLen * s),
      exageroL: largura / Math.max(1e-9, this.vehW * s),
      excede: corpo / Math.max(1e-9, footPx),
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

    // SEM ACOSTAMENTO. Eu tinha posto um traço quase-preto mais largo por baixo do
    // leito, copiando o dashboard (que tem fundo #1c1f26). Aqui o fundo é preto, e a
    // projeção do maquete já tinha tentado e desfeito isso: escuro sobre preto não
    // existe (mediu 1,4 de contraste). Quem descola a via do fundo é a própria via.
    // CADA FAIXA É UMA FITA, com um fio de preto entre elas. Traçando cada faixa na
    // largura cheia elas se encostam e a avenida vira UMA LAJE lisa de 60 px, em que
    // não dá para ver quantas pistas existem nem onde acaba um sentido e começa o
    // outro. A 8% de folga o vão dá ~1,2 px: não é buraco, é a marcação — e ela
    // funciona por BORDA (preto entre dois claros), que é o que um projetor entrega.
    ctx.strokeStyle = COL.road;
    ctx.lineWidth = w * 0.92;
    for (const ln of this.lanes) { poly(ctx, T, ln.shape); ctx.stroke(); }

    // A junção fecha a costura das pontas de faixa por cima.
    ctx.fillStyle = COL.junction;
    for (const j of this.net.junctions) {
      if (j.shape.length >= 3) { poly(ctx, T, j.shape); ctx.closePath(); ctx.fill(); }
    }

    // Tracejado do eixo de cada faixa. O PASSO é proporcional à faixa DESENHADA, não
    // a metros de mundo. Com o passo em metros ele dava traço de 6,7 px com vão de
    // 4,9 px dentro de uma faixa de 15 px: quatro pontilhados por avenida, tão densos
    // que a via inteira lia como textura tremida em vez de asfalto. A marcação tem de
    // ser ESPARSA para ser marcação — o que se lê de longe é a direção, não o traço.
    ctx.globalAlpha = 0.62;
    ctx.strokeStyle = COL.dash;
    ctx.lineWidth = Math.max(1, Math.min(2, w * 0.065));
    ctx.setLineDash([w * 0.9, w * 1.3]);
    for (const ln of this.lanes) { poly(ctx, T, ln.shape); ctx.stroke(); }
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }


  // ------------------------------------------------------- camada por quadro
  paint(ctx, snap, nowMs, dt, opts = {}) {
    if (!this.T || !snap) return;
    const { heat = true, signals = true, cars = true, footprint = true,
            verdade = false } = opts;
    this._advanceHeat(snap.heat, dt);
    if (heat) this._paintHeat(ctx, nowMs);
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

  // ------------------------------------------------------- acúmulo (a fila)
  // UMA BANDA DENTRO DA VIA, COM BORDA. Antes eram dois traços: um "bloom" de 1,75x a
  // largura da faixa a 30% de alfa, e a banda por cima. O bloom é o que vazava para
  // fora do asfalto — cada aproximação carregada virava uma mancha laranja maior que a
  // própria rua, e doze cruzamentos viravam doze borrões. Num projetor fraco isso se
  // defendia como "calor"; numa imagem nítida é sujeira, e era a primeira coisa que se
  // via na tela.
  //
  // A banda agora é SÓLIDA e termina onde a fila termina. Quem carrega a informação é
  // a BORDA DE ATAQUE dela: um degrau visível que anda para trás enquanto a fila
  // cresce e volta quando o verde abre. Borda dura se acompanha a três metros;
  // degradê que morre devagar, não. O alcance continua sendo o físico (`reach`), então
  // o que mudou é como a banda é pintada, não o que ela mede.
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
      // Pulso só na saturação, e de 4% em alfa. O de 18% em LARGURA fazia a mancha
      // respirar de tamanho, que num projetor a 2 m lê como tremor de foco.
      const puls = u > 0.85 ? 1 + 0.04 * Math.sin(nowMs / 300) : 1;
      const k = coreK(u);
      for (const ln of lanes) {
        const sh = ln.shape, n = sh.length;
        const hx = T.X(sh[n - 1][0]), hy = T.Y(sh[n - 1][1]);
        const cx = T.X(sh[0][0]), cy = T.Y(sh[0][1]);
        // Alcance FÍSICO da fila: (parados / nº de faixas) × pegada / comprimento da
        // faixa. Com a pegada exata (`length + minGap`) isto não é estimativa: é o
        // pedaço da via que os carros parados de fato ocupam.
        //
        // O PISO É UMA VAGA, não uma fração da via. Ele era 10% do comprimento da
        // faixa — o que, numa quadra de 25 m, pintava 30 px de banda para UM carro
        // parado de 8 px. Enquanto o sprite era 2,5x maior que a vaga isso passava
        // despercebido; com o carro no tamanho certo a banda passou a desmentir os
        // carros que estão dentro dela. Uma vaga é o menor alcance que existe: abaixo
        // disso não há fila.
        const umaVaga = this.foot / this.lenOf[ln.id];
        const reach = Math.min(1, Math.max(umaVaga,
          (q / lanes.length) * this.foot / this.lenOf[ln.id]));
        // A BANDA COMEÇA ATRÁS DO FAROL, não em cima dele. A barra do farol fica na
        // linha de parada, e a fila nasce exatamente ali — os dois se encostavam, e
        // como a rampa termina em vermelho, farol fechado + fila saturada viravam uma
        // mancha vermelha só. Recuar a banda por uma largura de barra devolve a cada
        // um o seu território: o farol é dono da linha de parada, a fila é dona da via
        // atrás dela. Não se perde informação — o primeiro carro parado continua
        // desenhado ali, e ele é quem ocupa esse pedaço.
        const lanePx = Math.max(1, Math.hypot(cx - hx, cy - hy));
        const d0 = Math.min(0.30, (w * 0.42) / lanePx);
        const fim = Math.min(0.999, d0 + reach);
        const faixa = (cor, alpha) => {
          const g = ctx.createLinearGradient(hx, hy, cx, cy);
          g.addColorStop(0, rgba(cor, 0));
          g.addColorStop(d0, rgba(cor, 0));
          g.addColorStop(Math.min(fim, d0 + 0.002), rgba(cor, alpha));
          // 88% do alcance em cheio; os 12% finais são o degrau da borda de ataque —
          // é ele que se acompanha de longe quando a fila cresce e quando ela escoa
          g.addColorStop(Math.max(d0 + 0.003, d0 + reach * 0.88), rgba(cor, alpha));
          g.addColorStop(fim, rgba(cor, 0));
          g.addColorStop(1, rgba(cor, 0));
          return g;
        };
        // 0,88 da faixa: a banda fica DENTRO do asfalto, com um fio de via de cada
        // lado. É esse fio que diz que a mancha está numa rua.
        // `heatAlpha` e não uma fórmula local: é ela que o auditor de contraste mede.
        ctx.strokeStyle = faixa(c, Math.min(0.86, heatAlpha(u) * puls));
        ctx.lineWidth = w * 0.88;
        poly(ctx, T, ln.shape); ctx.stroke();
        // O núcleo incandescente: onde mora a GRAVIDADE. Vermelho saturado tem
        // luminância baixa por construção, então "mais vermelho" seria "mais escuro";
        // o núcleo claro e estreito é o canal que faz pior TAMBÉM ser mais claro.
        if (k > 0.01) {
          ctx.strokeStyle = faixa(CORE_RGB, CORE_A * k);
          ctx.lineWidth = w * (0.12 + 0.10 * k);
          poly(ctx, T, ln.shape); ctx.stroke();
        }
      }
    }
    ctx.lineCap = 'round';
  }


  // ------------------------------------------------------------------ faróis
  // BARRA COM CONTORNO, SEM HALO. O halo (`blitGlow` de 1,2·w a 45%) existia para o
  // farol "parecer um LED visto de longe" — e o preço era uma bola colorida de 36 px
  // em cima de cada linha de parada, justamente onde a fila já está acesa. Doze
  // cruzamentos × quatro aproximações = 48 bolas: era metade da sujeira da tela.
  //
  // O problema que o halo tentava resolver é real e está medido na §4: `farol vermelho
  // sobre a banda` dá 1,12 de contraste, ou seja, some. A solução aqui é a que o
  // projetor consegue de verdade — o preto, que é o único valor garantidamente abaixo
  // de qualquer fundo. Um traço ESCURO mais largo por baixo separa a barra da banda por
  // borda local, custa um stroke, e não acende nada.
  _paintSignals(ctx, tls) {
    const T = this.T, mult = this.laneMult();
    const w = this.laneW * T.s * mult;
    ctx.lineCap = 'butt';
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
        const barra = (lw, cor) => {
          ctx.beginPath();
          ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
          ctx.lineWidth = lw; ctx.strokeStyle = cor; ctx.stroke();
        };
        barra(Math.max(5.5, w * 0.60), COL.sigEdge);     // a moldura escura
        barra(Math.max(3.5, w * 0.40), col);             // a barra do estado
        // NÚCLEO BRANCO no miolo: entrega a leitura por LUMINÂNCIA, que é o canal que
        // sobrevive num projetor fraco, enquanto a cor em volta entrega o ESTADO.
        ctx.beginPath();
        ctx.moveTo(x0 * 0.66 + cx * 0.34, y0 * 0.66 + cy * 0.34);
        ctx.lineTo(x1 * 0.66 + cx * 0.34, y1 * 0.66 + cy * 0.34);
        ctx.lineWidth = Math.max(1.6, w * 0.18);
        ctx.strokeStyle = COL.sigCore;
        ctx.stroke();
      }
    }
    ctx.lineCap = 'round';
  }


  _paintCars(ctx, vehicles, footprint, verdade) {
    const T = this.T;
    const sp0 = this.sprite || this._medeSprite();
    const L = sp0.corpo, D = sp0.largura, r = D * 0.28;
    const footPx = sp0.footPx;
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

      // PEGADA DO SUMO como rastro: o espaço que o modelo reserva atrás do carro.
      // Só aparece quando ela é MAIOR que o corpo desenhado (`footPx > L·1,15`) e só
      // em quem está parando — no fluxo livre não há fila para representar, e um
      // rastro claro fora da via vira sujeira de render.
      if (footprint && footPx > L * 1.15 && f < 0.35) {
        const peso = 1 - f / 0.35;
        const g = ctx.createLinearGradient(0, 0, -footPx, 0);
        g.addColorStop(0, 'rgba(255,255,255,0)');
        g.addColorStop(0.14, col);
        g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.globalAlpha = 0.08 + 0.17 * peso;
        ctx.fillStyle = g;
        rrect(ctx, -footPx, -D * 0.42, footPx, D * 0.84, D * 0.2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      // MOLDURA POR FORA, não contorno por cima. Um `stroke` fica metade para dentro
      // do caminho, e numa largura de ~4 px isso come um terço do corpo: o carro
      // perdia mais silhueta para o próprio contorno do que ganhava de separação.
      // Aqui a borda é um retângulo PREENCHIDO 0,8 px maior em volta, e o corpo vem
      // inteiro por cima — a moldura não tira nada do carro, e continua entregando a
      // separação por BORDA local, que é o que o olho usa para achar forma sobre a
      // fila acesa (onde o contraste global do carro cai).
      const m = 0.8;
      rrect(ctx, -L - m, -D / 2 - m, L + 2 * m, D + 2 * m, r + m);
      ctx.fillStyle = COL.carEdge; ctx.fill();
      // Corpo: um retângulo CHAPADO de cantos suaves (a posição do SUMO é o
      // para-choque DIANTEIRO, então ele recua de 0 a -L). Nesta escala forma se faz
      // com SILHUETA: cápsula de canto muito redondo lia como comprimido, e o degradê
      // de "volume" que já esteve aqui escurecia a traseira em 30% e borrava a única
      // coisa que o sprite tem para dar.
      rrect(ctx, -L, -D / 2, L, D, r);
      ctx.fillStyle = col; ctx.fill();

      // MODO VERDADE (tecla V): o carro REAL, na escala real, dentro do sprite. Com o
      // sprite grande ele deixou de ser curiosidade e virou a prova de QUANTO o
      // desenho exagera — a foto de bancada precisa dele mais do que antes.
      if (verdade) {
        ctx.lineWidth = 1;
        ctx.strokeStyle = COL.truth;
        ctx.strokeRect(-sp0.realC, -sp0.realL / 2, sp0.realC, sp0.realL);
      }

      ctx.restore();
      // SEM HALO NO CARRO PARADO. Ele era um disco de 1,7·D em volta de cada veículo
      // parado — e carro parado anda em fila, então os halos se somavam e a fila
      // inteira virava uma névoa clara onde não se contava mais nada. Quem diz
      // "parado" é a cor quente do corpo e a banda de acúmulo embaixo dele.
    }
  }

}
