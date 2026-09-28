// placar.js — a tarja de estatísticas da projeção. O que o público lê.
//
// O contrato é o C7 (`feira/contratos/frame.py`): a mensagem `placar` traz `fase`,
// `t`, `t_restante`, `chave` e `linhas`, com os TRÊS braços no MESMO `t` simulado.
// Este arquivo não inventa métrica: ele desenha o que veio.
//
// A FORMA VEM DA REFERÊNCIA, a tarja `#solo` da projeção do maquete
// (`smart-traffic-maquete/dashboard/frontend/projecao/`). De lá vêm os elementos e a
// distribuição: uma COLUNA POR MÉTRICA, separadas por filete; em cada coluna o rótulo
// pequeno em versalete, o DELTA grande com seta (▲/▼, verde quando melhora) e uma
// linha fina por política — barra proporcional + número tabular. A adaptação está
// explicada no `index.html`: lá são dois braços e cada coluna repete os rótulos; aqui
// são três, e a identidade saiu para uma coluna própria à esquerda.
//
// SEIS DECISÕES QUE MANDAM AQUI
// -----------------------------
// 1. A MANCHETE É `entregues`. Tempo de viagem e fila são as OUTRAS DUAS COLUNAS, em
//    barra fina e sem régua. O motivo está no cabeçalho do C7: a média de tempo só
//    conta quem CHEGOU, então quem trava a rede ganharia com a média dos poucos
//    sobreviventes; `entregues` colapsa sob travamento e não é enganável do mesmo
//    jeito. Por isso a coluna dela é a mais larga, e é a única com régua, ticks e
//    moldura de vencedor.
//
// 2. A ESCALA DA BARRA DE `entregues` NÃO É FIXA E NÃO É "O MÁXIMO É A RL". Ela sai de
//    quem estiver na frente AGORA, arredondada para cima em passos de 10 carros, e
//    NUNCA encolhe dentro de uma rodada. Duas armadilhas que isso evita:
//      · fixar em "o máximo é a RL" quebra assim que a RL fica em último — e ela já
//        ficou (93 e 82 contra 111 e 109 do timer, antes do retreino do A6) e hoje
//        ganha (120 e 126 contra 111 e 109). Os dois regimes já passaram por aqui;
//      · fixar num absoluto chumbado quebra quando a demanda ou a janela mudarem.
//    `entregues` cresce monotonicamente dentro da rodada, então "nunca encolher" não
//    custa nada e elimina o tremor de escala. As outras duas métricas NÃO crescem
//    monotonicamente (a fila sobe e desce), então lá a escala é o máximo do quadro —
//    como na referência, que normaliza cada métrica pelo maior dos dois braços.
//
// 3. A ORDEM DAS LINHAS É FIXA (timer, rede, você), a COLOCAÇÃO é que muda. Reordenar
//    as linhas por posição faria a tela dançar a cada carro entregue e obrigaria a
//    plateia a reler os rótulos. A colocação aparece num selo 1º/2º/3º ao lado do
//    nome — explícita, e correta em qualquer ordem, inclusive com a RL em último.
//
// 4. `vencedor: null` NÃO É UM ESTADO. São quatro, e o C7 agora deixa separá-los com
//    `pareado` e `motivo`. Misturá-los foi o defeito que o motor carregava calado:
//
//      pareado=false                  -> a rodada NÃO VALE (os braços partiram de
//                                        estados diferentes em t0). Sem vencedor E
//                                        SEM COLOCAÇÃO: se a comparação não vale,
//                                        segundo lugar também não existe.
//      vencedor != null               -> alguém venceu.
//      sem linha do humano            -> a rodada não chegou ao fim (abortada, ou o
//                                        SUMO caiu). Não é empate: ninguém empatou.
//      resto (humano presente, topo
//      compartilhado)                 -> EMPATE, resultado legítimo.
//
//    `veredito()` embaixo é essa decisão, isolada e pura — é ela que o teste prova.
//
// 5. O DELTA CONTRA O TIMER É DERIVADO AQUI, e de propósito. O C7 não manda delta
//    nenhum: manda três braços no mesmo `t`. A subtração é da TELA, não do contrato —
//    e ela some junto com a colocação quando `compara` é falso, porque "+7 contra o
//    timer" é uma afirmação de comparação igual a "2º lugar".
//
//    ONDE ELE MORA MUDOU. Era um número por linha, ao lado de cada barra; agora é a
//    MANCHETE DE CADA COLUNA, grande e com seta, na forma da referência. A troca não
//    é de gosto: com três braços havia dois deltas por métrica competindo pelo mesmo
//    olhar, e nenhum dos dois era a pergunta da tela. A pergunta é "o protagonista da
//    rodada está ganhando do plano fixo?" — o protagonista é o VOCÊ quando há humano,
//    e a REDE no ocioso. A porcentagem vai grande; o absoluto (+9 carros) fica logo
//    atrás, menor, porque é ele que torna a porcentagem auditável.
//
// 6. AQUECIMENTO, herdado da referência (`AQUECIMENTO` em projecao.js do maquete).
//    Nos primeiros segundos um braço tem 2 viagens e o outro 0, e a tela anunciaria
//    "▲ 100%" — verdadeiro na aritmética e falso na substância. Abaixo de 8 entregues
//    dos dois lados o delta sai como "—". As BARRAS continuam desenhando: elas não
//    mentem, só ainda não dizem muito.

