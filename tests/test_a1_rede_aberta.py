"""A rede aberta (agente A1): o que ela tem que ser, verificado no arquivo.

Estes testes sao o DoD (a), (b) e a similitude escritos em codigo. Eles NAO
regeram a rede: leem o `.net.xml` que `sumo/aberta/build_rede_aberta.py` produziu.
Se o gerador mudar e a rede nao for regerada, e isto que denuncia.

Marcadores:
  `sumo`   - precisa de `sumolib` ($SUMO_HOME/tools);
  `aberta` - precisa da rede aberta construida.
"""
from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
NET = RAIZ / "sumo" / "aberta" / "network" / "maquete_aberta.net.xml"
CFG = RAIZ / "sumo" / "aberta" / "config" / "maquete_aberta.sumocfg"
ADD = RAIZ / "sumo" / "aberta" / "demanda" / "maquete_aberta.add.xml"
NET_REAL = (RAIZ.parent / "smart-traffic-maquete" / "sumo" / "small_network"
            / "network" / "net_loop.net.xml")

K = 6.0                       # fator de similitude do cenario

pytestmark = [
    pytest.mark.sumo,
    pytest.mark.aberta,
    pytest.mark.skipif("SUMO_HOME" not in os.environ, reason="sem SUMO_HOME"),
    pytest.mark.skipif(not NET.exists(),
                       reason="rode sumo/aberta/build_rede_aberta.py"),
]


@pytest.fixture(scope="module")
def net():
    sys.path.append(str(Path(os.environ["SUMO_HOME"]) / "tools"))
    import sumolib
    return sumolib.net.readNet(str(NET))


def _tl_verdes(caminho: Path) -> dict[str, int]:
    """{id do TL: nº de fases VERDES}, lendo o programa "0" (o que o TraCI pega)."""
    root = ET.parse(caminho).getroot()
    fora: dict[str, int] = {}
    for tl in root.findall("tlLogic"):
        tid = tl.get("id")
        if tid in fora and tl.get("programID") != "0":
            continue
        estados = [p.get("state") for p in tl.findall("phase")]
        fora[tid] = sum(1 for s in estados
                        if "g" in s.lower() and "y" not in s.lower())
    return fora


# ------------------------------------------------------------------ DoD (b)
def test_doze_semaforos_todos_controlaveis():
    """O item (b) do DoD, contra 10 semaforos / 6 controlaveis da rede fechada.

    Abrir a borda devolve os cantos H1V4/H3V4 a semaforizacao (o U-turn de retorno
    deixa de existir) e da uma segunda aproximacao a H1V1/H1V3/H3V1/H3V2, que na
    rede fechada eram terminos de corredor com uma fase verde so.
    """
    verdes = _tl_verdes(NET)
    assert len(verdes) == 12, verdes
    nao_controlaveis = sorted(t for t, n in verdes.items() if n < 2)
    assert nao_controlaveis == [], nao_controlaveis


_CONTA_TLS = """
import sys
import sim.environment.constants as C
C.NET_FILE, C.ADD_FILE = sys.argv[1], sys.argv[2]
import sim.environment.net_topology as T
print(T.N_INTERSECTIONS,
      sum(1 for t in T.TLS_IDS if T.TL_PHASES[t].controllable),
      len(T._UNCLASSIFIED))
"""


