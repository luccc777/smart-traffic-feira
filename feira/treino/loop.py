"""O loop de treino da DDQN+GNN no cenário `aberta.maquete` (agente A6).

Reaproveita o `DDQNAgent`, a `GraphQNetwork` e o `TrafficEnv` do maquete — nada
de rede neural é reescrito aqui. O que este módulo acrescenta são as QUATRO
coisas que o `sim.training.train` do maquete não podia ter, porque ele foi
escrito para a rede FECHADA:

1. **A demanda ROTACIONA por episódio.** `train.py` faz
   `TrafficEnv(deterministic_demand=False)` uma vez e depois `env.reset()`. Na
   rede fechada isso basta: a frota persistente reembaralha os destinos a cada
   reset. Na rede aberta a demanda vem do `.rou.xml` que o `constants.SUMOCFG`
   aponta, **fixo na run inteira** — todo episódio veria a MESMA realização e a
   política decoraria uma. Aqui o `SUMOCFG` (e o seed do SUMO) é reapontado a
   cada episódio, sorteado de um pool de seeds de treino.
2. **Aquecimento de 300 s sob o timer, antes de o agente assumir.** É o mesmo
   plano de aquecimento que a Arena roda (`Cenario.warmup_plano`), pelo mesmo
   motivo: os 300 s iniciais de uma rede aberta são o transiente de ENCHIMENTO,
   um regime que não existe na janela em que a política vai ser medida.
3. **A validação passa pela `feira.arena.ArenaSumo` contra o `coordenado_c60`.**
   O `evaluate_policy`/`FixedTimerSim` do maquete pressupõem frota fechada.
4. **Seleção de checkpoint por VAZÃO, com porta de sanidade.** DoD (c): a média
   de tempo de viagem só conta quem chegou, então uma política que TRAVA a rede
   melhora essa métrica por seleção de amostra. Vazão desaba sob travamento.

WARM START
----------
Os pesos da GNN são compartilhados por nó (`docs` do `sim.models`), então o
checkpoint da rede fechada (N=10) carrega numa rede de N=12 sem tradução. O que
NÃO transfere junto é o `global_step`: carregá-lo deixaria o ε no piso, e a
política entraria em fine-tuning sem exploração nenhuma. Por isso o
`global_step` é zerado no warm start e o ε recomeça de `epsilon_start` (que o
chamador baixa para ~0,2 quando parte de pesos bons).

PARALELISMO
-----------
Um processo por variante. `sim.environment.constants` é singleton de processo:
duas variantes com `decision_interval` diferente no mesmo processo mediriam a
mesma coisa duas vezes, em silêncio.
"""
from __future__ import annotations

import csv
import json
import math
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..contratos import Resultado
from .ambiente import PLANO_BASELINE, RAIZ, SEEDS_TREINO, SEEDS_VALIDACAO, checa_disjuncao
from .avalia import janela_de, roda_um

__all__ = ["ConfigTreino", "treina"]

_EXPERIMENTOS = RAIZ / "experiments"
_RESULTADOS = RAIZ / "results" / "rl"
# Warm start default: `maq30_ats_di5_full` é o único checkpoint do maquete
# treinado em di5/mg7 — A MESMA grade do cenário aberto (`di5/vm7/am3`). O
# `maq30_ats_full` (10/10) fica como warm start do braço 10/10 do A/B.
CKPT_DI5 = RAIZ.parent / "smart-traffic-maquete" / "results" / "maq30_ats_di5_full_best.pt"
CKPT_DI10 = RAIZ.parent / "smart-traffic-maquete" / "results" / "maq30_ats_full_best.pt"