const ORDEM = ['timer', 'rl', 'humano'];
const ROTULO = { timer: 'TIMER FIXO', rl: 'REDE NEURAL', humano: 'VOCÊ' };
const CURTO = { timer: 'timer', rl: 'rede', humano: 'você' };
const PASSO = 10;          // granularidade da escala, em carros
const FOLGA = 1.12;        // o líder ocupa ~89% do trilho: a barra ainda "cresce"
const AQUECIMENTO = 8;     // entregues mínimos dos dois lados para o delta existir

const int = n => (n == null || !isFinite(n)) ? '—' : String(Math.round(n));
const dec = (n, c = 1) => (n == null || !isFinite(n)) ? '—'
  : n.toFixed(c).replace('.', ',');

// As TRÊS COLUNAS da tarja, na ordem em que aparecem. `maior` diz para que lado é
// melhor — é o que decide a seta e a cor do delta, e é por isso que "tempo caiu 6%"
// sai verde e "fila subiu 6%" sai âmbar sem ninguém escrever a regra duas vezes.
// `−0 carros` é o tipo de coisa que sai de um formatador ingênuo e que a plateia lê
// como defeito. Quando o absoluto arredonda para zero, o texto é "empatado".
const sinal = d => (d > 0 ? '+' : '−');

const METRICAS = [
  { chave: 'entregues', nome: 'carros entregues', maior: true, fmt: int,
    abs: d => Math.round(d) === 0 ? 'empatado'
      : `${sinal(d)}${Math.abs(Math.round(d))} ${Math.abs(Math.round(d)) === 1 ? 'carro' : 'carros'}` },
  { chave: 'tempo_medio', nome: 'tempo de viagem', maior: false,
    fmt: v => v > 0 ? dec(v, 0) + ' s' : '—',
    abs: d => Math.abs(d) < 0.5 ? 'empatado' : `${sinal(d)}${dec(Math.abs(d), 0)} s` },
  { chave: 'fila', nome: 'carros parados', maior: false, fmt: v => dec(v, 1),
    abs: d => Math.abs(d) < 0.05 ? 'empatado' : `${sinal(d)}${dec(Math.abs(d), 1)}` },
];

// As regras 2 e 3 acima, como funções PURAS. Estão separadas da classe de propósito:
// um teste que precise de DOM para provar "a escala não se ancora na RL" não seria
// rodado.

