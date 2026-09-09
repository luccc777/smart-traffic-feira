"""`GeradorDemandaAberta` (agente A1): o invariante do C2 e o que o arquivo diz.

O teste que importa e o primeiro: MESMA SEED -> MESMO sha256. Os outros existem
para que, quando ele quebrar, o motivo apareca no mesmo lugar (rota invalida,
ordem de partida, par OD degenerado) em vez de so "o hash mudou".
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
NET = RAIZ / "sumo" / "aberta" / "network" / "maquete_aberta.net.xml"

pytestmark = [
    pytest.mark.sumo,
    pytest.mark.aberta,
    pytest.mark.skipif("SUMO_HOME" not in os.environ, reason="sem SUMO_HOME"),
    pytest.mark.skipif(not NET.exists(),
                       reason="rode sumo/aberta/build_rede_aberta.py"),
]


@pytest.fixture
def cen(tmp_path):
    """O cenario da feira inteiro espelhado num tmp, com a MESMA arvore relativa.

    Nao basta desviar o `rou_pattern`: o gerador escreve tambem o `.sumocfg` da
    seed AO LADO DO CANONICO (e a convencao que a Arena procura), entao um teste
    que so desvie as rotas escreveria dentro de `sumo/aberta/config/` do repo e
    apontaria o cfg oficial da seed 42 para um arquivo em tmp. Copiamos rede, vType
    e cfg preservando `config/` e `demanda/` como irmaos, que e o que os caminhos
    relativos do `.sumocfg` esperam.
    """
    import shutil

    from feira.contratos import cenario
    c = cenario("aberta.maquete")
    for sub in ("config", "network", "demanda"):
        (tmp_path / sub).mkdir()
    shutil.copy(c.net_file, tmp_path / "network" / Path(c.net_file).name)
    shutil.copy(c.add_file, tmp_path / "demanda" / Path(c.add_file).name)
    shutil.copy(c.sumocfg, tmp_path / "config" / Path(c.sumocfg).name)
    return replace(
        c,
        net_file=str(tmp_path / "network" / Path(c.net_file).name),
        add_file=str(tmp_path / "demanda" / Path(c.add_file).name),
        sumocfg=str(tmp_path / "config" / Path(c.sumocfg).name),
        rou_pattern=str(tmp_path / "demanda" / "demanda_s{seed}.rou.xml"),
    )


@pytest.fixture(scope="module")
def ger():
    from feira.demanda import GeradorDemandaAberta
    return GeradorDemandaAberta(veh_por_hora=3600.0, horizonte_s=600.0)


def _rotas(caminho: Path) -> list[list[str]]:
    import re
    return [m.split() for m in
            re.findall(r'<route edges="([^"]+)"/>',
                       caminho.read_text(encoding="utf-8"))]


def _departs(caminho: Path) -> list[float]:
    import re
    return [float(x) for x in
            re.findall(r'depart="([0-9.]+)"', caminho.read_text(encoding="utf-8"))]


# ------------------------------------------------------------------ o contrato
def test_satisfaz_o_protocolo(ger):
    from feira.contratos import GeradorDemanda
    assert isinstance(ger, GeradorDemanda)


def test_mesma_seed_mesmo_sha256(ger, cen):
    m1 = ger.gera(cen, 42, forcar=True)
    bytes1 = cen.rou_file(42).read_bytes()
    m2 = ger.gera(cen, 42, forcar=True)
    assert m1.sha256 == m2.sha256
    assert cen.rou_file(42).read_bytes() == bytes1     # byte a byte, nao "equivalente"


def test_seeds_diferentes_sha_diferente(ger, cen):
    shas = {s: ger.gera(cen, s, forcar=True).sha256 for s in (42, 43, 44)}
    assert len(set(shas.values())) == 3, shas


def test_determinismo_entre_processos(cen, tmp_path):
    """O modo de falha classico: `hash()` de str/tupla e ALEATORIZADO por processo.

    Gerar em dois subprocessos com `PYTHONHASHSEED` diferente e o unico jeito de
    provar que nenhuma ordem de `dict`/`set` vazou para o arquivo. Rodar duas
    vezes no MESMO processo nao pega isso.
    """
    codigo = (
        "import sys;from dataclasses import replace;"
        "from feira.contratos import cenario;"
        "from feira.demanda import GeradorDemandaAberta;"
        "c=replace(cenario('aberta.maquete'), rou_pattern=sys.argv[1],"
        " sumocfg=sys.argv[2]);"
        "g=GeradorDemandaAberta(veh_por_hora=3600.0, horizonte_s=600.0);"
        "m=g.gera(c, 42, forcar=True);"
        "print(m.sha256, m.parametros['sumocfg_seed_sha256'])"
    )
    # O `sumocfg` do subprocesso TEM que ir para o tmp: o gerador escreve o cfg da
    # seed ao lado dele, e com o canonico aqui o teste reescreveria o cfg oficial
    # da seed 42 do repo apontando para um arquivo em tmp. (Aconteceu.)
    cfg_tmp = cen.sumocfg          # a fixture `cen` ja o espelhou dentro do tmp

    saidas = []
    for hseed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=hseed)
        padrao = str(tmp_path / "demanda" / ("h%s_s{seed}.rou.xml" % hseed))
        r = subprocess.run([sys.executable, "-c", codigo, padrao, cfg_tmp],
                           cwd=str(RAIZ), env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        saidas.append(r.stdout.strip().split()[0])   # so o sha do .rou.xml
        assert r.stdout.strip().split()[1] != "None"  # o cfg da seed foi escrito
    assert len(set(saidas)) == 1, saidas


def test_idempotente_nao_regera(ger, cen):
    m1 = ger.gera(cen, 42)
    mtime = cen.rou_file(42).stat().st_mtime_ns
    m2 = ger.gera(cen, 42)
    assert m1 == m2 and cen.rou_file(42).stat().st_mtime_ns == mtime


def test_manifesto_denuncia_adulteracao(ger, cen):
    from feira.contratos import DemandaDivergente
    man = ger.gera(cen, 42, forcar=True)
    rou = cen.rou_file(42)
    rou.write_text(rou.read_text(encoding="utf-8").replace("car00000", "car99999"),
                   encoding="utf-8")
    with pytest.raises(DemandaDivergente):
        man.confere(rou)


def test_manifesto_carimba_a_rede(ger, cen):
    """A rota depende da REDE. Se a rede for regerada e a demanda nao, a run
    antiga deixa de ser reproduzivel - e isso tem que aparecer."""
    from feira.contratos import sha256_arquivo
    man = ger.gera(cen, 42, forcar=True)
    assert man.parametros["net_sha256"] == sha256_arquivo(NET)
    assert man.parametros["od_weight"] == "capacity"
    assert man.parametros["od_weight_pow"] == 1.0


# ------------------------------------------------------------- o que o arquivo diz
def test_partidas_em_ordem_nao_decrescente(ger, cen):
    ger.gera(cen, 42, forcar=True)
    d = _departs(cen.rou_file(42))
    assert d == sorted(d) and len(d) > 50


def test_toda_rota_sai_de_uma_fonte_e_morre_num_sorvedouro(ger, cen):
    from feira.demanda.malha import Malha
    m = Malha(NET)
    ger.gera(cen, 42, forcar=True)
    rotas = _rotas(cen.rou_file(42))
    assert rotas
    for r in rotas:
        assert r[0] in m.fontes, r[0]
        assert r[-1] in m.sorvedouros, r[-1]


def test_toda_rota_e_um_caminho_valido_na_rede(ger, cen):
    """Rota invalida so aparece como erro do SUMO no meio de uma run de 3600 s.
    Aqui aparece como assert."""
    from feira.demanda.malha import Malha
    m = Malha(NET)
    ger.gera(cen, 42, forcar=True)
    for r in _rotas(cen.rou_file(42)):
        for a, b in zip(r, r[1:]):
            assert b in m.saidas[a], "%s -> %s nao e conexao da rede" % (a, b)


def test_nenhuma_viagem_trivial(ger, cen):
    """Viagem de 2 edges e "entra e sai" - infla a vazao sem carregar a malha, e
    na Frente 3 o placar e em CARROS ENTREGUES."""
    from feira.demanda import aberta as A
    ger.gera(cen, 42, forcar=True)
    assert min(len(r) for r in _rotas(cen.rou_file(42))) >= A.MIN_EDGES


def test_h2_tem_participacao_dominante(ger, cen):
    """A arterial de 3 faixas tem que dominar o OD - e o que torna a ONDA VERDE
    (agente A5) relevante. Com `od_weight=capacity` pow=1 isso sai da capacidade,
    nao de um numero escolhido a mao: 3 faixas x v contra 2 faixas x v.
    """
    ger.gera(cen, 42, forcar=True)
    rotas = _rotas(cen.rou_file(42))
    origens_h2 = sum(1 for r in rotas if r[0].startswith("H2"))
    destinos_h2 = sum(1 for r in rotas if r[-1].startswith("H2"))
    for nome, n in (("origens", origens_h2), ("destinos", destinos_h2)):
        frac = n / len(rotas)
        assert 0.28 <= frac <= 0.42, "%s em H2: %.3f" % (nome, frac)
        # dominante = mais que o dobro de qualquer corredor secundario (9,3% cada)
        assert frac > 2 * 0.093


def test_horizonte_maior_so_acrescenta_no_fim(cen):
    """Aumentar o horizonte NAO redesenha a demanda: a de horizonte menor e
    prefixo exato da de horizonte maior, mesma seed e mesma taxa.

    E o que permite calibrar com runs curtas e usar o resultado nas longas sem
    desconfiar que "e outro transito". Sai de graca do desenho (as chegadas sao
    consumidas em ordem de tempo, um `random()` por chegada), mas so vale
    enquanto o gerador nao passar a sortear nada em funcao do total.
    """
    from feira.demanda import GeradorDemandaAberta
    curta = GeradorDemandaAberta(veh_por_hora=3500.0, horizonte_s=1200.0)
    longa = GeradorDemandaAberta(veh_por_hora=3500.0, horizonte_s=3600.0)
    curta.gera(cen, 42, forcar=True)
    linhas_curta = cen.rou_file(42).read_text(encoding="utf-8").splitlines()
    longa.gera(cen, 42, forcar=True)
    linhas_longa = cen.rou_file(42).read_text(encoding="utf-8").splitlines()
    def veic(ls):
        return [x for x in ls if x.strip().startswith("<vehicle")]

    a, b = veic(linhas_curta), veic(linhas_longa)
    assert 0 < len(a) < len(b)
    assert a == b[:len(a)]


def test_departlane_best_no_arquivo(ger, cen):
    """`departLane="first"` (o default) faz TODO carro nascer na faixa 0: avenida
    de 3 faixas escoando em fila unica. Medido na Vila Olimpia: producao +119%
    com "best"."""
    ger.gera(cen, 42, forcar=True)
    txt = cen.rou_file(42).read_text(encoding="utf-8")
    assert 'departLane="best"' in txt
    assert 'departLane="first"' not in txt


# ------------------------------------------------------------------ integracao
def test_o_sumo_carrega_a_demanda_sem_erro(ger, cen):
    """O teste que fecha o circuito: rota valida para o ROTEADOR DO SUMO, nao so
    para o nosso Dijkstra.

    O unico aviso tolerado e o teleporte por colisao numerica, que existe e esta
    MEDIDO (docs/CALIBRACAO_ABERTA.md §6-7: 0,49% dos veiculos a 3800 veh/h, em
    trecho de multiplas faixas). O teto de 3% aqui e guarda de regressao: se
    alguma mudanca fizer a colisao explodir, isto quebra em vez de passar batido.
    """
    from feira.contratos import cenario
    c = cenario("aberta.maquete")
    ger.gera(cen, 42, forcar=True)
    exe = str(Path(os.environ["SUMO_HOME"]) / "bin" / "sumo")
    r = subprocess.run(
        [exe, "-c", c.sumocfg, "-r", str(cen.rou_file(42)), "--seed", "42",
         "--end", "300", "--no-step-log", "true",
         "--duration-log.statistics", "true"],
        capture_output=True, text=True)
    saida = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, saida
    assert "Error" not in saida, saida

    avisos = [ln for ln in saida.splitlines() if ln.startswith("Warning")]
    fora_de_colisao = [ln for ln in avisos if "eleporting" not in ln]
    assert fora_de_colisao == [], fora_de_colisao

    import re
    inseridos = int(re.search(r"Inserted: (\d+)", saida).group(1))
    colisoes = sum(1 for ln in avisos if "collision with vehicle" in ln)
    assert inseridos > 100, saida
    assert colisoes <= 0.03 * inseridos, "%d colisoes em %d inseridos" % (
        colisoes, inseridos)


@pytest.fixture(scope="module")
def replay():
    """`sumo/aberta/replay.py` carregado por caminho: `sumo/` e diretorio de
    artefatos do SUMO, nao um pacote Python (e nao deve virar um)."""
    import importlib.util
    caminho = RAIZ / "sumo" / "aberta" / "replay.py"
    spec = importlib.util.spec_from_file_location("replay_a1", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("seed", [42, 43, 44])
def test_replay_de_t0_reproduz_o_mesmo_estado(seed, ger, cen, replay):
    """DoD (e): rodar de t=0 ate um t0 arbitrario duas vezes da estado IDENTICO.

    E o que a Frente 3 (modo jogo) precisa: a rodada parte de um estado neutro
    canonico da seed, reconstruido por replay - os tres bracos tem que ver
    exatamente a mesma rede quando o publico assume os semaforos.

    A impressao digital e (id, edge, posicao, velocidade) de TODO veiculo vivo, e
    nao so a contagem: contagem igual com os carros noutros lugares nao e o mesmo
    estado. `t0=300 s` aqui e so para o teste ser barato; o numero de verdade
    (1200 s, 3 seeds) esta em docs/CALIBRACAO_ABERTA.md.
    """
    ger.gera(cen, seed, forcar=True)
    rou = str(cen.rou_file(seed))
    f1 = replay.impressao_em(rou, seed, t0=300.0)
    f2 = replay.impressao_em(rou, seed, t0=300.0)
    assert f1 == f2
    assert len(f1) > 20, "rede vazia demais para o teste valer algo"


# ======================================================= o .sumocfg por seed
# O bug que estes testes fecham (achado pelo agente A2): com um `.sumocfg` so, a
# Arena subia a MESMA demanda para qualquer seed, SEM erro - o `TrafficEnv` do
# maquete monta a linha de comando do SUMO sozinho e nao aceita route-files.


def test_gera_escreve_o_sumocfg_da_seed(ger, cen):
    import xml.etree.ElementTree as ET

    from feira.demanda import caminho_config_seed
    man = ger.gera(cen, 42, forcar=True)
    cfg = caminho_config_seed(cen, 42)
    assert cfg.exists() and cfg.name == "maquete_aberta_s42.sumocfg"
    assert man.parametros["sumocfg_seed"] == cfg.name
    ET.parse(cfg)                                    # declaracao XML no lugar certo
    texto = cfg.read_text(encoding="utf-8")
    assert '<route-files value="../demanda/demanda_s42.rou.xml"/>' in texto
    # e o canonico continua SEM demanda: subir ele sozinho da rede vazia, nunca
    # "a demanda de outra seed".
    assert "<route-files value" not in Path(cen.sumocfg).read_text(encoding="utf-8")


def test_o_caminho_do_cfg_bate_com_o_que_a_arena_procura(ger, cen):
    """Se as duas formacoes de nome divergirem, a Arena cai no canonico e a
    demanda para de seguir a seed - em silencio, que e o bug original."""
    from feira.arena.sumo import _sumocfg_da_seed
    from feira.demanda import caminho_config_seed
    ger.gera(cen, 43, forcar=True)
    assert Path(_sumocfg_da_seed(cen, 43)) == caminho_config_seed(cen, 43)


def test_sumocfg_da_seed_falha_alto_quando_falta(ger, cen):
    """Quem pedir a seed 43 e so achar o canonico recebe EXCECAO, nunca a
    demanda da 42."""
    from feira.demanda import ConfigDaSeedAusente, caminho_config_seed, sumocfg_da_seed
    ger.gera(cen, 42, forcar=True)
    assert sumocfg_da_seed(cen, 42) == caminho_config_seed(cen, 42)
    with pytest.raises(ConfigDaSeedAusente, match="43"):
        sumocfg_da_seed(cen, 43)


def test_manifesto_recusa_cfg_da_seed_trocado(ger, cen):
    """O manifesto e o ponto por onde todo braco passa antes de subir o SUMO -
    e por isso a checagem mora nele."""
    from feira.demanda import ConfigDaSeedAusente, caminho_config_seed
    ger.gera(cen, 42, forcar=True)
    assert ger.manifesto(cen, 42).seed == 42
    cfg = caminho_config_seed(cen, 42)
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("demanda_s42", "demanda_s43"),
                   encoding="utf-8")
    with pytest.raises(ConfigDaSeedAusente):
        ger.manifesto(cen, 42)
    cfg.unlink()
    with pytest.raises(ConfigDaSeedAusente):
        ger.manifesto(cen, 42)


def test_gera_recria_o_cfg_apagado_sem_regerar_as_rotas(ger, cen):
    """O cfg nao vai versionado: some num clone novo ou num `git clean`. Recriar
    tem que ser barato e NAO pode mexer no `.rou.xml` (a run que o consumiu
    continua valida)."""
    from feira.demanda import caminho_config_seed
    ger.gera(cen, 42, forcar=True)
    mtime = cen.rou_file(42).stat().st_mtime_ns
    caminho_config_seed(cen, 42).unlink()
    ger.gera(cen, 42)
    assert caminho_config_seed(cen, 42).exists()
    assert cen.rou_file(42).stat().st_mtime_ns == mtime


def test_seeds_diferentes_sobem_trafego_diferente_no_sumo(ger, cen):
    """O teste que teria pego o bug: ponta a ponta, com `-c` e SEM `-r`.

    Comparar o sha do `.rou.xml` nao bastava - os arquivos SEMPRE foram
    diferentes; o que era igual era o que o SUMO de fato subia, porque o
    `.sumocfg` era um so. Aqui a asserção e sobre veiculos INSERIDOS.
    """
    import re
    exe = str(Path(os.environ["SUMO_HOME"]) / "bin" / "sumo")

    def inseridos(cfg: Path) -> int:
        r = subprocess.run([exe, "-c", str(cfg), "--end", "600", "--no-step-log",
                            "true", "--duration-log.statistics", "true"],
                           capture_output=True, text=True)
        saida = (r.stdout or "") + (r.stderr or "")
        assert r.returncode == 0, saida
        return int(re.search(r"Inserted: (\d+)", saida).group(1))

    from feira.demanda import caminho_config_seed
    ger.gera(cen, 42, forcar=True)
    ger.gera(cen, 43, forcar=True)
    n42 = inseridos(caminho_config_seed(cen, 42))
    n43 = inseridos(caminho_config_seed(cen, 43))
    assert n42 > 100 and n43 > 100, (n42, n43)
    assert n42 != n43, "duas seeds subiram a MESMA demanda: %d" % n42
    # e o canonico sozinho nao sobe demanda nenhuma - nao ha "demanda default"
    # que alguem meca sem perceber qual seed estava rodando.
    assert inseridos(Path(cen.sumocfg)) == 0


def test_parametro_mudado_regera_em_vez_de_devolver_o_disco(cen):
    """Manifesto que bate com o arquivo mas NAO com o codigo tem que regerar.

    `ManifestoDemanda.confere()` prova que o ARQUIVO bate com o MANIFESTO. Nao
    prova que o manifesto bate com o GERADOR de hoje. Sem esta guarda, mudar
    `horizonte_s` (ou a taxa) no codigo deixava em disco a demanda do regime
    ANTIGO, com o sha intacto, e `gera()` a devolvia calada - a mesma classe de
    falha silenciosa que fez a Arena rodar a malha vazia. Foi o que obrigou o A5 a
    carimbar o horizonte no nome da pasta em `tune_baseline_capacidade.py`.
    """
    from feira.demanda import GeradorDemandaAberta

    curto = GeradorDemandaAberta(veh_por_hora=3600.0, horizonte_s=600.0)
    a = curto.gera(cen, 42)
    assert curto.ultimo_motivo == "nao existia em disco"

    # segunda chamada, MESMOS parametros: reaproveita, nao reescreve
    b = curto.gera(cen, 42)
    assert curto.ultimo_motivo is None
    assert b.sha256 == a.sha256

    # so o horizonte muda. O arquivo em disco continua integro e batendo com o
    # seu proprio manifesto - e mesmo assim tem que ser reescrito.
    longo = GeradorDemandaAberta(veh_por_hora=3600.0, horizonte_s=1200.0)
    c = longo.gera(cen, 42)
    assert longo.ultimo_motivo and "horizonte_s" in longo.ultimo_motivo
    assert c.sha256 != a.sha256
    assert c.t_ultimo > a.t_ultimo

    # e a taxa idem, pelo mesmo motivo
    outra = GeradorDemandaAberta(veh_por_hora=1800.0, horizonte_s=1200.0)
    outra.gera(cen, 42)
    assert outra.ultimo_motivo and "veh_por_hora" in outra.ultimo_motivo