@dataclass
class ConfigTreino:
    """Tudo que define uma variante. Vai inteiro para o `config.json` da run."""

    nome: str
    # --- duração ---
    episodios: int = 160
    segundos_por_episodio: int = 3600
    # --- espaço de ação (None = o default do C1: di5/vm7/am3/mr0) ---
    decision_interval: int | None = None
    min_green: int | None = None
    max_red: float | None = None
    # --- recompensa ---
    recompensa: str = "queue"          # queue | pressure | diff_waiting | composite
    escala_recompensa: float = 1.0
    penalidade_troca: float = 0.0
    # --- seeds ---
    seeds_treino: tuple[int, ...] = SEEDS_TREINO
    seeds_validacao: tuple[int, ...] = SEEDS_VALIDACAO[:2]
    semente_torch: int = 7             # torch/numpy/random. NÃO é seed de demanda.
    # --- warm start ---
    warm_start: str | None = str(CKPT_DI5)
    # --- DDQN ---
    lr: float = 3e-4
    gamma: float = 0.99
    batch_size: int = 64
    buffer_capacity: int = 50_000
    epsilon_start: float = 0.20        # warm start: pesos já bons, exploração curta
    epsilon_end: float = 0.01
    epsilon_decay_steps: int = 40_000
    target_update_freq: int = 1000
    grad_clip: float = 10.0
    learning_starts: int = 1000
    # --- validação ---
    avalia_cada: int = 10
    janela_validacao_s: float = 7200.0
    plano_baseline: str = PLANO_BASELINE
    # --- infra ---
    threads: int = 1
    device: str = "cpu"
    saida: str = ""
    # `results/rl/<nome>.pt` é a prateleira dos CANDIDATOS a política da feira.
    # Uma corrida de fumaça não publica campeão — por isso a cópia é opcional.
    copia_para_results: bool = True

    def dir_saida(self) -> Path:
        return Path(self.saida) if self.saida else (_EXPERIMENTOS / self.nome)

    def config_recompensa(self):
        from sim.environment.rewards import RewardConfig

        return RewardConfig(kind=self.recompensa, scale=self.escala_recompensa,
                            switch_penalty=self.penalidade_troca)

    def hparams(self):
        from sim.agents import HParams

        return HParams(lr=self.lr, gamma=self.gamma, batch_size=self.batch_size,
                       buffer_capacity=self.buffer_capacity,
                       epsilon_start=self.epsilon_start, epsilon_end=self.epsilon_end,
                       epsilon_decay_steps=self.epsilon_decay_steps,
                       target_update_freq=self.target_update_freq,
                       grad_clip=self.grad_clip, learning_starts=self.learning_starts)


@dataclass
class _Csv:
    """CSV incremental — cabeçalho no primeiro write, flush a cada linha.

    Flush por linha de propósito: um treino de 3 h que morre no meio tem que
    deixar em disco tudo o que já mediu.
    """

    path: Path
    _campos: list[str] | None = field(default=None, init=False)

    def escreve(self, linha: dict) -> None:
        novo = self._campos is None
        if novo:
            self._campos = list(linha.keys())
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self._campos)
            if novo:
                w.writeheader()
            w.writerow(linha)


def _aquece(env, C, topo, cen, leitor, arena, alvo_s: float) -> int:
    """Roda o plano de aquecimento até `alvo_s` (tempo SIMULADO). Devolve sim-steps.

    Usa o mesmo `ControladorTimer(BASELINE_GREEN)` e a mesma `Observacao` que a
    `ArenaSumo` monta — é isso que faz o estado em que o agente ASSUME o controle
    durante o treino ser o mesmo estado em que ele assume na avaliação.
    """
    import traci

    from ..controladores import ControladorTimer

    aquecedor = ControladorTimer(float(C.BASELINE_GREEN), nome="aquecimento")
    aquecedor.reset(topo, cen.restricoes, float(traci.simulation.getTime()))
    n = 0
    while float(traci.simulation.getTime()) < alvo_s:
        obs = arena._observacao(env, C, topo, leitor, float(traci.simulation.getTime()))
        for _sub, _ in env.step_substeps(aquecedor.decide(obs)):
            leitor.le(acumula=False)
            n += 1
    return n


