"""Configuracao comum dos testes.

Nada aqui importa `sim`, `traci` nem `torch`: a suite de contratos roda numa
maquina sem SUMO. O unico teste que toca o pacote `sim` (tests/test_pacote_sim.py)
se pula sozinho quando ele nao esta instalado.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _env_limpo(monkeypatch):
    """Nenhum teste herda ST_* do shell de quem roda.

    Motivo concreto: `ST_SCENARIO`/`ST_MIN_GREEN` deixados de uma run anterior
    fariam o teste de cenario passar (ou falhar) pelo motivo errado.
    """
    for k in list(os.environ):
        if k.startswith("ST_"):
            monkeypatch.delenv(k, raising=False)
