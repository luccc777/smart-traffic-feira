// placar.js — as três barras vivas em CARROS ENTREGUES. O que o público lê.
//
// O contrato é o C7 (`feira/contratos/frame.py`): a mensagem `placar` traz `fase`,
// `t`, `t_restante`, `chave` e `linhas`, com os TRÊS braços no MESMO `t` simulado.
// Este arquivo não inventa métrica: ele desenha o que veio.
//
// TRÊS DECISÕES QUE MANDAM AQUI
// -----------------------------
// 1. A MANCHETE É `entregues`. Tempo de viagem e fila são secundárias, em corpo
//    menor. O motivo está no cabeçalho do C7: a média de tempo só conta quem CHEGOU,
//    então quem trava a rede ganharia com a média dos poucos sobreviventes;
//    `entregues` colapsa sob travamento e não é enganável do mesmo jeito.
//
// 2. A ESCALA DA BARRA NÃO É FIXA E NÃO É "O MÁXIMO É A RL". Ela sai de quem estiver
//    na frente AGORA, arredondada para cima em passos de 10 carros, e NUNCA encolhe
//    dentro de uma rodada. Duas armadilhas que isso evita:
//      · fixar em "o máximo é a RL" quebra assim que a RL fica em último — e hoje ela
//        FICA (93 e 82 entregues contra 111 e 109 do timer na rede aberta), e o A6
//        está retreinando em paralelo, então o regime vai mudar de novo;
//      · fixar num absoluto chumbado quebra quando a demanda ou a janela mudarem.
//    `entregues` cresce monotonicamente dentro da rodada, então "nunca encolher" não
//    custa nada e elimina o tremor de escala.
//
// 3. A ORDEM DAS LINHAS É FIXA (timer, rede, você), a COLOCAÇÃO é que muda. Reordenar
//    as linhas por posição faria a tela dançar a cada carro entregue e obrigaria a
//    plateia a reler os rótulos. A colocação aparece num selo 1º/2º/3º ao lado da
//    barra — explícita, e correta em qualquer ordem, inclusive com a RL em último.
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

const ORDEM = ['timer', 'rl', 'humano'];
const ROTULO = { timer: 'TIMER FIXO', rl: 'REDE NEURAL', humano: 'VOCÊ' };
const PASSO = 10;          // granularidade da escala, em carros
const FOLGA = 1.12;        // o líder ocupa ~89% do trilho: a barra ainda "cresce"

const int = n => (n == null || !isFinite(n)) ? '—' : String(Math.round(n));
const dec = (n, c = 1) => (n == null || !isFinite(n)) ? '—'
  : n.toFixed(c).replace('.', ',');

// As duas regras acima, como funções PURAS. Estão separadas da classe de propósito:
// são elas que carregam as decisões 2 e 3 do cabeçalho, e um teste que precise de DOM
// para provar "a escala não se ancora na RL" não seria rodado.

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
 *   estado  'vencedor' | 'empate' | 'nao_pareada' | 'sem_placar' | 'em_curso'
 *   coroa   o braço a coroar, ou null — NUNCA preenchido fora de 'vencedor'
 *   compara false = a tela não pode apresentar colocação nem régua
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

export class Placar {
  constructor(raiz) {
    this.raiz = raiz;
    this.linhas = {};
    this.escala = PASSO;
    this.ultima = null;
    for (const braco of ORDEM) this.linhas[braco] = this._monta(braco);
  }

  _monta(braco) {
    const el = document.createElement('div');
    el.className = 'pl-linha';
    el.dataset.braco = braco;
    el.hidden = true;
    el.innerHTML = `
      <div class="pl-id">
        <span class="pl-pos">—</span>
        <span class="pl-rot">${ROTULO[braco]}</span>
        <span class="pl-tag"></span>
      </div>
      <div class="pl-trilho">
        <i class="pl-fill"></i>
        <i class="pl-regua" hidden></i>
        <span class="pl-ticks"></span>
        <b class="pl-moldura" hidden></b>
      </div>
      <div class="pl-num"><b>—</b></div>
      <div class="pl-sec">
        <span>fila <b class="pl-fila">—</b></span>
        <span>viagem <b class="pl-tt">—</b> s</span>
      </div>`;
    this.raiz.appendChild(el);
    return {
      el,
      pos: el.querySelector('.pl-pos'),
      tag: el.querySelector('.pl-tag'),
      fill: el.querySelector('.pl-fill'),
      regua: el.querySelector('.pl-regua'),
      ticks: el.querySelector('.pl-ticks'),
      moldura: el.querySelector('.pl-moldura'),
      num: el.querySelector('.pl-num b'),
      fila: el.querySelector('.pl-fila'),
      tt: el.querySelector('.pl-tt'),
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
    }
  }

  // `linhas` = a lista `linhas` da mensagem `placar` (C7). `vencedor` só no RESULTADO.
  // `compara=false` (rodada não pareada) tira COLOCAÇÃO, RÉGUA e COROA — as três são
  // afirmações de comparação, e é exatamente a comparação que não vale.
  atualiza(linhas, { vencedor = null, fase = '', compara = true } = {}) {
    const vivas = (linhas || []).filter(l => ORDEM.includes(l.braco));
    this.ultima = vivas;
    this.escala = escalaPara(vivas, this.escala);     // ver decisão 2 do cabeçalho
    // Empate fica na MESMA posição: inventar desempate por tempo médio seria trocar a
    // manchete por baixo do pano.
    const posDe = compara ? colocacoes(vivas) : {};

    // A RÉGUA: o timer fixo é a referência do projeto, então ele vira uma marca
    // vertical atravessando os TRÊS trilhos. Quem está à direita da régua está
    // ganhando do plano fixo; quem está à esquerda, perdendo. É a leitura de longe,
    // sem ler número — e ela funciona com a RL em qualquer colocação.
    const ref = compara ? vivas.find(l => l.braco === 'timer') : null;
    const refFrac = ref ? Math.min(1, (ref.entregues || 0) / this.escala) : null;

    for (const braco of ORDEM) {
      const L = this.linhas[braco];
      const d = vivas.find(l => l.braco === braco);
      L.el.hidden = !d;
      if (!d) continue;
      const frac = Math.min(1, (d.entregues || 0) / this.escala);
      L.fill.style.width = (frac * 100).toFixed(2) + '%';
      L.num.textContent = int(d.entregues);
      L.fila.textContent = dec(d.fila);
      L.tt.textContent = dec(d.tempo_medio, 0);
      L.pos.textContent = compara ? posDe[braco] + 'º' : '—';
      L.tag.textContent = d.fantasma ? 'pré-computado' : 'ao vivo';
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
    this.raiz.dataset.escala = String(this.escala);
    this.raiz.dataset.compara = compara ? '1' : '0';
    return { escala: this.escala, posicoes: posDe, compara };
  }
}

export { ORDEM, ROTULO, PASSO, FOLGA };