def _baseline_validacao(cen, seeds, janela, plano: str, destino: Path) -> dict[int, Resultado]:
    """O `coordenado_c60` nas seeds de validação — rodado UMA vez e cacheado.

    Plano de tempo fixo + demanda em arquivo = corrida determinística: o número
    não muda entre avaliações, e recomputá-lo a cada 10 episódios dobraria o
    custo da validação sem trazer informação.
    """
    from ..controladores import ControladorCoordenado

    saida: dict[int, Resultado] = {}
    for s in seeds:
        ctl = ControladorCoordenado(plano, nome="timer:coordenado_c60")
        saida[int(s)] = roda_um(cen, int(s), ctl, janela)
    destino.write_text(json.dumps(
        {str(k): {"entregues": v.entregues, "fila_media": v.fila_media,
                  "tempo_medio_no_sistema": v.tempo_medio_no_sistema,
                  "tempo_medio_entregue": v.tempo_medio_entregue,
                  "espera_media": v.espera_media, "inseridos": v.inseridos,
                  "backlog_insercao": v.backlog_insercao}
         for k, v in saida.items()}, indent=2, ensure_ascii=False), encoding="utf-8")
    return saida


def _valida(cen, seeds, janela, ckpt: Path, base: dict[int, Resultado]) -> dict:
    """Roda a política greedy nas seeds de validação e devolve o agregado.

    O braço RL passa pelo `ControladorRL` carregando o `.pt` de DISCO — não pelo
    agente em memória. Assim o que é medido é literalmente o arquivo que pode ser
    escolhido, e um bug de serialização aparece aqui, não na held-out.
    """
    from ..contratos import comparar
    from ..controladores import ControladorRL
    from ..metricas import sinais_de_travamento

    linhas = []
    for s in seeds:
        ctl = ControladorRL(str(ckpt), nome="rl:validacao")
        r = roda_um(cen, int(s), ctl, janela)
        d = comparar(base[int(s)], r).deltas
        linhas.append((int(s), r, d))
    # A porta de sanidade da seleção. `sane()` sozinho NÃO basta, e isto está
    # medido nesta própria corrida: a variante `pressure`+`max_red` produziu uma
    # validação com lacuna de sobrevivência de 94% e backlog de 660 carros que
    # `sane()` APROVOU — o backlog ficou em 9,8% dos agendados, um décimo de
    # ponto abaixo do teto de 10% do C5. `sinais_de_travamento` (limiar de
    # lacuna declarado pelo chamador, como o C5 manda) pega o caso.
    fora = [f for _s, r, _d in linhas for f in sinais_de_travamento(r)]
    ok = all(r.sane()[0] and not r.travou for _s, r, _d in linhas) and not fora
    n = len(linhas)
    agg = {
        "entregues": sum(r.entregues for _s, r, _d in linhas) / n,
        "fila_media": sum(r.fila_media for _s, r, _d in linhas) / n,
        "tempo_medio_no_sistema": sum(r.tempo_medio_no_sistema for _s, r, _d in linhas) / n,
        "tempo_medio_entregue": sum(r.tempo_medio_entregue for _s, r, _d in linhas) / n,
        "espera_media": sum(r.espera_media for _s, r, _d in linhas) / n,
        "d_entregues_pct": sum(d["entregues"] for _s, _r, d in linhas) / n,
        "d_tempo_sistema_pct": sum(d["tempo_medio_no_sistema"] for _s, _r, d in linhas) / n,
        "d_fila_pct": sum(d["fila_media"] for _s, _r, d in linhas) / n,
        "trincas": sum(1 for _s, _r, d in linhas
                       if d["entregues"] > 0 and d["tempo_medio_no_sistema"] > 0
                       and d["fila_media"] > 0),
        "travamentos": sum(1 for _s, r, _d in linhas if r.travou),
        "sa": ok,
        "sinais": " | ".join(sorted(set(fora))),
        "lacuna_max": max(r.lacuna_sobrevivencia for _s, r, _d in linhas),
        "backlog_max": max(r.backlog_insercao for _s, r, _d in linhas),
    }
    return agg