/** A escala do trilho, em carros. Nunca ancora num braço; nunca encolhe na rodada. */
export function escalaPara(linhas, escalaAtual = PASSO) {
  const maior = Math.max(1, ...linhas.map(l => l.entregues || 0));
  const alvo = Math.ceil((maior * FOLGA) / PASSO) * PASSO;
  return Math.max(alvo, escalaAtual || PASSO);
}

/**
 * O veredito de uma mensagem `placar` do C7, sem tocar em DOM.
 *
 * Devolve `{estado, coroa, motivo, compara}`:
 *   estado  'vencedor' | 'empate' | 'nao_pareada' | 'travou' | 'sem_placar' | 'em_curso'
 *   coroa   o braço a coroar, ou null — NUNCA preenchido fora de 'vencedor'
 *   compara false = a tela não pode apresentar colocação nem régua
 *   sinais  só em 'travou': os sinais de saúde que dispararam (C7 `sinais`)
 */
export function veredito(msg) {
  const linhas = (msg && msg.linhas) || [];
  const motivo = (msg && msg.motivo) || '';
  // `pareado` ausente = mensagem antiga (antes do campo existir): assume pareada, que
  // é como a tela se comportava. O campo só some para trás, nunca para frente.
  const pareado = !msg || msg.pareado === undefined ? true : !!msg.pareado;
  if (!pareado) {
    return { estado: 'nao_pareada', coroa: null, motivo, compara: false };
  }
  if (!msg || msg.fase !== 'resultado') {
    return { estado: 'em_curso', coroa: null, motivo, compara: true };
  }
  // O SEXTO DESFECHO: a malha travou no braço humano (`sinais` não vazio, C7). É o
  // portão de saúde da rodada curta (docs/DIFICULDADE.md §7): o visitante que deixou
  // os semáforos parados entrega 36 carros contra 112 — e sem este campo isso chegava
  // à tela idêntico a um EMPATE (pareado, sem vencedor, com linha do humano). Os
  // números FICAM na tela (a pessoa vê o que fez); o que sai é a comparação: sem
  // coroa, sem colocação, sem régua. `sinais` ausente = mensagem antiga = como antes.
  if (Array.isArray(msg.sinais) && msg.sinais.length) {
    return { estado: 'travou', coroa: null, motivo, compara: false,
             sinais: msg.sinais.slice() };
  }
  if (msg.vencedor) {
    return { estado: 'vencedor', coroa: msg.vencedor, motivo, compara: true };
  }
  // Sem a linha do humano a rodada não aconteceu — abortada pelo operador ou o SUMO
  // caiu. Chamar isso de "empate" seria dar ao visitante um resultado que ele não fez.
  const temHumano = linhas.some(l => l.braco === 'humano');
  const topo = Math.max(-Infinity, ...linhas.map(l => l.entregues || 0));
  const noTopo = linhas.filter(l => (l.entregues || 0) === topo).length;
  if (!temHumano || linhas.length < 2 || noTopo < 2) {
    return { estado: 'sem_placar', coroa: null, motivo, compara: true };
  }
  return { estado: 'empate', coroa: null, motivo, compara: true };
}

/**
 * O delta de um braço contra a RÉGUA (o timer fixo), em carros entregues.
 *
 * Devolve `null` quando não há régua na mensagem, e para o PRÓPRIO timer: "o timer
 * está 0 à frente do timer" é ruído, não informação. Quem lê a tela quer saber se
 * está ganhando DO PLANO FIXO, que é a pergunta do projeto inteiro.
 */
export function deltaContraRegua(linhas, braco) {
  const ref = (linhas || []).find(l => l.braco === 'timer');
  const eu = (linhas || []).find(l => l.braco === braco);
  if (!ref || !eu || braco === 'timer') return null;
  return (eu.entregues || 0) - (ref.entregues || 0);
}