def test_o_mesmo_numero_pelo_caminho_do_pacote_sim():
    """A contagem que vale e a que `sim.environment.net_topology` faz - e o mesmo
    objeto que a politica e a Arena vao consumir. Ler o XML por conta propria e
    concordar com ele nao e redundancia: e o acoplamento sendo testado.

    RODA EM SUBPROCESSO, e isso NAO e paranoia: `sim.environment.constants` le
    env var no import e vira singleton de modulo (a armadilha que o docstring da
    C1 descreve). Fazer isso no processo do pytest deixaria `sim` congelado na
    rede ABERTA para todos os testes seguintes - e a Arena do agente A2, que
    roda na rede fechada, quebraria com `ArenaNaoConfigurada`. Aconteceu.
    """
    pytest.importorskip("sim", reason="pip install -e ../smart-traffic-maquete")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ST_")}
    env["ST_SCENARIO"] = "maquete_sim"
    r = subprocess.run([sys.executable, "-c", _CONTA_TLS, str(NET), str(ADD)],
                       cwd=str(RAIZ), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    n, controlaveis, nao_classificadas = (int(x) for x in r.stdout.split())
    assert n == 12
    assert controlaveis == 12
    # Aproximacao nao classificada = feature do estado CEGA naquela via. Os cotos
    # herdam o prefixo do corredor exatamente para isto dar zero.
    assert nao_classificadas == 0, r.stdout + r.stderr


# ------------------------------------------------------------------ bordas
def test_nove_fontes_e_nove_sorvedouros(net):
    normais = [e for e in net.getEdges() if e.getFunction() == ""]
    fontes = sorted(e.getID() for e in normais if not e.getIncoming())
    sorvedouros = sorted(e.getID() for e in normais if not e.getOutgoing())
    assert len(fontes) == 9, fontes
    assert len(sorvedouros) == 9, sorvedouros
    # um par por corredor de mao unica, e nenhum edge e fonte E sorvedouro
    assert set(fontes).isdisjoint(sorvedouros)
    corredores = {"H1", "H2E", "H2W", "H3", "V1", "V2", "V3", "V4S", "V4N"}
    assert {e.split("_")[0] for e in fontes} == corredores
    assert {e.split("_")[0] for e in sorvedouros} == corredores


def test_o_retorno_fechado_sumiu(net):
    assert not [e for e in net.getEdges() if e.getID().startswith("ret_")]
    assert not [n for n in net.getNodes() if n.getID().startswith("RET_")]


def test_todo_par_od_de_borda_e_alcancavel():
    """Risco 3 do plano: mao unica com 9 fontes/9 sorvedouros pode degenerar a
    escolha de rota. Aqui so o minimo inegociavel - nenhum par sem caminho; a
    contagem de caminhos alternativos esta em docs/CALIBRACAO_ABERTA.md."""
    from feira.demanda.malha import Malha
    m = Malha(NET)
    sem_caminho = [(o, d) for o in m.fontes for d in m.sorvedouros
                   if m.caminho_mais_curto(o, d) is None]
    assert sem_caminho == []


# ------------------------------------------------------------------ similitude
def test_tempo_de_travessia_e_invariante_sob_similitude(net):
    """A similitude e `x'=x/K, v'=v/K, t'=t`: o TEMPO nao muda.

    Comparamos com a rede `real` (escala 1:1) faixa a faixa, nas faixas que as
    duas tem em comum. E o teste que separa "similitude" de "rede comprimida":
    na `maquete` de hoje este erro seria de 500% (quarteirao de 2,5 s contra
    15,2 s), aqui tem que ficar em poucos por cento.

    A tolerancia nao e zero e nao pode ser: o netconvert apara o edge no raio da
    juncao, e a rede aberta tem juncoes com MAIS aproximacoes (logo raio um pouco
    diferente) que a fechada. O desvio e de geometria de juncao, nao de escala.
    """
    if not NET_REAL.exists():
        pytest.skip("rede `real` do maquete indisponivel")
    sys.path.append(str(Path(os.environ["SUMO_HOME"]) / "tools"))
    import sumolib
    real = sumolib.net.readNet(str(NET_REAL))

    def tempos(n):
        return {ln.getID(): ln.getLength() / ln.getSpeed()
                for e in n.getEdges() if e.getFunction() == ""
                for ln in e.getLanes()}

    t_real, t_ab = tempos(real), tempos(net)
    comuns = sorted(set(t_real) & set(t_ab))
    assert len(comuns) >= 40, "poucas faixas em comum: %d" % len(comuns)
    erros = sorted(abs(t_ab[k] - t_real[k]) / t_real[k] for k in comuns)
    assert erros[len(erros) // 2] < 0.02, "erro mediano %.4f" % erros[len(erros) // 2]
    assert erros[-1] < 0.10, "pior faixa %.4f" % erros[-1]


def test_velocidades_escalam_por_um_sexto(net):
    """v_max = 13,89/6. Se alguem regerar sem `--junctions.limit-turn-speed`
    escalado, as faixas INTERNAS ficam sqrt(6)=2,45x rapidas demais - e o teste
    acima (que so olha faixas normais) nao pegaria."""
    v_normais = [ln.getSpeed() for e in net.getEdges() if e.getFunction() == ""
                 for ln in e.getLanes()]
    assert abs(max(v_normais) - 13.89 / K) < 0.01
    # `readNet` NAO carrega edges internas sem `withInternal=True`; lemos do XML,
    # que e a fonte de verdade e nao depende dessa opcao.
    raiz = ET.parse(NET).getroot()
    v_internas = [float(ln.get("speed")) for e in raiz.findall("edge")
                  if e.get("function") == "internal" for ln in e.findall("lane")]
    assert v_internas, "rede sem faixas internas?"
    # Nenhuma faixa interna pode ser mais rapida que a via mais rapida da rede.
    # Sem o --junctions.limit-turn-speed escalado, as curvas ficariam ate
    # sqrt(6)=2,45x acima disto.
    assert max(v_internas) <= max(v_normais) + 1e-6


def test_vtype_tambem_escala():
    """Se o carro nao escalar junto, a rede volta a ser `comprimida`: a faixa
    guarda ~5 carros em vez de ~32 e o ganho da RL vira artefato de geometria."""
    vt = ET.parse(ADD).getroot().find("vType")
    assert abs(float(vt.get("length")) - 3.5 / K) < 0.002
    assert abs(float(vt.get("minGap")) - 1.75 / K) < 0.002
    assert abs(float(vt.get("accel")) - 2.6 / K) < 0.002
    assert abs(float(vt.get("decel")) - 4.5 / K) < 0.002


def test_o_net_xml_nao_carrega_timestamp_nem_caminho_da_maquina():
    """Build reproduzivel: o mesmo fonte tem que dar o mesmo `.net.xml`.

    O netconvert poe no topo um comentario "generated on <timestamp>" contendo a
    configuracao inteira com CAMINHOS ABSOLUTOS. Com ele, o `.net.xml` muda de
    sha256 a cada build, e o `net_sha256` que o manifesto da demanda carimba (a
    prova de que aquela demanda foi roteada NESTA rede) vira alarme falso.
    `build_rede_aberta.tira_cabecalho` remove; isto guarda a remocao.
    """
    cabeca = NET.read_text(encoding="utf-8")[:2000]
    assert "generated on" not in cabeca
    assert "netconvertConfiguration" not in cabeca
    assert "netconvert" not in cabeca.lower()


def test_manifestos_versionados_apontam_para_esta_rede():
    """A rota depende da REDE, e o manifesto e o que sobrevive ao `.rou.xml`
    (que nao vai versionado). Se a rede foi regerada e a demanda nao, a run
    antiga deixou de ser reproduzivel - e tem que aparecer aqui, nao na feira.

    Conserto: `python -m feira.demanda --forcar`.
    """
    from feira.contratos import sha256_arquivo
    from feira.contratos.demanda import ManifestoDemanda
    manifestos = sorted((NET.parent.parent / "demanda").glob("*.manifesto.json"))
    if not manifestos:
        pytest.skip("nenhuma demanda canonica gerada ainda (python -m feira.demanda)")
    atual = sha256_arquivo(NET)
    velhos = [m.name for m in manifestos
              if ManifestoDemanda.carrega(m).parametros.get("net_sha256") != atual]
    assert velhos == [], velhos


# ------------------------------------------------------------------ cenario
def test_o_cenario_aponta_para_estes_arquivos_e_esta_disponivel():
    from feira.contratos import cenario
    c = cenario("aberta.maquete")
    assert Path(c.net_file) == NET and Path(c.sumocfg) == CFG
    assert c.disponivel()
    assert c.warmup_s is not None, (
        "warmup_s continua None: a Arena recusa rodar. E o numero MEDIDO em "
        "docs/CALIBRACAO_ABERTA.md.")
    assert c.n_vehicles == 0 and c.modelo_demanda == "arquivo"


def test_o_sumocfg_carrega_no_sumo():
    """DoD (a) na pratica: o SUMO abre a config sem erro. `--end 1` e barato e
    pega XML invalido, caminho relativo quebrado e opcao inexistente."""
    import subprocess
    exe = str(Path(os.environ["SUMO_HOME"]) / "bin" / "sumo")
    r = subprocess.run([exe, "-c", str(CFG), "--end", "1", "--no-step-log", "true"],
                       capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    assert "Error" not in (r.stderr or "")