def treina(cfg: ConfigTreino) -> dict:
    """Treina uma variante e devolve o resumo. Escreve tudo em `cfg.dir_saida()`."""
    checa_disjuncao(cfg.seeds_treino, cfg.seeds_validacao)
    if not cfg.seeds_treino:
        raise ValueError("pool de seeds de treino vazio")

    from .ambiente import cenario_variante

    cen = cenario_variante(decision_interval=cfg.decision_interval,
                           min_green=cfg.min_green, max_red=cfg.max_red)
    cen.aplicar(forcar=True)

    # A amarração com o pacote `sim` é a da Arena — inclusive o `N_VEHICLES=0`,
    # sem o qual a frota persistente injeta carros por cima do `.rou.xml`.
    from ..arena import ArenaSumo
    from ..arena.sumo import _amarra_sim, _lanes_de_aproximacao, _LeitorDeFaixas

    seed0 = int(cfg.seeds_treino[0])
    C = _amarra_sim(cen, seed0)

    import torch
    from sim.agents import DDQNAgent
    from sim.environment import net_topology as nt
    from sim.environment.traffic_env import TrafficEnv

    torch.set_num_threads(max(1, int(cfg.threads)))
    random.seed(cfg.semente_torch)
    np.random.seed(cfg.semente_torch)
    torch.manual_seed(cfg.semente_torch)

    saida = cfg.dir_saida()
    ckpt_dir = saida / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    _RESULTADOS.mkdir(parents=True, exist_ok=True)

    arena = ArenaSumo()
    topo = arena.topologia(cen)
    lanes = _lanes_de_aproximacao(nt)
    janela_val = janela_de(cen, cfg.janela_validacao_s)
    passo = float(C.STEP_LENGTH)
    decisoes_por_ep = int(cfg.segundos_por_episodio // (C.DECISION_INTERVAL * passo))
    warmup_s = float(cen.warmup_s or 0.0)

    print("=" * 72)
    print("A6 · treino DDQN+GNN em %s | run=%s" % (cen.chave, cfg.nome))
    print("  espaço de ação: %s (verde mínimo alcançável %d s)"
          % (cen.restricoes.assinatura, cen.restricoes.verde_minimo_alcancavel))
    print("  recompensa=%s escala=%g | warm start=%s"
          % (cfg.recompensa, cfg.escala_recompensa,
             Path(cfg.warm_start).name if cfg.warm_start else "NENHUM (do zero)"))
    print("  %d episódios x %d s (%d decisões/ep) | aquecimento %.0f s sob timer %g s"
          % (cfg.episodios, cfg.segundos_por_episodio, decisoes_por_ep, warmup_s,
             float(C.BASELINE_GREEN)))
    print("  seeds treino=%s" % (list(cfg.seeds_treino),))
    print("  seeds validação=%s (janela %.0f s, adversário %s)"
          % (list(cfg.seeds_validacao), cfg.janela_validacao_s,
             Path(cfg.plano_baseline).stem))
    print("=" * 72, flush=True)

    # --- baseline de validação (1x, determinístico) -------------------------
    t_start = time.perf_counter()
    base_val = _baseline_validacao(cen, cfg.seeds_validacao, janela_val,
                                   cfg.plano_baseline, saida / "baseline_validacao.json")
    for s, r in sorted(base_val.items()):
        print("[baseline] seed %d | entregues=%d fila=%.2f t_sistema=%.1f"
              % (s, r.entregues, r.fila_media, r.tempo_medio_no_sistema), flush=True)

    # --- ambiente + agente --------------------------------------------------
    env = TrafficEnv(seed=seed0, deterministic_demand=True, reward=cfg.config_recompensa())
    agent = DDQNAgent.from_env(env, hp=cfg.hparams(), dueling=False, device=cfg.device)
    warm_ok = False
    if cfg.warm_start:
        agent.load(cfg.warm_start)
        # o `global_step` do checkpoint viria com o ε já no piso: o fine-tuning
        # começaria 100% guloso. Zerar devolve o cronograma de exploração ao
        # controle desta run (epsilon_start baixo é a alavanca, não o acaso).
        agent.global_step = 0
        warm_ok = True

    with open(saida / "config.json", "w", encoding="utf-8") as f:
        json.dump({"config": asdict(cfg), "cenario": cen.chave,
                   "restricoes": cen.restricoes.assinatura,
                   "verde_minimo_alcancavel": cen.restricoes.verde_minimo_alcancavel,
                   "net_file": cen.net_file, "n_intersecoes": topo.n,
                   "n_controlaveis": topo.n_controlaveis,
                   "state_kind": C.STATE_KIND, "state_dim": int(C.STATE_DIM),
                   "decisoes_por_episodio": decisoes_por_ep,
                   "warm_start_carregado": warm_ok,
                   "baseline": {str(k): v.entregues for k, v in base_val.items()}},
                  f, indent=2, ensure_ascii=False, default=list)

    log_treino = _Csv(saida / "train_log.csv")
    log_val = _Csv(saida / "eval_log.csv")

    melhor_vazao = -math.inf
    melhor_ep = None
    melhor_path = ckpt_dir / "best_vazao.pt"
    pool = list(int(s) for s in cfg.seeds_treino)
    rng_pool = random.Random(cfg.semente_torch)
    ordem: list[int] = []

    falhas_seguidas = 0
    ep = 0
    try:
        while ep < cfg.episodios:
            ep += 1
            if not ordem:
                ordem = pool[:]
                rng_pool.shuffle(ordem)
            seed_ep = ordem.pop()
            try:
                # a demanda deste episódio: reaponta o `.sumocfg` (é ele que carrega
                # o `<route-files>`) E o seed do SUMO, antes do reset.
                from ..arena.sumo import _sumocfg_da_seed

                C.SUMOCFG = _sumocfg_da_seed(cen, seed_ep)
                env.seed = int(seed_ep)
                env.reset()

                leitor = _LeitorDeFaixas(lanes, usar_subscriptions=True)
                leitor.le(acumula=False)
                import traci

                t_boot = float(traci.simulation.getTime())
                _aquece(env, C, topo, cen, leitor, arena, max(warmup_s, t_boot))

                estado = env.last_state if env.last_state is not None else env._get_state()
                retorno = 0.0
                perdas: list[float] = []
                chegadas = 0
                for _d in range(decisoes_por_ep):
                    acoes = agent.select_actions(estado, explore=True)
                    for _sub, _ in env.step_substeps(acoes):
                        chegadas += int(traci.simulation.getArrivedNumber())
                    proximo = env.last_state
                    recompensas = env.last_rewards
                    agent.push(estado, acoes, recompensas, proximo, False)
                    perda = agent.train_step()
                    if perda is not None:
                        perdas.append(perda)
                    retorno += float(np.sum(recompensas))
                    estado = proximo
            except Exception as e:
                if not _erro_de_sumo(e):
                    raise
                falhas_seguidas += 1
                print("[ep %d] SUMO caiu (%s) — tentativa %d/5; repetindo o episódio"
                      % (ep, type(e).__name__, falhas_seguidas), flush=True)
                try:
                    env.close()
                except Exception:
                    pass
                if falhas_seguidas >= 5:
                    raise
                ep -= 1
                time.sleep(1.0)
                continue
            falhas_seguidas = 0

            linha = {
                "episodio": ep, "seed": seed_ep,
                "wall_s": round(time.perf_counter() - t_start, 1),
                "global_step": agent.global_step,
                "epsilon": round(agent.epsilon, 4),
                "retorno": round(retorno, 1),
                "perda_media": round(float(np.mean(perdas)), 5) if perdas else None,
                "chegadas": chegadas,
                "trocas_forcadas": int(getattr(env, "forced_switches", 0)),
            }
            log_treino.escreve(linha)
            print("[ep %3d/%d] seed=%d eps=%.3f retorno=%10.1f perda=%s chegadas=%d"
                  % (ep, cfg.episodios, seed_ep, linha["epsilon"], linha["retorno"],
                     linha["perda_media"], chegadas), flush=True)

            # --- validação periódica ---------------------------------------
            if ep % cfg.avalia_cada == 0 or ep == cfg.episodios:
                env.close()
                ck = ckpt_dir / ("ckpt_ep%03d.pt" % ep)
                agent.save(ck)
                agg = _valida(cen, cfg.seeds_validacao, janela_val, ck, base_val)
                agg.update({"episodio": ep, "global_step": agent.global_step,
                            "wall_s": round(time.perf_counter() - t_start, 1)})
                log_val.escreve({k: (round(v, 4) if isinstance(v, float) else v)
                                 for k, v in agg.items()})
                print("  >> VALIDAÇÃO ep %d | entregues=%.0f (%+.2f%%) fila=%.2f (%+.2f%%) "
                      "t_sistema=%.1f (%+.2f%%) trincas=%d/%d sã=%s"
                      % (ep, agg["entregues"], agg["d_entregues_pct"], agg["fila_media"],
                         agg["d_fila_pct"], agg["tempo_medio_no_sistema"],
                         agg["d_tempo_sistema_pct"], agg["trincas"],
                         len(cfg.seeds_validacao), agg["sa"]), flush=True)
                # DoD (c): VAZÃO, e só entre corridas SÃS. Uma política que trava a
                # rede melhora o tempo médio por seleção de amostra — a vazão, não.
                if agg["sa"] and agg["entregues"] > melhor_vazao:
                    melhor_vazao = agg["entregues"]
                    melhor_ep = ep
                    agent.save(melhor_path)
                    print("     * novo melhor por vazão (%.0f entregues) -> best_vazao.pt"
                          % melhor_vazao, flush=True)
    finally:
        try:
            env.close()
        except Exception:
            pass

    agent.save(ckpt_dir / "final.pt")
    copia = _RESULTADOS / ("%s.pt" % cfg.nome)
    publicou = bool(cfg.copia_para_results and melhor_path.exists())
    if publicou:
        import shutil

        shutil.copyfile(melhor_path, copia)

    resumo = {
        "nome": cfg.nome,
        "dir": str(saida),
        "restricoes": cen.restricoes.assinatura,
        "recompensa": cfg.recompensa,
        "warm_start": cfg.warm_start,
        "episodios": ep,
        "melhor_episodio": melhor_ep,
        "melhor_vazao_validacao": None if melhor_vazao == -math.inf else round(melhor_vazao, 1),
        "baseline_vazao_validacao": round(
            sum(r.entregues for r in base_val.values()) / len(base_val), 1),
        "checkpoint": str(melhor_path) if melhor_path.exists() else None,
        "copia_results": str(copia) if publicou else None,
        "minutos": round((time.perf_counter() - t_start) / 60.0, 1),
    }
    with open(saida / "summary.json", "w", encoding="utf-8") as f:
        json.dump(resumo, f, indent=2, ensure_ascii=False)
    print("=" * 72)
    print("FIM %s | %.1f min | melhor ep=%s vazão=%s (baseline %s)"
          % (cfg.nome, resumo["minutos"], melhor_ep, resumo["melhor_vazao_validacao"],
             resumo["baseline_vazao_validacao"]))
    print("=" * 72, flush=True)
    return resumo


def _erro_de_sumo(e: Exception) -> bool:
    """O erro é uma queda de SUMO/TraCI (retentável) ou um bug de verdade?

    Mesmo critério do `sim.training.train`: `RuntimeError` genérico NÃO entra —
    um erro de shape do torch mascarado como "SUMO caiu" desperdiça 5 retries e
    esconde o traceback real.
    """
    try:
        import traci
        from sim.environment.sumo_session import SumoStartError

        return isinstance(e, (traci.exceptions.FatalTraCIError,
                              traci.exceptions.TraCIException, SumoStartError))
    except Exception:  # pragma: no cover — sem SUMO o treino nem começa
        return False