/**
 * O MESMO delta em PORCENTAGEM da régua. `null` quando não há delta, e também
 * quando a régua ainda está em zero — dividir por zero no primeiro segundo da
 * rodada produziria um "+Infinity%" na tela.
 *
 * Ele existe porque o absoluto sozinho MENTE por omissão. A campanha do A8 mede
 * +11,6 carros da RL sobre o timer em 120 s — o mesmo número é +10,3% de vazão.
 * "Dez carros" soa a ruído; "10%" é o resultado do projeto. São o mesmo dado.
 */
export function deltaPercentual(linhas, braco) {
  const d = deltaContraRegua(linhas, braco);
  if (d == null) return null;
  const ref = (linhas || []).find(l => l.braco === 'timer');
  const base = ref ? (ref.entregues || 0) : 0;
  return base > 0 ? (100 * d) / base : null;
}

/** Colocação por `entregues`, empate na MESMA posição (1, 1, 3). */
export function colocacoes(linhas) {
  const ordenado = [...linhas].sort((a, b) => (b.entregues || 0) - (a.entregues || 0));
  const pos = {};
  ordenado.forEach((l, i) => {
    const anterior = ordenado[i - 1];
    pos[l.braco] = (anterior && anterior.entregues === l.entregues)
      ? pos[anterior.braco] : i + 1;
  });
  return pos;
}

/**
 * Quem é o PROTAGONISTA da comparação — de quem é o delta que vai grande em cada
 * coluna. É o humano quando ele está na rodada, e a rede neural no ocioso (onde o
 * mapa já está mostrando a RL ao vivo). Nunca o timer: ele é a régua.
 */
export function protagonista(linhas) {
  const tem = b => (linhas || []).some(l => l.braco === b);
  return tem('humano') ? 'humano' : (tem('rl') ? 'rl' : null);
}

/**
 * O delta de UMA métrica qualquer contra o timer, em porcentagem, com o sinal cru
 * (positivo = subiu). Quem decide se subir é bom é a coluna, não esta função.
 *
 * `null` quando falta um dos lados, quando a régua está em zero, ou quando a rodada
 * ainda não aqueceu (regra 6): abaixo de `AQUECIMENTO` entregues dos dois lados
 * qualquer razão é ruído amplificado.
 */
export function deltaMetrica(linhas, braco, chave) {
  const ref = (linhas || []).find(l => l.braco === 'timer');
  const eu = (linhas || []).find(l => l.braco === braco);
  if (!ref || !eu || braco === 'timer') return null;
  if ((ref.entregues || 0) < AQUECIMENTO || (eu.entregues || 0) < AQUECIMENTO) return null;
  const a = Number(ref[chave]) || 0, b = Number(eu[chave]) || 0;
  if (!(a > 0)) return null;
  return { pct: (b - a) / a * 100, abs: b - a };
}

export class Placar {
  constructor(raiz) {
    this.raiz = raiz;
    this.linhas = {};
    this.cabs = {};
    this.escala = PASSO;
    this.ultima = null;
    this._montaCabecalho();
    for (const braco of ORDEM) this.linhas[braco] = this._monta(braco);
  }

  // A primeira linha da grade: o rótulo e o delta de cada coluna. A célula da
  // identidade fica com o período da rodada — é a legenda de "entregues em quanto
  // tempo", e sem ela o número da manchete não tem unidade.
  // A célula da identidade (marca + relógio) é estática, vem do index.html e já está
  // na grade. Aqui entram só os cabeçalhos das métricas.
  _montaCabecalho() {
    for (const m of METRICAS) {
      const el = document.createElement('div');
      el.className = 't-hd';
      el.dataset.m = m.chave;
      el.innerHTML = `
        <div class="t-linha">
          <span class="t-name">${m.nome}</span>
          <span class="t-quem"></span>
        </div>
        <div class="vitem"><b>—</b><i class="pl-delta"></i></div>`;
      this.raiz.appendChild(el);
      this.cabs[m.chave] = {
        el,
        quem: el.querySelector('.t-quem'),
        vitem: el.querySelector('.vitem'),
        pct: el.querySelector('.vitem b'),
        abs: el.querySelector('.pl-delta'),
      };
    }
  }

