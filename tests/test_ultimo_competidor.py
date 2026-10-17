from feira.jogo.web import EstadoProjecao
from feira.jogo.ranking import Ranking


def test_resultado_guarda_nome_antes_de_limpar_e_sobrevive_ao_ocioso():
    estado = EstadoProjecao(ranking=Ranking())
    estado.define_jogador('Ana')
    resultado = {
        'tipo': 'placar', 'fase': 'resultado', 'rodada': 1,
        'pareado': True, 'chave': {'seed': 100},
        'sinais': ['congestionamento'],
        'linhas': [{'braco': 'humano', 'entregues': 20},
                   {'braco': 'timer', 'entregues': 80},
                   {'braco': 'rl', 'entregues': 90}],
    }
    estado.absorve(resultado)
    estado.absorve(resultado)  # retransmissão não troca Ana por Visitante 2
    estado.absorve({'tipo': 'placar', 'fase': 'ocioso', 'linhas': []})
    assert estado.jogador is None
    assert estado.ranking.topo()[0].nome == 'Ana'
    guardado = next(m for m in estado.inicial() if m['tipo'] == 'ultimo_resultado')
    assert guardado['nome'] == 'Ana'
    assert guardado['placar'] == resultado
