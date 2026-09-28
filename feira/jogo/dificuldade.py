"""O nível da seed — a hora de trânsito sorteada é um botão de dificuldade, e a tela diz.

`docs/DIFICULDADE.md` §5 mede, para o melhor humano plausível (`gulosa_fase:f=1`
com ruído de mão, 20 rodadas por seed), P(vitória contra a RL) de **0%** (seeds 101,
104, 109) a **100%** (107, 108, 111). Não é defeito: os três braços enfrentam a mesma
hora de trânsito. Mas o visitante não tem como saber que a seed era a diferença, e
por isso a tela anuncia o nível ANTES da rodada, na linguagem de jogo.

"Difícil" é difícil PARA O HUMANO — seeds em que a RL é forte. A tabela é a do A8,
fixa; o que a feira produz entra ao lado, ao vivo (`Ranking.por_seed`), e os dois
aparecem juntos, o do A8 rotulado como "previsto".
"""
from __future__ import annotations

__all__ = ["P_VITORIA_PREVISTA", "nivel_da_seed", "NIVEIS", "descreve"]

# P(vitória) do melhor humano plausível contra a RL, por seed held-out, 120 s
# (`docs/DIFICULDADE.md` §5, coluna "P(vitória) na seed").
P_VITORIA_PREVISTA: dict[int, float] = {
    100: 0.10, 101: 0.00, 102: 0.20, 103: 0.60, 104: 0.00, 105: 0.70,
    106: 0.50, 107: 1.00, 108: 1.00, 109: 0.00, 110: 0.80, 111: 1.00,
}

DIFICIL, MEDIO, FACIL, DESCONHECIDO = "dificil", "medio", "facil", "desconhecido"
NIVEIS = (DIFICIL, MEDIO, FACIL)
ROTULO = {DIFICIL: "DIFÍCIL", MEDIO: "MÉDIO", FACIL: "FÁCIL", DESCONHECIDO: "—"}


def nivel_da_seed(seed: int) -> str:
    """≤20% difícil · 20–70% médio · ≥80% fácil; seed fora das held-out: desconhecido."""
    p = P_VITORIA_PREVISTA.get(int(seed))
    if p is None:
        return DESCONHECIDO
    if p <= 0.20:
        return DIFICIL
    if p >= 0.80:
        return FACIL
    return MEDIO


def descreve(seed: int, hoje: dict | None = None) -> dict:
    """O que a tela mostra no `ocioso`: seed, nível, previsão do A8 e o que a feira já viu."""
    n = nivel_da_seed(seed)
    d = {"seed": int(seed), "nivel": n, "rotulo": ROTULO[n],
         "p_vitoria_prevista": P_VITORIA_PREVISTA.get(int(seed))}
    if hoje:
        d["hoje"] = {"jogaram": int(hoje.get("jogaram", 0)),
                     "bateram": int(hoje.get("bateram", 0))}
    return d