  _monta(braco) {
    const el = document.createElement('div');
    el.className = 'pl-linha';
    el.dataset.braco = braco;
    el.hidden = true;
    // A coluna de `entregues` é a única com régua, ticks e moldura: é a manchete
    // (regra 1). As outras duas são barra e número, como na referência.
    el.innerHTML = `
      <div class="pl-id">
        <span class="pl-pos">—</span>
        <span class="pl-rot">${ROTULO[braco]}</span>
        <span class="pl-tag"></span>
      </div>
      <div class="pl-cel" data-m="entregues">
        <span class="pl-trilho">
          <i class="pl-fill"></i>
          <i class="pl-regua" hidden></i>
          <span class="pl-ticks"></span>
          <b class="pl-moldura" hidden></b>
        </span>
        <span class="pl-num">—</span>
      </div>
      <div class="pl-cel" data-m="tempo_medio">
        <span class="t-track"><i></i></span><span class="t-val">—</span>
      </div>
      <div class="pl-cel" data-m="fila">
        <span class="t-track"><i></i></span><span class="t-val">—</span>
      </div>`;
    this.raiz.appendChild(el);
    const cel = chave => el.querySelector(`.pl-cel[data-m="${chave}"]`);
    return {
      el,
      pos: el.querySelector('.pl-pos'),
      tag: el.querySelector('.pl-tag'),
      fill: el.querySelector('.pl-fill'),
      regua: el.querySelector('.pl-regua'),
      ticks: el.querySelector('.pl-ticks'),
      moldura: el.querySelector('.pl-moldura'),
      num: el.querySelector('.pl-num'),
      barras: {
        tempo_medio: cel('tempo_medio').querySelector('.t-track i'),
        fila: cel('fila').querySelector('.t-track i'),
      },
      vals: {
        tempo_medio: cel('tempo_medio').querySelector('.t-val'),
        fila: cel('fila').querySelector('.t-val'),
      },
    };
  }

  // Chamado quando a rodada recomeça: a escala de uma rodada não vale para a próxima.
  reinicia() {
    this.escala = PASSO;
    this.ultima = null;
    for (const braco of ORDEM) {
      const L = this.linhas[braco];
      L.el.hidden = true;
      L.el.classList.remove('venceu', 'perdeu');
      L.moldura.hidden = true;
      L.fill.style.width = '0%';
      L.num.textContent = '—';
      for (const k of ['tempo_medio', 'fila']) {
        L.barras[k].style.width = '0%';
        L.vals[k].textContent = '—';
      }
    }
    for (const m of METRICAS) this._cabVazio(m.chave);
  }

  _cabVazio(chave) {
    const C = this.cabs[chave];
    if (!C) return;
    C.pct.textContent = '—';
    C.abs.textContent = '';
    C.quem.textContent = '';
    C.vitem.className = 'vitem';
  }

