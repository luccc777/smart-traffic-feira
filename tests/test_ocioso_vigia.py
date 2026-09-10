"""O vigia de população do feed ocioso — a precaução contra a feira de 8 horas.

O feed da tela ociosa já recomeçava a cada `--duracao`, mas o relógio sozinho é
uma aposta sobre QUANDO a malha degrada, e a resposta depende do braço, da seed e
do regime. Medido neste projeto: o timer uniforme trava em t ~ 3995 s na seed 42
(`docs/AUDITORIA_COMPARACAO.md` §9) e, a 3800 veh/h, as seeds que travam vão de
157 para 552-582 ativos. O vigia olha o sintoma em vez do calendário.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _carrega(nome: str, caminho: Path):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def oc():
    return _carrega("projecao_ocioso", RAIZ / "scripts" / "projecao_ocioso.py")


@dataclass
class _Quadro:
    t: float
    veiculos: list


def _quadro(t: float, n: int) -> _Quadro:
    return _Quadro(t=t, veiculos=[{"id": "c%d" % i} for i in range(n)])


def test_regime_normal_nao_dispara(oc):
    """157 ativos e a faixa 141-170 das fatias de 600 s são o REGIME, não sintoma."""
    v = oc._Vigia(320, 60.0)
    for t in range(0, 1800):
        v.ve(_quadro(float(t), 141 + (t % 30)))       # oscila 141-170
    assert v.pico == 170


def test_pico_isolado_nao_derruba_a_volta(oc):
    """Um pico é flutuação de inserção; acúmulo é outra coisa, e persiste."""
    v = oc._Vigia(320, 60.0)
    for t in range(0, 100):
        v.ve(_quadro(float(t), 400 if 10 <= t < 40 else 160))   # 30 s acima, some
    assert v.pico == 400          # viu o pico...
    v.ve(_quadro(200.0, 160))     # ...e seguiu, porque não persistiu


def test_acumulo_sustentado_aborta_a_volta(oc):
    v = oc._Vigia(320, 60.0)
    with pytest.raises(oc._Encheu, match="teto 320"):
        for t in range(0, 300):
            v.ve(_quadro(float(t), 160 if t < 100 else 500))
    # e aborta LOGO depois de cumprido o prazo, não no fim da volta de 1800 s
    assert t < 170, "demorou demais para abortar: t=%s" % t


def test_teto_zero_desliga_o_vigia(oc):
    """Quem quiser a volta inteira, aconteça o que acontecer, pode pedir."""
    v = oc._Vigia(0, 60.0)
    for t in range(0, 300):
        v.ve(_quadro(float(t), 900))
    assert v.pico == 900          # mediu, mas não interferiu
