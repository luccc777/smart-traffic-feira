"""`FonteComReserva` — a botoeira caindo no meio da rodada não derruba o jogo.

Risco 7 do plano: um operador só na feira. Se o cabo USB sai, `viva()` da fonte
primária vira False e a partir daí tudo — `poll`, `feedback` — passa a ir para a
reserva (o teclado), **sem interromper a rodada**. É o DoD (c) do agente A4, mas
mora aqui porque não depende de `pyserial`: a primária é qualquer `FonteEntrada`.

A troca é de mão única de propósito. Uma botoeira que reconecta no meio da
rodada voltaria a mandar bordas de um dispositivo que perdeu o estado dos LEDs,
e o público veria o painel discordar da tela. Reconexão é entre rodadas
(`reconecta()`), com o operador olhando.
"""
from __future__ import annotations

from ..contratos import EventoBotao, FonteEntrada, valida_estados

__all__ = ["FonteComReserva"]


class FonteComReserva:
    """Fonte primária com queda automática para uma reserva."""

    passo_por_tick = False

    def __init__(self, primaria: FonteEntrada, reserva: FonteEntrada,
                 *, nome: str | None = None) -> None:
        if int(primaria.n_botoes) != int(reserva.n_botoes):
            raise ValueError("primária tem %d botões e a reserva %d — o índice do "
                             "botão significaria coisas diferentes nas duas"
                             % (primaria.n_botoes, reserva.n_botoes))
        self.primaria = primaria
        self.reserva = reserva
        self.n_botoes = int(primaria.n_botoes)
        self.nome = nome or "%s+%s" % (primaria.nome, reserva.nome)
        self.caiu = False
        self.quedas = 0

    # -------------------------------------------------------------- C6
    @property
    def ativa(self) -> FonteEntrada:
        return self.reserva if self.caiu else self.primaria

    def poll(self) -> list[EventoBotao]:
        if not self.caiu and not self.primaria.viva():
            self.caiu = True
            self.quedas += 1
        eventos = list(self.ativa.poll())
        if not self.caiu:
            # a reserva continua sendo drenada para não acumular um buffer de
            # teclas que dispararia tudo de uma vez na hora da queda.
            try:
                self.reserva.poll()
            except Exception:
                pass
        return eventos

    def feedback(self, estados: list[str], start: str | None = None) -> None:
        estados = list(valida_estados(estados, self.n_botoes))
        for fonte in (self.primaria, self.reserva):
            try:
                fonte.feedback(list(estados), start)
            except Exception:
                # LED que não acende não pode derrubar a rodada.
                pass

    def feedback_start(self, estado: str) -> None:
        """O 13º LED (o botão START), repassado a quem souber acendê-lo.

        MANTIDO por compatibilidade: o C6 passou a aceitar `feedback(estados,
        start=...)`, que é o caminho preferido. Este atalho continua útil para
        acender só o START sem repintar os doze semáforos, e para fontes
        antigas que ainda não tenham o parâmetro."""
        for fonte in (self.primaria, self.reserva):
            metodo = getattr(fonte, "feedback_start", None)
            if callable(metodo):
                try:
                    metodo(estado)
                except Exception:
                    pass

    def viva(self) -> bool:
        """Viva enquanto QUALQUER uma responder — é o ponto do conjunto."""
        return self.primaria.viva() or self.reserva.viva()

    def close(self) -> None:
        for fonte in (self.primaria, self.reserva):
            try:
                fonte.close()
            except Exception:
                pass

    # ------------------------------------------------------------ extras
    def reconecta(self) -> bool:
        """Tenta voltar para a primária. Só entre rodadas (ver o cabeçalho)."""
        if self.caiu and self.primaria.viva():
            self.caiu = False
            return True
        return False