  // `linhas` = a lista `linhas` da mensagem `placar` (C7). `vencedor` só no RESULTADO.
  // `compara=false` (rodada não pareada) tira COLOCAÇÃO, RÉGUA, DELTA e COROA — as
  // quatro são afirmações de comparação, e é exatamente a comparação que não vale.
  atualiza(linhas, { vencedor = null, fase = '', compara = true } = {}) {
    const vivas = (linhas || []).filter(l => ORDEM.includes(l.braco));
    this.ultima = vivas;
    this.escala = escalaPara(vivas, this.escala);     // ver regra 2 do cabeçalho
    // Empate fica na MESMA posição: inventar desempate por tempo médio seria trocar a
    // manchete por baixo do pano.
    const posDe = compara ? colocacoes(vivas) : {};

    // A RÉGUA: o timer fixo é a referência do projeto, então ele vira uma marca
    // vertical atravessando os trilhos de `entregues`. Quem está à direita da régua
    // está ganhando do plano fixo; quem está à esquerda, perdendo. É a leitura de
    // longe, sem ler número — e ela funciona com a RL em qualquer colocação.
    const ref = compara ? vivas.find(l => l.braco === 'timer') : null;
    const refFrac = ref ? Math.min(1, (ref.entregues || 0) / this.escala) : null;

    // As escalas das outras duas colunas: o maior do quadro, como na referência.
    const maxDe = {};
    for (const k of ['tempo_medio', 'fila']) {
      maxDe[k] = Math.max(1e-9, ...vivas.map(l => Number(l[k]) || 0));
    }

    for (const braco of ORDEM) {
      const L = this.linhas[braco];
      const d = vivas.find(l => l.braco === braco);
      L.el.hidden = !d;
      if (!d) continue;
      const frac = Math.min(1, (d.entregues || 0) / this.escala);
      L.fill.style.width = (frac * 100).toFixed(2) + '%';
      L.num.textContent = int(d.entregues);
      L.pos.textContent = compara ? posDe[braco] + 'º' : '—';
      L.tag.textContent = d.fantasma ? 'pré-computado' : 'ao vivo';
      for (const m of METRICAS.slice(1)) {
        const v = Number(d[m.chave]) || 0;
        L.barras[m.chave].style.width = (v / maxDe[m.chave] * 100).toFixed(1) + '%';
        L.vals[m.chave].textContent = m.fmt(v);
      }
      L.el.classList.toggle('fantasma', !!d.fantasma);
      L.ticks.style.setProperty('--ticks', String(this.escala / PASSO));
      if (refFrac != null && braco !== 'timer') {
        L.regua.hidden = false;
        L.regua.style.left = (refFrac * 100).toFixed(2) + '%';
      } else {
        L.regua.hidden = true;
      }
      const venceu = compara && fase === 'resultado' && vencedor === braco;
      L.el.classList.toggle('venceu', venceu);
      L.el.classList.toggle('perdeu',
                            compara && fase === 'resultado' && !!vencedor && !venceu);
      // O vencedor é marcado por MOLDURA e por texto, nunca só por cor: a barra do
      // VOCÊ já é a mais clara possível, e não há cor acima dela para "realçar"
      // (medido: qualquer realce sobre ela fica em 1,1 de contraste).
      L.moldura.hidden = !venceu;
    }

    this._manchetes(vivas, compara);

    this.raiz.dataset.escala = String(this.escala);
    this.raiz.dataset.compara = compara ? '1' : '0';
    // Quantas linhas a tarja tem de abrir. No OCIOSO não existe braço humano, e uma
    // grade fixa de três deixaria um terço da tarja vazio a feira inteira.
    this.raiz.dataset.n = String(vivas.length);
    return { escala: this.escala, posicoes: posDe, compara };
  }

  // O delta grande de cada coluna: o protagonista contra a régua (regra 5).
  _manchetes(vivas, compara) {
    const alvo = compara ? protagonista(vivas) : null;
    if (!alvo) {
      for (const m of METRICAS) this._cabVazio(m.chave);
      return;
    }
    for (const m of METRICAS) {
      const C = this.cabs[m.chave];
      C.quem.textContent = `${CURTO[alvo]} vs timer`;
      const dd = deltaMetrica(vivas, alvo, m.chave);
      if (!dd) { C.pct.textContent = '—'; C.abs.textContent = ''; C.vitem.className = 'vitem'; continue; }
      // 0,05 de zona morta: sem ela a seta pisca entre ▲ e ▼ a cada quadro quando os
      // dois braços estão praticamente empatados, que é o caso mais comum no começo.
      const melhor = m.maior ? dd.pct > 0.05 : dd.pct < -0.05;
      const pior = m.maior ? dd.pct < -0.05 : dd.pct > 0.05;
      const seta = dd.pct > 0.05 ? '▲' : (dd.pct < -0.05 ? '▼' : '·');
      C.pct.textContent = `${seta} ${dec(Math.abs(dd.pct), 1)}%`;
      C.abs.textContent = m.abs(dd.abs);
      C.vitem.className = 'vitem ' + (melhor ? 'bom' : pior ? 'ruim' : '');
    }
  }
}

