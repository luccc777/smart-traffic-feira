"""A11 — o que uma PESSOA faz num teclado, e não o que o fluxo feliz previu.

A feira é um teclado no chão, uma fila atrás e ninguém explicando. Os testes daqui
não perguntam "o jogo funciona?" — isso o A9/A10 já cobrem. Eles perguntam o que
acontece quando alguém **desiste**, **erra**, **segura a tecla**, **vai embora no
meio** ou aperta a tecla que todo usuário de computador aperta para cancelar: Esc.

O harness é o do `test_a7_front.py`: Node importando os arquivos do repo. Sem Node,
pula.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from feira.contratos.frame import OCIOSO, RESULTADO
from feira.jogo.web import EstadoProjecao

_A7 = Path(__file__).resolve().parent / "test_a7_front.py"
_spec = importlib.util.spec_from_file_location("test_a7_front", _A7)
_a7 = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("test_a7_front", _a7)
_spec.loader.exec_module(_a7)
_node, _url, sem_node = _a7._node, _a7._url, _a7.sem_node


# ===================================================== o visitante que desiste
_DESISTE = """
import { reduzEntrada, estadoInicial, aoMudarFase, aceitaEvento, revisaEspera,
         ESC_JANELA_MS, NOME_VALIDADE_MS } from %s;

// `toca` aplica uma sequência de teclas e devolve o estado final + tudo que saiu
// da página para o servidor.
function toca(estado, teclas, t0 = 1000, passo = 200) {
  let e = estado, t = t0;
  const saiu = [];
  for (const k of teclas) {
    const r = reduzEntrada(e, k, t);
    e = r.estado;
    for (const a of r.acoes) saiu.push(a.tipo);
    t += passo;
  }
  return { estado: e, saiu };
}

const out = {};

// (1) digitou, se arrependeu no meio, apertou Esc
out.esc_limpa_o_nome = toca(estadoInicial('ocioso'), ['A', 'N', 'A', 'Escape']);

// (2) NÃO confirmou e foi embora; o próximo chega e digita o dele
out.sem_enter_o_proximo_sobrescreve =
  toca(estadoInicial('ocioso'), ['A', 'N', 'A', 'Escape', 'B', 'I', 'A']);

// (3) CONFIRMOU (Enter) e desistiu: consegue voltar atrás?
const confirmou = toca(estadoInicial('ocioso'), ['A', 'N', 'A', 'Enter']);
out.confirmou = confirmou;
out.depois_do_enter_esc  = toca(confirmou.estado, ['Escape']);
out.depois_do_enter_bs   = toca(confirmou.estado, ['Backspace']);
out.depois_do_enter_3esc = toca(confirmou.estado, ['Escape', 'Escape', 'Escape'], 1000, 300);

// (4) Esc é a tecla do reflexo (sair da tela cheia). Um sozinho não pode abortar,
//     e três LENTOS também não — a janela é de 1,5 s.
out.um_esc_no_jogo     = toca({ fase: 'jogando', campo: false, nome: '' }, ['Escape']);
out.tres_esc_rapidos   = toca({ fase: 'jogando', campo: false, nome: '' },
                              ['Escape', 'Escape', 'Escape'], 1000, 300);
out.tres_esc_lentos    = toca({ fase: 'jogando', campo: false, nome: '' },
                              ['Escape', 'Escape', 'Escape'], 1000, ESC_JANELA_MS + 50);

// (5) apertou ESPAÇO com o nome digitado mas NÃO confirmado
out.espaco_com_nome    = toca(estadoInicial('ocioso'), ['A', 'N', 'A', ' ']);
out.espaco_sem_nome    = toca(estadoInicial('ocioso'), [' ']);
out.enter_sem_nome     = toca(estadoInicial('ocioso'), ['Enter']);

// (6) as teclas do JOGO enquanto o campo está aberto NÃO podem virar botão
out.letras_do_jogo_no_campo = toca(estadoInicial('ocioso'), ['q', 'w', 'e', 'r']);

// (7) segurou a tecla (keydown com repeat)
out.repeat_no_jogo = aceitaEvento({ campo: false }, { key: 'q', repeat: true });
out.repeat_backspace = aceitaEvento({ campo: true, nome: 'ANA' },
                                    { key: 'Backspace', repeat: true });
out.repeat_letra = aceitaEvento({ campo: true, nome: 'ANA' }, { key: 'A', repeat: true });

