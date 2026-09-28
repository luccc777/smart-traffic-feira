"""ranking.py — o quadro de recordes da feira: as melhores rodadas HUMANAS do dia.

POR QUE ELE MORA AQUI, E NÃO NO MOTOR
-------------------------------------
Ele se alimenta inteiro da mensagem `placar` do C7 — a mesma que a projeção já
recebe. Não precisa de nada que o motor saiba e o fio não carregue, então não há
motivo para o motor ganhar uma responsabilidade nova. `EstadoProjecao.absorve`
chama `registra()` e acabou. O NOME do visitante é assunto de tela (é a tela que o
recebe, no `ocioso`) e entra por `registra(msg, nome=...)`.

O QUE ENTRA, E O QUE NÃO ENTRA
------------------------------
Entra rodada de gente: `fase == 'resultado'`, com linha do humano, **pareada** e
**sem sinal de travamento** (`Placar.sinais`, o portão de saúde da rodada curta). Os
filtros são a mesma regra que o resto da tela segue — se a comparação não vale, não
vale para o quadro também. Uma rodada travada num quadro de recordes é pior que não
ter quadro: vira um "36" que ninguém entende e que ninguém quer bater.

A PONTUAÇÃO É PAREADA (docs/GAMIFICACAO.md §3.1)
------------------------------------------------
    score = entregues(você) − entregues(timer, MESMA seed, MESMA janela)

E não o número cru, por um motivo medido: o desvio do absoluto numa rodada de 120 s
é de 10–12 carros (é a seed: `docs/DIFICULDADE.md` §5 vai de 89 a 146 na mesma
política), o da DIFERENÇA contra o timer é 2,8–4,0 (`JOGO.md` §6.2, A8 §6.1).
Ordenar por absoluto é ordenar por sorte; ordenar pela diferença é ordenar por
habilidade com o ruído de jogada (3,3) como piso. A seed continua GRAVADA (sem ela
o número não é auditável), só não manda na ordem.

AS MEDALHAS SÃO LEITURA, NÃO ESTADO
-----------------------------------
`vencedor`, `pareado`, `sinais` continuam significando o que o C7 diz. A medalha é
calculada aqui, das três linhas: ouro = bateu a rede; prata = ficou a até
`PRATA_CARROS` da rede (o ruído de jogada — "a diferença entre você e a rede é menor
que a diferença entre duas jogadas suas"); bronze = bateu o timer.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

__all__ = ["Marca", "Ranking", "medalha_de", "normaliza_nome", "PRATA_CARROS",
           "MEDALHAS", "NOME_MAX"]

TOPO_PADRAO = 5
LIMITE = 500          # o arquivo não cresce sem fim numa feira de dois dias
VERSAO = 2

# O ruído de jogada, em carros: desvio-padrão da diferença entre duas rodadas do
# MESMO jogador na MESMA seed, medido pelo A8 em 240 rodadas por adversário
# (`docs/DIFICULDADE.md` §6.1: 3,26–3,69). Ficar a até isso da rede é "lado a lado".
PRATA_CARROS = 3

OURO, PRATA, BRONZE, SEM = "ouro", "prata", "bronze", ""
MEDALHAS = (OURO, PRATA, BRONZE)

NOME_MAX = 12
ANONIMO = "Visitante"


def normaliza_nome(nome) -> str:
    """Apelido de tela pública: letras, dígitos e espaço simples, até `NOME_MAX`.

    Acento fica (é nome de gente); o que sai é controle, pontuação e emoji — a
    fonte do projetor não tem glifo para tudo, e um nome que vira caixa vazia na
    tela é pior que um nome cortado. Vazio devolve "" (o chamador põe o anônimo).
    """
    if nome is None:
        return ""
    s = unicodedata.normalize("NFC", str(nome))
    s = "".join(ch for ch in s if ch.isalnum() or ch == " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:NOME_MAX].strip()


def medalha_de(entregues: int, rl: int | None, timer: int | None) -> str:
    """Ouro / prata / bronze / "" a partir das três linhas. `None` = braço ausente."""
    if rl is not None:
        if entregues > rl:
            return OURO
        if entregues >= rl - PRATA_CARROS:
            return PRATA
    if timer is not None and entregues > timer:
        return BRONZE
    return SEM


@dataclass(frozen=True)
class Marca:
    """Uma rodada humana que terminou e vale para o quadro."""

    entregues: int
    seed: int
    venceu: bool               # bateu a REDE NEURAL nesta seed?
    rl: int                    # o que a rede entregou na mesma rodada (0 = não havia)
    timer: int                 # o que o timer entregou na mesma rodada (0 = não havia)
    quando: float = field(default_factory=time.time)
    # --- v2 ---
    nome: str = ""             # apelido; vazio = anônimo (o quadro mostra "Visitante N")
    rodada: int = 0            # `Placar.rodada` (0 = mensagem anterior ao campo)
    teste: bool = False        # rodada do operador/ensaio: fica no arquivo, sai do topo
    removida: bool = False     # moderação: soft-delete, o arquivo não perde linha
    ordem: int = 0             # ordinal no arquivo do dia (1, 2, 3...) — é o N do "Visitante N"

    # ------------------------------------------------------------ derivados
    @property
    def score(self) -> int:
        """Δ contra o timer da mesma seed — a pontuação do quadro."""
        return int(self.entregues) - int(self.timer)

    @property
    def delta_rl(self) -> int | None:
        return int(self.entregues) - int(self.rl) if self.rl else None

    @property
    def medalha(self) -> str:
        return medalha_de(self.entregues, self.rl or None, self.timer or None)

    @property
    def degradada(self) -> bool:
        """Sem a rede na rodada: não há ouro nem prata possíveis."""
        return not self.rl

    @property
    def conta(self) -> bool:
        """Entra no topo? (não é teste, não foi removida, tem régua)"""
        return bool(self.timer) and not self.teste and not self.removida

    @property
    def id(self) -> str:
        return "m%d" % self.ordem

    @property
    def chave(self) -> tuple:
        """Identidade da rodada, para não gravar a mesma duas vezes.

        Com `rodada` no fio a identidade é o contador do motor; sem ele (mensagem
        antiga), a tupla de números — que colide legitimamente quando duas pessoas
        entregam o mesmo tanto na mesma seed, e é por isso que o campo existe."""
        if self.rodada:
            return ("rodada", self.rodada, self.seed)
        return (self.seed, self.entregues, self.rl, self.timer)

    def json(self) -> dict:
        d = asdict(self)
        d.update(id=self.id, score=self.score, delta_rl=self.delta_rl,
                 medalha=self.medalha, degradada=self.degradada,
                 hora=time.strftime("%H:%M", time.localtime(self.quando)))
        return d


def _linha(msg: dict, braco: str) -> dict | None:
    for ln in (msg.get("linhas") or ()):
        if ln.get("braco") == braco:
            return ln
    return None


def _ordem(m: Marca) -> tuple:
    """Score maior primeiro; desempate por entregues; depois quem fez antes."""
    return (-m.score, -m.entregues, m.quando)


class Ranking:
    """As melhores rodadas humanas, em memória e (se houver caminho) em disco.

    Thread-safe de propósito: `registra` é chamado da asyncio loop do servidor e
    `topo` pode ser lido de um handler HTTP. Nenhum dos dois pode levantar — este
    objeto está no caminho da projeção, e a projeção nunca derruba o jogo.
    """

    def __init__(self, caminho: Path | None = None, *, limite: int = LIMITE,
                 dia: str | None = None, validade_s: float | None = None,
                 agora=time.time) -> None:
        self.caminho = Path(caminho) if caminho else None
        self.limite = int(limite)
        self.dia = dia or time.strftime("%Y-%m-%d")
        # VALIDADE (decisão do dono, 2026-09-14): uma marca só conta no QUADRO enquanto
        # tem menos de `validade_s` — senão quem jogou bem às 9h é o campeão o evento
        # inteiro e ninguém que chega às 15h tem o que bater. O ARQUIVO guarda tudo
        # (auditoria, contagens do dia); o que expira é a colocação. `None` = nunca.
        self.validade_s = None if validade_s is None else float(validade_s)
        self._agora = agora
        self._lock = threading.Lock()
        self._marcas: list[Marca] = []
        self._vistas: set[tuple] = set()
        self._carrega()

    # ----------------------------------------------------------- fábricas
    @classmethod
    def do_dia(cls, pasta: Path, dia: str | None = None, **kw) -> "Ranking":
        """`<pasta>/ranking_<dia>.json` — um arquivo por dia de feira."""
        dia = dia or time.strftime("%Y-%m-%d")
        return cls(Path(pasta) / ("ranking_%s.json" % dia), dia=dia, **kw)

    @staticmethod
    def da_feira(pasta: Path) -> list[Marca]:
        """A união dos dias: todas as marcas de todos os `ranking_*.json` da pasta."""
        saida: list[Marca] = []
        pasta = Path(pasta)
        if not pasta.exists():
            return saida
        for arq in sorted(pasta.glob("ranking_*.json")):
            saida.extend(Ranking(arq)._marcas)
        return saida

    # ------------------------------------------------------------------ disco
    @staticmethod
    def _marca_de(d: dict) -> Marca:
        return Marca(entregues=int(d["entregues"]), seed=int(d["seed"]),
                     venceu=bool(d["venceu"]), rl=int(d.get("rl", 0)),
                     timer=int(d.get("timer", 0)),
                     quando=float(d.get("quando", 0.0)),
                     nome=normaliza_nome(d.get("nome", "")),
                     rodada=int(d.get("rodada", 0)),
                     teste=bool(d.get("teste", False)),
                     removida=bool(d.get("removida", False)),
                     ordem=int(d.get("ordem", 0)))

    def _carrega(self) -> None:
        if not self.caminho or not self.caminho.exists():
            return
        try:
            cru = json.loads(self.caminho.read_text(encoding="utf-8"))
            # v1 (sem `versao`) carrega igual: os campos novos têm default, e
            # `score`/`medalha` são derivados — nenhuma marca se perde.
            for i, d in enumerate(cru.get("marcas", []), 1):
                m = self._marca_de(d)
                if not m.ordem:                 # v1: o ordinal é a posição no arquivo
                    m = Marca(**{**asdict(m), "ordem": i})
                self._marcas.append(m)
                # A identidade por `rodada` é DESTE processo: o contador do motor
                # reinicia a cada servidor, e a rodada 2 de hoje à tarde colidiria
                # com a rodada 2 de hoje de manhã na mesma seed — a marca nova seria
                # engolida em silêncio (aconteceu: 2026-09-14, seed 101). Do disco só
                # entra a chave por tupla, das mensagens antigas sem `rodada`.
                if not m.rodada:
                    self._vistas.add(m.chave)
        except Exception:
            # Quadro de recordes corrompido não pode derrubar a feira: começa vazio.
            self._marcas, self._vistas = [], set()

    def _grava(self) -> None:
        if not self.caminho:
            return
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            corpo = json.dumps({"versao": VERSAO, "dia": self.dia,
                                "marcas": [asdict(m) for m in self._marcas]},
                               ensure_ascii=False, indent=1)
            # Escrita atômica: uma feira que acaba em Ctrl-C no meio de um `write`
            # não pode deixar o arquivo pela metade.
            fd, tmp = tempfile.mkstemp(dir=str(self.caminho.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(corpo)
                os.replace(tmp, self.caminho)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except Exception:
            pass

    # --------------------------------------------------------------- ingestão
    def registra(self, msg: dict, *, nome: str | None = None,
                 teste: bool = False) -> Marca | None:
        """Absorve uma mensagem `placar` do C7. Devolve a marca gravada, ou None."""
        try:
            if (msg.get("tipo") or msg.get("type")) != "placar":
                return None
            if msg.get("fase") != "resultado":
                return None
            # `pareado` ausente = mensagem antiga: assume pareada, como o resto da tela.
            if msg.get("pareado") is False:
                return None
            if msg.get("sinais"):
                return None                     # travou: a rodada não vale
            humano = _linha(msg, "humano")
            if humano is None:
                return None                     # rodada abortada: ninguém jogou
            rl = _linha(msg, "rl") or {}
            timer = _linha(msg, "timer") or {}
            chave = msg.get("chave") or {}
            n_rl = int(rl.get("entregues") or 0)
            n_h = int(humano.get("entregues") or 0)
            # `venceu` é "bateu a REDE": sai dos números, não de `vencedor` — numa
            # rodada degradada (sem RL) o motor coroa o humano por bater o timer, e
            # isso não é bater a rede.
            m = Marca(entregues=n_h,
                      seed=int(chave.get("seed") or -1),
                      venceu=bool(n_rl and n_h > n_rl),
                      rl=n_rl,
                      timer=int(timer.get("entregues") or 0),
                      nome=normaliza_nome(nome),
                      rodada=int(msg.get("rodada") or 0),
                      teste=bool(teste), quando=float(self._agora()))
        except Exception:
            return None
        with self._lock:
            if m.chave in self._vistas:
                return None
            m = Marca(**{**asdict(m),
                         "ordem": 1 + max((x.ordem for x in self._marcas), default=0)})
            self._vistas.add(m.chave)
            self._marcas.append(m)
            if len(self._marcas) > self.limite:
                # Descarta as PIORES (por score), não as mais velhas: o quadro é de
                # recordes. Teste e removida vão primeiro.
                self._marcas.sort(key=lambda x: (not x.conta, _ordem(x)))
                del self._marcas[self.limite:]
                self._marcas.sort(key=lambda x: x.ordem)
                self._vistas = {x.chave for x in self._marcas}
            self._grava()
        return m

    # -------------------------------------------------------------- moderação
    def altera(self, id: str, *, nome: str | None = None, teste: bool | None = None,
               removida: bool | None = None) -> Marca | None:
        """Renomeia / marca teste / remove (soft). Devolve a marca nova, ou None."""
        with self._lock:
            for i, m in enumerate(self._marcas):
                if m.id != id:
                    continue
                novo = Marca(**{**asdict(m),
                                "nome": normaliza_nome(nome) if nome is not None else m.nome,
                                "teste": m.teste if teste is None else bool(teste),
                                "removida": m.removida if removida is None else bool(removida)})
                self._marcas[i] = novo
                self._grava()
                return novo
        return None

    # ----------------------------------------------------------------- leitura
    def _rotulo(self, m: Marca) -> str:
        """O nome como a tela mostra: o apelido, ou `Visitante N` (N = ordem do dia)."""
        return m.nome or "%s %d" % (ANONIMO, m.ordem)

    def vigente(self, m: Marca) -> bool:
        """Ainda dentro da validade? (sempre True sem validade configurada)"""
        if self.validade_s is None:
            return True
        return (float(self._agora()) - float(m.quando)) <= self.validade_s

    def _validas(self, marcas: list[Marca] | None = None) -> list[Marca]:
        """As que contam no quadro AGORA: válidas (conta) e dentro da validade."""
        return [m for m in (self._marcas if marcas is None else marcas)
                if m.conta and self.vigente(m)]

    def _do_dia(self, marcas: list[Marca] | None = None) -> list[Marca]:
        """As que contam nos TOTAIS do dia: válidas, expiradas ou não."""
        return [m for m in (self._marcas if marcas is None else marcas) if m.conta]

    def topo(self, n: int = TOPO_PADRAO, *, marcas: list[Marca] | None = None) -> list[Marca]:
        """As `n` melhores, UMA por apelido (a melhor rodada de cada pessoa)."""
        with self._lock:
            ordenadas = sorted(self._validas(marcas), key=_ordem)
            vistas: set[str] = set()
            saida: list[Marca] = []
            for m in ordenadas:
                r = self._rotulo(m)
                if r in vistas:
                    continue
                vistas.add(r)
                saida.append(m)
                if len(saida) >= max(0, int(n)):
                    break
            return saida

    def posicao(self, marca: Marca) -> tuple[int | None, int]:
        """`(posição, total)` da marca entre as válidas do dia — uma por apelido.

        A posição é a da PESSOA (a melhor rodada dela), então uma rodada pior que a
        melhor da mesma pessoa devolve a posição que a pessoa já tinha."""
        with self._lock:
            validas = sorted(self._validas(), key=_ordem)
        if not validas:
            return None, 0
        melhores: dict[str, Marca] = {}
        for m in validas:
            r = self._rotulo(m)
            if r not in melhores:
                melhores[r] = m
        fila = sorted(melhores.values(), key=_ordem)
        rot = self._rotulo(marca)
        for i, m in enumerate(fila, 1):
            if self._rotulo(m) == rot:
                return i, len(fila)
        return None, len(fila)

    def por_seed(self, seed: int) -> dict:
        """Quantos jogaram esta seed hoje e quantos bateram a rede — o nível AO VIVO."""
        with self._lock:
            jog = [m for m in self._do_dia() if m.seed == int(seed)]
        return {"jogaram": len(jog), "bateram": sum(1 for m in jog if m.venceu)}

    def json(self, n: int = TOPO_PADRAO, *, ultima: Marca | None = None,
             marcas: list[Marca] | None = None, escopo: str = "dia") -> dict:
        with self._lock:
            do_dia = self._do_dia(marcas)
            total = len(do_dia)
            vitorias = sum(1 for m in do_dia if m.venceu)
            bronzes = sum(1 for m in do_dia if m.score > 0)
        d = {"tipo": "ranking", "escopo": escopo, "dia": self.dia,
             "total": total, "vitorias": vitorias, "venceram_timer": bronzes,
             "validade_s": self.validade_s,
             "topo": [{**m.json(), "rotulo": self._rotulo(m)}
                      for m in self.topo(n, marcas=marcas)]}
        if ultima is not None:
            pos, total_pessoas = self.posicao(ultima)
            d["ultima"] = {**ultima.json(), "rotulo": self._rotulo(ultima),
                           "posicao": pos, "pessoas": total_pessoas,
                           "recorde": pos == 1 and ultima.conta}
        return d