/**
 * O quadro de recordes, desenhado a partir de `GET /api/ranking`.
 *
 * POR QUE ELE MOSTRA "bateu a IA" E NÃO SÓ O NÚMERO: o quadro ordena por carros
 * entregues, e carros entregues dependem da SEED — `docs/DIFICULDADE.md` §5 mede de
 * 89 a 146 entregues na MESMA política, dependendo da hora de trânsito sorteada.
 * Então o primeiro lugar pode ter jogado um cenário mais fácil que o quinto. A
 * marca "bateu a IA" é a única coluna justa entre seeds, porque compara cada
 * visitante com a rede neural da rodada DELE. Sem ela o quadro seria um ranking de
 * sorte com cara de ranking de habilidade.
 */
/** O título do quadro: "MELHORES DA FEIRA", ou "MELHORES · ÚLTIMOS 30 MIN" com validade. */
export function tituloDoQuadro(dados) {
  const v = dados && dados.validade_s;
  if (!v || !isFinite(v) || v <= 0) return 'MELHORES DA FEIRA';
  const min = Math.round(v / 60);
  return min >= 1 ? `MELHORES · ÚLTIMOS ${min} MIN` : 'MELHORES · AGORA';
}

export class QuadroDeRecordes {
  constructor(lista, resumo) {
    this.lista = lista;
    this.resumo = resumo;
    this.desenha(null);
  }

  desenha(dados) {
    const topo = (dados && dados.topo) || [];
    // VALIDADE: com `validade_s` no JSON o quadro é dos últimos N minutos, não do dia
    // — senão quem jogou bem às 9h é o campeão o evento inteiro e ninguém que chega
    // às 15h tem o que bater. O título diz qual dos dois está na tela.
    const titulo = this.lista.ownerDocument && this.lista.ownerDocument.getElementById('rk-titulo');
    if (titulo) titulo.textContent = tituloDoQuadro(dados);
    // O resumo ("27 rodadas · 11 venceram a IA") era a menor linha da tela inteira,
    // em 15 px, e contava do DIA — não da pessoa que está na frente do projetor. Ficou
    // só no `resultado`, onde a tarja é a tela toda e há corpo para ele.
    if (this.resumo) {
      this.resumo.textContent = dados && dados.total
        ? `${dados.total} rodadas · ${dados.vitorias} venceram a IA`
          + (dados.venceram_timer != null ? ` · ${dados.venceram_timer} venceram o timer` : '')
        : '';
    }
    this.lista.replaceChildren();
    if (!topo.length) {
      const li = document.createElement('li');
      li.className = 'vazio';
      li.textContent = dados && dados.desligado
        ? 'quadro desligado nesta sessão'
        : 'ninguém jogou ainda. A primeira rodada do dia abre o quadro.';
      this.lista.appendChild(li);
      return;
    }
    topo.forEach((m, i) => {
      const li = document.createElement('li');
      if (m.venceu) li.classList.add('bateu');
      const pos = document.createElement('span');
      pos.className = 'rk-pos';
      pos.textContent = (i + 1) + 'º';
      const r = linhaRecorde(m);
      if (r.v2) {
        // A LINHA DA v2: nome, SCORE e medalha. O número cru saiu da linha — ele
        // depende da seed (89 a 146 na mesma política, DIFICULDADE.md §5), e o score
        // pareado contra o timer é o que ordena o quadro. O cru continua no arquivo.
        li.classList.add('v2');
        if (r.medalha) li.classList.add('med-' + r.medalha);
        const nome = document.createElement('span');
        nome.className = 'rk-nome';
        nome.textContent = r.rotulo;
        const n = document.createElement('b');
        n.textContent = r.score;
        const med = document.createElement('i');
        med.className = 'rk-med' + (r.medalha ? ' ' + r.medalha : '');
        med.textContent = r.letra;
        med.title = r.medalhaTexto;
        li.append(pos, nome, n, med);
      } else {
        const n = document.createElement('b');
        n.textContent = m.entregues;
        const nota = document.createElement('span');
        nota.className = 'rk-nota';
        // Contra a RL DAQUELA rodada — é o que torna a linha comparável entre seeds.
        nota.textContent = m.venceu ? 'bateu a IA'
          : (m.rl ? `IA fez ${m.rl}` : '');
        // A HORA SAIU. `14:22` não diz nada a quem está olhando o quadro — nem quem
        // jogou, nem quão difícil foi — e era mais uma coluna de 19 px atravessando a
        // tarja. O que a linha precisa carregar é o número e se aquela pessoa bateu a
        // rede; a hora continua no `results/feira/ranking.json`, que é onde ela serve.
        li.append(pos, n, nota);
      }
      this.lista.appendChild(li);
    });
  }
}

