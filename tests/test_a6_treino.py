"""O que o agente A6 precisa que continue verdadeiro (sem SUMO, sem torch).

Três coisas, e todas são "erro que já custou caro em algum lugar deste projeto":

1. **As faixas de seed são disjuntas.** Treinar numa held-out não quebra nada em
   tempo de execução — ele só devolve um número mais bonito e sem valor. Por isso
   a checagem é um erro alto, e por isso ela é testada.
2. **A variante de espaço de ação não mexe no contrato.** `cenario_variante`
   devolve uma CÓPIA; `RESTRICOES_ABERTA` continua sendo o default do C1.
3. **Corrida vazia é erro, não resultado.** A Arena já caiu num `.sumocfg` sem
   `<route-files>` uma vez, rodou a malha vazia e reportou o caminho certo.

Os testes marcados `sumo`/`aberta` fecham o quarto: que o loop de treino de fato
TROCA a demanda entre episódios — a armadilha nº 1 do escopo do A6.
"""
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

import pytest

from feira import _fakes as F
from feira.contratos import RESTRICOES_ABERTA, Janela, cenario
from feira.treino import avalia as A
from feira.treino.ambiente import (
    SEEDS_HELD_OUT,
    SEEDS_SELECAO,
    SEEDS_TREINO,
    SEEDS_VALIDACAO,
    SeedContaminada,
    cenario_variante,
    checa_disjuncao,
    seeds_de_texto,
)

_RAIZ = Path(__file__).resolve().parents[1]
TEM_SUMO = bool(os.environ.get("SUMO_HOME")) and cenario("aberta.maquete").disponivel()
# Os marcadores do repo (`pyproject.toml`) + o skip automático: `-m "not sumo"`
# deseleciona, e uma máquina sem SUMO pula em vez de quebrar.
_pula = pytest.mark.skipif(not TEM_SUMO, reason="requer SUMO_HOME + a rede aberta")


def sumo(f):
    """`@pytest.mark.sumo` + `@pytest.mark.aberta` + o skip, num decorador só."""
    return pytest.mark.sumo(pytest.mark.aberta(_pula(f)))


# ======================================================== as faixas de seed
def test_faixas_de_seed_sao_disjuntas_por_construcao():
    assert not (set(SEEDS_TREINO) & set(SEEDS_HELD_OUT))
    assert not (set(SEEDS_TREINO) & set(SEEDS_SELECAO))
    assert not (set(SEEDS_VALIDACAO) & set(SEEDS_HELD_OUT))
    assert not (set(SEEDS_VALIDACAO) & set(SEEDS_SELECAO))
    assert not (set(SEEDS_VALIDACAO) & set(SEEDS_TREINO))


@pytest.mark.parametrize("invasora", [100, 111, 42, 47])
def test_treinar_em_seed_reservada_levanta(invasora):
    with pytest.raises(SeedContaminada):
        checa_disjuncao((200, 201, invasora), (230,))


def test_validar_numa_seed_de_treino_levanta():
    """A validação ESCOLHE o checkpoint. Se ela for seed de treino, escolhe pelo
    que foi decorado — e o 'melhor' checkpoint é o que mais sobreajustou."""
    with pytest.raises(SeedContaminada):
        checa_disjuncao((200, 201), (201,))


def test_disjuncao_aceita_o_default():
    checa_disjuncao(SEEDS_TREINO, SEEDS_VALIDACAO)


@pytest.mark.parametrize("txt,esperado", [
    ("200-203", (200, 201, 202, 203)),
    ("200,205", (200, 205)),
    ("100-102,110", (100, 101, 102, 110)),
    (" 42 ", (42,)),
])
def test_seeds_de_texto(txt, esperado):
    assert seeds_de_texto(txt) == esperado


# ================================================ a variante de espaço de ação
def test_variante_sem_override_e_o_cenario_do_contrato():
    assert cenario_variante() == cenario("aberta.maquete")
    assert cenario_variante().restricoes is RESTRICOES_ABERTA


def test_variante_nao_muda_o_default_do_contrato():
    """A cópia é local: mudar a grade num experimento não pode vazar para o C1 —
    as restrições são as MESMAS para os três braços por decisão fechada."""
    v = cenario_variante(decision_interval=10, min_green=10)
    assert v.restricoes.assinatura == "di10/vm10/am3/mr0"
    assert v.restricoes.verde_minimo_alcancavel == 17
    assert cenario("aberta.maquete").restricoes.assinatura == "di5/vm7/am3/mr0"
    assert RESTRICOES_ABERTA.decision_interval == 5


