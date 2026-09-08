"""A4 — a MESMA suíte de conformidade do C6, aplicada ao `SerialInput`.

Item (a) do DoD do agente A4: *"`SerialInput` passa a mesma suíte de conformidade
que o teclado"*. "Mesma" aqui é literal, não moral: os quatro testes de C6 são
**importados de `tests/test_conformidade.py`** e chamados com a fábrica da
botoeira. Não há cópia — se alguém apertar o contrato lá, aperta aqui junto.

Por que não entrar direto na `IMPLS_ENTRADA` de lá: `tests/test_conformidade.py`
está fora das fronteiras de escrita deste agente (é arquivo compartilhado, e o A3
mexe nele para plugar o teclado). A linha da botoeira já está escrita lá, em
comentário, exatamente como esta fábrica —
`pytest.param(lambda: SerialInput(porta_falsa()), id="botoeira")` — e é por isso
que `porta_falsa()` nasce com o roteiro `[[0, 3], [], [BOTAO_START]]` já dentro:
no dia em que a linha for descomentada, ela funciona sem argumento nenhum.
"""
from __future__ import annotations

import pytest

# Importado como MÓDULO, não com `from ... import test_*`: pytest coleta por nome,
# e nomes `test_*` puxados para cá seriam recolhidos e rodariam em dobro.
import test_conformidade as C6

from feira.entrada_serial import SerialInput, porta_falsa


def botoeira() -> SerialInput:
    """A fábrica da `IMPLS_ENTRADA`: botoeira contra o Pico em software."""
    return SerialInput(porta_falsa())


IMPLS_ENTRADA_A4 = [pytest.param(botoeira, id="botoeira")]


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA_A4)
def test_a4_entrada_satisfaz_o_protocolo(fabrica):
    C6.test_entrada_satisfaz_o_protocolo(fabrica)


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA_A4)
def test_a4_entrada_devolve_bordas_e_nao_bloqueia(fabrica):
    C6.test_entrada_devolve_bordas_e_nao_bloqueia(fabrica)


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA_A4)
def test_a4_entrada_valida_feedback(fabrica):
    C6.test_entrada_valida_feedback(fabrica)


@pytest.mark.parametrize("fabrica", IMPLS_ENTRADA_A4)
def test_a4_entrada_reporta_morte(fabrica):
    C6.test_entrada_reporta_morte(fabrica)


def test_a4_o_modulo_importa_sem_pyserial():
    """O invariante do projeto inteiro, na forma mais direta.

    `pyserial` NÃO está no venv compartilhado (medido). Se este teste falhar, ou
    alguém instalou o pacote (e o teste deixou de provar algo), ou alguém subiu o
    `import serial` para o topo do módulo — e aí o jogo de teclado morre junto com
    a botoeira ausente.
    """
    import importlib.util
    import sys

    assert "feira.entrada_serial" in sys.modules      # já importado no topo daqui
    if importlib.util.find_spec("serial") is not None:
        pytest.skip("pyserial instalado neste ambiente: o teste perde o sentido")
    assert "serial" not in sys.modules

    # E o caminho de abertura degrada em silêncio em vez de explodir.
    from feira.entrada_serial import abre_botoeira, detecta_porta, lista_portas
    assert lista_portas() == []
    assert detecta_porta() is None
    assert abre_botoeira() is None
