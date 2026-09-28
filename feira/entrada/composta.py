"""`FonteComposta` — várias fontes ao mesmo tempo; quem tiver foco manda.

É a composição certa para a feira (docs/GAMIFICACAO.md §3.3): a página projetada
(`FonteWeb`) e o teclado do terminal (`TecladoInput`) lidos JUNTOS. Não é a
`FonteComReserva`, que troca de mão única quando a primária morre: aqui nenhuma
morre "de verdade" — o que muda é qual janela tem o foco do sistema operacional, e
isso vai e volta. Com as duas drenadas a cada `poll()`, o jogo recebe a tecla de
onde ela cair, e o feedback vai para todas (a página desenha, o teclado guarda).

A botoeira física (A4), quando existir, entra na mesma lista.
"""
from __future__ import annotations

from ..contratos import EventoBotao, FonteEntrada, valida_estados

__all__ = ["FonteComposta"]


class FonteComposta:
    """União de fontes com o mesmo número de botões."""

    passo_por_tick = False

    def __init__(self, *fontes: FonteEntrada, nome: str | None = None) -> None:
        if not fontes:
            raise ValueError("FonteComposta precisa de pelo menos uma fonte")
        n = {int(f.n_botoes) for f in fontes}
        if len(n) != 1:
            raise ValueError("as fontes têm números de botões diferentes: %s — o índice "
                             "do botão significaria coisas diferentes" % sorted(n))
        self.fontes = tuple(fontes)
        self.n_botoes = n.pop()
        self.nome = nome or "+".join(getattr(f, "nome", "?") for f in fontes)
        self._ao_abortar = None

    # ------------------------------------------------------------ operador
    @property
    def ao_abortar(self):
        return self._ao_abortar

    @ao_abortar.setter
    def ao_abortar(self, fn) -> None:
        """Propaga para toda fonte que saiba avisar o aborto (Esc, botão da página)."""
        self._ao_abortar = fn
        for f in self.fontes:
            if hasattr(f, "ao_abortar"):
                try:
                    f.ao_abortar = fn
                except Exception:
                    pass

    def ao_tick(self, t: float) -> None:
        """O tick da grade, repassado a toda fonte que saiba mostrá-lo (a página)."""
        for f in self.fontes:
            m = getattr(f, "ao_tick", None)
            if callable(m):
                try:
                    m(t)
                except Exception:
                    pass

    # ------------------------------------------------------------------ C6
    def poll(self) -> list[EventoBotao]:
        eventos: list[EventoBotao] = []
        for f in self.fontes:
            try:
                eventos.extend(f.poll())
            except Exception:
                pass
        eventos.sort(key=lambda e: e.t_wall)
        return eventos

    def feedback(self, estados: list[str], start: str | None = None) -> None:
        estados = list(valida_estados(estados, self.n_botoes))
        for f in self.fontes:
            try:
                f.feedback(list(estados), start)
            except Exception:
                pass          # LED que não acende não derruba a rodada

    def feedback_start(self, estado: str) -> None:
        for f in self.fontes:
            m = getattr(f, "feedback_start", None)
            if callable(m):
                try:
                    m(estado)
                except Exception:
                    pass

    def viva(self) -> bool:
        return any(f.viva() for f in self.fontes)

    def close(self) -> None:
        for f in self.fontes:
            try:
                f.close()
            except Exception:
                pass