def test_variante_preserva_amarelo_e_o_resto_do_cenario():
    v = cenario_variante(max_red=60.0)
    base = cenario("aberta.maquete")
    assert v.restricoes.yellow == base.restricoes.yellow == 3
    assert (v.net_file, v.sumocfg, v.warmup_s, v.rou_pattern) == \
           (base.net_file, base.sumocfg, base.warmup_s, base.rou_pattern)
    assert v.restricoes.assinatura == "di5/vm7/am3/mr60"


def test_max_red_curto_demais_e_recusado_pelo_contrato():
    """O C1 já valida `max_red > min_green + yellow`: abaixo disso a guarda
    dispara antes de o verde mínimo fechar e TODA decisão do agente vira no-op."""
    with pytest.raises(ValueError):
        cenario_variante(max_red=9.0)


# ============================================================ corrida vazia
def test_corrida_sem_insercao_levanta():
    r = F.resultado_fake(inseridos=0, entregues=0, ativos_fim=0, ativos_inicio=0)
    with pytest.raises(A.CorridaVazia):
        A._confere_insercao(r, "rl")


def test_corrida_com_insercao_passa():
    r = F.resultado_fake()
    assert A._confere_insercao(r, "rl") is r


# ================================================= o trânsito entre processos
def test_resultado_sobrevive_ao_round_trip_de_processo():
    """`avalia_seeds(procs>1)` devolve o `Resultado` como dict e o reconstrói.
    Se o round-trip perder um campo, o t-test roda sobre outra coisa."""
    r = F.resultado_fake(chave=F.chave_fake(seed=107, t0=300.0, t1=7500.0))
    assert A._de_dict(asdict(r)) == r


# =========================================================== o resumo pareado
def _par(seed, entregues_base, entregues_novo, fila_base, fila_novo,
         t_base, t_novo):
    k = F.chave_fake(seed=seed, cenario="aberta.maquete", t0=300.0, t1=7500.0,
                     restricoes="di5/vm7/am3/mr0")
    b = F.resultado_fake(k, controlador="timer:coordenado_c60",
                         entregues=entregues_base, fila_media=fila_base,
                         tempo_medio_no_sistema=t_base)
    n = F.resultado_fake(k, controlador="rl:v1", entregues=entregues_novo,
                         fila_media=fila_novo, tempo_medio_no_sistema=t_novo)
    return b, n


def test_vitoria_na_trinca_exige_as_tres_metricas():
    """DoD (a) é uma conjunção: ganhar em fila e perder em vazão não é vitória."""
    pares = [
        _par(100, 7000, 7010, 50.0, 45.0, 160.0, 150.0),   # ganha nas três
        _par(101, 7000, 6990, 50.0, 45.0, 160.0, 150.0),   # perde vazão
        _par(102, 7000, 7010, 50.0, 55.0, 160.0, 150.0),   # perde fila
        _par(103, 7000, 7010, 50.0, 45.0, 160.0, 170.0),   # perde tempo
    ]
    res = A.resumo_json([b for b, _ in pares], [n for _, n in pares])
    assert res["vitorias_trinca"] == 1
    assert res["n_seeds"] == 4
    assert res["testes"]["entregues"]["vitorias"] == 3


def test_resumo_json_e_serializavel():
    """`inf`/`nan` não são JSON válidos — a lacuna infinita de uma corrida sem
    entregas viraria um arquivo que ninguém consegue ler de volta."""
    import json

    pares = [_par(100 + i, 7000, 7010, 50.0, 45.0, 160.0, 150.0) for i in range(3)]
    res = A.resumo_json([b for b, _ in pares], [n for _, n in pares])
    json.dumps(res)   # não levanta


def test_janela_comeca_no_fim_do_aquecimento_medido():
    cen = cenario("aberta.maquete")
    j = A.janela_de(cen, 7200.0)
    assert j == Janela(300.0, 7500.0)