// ------------------------------------------------------------- gamificação
// O que a gamificação (docs/GAMIFICACAO.md) acrescenta ao quadro e ao resultado, como
// funções PURAS: a marca do ranking (`feira/jogo/ranking.py`) vira texto aqui, e o
// teste prova a decisão sem DOM.

const MEDALHA = {
  ouro: { letra: 'O', texto: 'OURO · bateu a rede neural' },
  prata: { letra: 'P', texto: 'PRATA · lado a lado com a rede' },
  bronze: { letra: 'B', texto: 'BRONZE · bateu o timer' },
};

/** `+15`, `−4`, `0` — o score do quadro, sempre com sinal (é uma diferença). */
export function formataScore(n) {
  if (n == null || !isFinite(n)) return '—';
  const v = Math.round(n);
  return v > 0 ? `+${v}` : (v < 0 ? `−${Math.abs(v)}` : '0');
}

/**
 * Uma linha do quadro. `v2` diz se a marca veio do ranking novo (tem `score` e
 * `rotulo`); sem isso a tela desenha a linha antiga, com o número cru.
 */
export function linhaRecorde(m) {
  const v2 = !!m && m.score !== undefined && m.rotulo !== undefined;
  const med = (m && m.medalha && MEDALHA[m.medalha]) ? m.medalha : '';
  return {
    v2,
    rotulo: v2 ? String(m.rotulo || '') : '',
    score: v2 ? formataScore(m.score) : '',
    medalha: med,
    letra: med ? MEDALHA[med].letra : '',
    medalhaTexto: med ? MEDALHA[med].texto : '',
  };
}

/**
 * O texto da COLOCAÇÃO no resultado, a partir de `ultima` da mensagem `ranking`:
 * `VOCÊ FICOU EM 7º DE 31`, ou `NOVO RECORDE DA FEIRA` quando ela é a primeira.
 * `null` quando não há o que dizer (sem marca — rodada travada, não pareada, teste).
 */
export function textoColocacao(ultima) {
  if (!ultima || ultima.posicao == null) return null;
  const med = (ultima.medalha && MEDALHA[ultima.medalha]) ? ultima.medalha : '';
  const linhas = [];
  if (ultima.recorde) linhas.push('NOVO RECORDE DA FEIRA');
  linhas.push(`VOCÊ FICOU EM ${ultima.posicao}º DE ${ultima.pessoas || ultima.posicao}`);
  return {
    titulo: linhas[0],
    sub: linhas.length > 1 ? linhas[1] : '',
    medalha: med,
    letra: med ? MEDALHA[med].letra : '',
    medalhaTexto: med ? MEDALHA[med].texto : (ultima.degradada ? 'sem IA nesta rodada' : ''),
    score: formataScore(ultima.score),
    recorde: !!ultima.recorde,
  };
}

export { ORDEM, ROTULO, CURTO, PASSO, FOLGA, AQUECIMENTO, METRICAS };
