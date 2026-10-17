"""Contrato do placar compacto executado no mesmo JavaScript do navegador."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='requer Node')
def test_alfabeto_da_interface_chega_aos_mesmos_doze_botoes(tmp_path):
    from feira.entrada.web import FonteWeb

    modulo = (Path(__file__).resolve().parents[1] / 'web/js/entrada.js').as_uri()
    script = tmp_path / 'teclas.mjs'
    script.write_text('''
import { MAPA_TECLAS, mensagemControle } from MODULO;
console.log(JSON.stringify({letras:Object.keys(MAPA_TECLAS),
 mensagens:[...'abcdefghijkl'].map(k=>mensagemControle({tipo:'tecla',k}))}));
'''.replace('MODULO', json.dumps(modulo)), encoding='utf-8')
    proc = subprocess.run([shutil.which('node'), str(script)], capture_output=True,
                          text=True, encoding='utf-8', check=True)
    dados = json.loads(proc.stdout)
    assert dados['letras'] == list('abcdefghijkl')
    fonte = FonteWeb()
    for msg in dados['mensagens']:
        fonte.recebe(msg)
    assert [e.indice for e in fonte.poll()] == list(range(12))
    assert fonte.n_desconhecidas == 0


@pytest.mark.skipif(not shutil.which('node'), reason='requer Node')
def test_barras_comparaveis_e_relogio_real(tmp_path):
    modulo = (Path(__file__).resolve().parents[1] / 'web/js/compacto.js').as_uri()
    script = tmp_path / 'compacto.mjs'
    script.write_text('''
import { resumoCompacto } from MODULO;
const linhas = [{braco:'timer',entregues:100}, {braco:'rl',entregues:80}, {braco:'humano',entregues:100}];
const m = {fase:'jogando',pareado:true,t_restante:119,linhas};
console.log(JSON.stringify({
  jogo:resumoCompacto(m,10,2),
  contagem:resumoCompacto({...m,fase:'contagem',t_restante:3},10,2),
  invalido:resumoCompacto({...m,pareado:false},10,2),
  ocioso:resumoCompacto({...m,fase:'ocioso',linhas:linhas.slice(0,2)},10,2),
  fim:resumoCompacto({...m,fase:'resultado',vencedor:null},10,2)
}));
'''.replace('MODULO', json.dumps(modulo)), encoding='utf-8')
    proc = subprocess.run([shutil.which('node'), str(script)], capture_output=True,
                          text=True, encoding='utf-8', check=True)
    r = json.loads(proc.stdout)
    assert r['jogo']['relogio'] == '01:00'
    assert r['contagem']['relogio'] == '00:03'
    assert r['fim']['relogio'] == '00:00'
    barras = r['jogo']['barras']
    assert [b['braco'] for b in barras] == ['timer', 'rl', 'humano']
    assert barras[0]['porcentagem'] == barras[2]['porcentagem']
    assert barras[1]['porcentagem'] < barras[0]['porcentagem'] <= 100
    assert barras[0]['posto'] == barras[2]['posto'] == 1
    assert all(b['posto'] is None and b['porcentagem'] == 0 for b in r['invalido']['barras'])
    assert r['ocioso']['barras'][2]['valor'] is None
    assert r['ocioso']['relogio'] == '—:—'