// (8) a rodada acabou: o campo reabre VAZIO para o próximo
out.volta_ao_ocioso = aoMudarFase({ fase: 'resultado', campo: false, nome: 'ANA',
                                    confirmado: true }, 'ocioso');

// (9) O RELÓGIO DA ESPERA: confirmou e foi embora sem apertar nada.
const esperando = confirmou.estado;
out.espera_curta = revisaEspera(esperando, (esperando.confirmadoEm || 0) + 1000);
out.espera_longa = revisaEspera(esperando,
                                (esperando.confirmadoEm || 0) + NOME_VALIDADE_MS + 1);
// e o relógio não mexe em quem está digitando, nem no meio da rodada
out.espera_digitando = revisaEspera(toca(estadoInicial('ocioso'), ['A','N']).estado,
                                    10 ** 9);
out.espera_na_rodada = revisaEspera({ fase: 'jogando', campo: false, nome: 'ANA',
                                      confirmado: true, confirmadoEm: 0 }, 10 ** 9);

console.log(JSON.stringify(out));
"""


@sem_node
def test_o_visitante_que_desiste_antes_de_confirmar(tmp_path):
    r = _node(_DESISTE % json.dumps(_url("entrada.js")), tmp_path)

    # Esc com o campo aberto LIMPA, e nunca aborta: é a tecla que todo mundo aperta
    # por reflexo para sair da tela cheia.
    assert r["esc_limpa_o_nome"]["estado"]["nome"] == ""
    assert r["esc_limpa_o_nome"]["saiu"] == [], "um Esc no campo mandou algo ao servidor"
    assert r["sem_enter_o_proximo_sobrescreve"]["estado"]["nome"] == "BIA"

    # Enter confirma e AVISA o servidor — uma vez só. E carimba QUANDO, que é o que
    # deixa o relógio da espera devolver a vez de quem confirmar e sumir.
    e = r["confirmou"]["estado"]
    assert (e["fase"], e["campo"], e["nome"], e["confirmado"]) == \
        ("ocioso", False, "ANA", True)
    assert e["confirmadoEm"] > 0
    assert r["confirmou"]["saiu"] == ["nome"]


@sem_node
def test_desistir_depois_do_enter_devolve_a_vez(tmp_path):
    """O BUG que esta suíte foi escrita para pegar, e a correção.

    Entre o ENTER e o ESPAÇO a pessoa já disse o nome e ainda não jogou. Dali não
    havia volta: Esc não fazia nada, Backspace não fazia nada, e Esc 3x mandava
    `abortar` (no-op fora da rodada) deixando o nome pendurado. Quem desistia ali
    entregava o apelido ao PRÓXIMO da fila — que jogava e entrava no quadro de
    recordes com o nome errado.
    """
    r = _node(_DESISTE % json.dumps(_url("entrada.js")), tmp_path)

    esc = r["depois_do_enter_esc"]
    assert esc["estado"]["nome"] == "", "Esc não cancelou o apelido confirmado"
    assert esc["estado"]["campo"] is True, "o campo não reabriu para o próximo"
    assert esc["estado"]["confirmado"] is False
    assert esc["saiu"] == ["nome"], "o servidor não foi avisado de que a vez voltou"

    # Backspace é o outro reflexo: reabre para CORRIGIR, sem perder o que já foi digitado
    bs = r["depois_do_enter_bs"]
    assert bs["estado"]["campo"] is True and bs["estado"]["nome"] == "AN"
    assert bs["saiu"] == ["nome"]


@sem_node
def test_o_apelido_abandonado_expira_sozinho(tmp_path):
    """A pessoa confirmou e foi embora sem apertar mais nada — nenhuma tecla resolve
    esse caso, então quem resolve é o relógio."""
    r = _node(_DESISTE % json.dumps(_url("entrada.js")), tmp_path)

    assert r["espera_curta"]["acoes"] == [], "expirou o apelido de quem acabou de confirmar"
    assert r["espera_curta"]["estado"]["nome"] == "ANA"

    longa = r["espera_longa"]
    assert longa["estado"]["nome"] == "" and longa["estado"]["campo"] is True
    assert [a["tipo"] for a in longa["acoes"]] == ["nome"]

    # o relógio não incomoda quem está digitando, nem a rodada em curso
    assert r["espera_digitando"]["acoes"] == []
    assert r["espera_digitando"]["estado"]["nome"] == "AN"
    assert r["espera_na_rodada"]["acoes"] == []


@sem_node
def test_esc_nao_dispara_por_acidente(tmp_path):
    r = _node(_DESISTE % json.dumps(_url("entrada.js")), tmp_path)
    assert r["um_esc_no_jogo"]["saiu"] == [], "um Esc sozinho abortou a rodada"
    assert r["tres_esc_rapidos"]["saiu"] == ["abortar"]
    assert r["tres_esc_lentos"]["saiu"] == [], "três Esc espaçados abortaram"


@sem_node
def test_o_campo_aberto_nao_deixa_nenhuma_tecla_virar_jogada(tmp_path):
    r = _node(_DESISTE % json.dumps(_url("entrada.js")), tmp_path)
    # `q w e r` são botões NA RODADA; no campo são letras do nome, e só.
    assert r["letras_do_jogo_no_campo"]["saiu"] == []
    assert r["letras_do_jogo_no_campo"]["estado"]["nome"] == "QWER"
    # ESPAÇO com nome digitado é ignorado (senão jogaria com o nome pela metade);
    # sem nome, começa como Visitante.
    assert r["espaco_com_nome"]["saiu"] == []
    assert r["espaco_sem_nome"]["saiu"] == ["start"]
    assert r["enter_sem_nome"]["saiu"] == []


@sem_node
def test_tecla_segurada_nao_vira_rajada(tmp_path):
    r = _node(_DESISTE % json.dumps(_url("entrada.js")), tmp_path)
    assert r["repeat_no_jogo"] is False, "segurar a tecla virou rajada de jogadas"
    assert r["repeat_letra"] is False, "segurar a letra encheu o nome"
    assert r["repeat_backspace"] is True, "segurar Backspace tem de apagar"


@sem_node
def test_a_rodada_acabou_e_o_campo_reabre_vazio(tmp_path):
    r = _node(_DESISTE % json.dumps(_url("entrada.js")), tmp_path)
    v = r["volta_ao_ocioso"]
    assert v["campo"] is True and v["nome"] == "" and v["confirmado"] is False


# ===================================================== o lado do servidor
def _placar(fase=RESULTADO, humano=True):
    linhas = [{"braco": "timer", "rotulo": "TIMER FIXO", "entregues": 100,
               "fila": 9.0, "tempo_medio": 60.0, "fantasma": True},
              {"braco": "rl", "rotulo": "REDE NEURAL", "entregues": 120,
               "fila": 7.0, "tempo_medio": 55.0, "fantasma": True}]
    if humano:
        linhas.append({"braco": "humano", "rotulo": "VOCÊ", "entregues": 90,
                       "fila": 11.0, "tempo_medio": 66.0, "fantasma": False})
    return {"tipo": "placar", "fase": fase, "t": 420.0, "t_restante": 0.0,
            "chave": {"cenario": "aberta.maquete", "seed": 100,
                      "janela": [300.0, 420.0], "demanda": "abc123"},
            "linhas": linhas, "vencedor": "rl", "pareado": True, "rodada": 1}


@pytest.fixture
def estado():
    return EstadoProjecao()


def test_a_rodada_acontecida_consome_o_nome(estado):
    """Quem jogou sai do lugar: o próximo visitante não herda o apelido."""
    estado.define_jogador("ANA")
    assert estado.jogador == "ANA"
    estado.absorve(_placar())
    assert estado.jogador is None


def test_rodada_que_nao_aconteceu_preserva_o_nome(estado):
    """Falha NOSSA (o SUMO caiu, sem linha do humano) não consome a vez: a pessoa
    continua na fila com o nome dela, e a rodada grátis repete a seed."""
    estado.define_jogador("ANA")
    estado.absorve(_placar(humano=False))
    assert estado.jogador == "ANA"


def test_desistir_e_ceder_a_vez_ao_proximo(estado):
    """O visitante confirmou o nome e foi embora. O operador (ou a página) tem de
    conseguir devolver a vez — senão o próximo joga com o nome do anterior."""
    estado.define_jogador("ANA")
    estado.define_jogador(None)
    assert estado.jogador is None
    assert estado.msg_jogador()["nome"] is None


def test_o_anonimo_nao_colide_com_quem_ja_jogou(estado):
    """Sem nome, a pessoa vira `Visitante N`. O N tem de andar com o quadro, senão
    dois visitantes do mesmo dia viram o mesmo nome."""
    assert estado.msg_jogador()["anonimo"].startswith("Visitante")


@pytest.mark.parametrize("fase", [OCIOSO, RESULTADO])
def test_nome_vazio_ou_so_espacos_nao_vira_jogador(estado, fase):
    estado.fase = fase
    for ruim in ("", "   ", None):
        estado.define_jogador(ruim)
        assert estado.jogador is None


# ===================================================== o reflexo do "de novo!"
def test_o_start_apertado_na_tela_de_resultado_nao_come_a_rodada_seguinte():
    """Quem acaba de jogar aperta ESPAÇO de novo, olhando para o próprio resultado.

    O evento ficava na fila da fonte e o `espera_start()` seguinte o encontrava — a
    tela padrão durava 20 ms (medido: resultado 493159 ms, ocioso 500176, preparando
    500196) e a rodada saía como `Visitante N`, com o próximo da fila sem chance de
    digitar o apelido. A contagem já descartava o que era martelado nela; faltava a
    outra ponta.
    """
    from feira.contratos import EventoBotao
    from feira.jogo.motor import MotorDoJogo

    class FonteFalsa:
        """Uma fonte com START engatilhado, como a de quem apertou no resultado."""

        n_botoes = 12
        nome = "falsa"

        def __init__(self):
            self.fila = [EventoBotao(indice=-1)]
            self.polls = 0

        def poll(self):
            self.polls += 1
            saida, self.fila = self.fila, []
            return saida

        def feedback(self, estados, start=None):
            pass

        def close(self):
            pass

    fonte = FonteFalsa()
    motor = MotorDoJogo.__new__(MotorDoJogo)      # sem SUMO: só o descarte é o assunto
    motor.fonte = fonte

    assert fonte.fila, "o teste precisa começar com um START pendente"
    motor._descarta_entrada()
    assert fonte.polls == 1 and fonte.fila == []

    # e o `espera_start` seguinte NÃO encontra nada: a tela padrão fica no ar
    assert motor.fonte.poll() == []


def test_descartar_entrada_sobrevive_a_fonte_morta():
    """Fonte caída no fim da rodada não pode derrubar o retorno ao `ocioso`."""
    from feira.jogo.motor import MotorDoJogo

    class FonteQueExplode:
        def poll(self):
            raise RuntimeError("cabo arrancado")

    motor = MotorDoJogo.__new__(MotorDoJogo)
    motor.fonte = FonteQueExplode()
    motor._descarta_entrada()                     # não levanta


def test_voltar_ao_ocioso_anuncia_a_proxima_hora_de_transito():
    """`proxima` só viajava no status INICIAL: quem abrisse a projeção via a seed
    daquele instante e nunca mais.

    Na feira isso aparece na primeira rodada: o motor passa para a 101 e a faixa
    continua dizendo "HORA DE TRÂNSITO 100 · hoje 0 de 0" — seed errada e estatística
    errada (a 100 já tinha um jogador). Medido na tela contra `/api/proxima`.
    """
    seeds = iter([100, 101])
    est = EstadoProjecao()
    est.proxima_seed = lambda: next(seeds)
    difundidas = []
    est._difunde = difundidas.append

    est.fase = "jogando"
    est.absorve({"tipo": "placar", "fase": OCIOSO, "t": 420.0, "t_restante": 0.0,
                 "chave": {}, "linhas": []})
    proximas = [m for m in difundidas if m.get("tipo") == "proxima"]
    assert proximas, "voltou ao ocioso sem dizer qual é a próxima hora de trânsito"
    assert proximas[-1]["seed"] == 100


def test_so_anuncia_quando_a_fase_MUDA_para_ocioso():
    """O ocioso publica placar a 1 Hz; anunciar em todo um deles seria uma mensagem
    por segundo para dizer sempre a mesma coisa."""
    est = EstadoProjecao()
    est.proxima_seed = lambda: 107
    difundidas = []
    est._difunde = difundidas.append
    est.fase = OCIOSO
    for _ in range(3):
        est.absorve({"tipo": "placar", "fase": OCIOSO, "t": 1.0, "t_restante": 0.0,
                     "chave": {}, "linhas": []})
    assert [m for m in difundidas if m.get("tipo") == "proxima"] == []
