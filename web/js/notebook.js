import { MAPA_TECLAS, filtraSpam, mensagemControle } from './entrada.js';
import { resumoCompacto, NOMES_HUD, BRACOS_HUD } from './compacto.js';
import { veredito } from './placar.js';
const $ = id => document.getElementById(id);
const ROTULOS = {ocioso:'Pronto para jogar',preparando:'Preparando os adversários',contagem:'Prepare-se!',jogando:'Sua vez de controlar a cidade',resultado:'Resultado da rodada'};
let fase='ocioso', ritmo=1, entradaWeb=false, conectado=false, canal=null, memo={}, iniciando=false, escs=[];
let ultimoPlacar=null, jogador=null;
let ultimoResultado=null, nomeCompetidor='Visitante';
try { ultimoResultado=JSON.parse(localStorage.getItem('st-ultimo-competidor')); } catch {}
const proto=location.protocol==='https:'?'wss':'ws';
const botoes=Object.keys(MAPA_TECLAS).map(k=>{
  const b=document.createElement('button'); b.type='button'; b.textContent=k.toUpperCase(); b.disabled=true;
  b.setAttribute('aria-label',`Semáforo ${k.toUpperCase()}`); b.onclick=()=>envia({tipo:'tecla',k});
  $('teclas').append(b); return b;
});
function habilita(){
  const pronto=conectado && entradaWeb && canal?.readyState===1;
  $('iniciar').disabled=!pronto || fase!=='ocioso' || iniciando;
  $('apelido').disabled=fase!=='ocioso' || iniciando;
  for(const b of botoes)b.disabled=!pronto || fase!=='jogando';
  $('conexao').textContent=!conectado?'Reconectando…':!entradaWeb?'Modo demonstração — jogo desligado':canal?.readyState===1?'Conectado · teclado ativo':'Conectando controles…';
}
function envia(msg){
  if(!conectado || !entradaWeb || canal?.readyState!==1)return false;
  if(msg.tipo==='tecla' && fase!=='jogando')return false;
  const filtro=filtraSpam(memo,msg,performance.now()); memo=filtro.memo;
  if(!filtro.envia)return false;
  // A letra da interface vira o índice físico já aceito pelo servidor.
  canal.send(JSON.stringify(mensagemControle(msg))); return true;
}
async function iniciar(){
  if($('iniciar').disabled)return;
  iniciando=true; habilita(); $('erro').textContent='';
  try{
    const r=await fetch('/api/jogador',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nome:$('apelido').value.trim()})});
    if(!r.ok)throw new Error('Não foi possível salvar o apelido.');
    jogador=await r.json();
    if(!envia({tipo:'start'}))throw new Error('Os controles desconectaram. Tente novamente.');
    $('apelido').blur();
  }catch(e){$('erro').textContent=e.message;iniciando=false;habilita();}
  setTimeout(()=>{if(fase==='ocioso'){iniciando=false;habilita();}},5000);
}
$('cadastro').onsubmit=e=>{e.preventDefault();iniciar();};
window.addEventListener('keydown',e=>{
  if(e.ctrlKey||e.altKey||e.metaKey||e.target.closest('input,textarea,select,[contenteditable="true"]'))return;
  const k=e.key.toLowerCase();
  if(fase==='ocioso' && e.code==='Space'){if(e.target.closest('button,a'))return;e.preventDefault();if(!e.repeat)iniciar();return;}
  if(fase!=='jogando')return;
  if(k in MAPA_TECLAS){e.preventDefault();if(!e.repeat)envia({tipo:'tecla',k});}
  if(k==='escape' && !e.repeat){escs=escs.filter(t=>performance.now()-t<1500);escs.push(performance.now());if(escs.length===3){envia({tipo:'abortar'});escs=[];}}
});
function mudaFase(nova){
  if(!nova)return;
  if(nova!==fase){iniciando=false;memo={};escs=[];if(nova==='ocioso')$('apelido').value='';}
  fase=nova;$('fase').textContent=ROTULOS[fase]||fase;
  $('orientacao').textContent=fase==='jogando'?'Use A B C D / E F G H / I J K L ou os botões ao lado. Esc três vezes cancela.':fase==='resultado'?'A próxima rodada ficará disponível automaticamente.':fase==='ocioso'?'Digite seu apelido e inicie. Os controles ficam neste notebook; a cidade fica na projeção.':fase==='contagem'?'Posicione as mãos: a rodada começa após a contagem.':'Calculando uma disputa com as mesmas condições para os três controles.';
  habilita();
}
function placar(m){
  ultimoPlacar=m;mudaFase(m.fase);const resumo=resumoCompacto(m,10,ritmo);
  $('tempo').textContent=resumo.relogio;
  if(m.fase==='resultado' && (m.linhas||[]).some(l=>l.braco==='humano')){
    guardaResultado({placar:m,nome:ultimoResultado?.placar.rodada===m.rodada?ultimoResultado.nome:nomeCompetidor});
  }
  if(m.fase==='jogando')mostraComparacao(m,nomeCompetidor);
  else if(ultimoResultado)mostraComparacao(ultimoResultado.placar,ultimoResultado.nome);
  if(m.fase==='resultado')buscaRanking();
}
function guardaResultado(r){
  ultimoResultado=r;
  try { localStorage.setItem('st-ultimo-competidor',JSON.stringify(r)); } catch {}
}
function mostraComparacao(m,nome){
  $('competidor').textContent=`${m.fase==='resultado'?'Último competidor':'Jogando agora'} · ${nome}`;
  const v=veredito(m);$('resultado').textContent=m.fase==='resultado'?(v.coroa?`${NOMES_HUD[v.coroa]} venceu`:'Rodada encerrada'):'Timer × rede neural × você';
  $('motivo').textContent=m.pareado===false?'Rodada fora do ranking: as condições iniciais dos três controles não coincidiram. Tente uma nova rodada.':v.motivo||'';
  if(m.pareado!==false && m.sinais?.length){
    $('motivo').textContent='A cidade congestionou. Sua pontuação considera os carros entregues em comparação com o timer.';
  }
  $('metricas').replaceChildren(...BRACOS_HUD.map(b=>{
    const l=(m.linhas||[]).find(x=>x.braco===b);const tr=document.createElement('tr');
    for(const valor of [NOMES_HUD[b],l?.entregues??'—',l?`${Number(l.tempo_medio||0).toFixed(1)} s`:'—',l?Number(l.fila||0).toFixed(1):'—']){const td=document.createElement('td');td.textContent=valor;tr.append(td);}return tr;
  }));
}
function ranking(m){
  $('ranking-info').textContent=`${m.total||0} ${m.total===1?'rodada':'rodadas'} · ${m.vitorias||0} venceram a rede neural`;
  $('ranking').replaceChildren(...(m.topo||[]).map(l=>{const li=document.createElement('li');li.textContent=l.rotulo||l.nome||'Visitante';const b=document.createElement('b');b.textContent=`${l.score>0?'+':''}${l.score??0}`;li.append(b);return li;}));
  if(!(m.topo||[]).length){const li=document.createElement('li');li.textContent=m.total?'Nenhuma marca nos últimos 30 minutos.':'A primeira rodada abre o ranking.';$('ranking').append(li);}
}
function buscaRanking(){fetch('/api/ranking?n=10').then(r=>r.json()).then(ranking).catch(()=>{});}
function recebe(m){
  const tipo=m.tipo||m.type;
  if(tipo==='ultimo_resultado'){guardaResultado(m);if(fase!=='jogando')mostraComparacao(m.placar,m.nome);}
  if(tipo==='placar')placar(m);
  if(tipo==='projecao'){
    entradaWeb=!!m.entrada_web;ritmo=m.ritmo||1;mudaFase(m.fase);
    $('erro').textContent=m.divergencia||m.motivo||'';
    if(m.proxima)$('situacao').textContent=`Trânsito ${m.proxima.seed} · ${m.proxima.rotulo||''}`;
    if(ultimoPlacar)$('tempo').textContent=resumoCompacto(ultimoPlacar,10,ritmo).relogio;
  }
  if(tipo==='jogador'){jogador=m;$('participante').textContent=m.nome||m.anonimo||'';if(m.nome||fase==='ocioso')nomeCompetidor=m.nome||m.anonimo||'Visitante';}
  if(tipo==='proxima')$('situacao').textContent=`Trânsito ${m.seed} · ${m.rotulo||''}`;
  if(tipo==='ranking')ranking(m);
  if(tipo==='leds')botoes.forEach((b,i)=>b.dataset.led=m.estados?.[i]||'off');
}
function conectaEntrada(){
  canal=new WebSocket(`${proto}://${location.host}/entrada`);canal.onopen=habilita;
  canal.onclose=()=>{habilita();setTimeout(conectaEntrada,800);};canal.onerror=()=>canal.close();
}
function conecta(){
  const ws=new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen=()=>{conectado=true;habilita();buscaRanking();};
  ws.onmessage=e=>{try{recebe(JSON.parse(e.data));}catch(err){$('erro').textContent='Não foi possível atualizar a rodada.';}};
  ws.onclose=()=>{conectado=false;habilita();setTimeout(conecta,800);};ws.onerror=()=>ws.close();
}
if(ultimoResultado)mostraComparacao(ultimoResultado.placar,ultimoResultado.nome);
conectaEntrada();conecta();buscaRanking();setInterval(buscaRanking,60000);
