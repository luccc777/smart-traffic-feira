import { escalaPara, colocacoes, veredito } from './placar.js';

export const ALTURA_HUD = 84;
export const BRACOS_HUD = ['timer', 'rl', 'humano'];
export const NOMES_HUD = { timer: 'TIMER', rl: 'REDE NEURAL', humano: 'VOCÊ' };

// A fase nunca entra no cálculo: os prédios físicos continuam sobre os quarteirões.
export function retanguloProjecao(w, h, unidade = 1) {
  return { x: 0, y: 0, w, h: Math.max(120, h - ALTURA_HUD * unidade) };
}

export function resumoCompacto(msg, escala = 10, ritmo = 1) {
  const linhas = msg.linhas || [];
  const verdict = veredito(msg);
  const maximo = escalaPara(linhas, escala);
  const postos = verdict.compara ? colocacoes(linhas) : {};
  const segundos = ['jogando', 'contagem'].includes(msg.fase)
    ? Math.max(0, Math.ceil((msg.t_restante || 0) / (msg.fase === 'contagem' ? 1 : ritmo))) : null;
  return {
    escala: maximo,
    relogio: segundos === null ? (msg.fase === 'resultado' ? '00:00' : '—:—')
      : `${String(Math.floor(segundos / 60)).padStart(2, '0')}:${String(segundos % 60).padStart(2, '0')}`,
    barras: BRACOS_HUD.map(braco => {
      const linha = linhas.find(l => l.braco === braco);
      const valor = linha ? Number(linha.entregues || 0) : null;
      return { braco, valor, posto: postos[braco] || null,
        porcentagem: valor === null || !verdict.compara ? 0 : Math.max(0, Math.min(100, valor / maximo * 100)) };
    }),
  };
}

export class HudCompacto {
  constructor(raiz) {
    this.escala = 10;
    this.fase = '';
    this.raiz = raiz;
    raiz.innerHTML = BRACOS_HUD.map(b => `<section class="compact-card" data-braco="${b}">
      <div class="compact-label"><span>${NOMES_HUD[b]}</span><b data-valor>—</b><small data-posto></small></div>
      <div class="compact-track" role="progressbar" aria-label="Carros entregues: ${NOMES_HUD[b]}" aria-valuemin="0"><i></i></div>
    </section>`).join('') + '<time class="compact-clock" aria-label="Tempo restante">—:—</time>';
  }
  atualiza(msg, ritmo = 1) {
    if (msg.fase !== this.fase && ['ocioso', 'preparando'].includes(msg.fase)) this.escala = 10;
    this.fase = msg.fase;
    const modelo = resumoCompacto(msg, this.escala, ritmo);
    this.escala = modelo.escala;
    for (const b of modelo.barras) {
      const card = this.raiz.querySelector(`[data-braco="${b.braco}"]`);
      card.querySelector('[data-valor]').textContent = b.valor === null ? '—' : b.valor;
      card.querySelector('[data-posto]').textContent = b.posto ? `${b.posto}º` : '';
      card.querySelector('i').style.width = `${b.porcentagem}%`;
      const track = card.querySelector('[role="progressbar"]');
      track.setAttribute('aria-valuemax', modelo.escala);
      track.setAttribute('aria-valuenow', b.valor || 0);
    }
    this.raiz.querySelector('time').textContent = modelo.relogio;
  }
  invalida() {
    this.raiz.querySelector('time').textContent = '—:—';
    for (const card of this.raiz.querySelectorAll('.compact-card')) {
      card.querySelector('[data-posto]').textContent = '';
      card.querySelector('[data-valor]').textContent = '—';
      card.querySelector('i').style.width = '0%';
      card.querySelector('[role="progressbar"]').setAttribute('aria-valuenow', '0');
    }
  }
}
