"""A aposta que barateia o repo: o `sim` do maquete entra como PACOTE, sem copia.

Se estes testes falharem, a alternativa e vendorizar (copiar) o ambiente de RL para
ca -- e ai passam a existir duas copias que divergem, que e exatamente o que a
separacao de repos deste projeto tentou evitar.

    pip install -e ../smart-traffic-maquete --no-deps
"""
from __future__ import annotations

import pytest

sim = pytest.importorskip(
    "sim", reason="rode: pip install -e ../smart-traffic-maquete --no-deps")


def test_sim_aponta_para_o_repo_maquete():
    assert "smart-traffic-maquete" in sim.__file__.replace("\\", "/")


def test_superficie_publica_que_este_repo_consome():
    """O que a Onda 1+ vai importar. Se algum destes sumir do maquete, o contrato
    entre os repos quebrou e tem que quebrar AQUI, num teste, nao na feira."""
    from sim.agents.policy import load_policy  # noqa: F401  (A6)
    from sim.baselines.fixed_timer_sim import FixedTimerSim  # noqa: F401  (A5)
    from sim.environment.scenarios import active_scenario  # noqa: F401  (A1)
    from sim.evaluation.metrics import MetricsCollector  # noqa: F401  (A2)


def test_fixed_timer_sim_tem_o_parametro_de_offset():
    """`offset_seconds` existe e nunca foi usado -- e a alavanca de ONDA VERDE do
    agente A5. Se sumir, o baseline honesto perde a coordenacao."""
    import inspect

    from sim.baselines.fixed_timer_sim import FixedTimerSim
    p = inspect.signature(FixedTimerSim.__init__).parameters
    assert "offset_seconds" in p and "all_red_seconds" in p