# =============================================== o adversário é o coordenado
def test_o_plano_adversario_existe_e_e_o_congelado():
    from feira.treino.ambiente import PLANO_BASELINE

    p = Path(PLANO_BASELINE)
    assert p.name == "coordenado_c60.json", "o adversário do A6 é o plano congelado"
    assert p.exists()


def test_warm_start_default_tem_a_grade_do_cenario():
    """`maq30_ats_di5_full` é o único checkpoint do maquete treinado em di5/mg7 —
    a MESMA grade de `RESTRICOES_ABERTA`. O de 10/10 serve ao braço 10/10."""
    from feira.treino.loop import CKPT_DI5, CKPT_DI10

    cfg = Path(CKPT_DI5).resolve().parent.parent / "experiments" / "maq30_ats_di5_full"
    assert Path(CKPT_DI5).name == "maq30_ats_di5_full_best.pt"
    assert Path(CKPT_DI10).name == "maq30_ats_full_best.pt"
    if (cfg / "config.json").exists():
        import json

        env = json.loads((cfg / "config.json").read_text(encoding="utf-8"))["env_scenario"]
        assert (env["decision_interval"], env["min_green"]) == \
               (RESTRICOES_ABERTA.decision_interval, RESTRICOES_ABERTA.min_green)


# ==================================================== com SUMO: a demanda gira
@sumo
def test_o_loop_troca_a_demanda_entre_episodios(tmp_path):
    """A armadilha nº 1 do A6: `train.py` do maquete constrói o env UMA vez e o
    `.rou.xml` fica fixo na run inteira — todo episódio veria a mesma realização
    e a política decoraria uma. Aqui: dois episódios, duas seeds, dois sha."""
    from feira.arena.sumo import _amarra_sim, sha_demanda

    cen = cenario_variante()
    cen.aplicar(forcar=True)
    C = _amarra_sim(cen, 200)
    from feira.arena.sumo import _sumocfg_da_seed

    vistos = []
    for s in (200, 201):
        C.SUMOCFG = _sumocfg_da_seed(cen, s)
        vistos.append((C.SUMOCFG, sha_demanda(cen, s)))
    assert vistos[0][0] != vistos[1][0], "o `.sumocfg` não mudou entre episódios"
    assert vistos[0][1] != vistos[1][1], "o sha da demanda não mudou entre episódios"


@sumo
def test_todas_as_seeds_de_treino_e_validacao_existem_em_disco():
    """Uma seed sem `.rou.xml` só falharia no meio do treino, horas depois."""
    cen = cenario("aberta.maquete")
    faltando = [s for s in tuple(SEEDS_TREINO) + tuple(SEEDS_VALIDACAO)
                if not cen.rou_file(s).exists()]
    assert not faltando, "gere com `python -m feira.demanda --seeds ...`: %s" % faltando


@sumo
def test_o_pipeline_inteiro_roda_e_o_checkpoint_escolhido_e_avaliavel(tmp_path):
    """Um episódio minúsculo, ponta a ponta: warm start -> demanda rotativa ->
    treino -> `.pt` em disco -> validação pela Arena contra o `coordenado_c60`.

    Existe porque cada elo já quebrou sozinho em algum lugar deste projeto — e um
    treino de 3 h que descobre na última linha que o checkpoint não carrega é o
    pior jeito possível de descobrir isso.
    """
    from feira.treino.loop import CKPT_DI5, ConfigTreino, treina

    if not Path(CKPT_DI5).exists():
        pytest.skip("checkpoint de warm start ausente")
    cfg = ConfigTreino(
        nome="teste_pipeline", episodios=1, segundos_por_episodio=100,
        seeds_treino=(200,), seeds_validacao=(230,), avalia_cada=1,
        janela_validacao_s=300.0, learning_starts=10, batch_size=8,
        saida=str(tmp_path / "run"), copia_para_results=False,
    )
    resumo = treina(cfg)

    assert resumo["episodios"] == 1
    assert resumo["checkpoint"] and Path(resumo["checkpoint"]).exists()
    assert (tmp_path / "run" / "train_log.csv").exists()
    assert (tmp_path / "run" / "eval_log.csv").exists()
    # a seleção por vazão só carimba um checkpoint quando a corrida foi SÃ
    assert resumo["melhor_vazao_validacao"] is not None
    assert resumo["restricoes"] == "di5/vm7/am3/mr0"
