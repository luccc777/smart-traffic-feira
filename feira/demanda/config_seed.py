"""O `.sumocfg` POR SEED - e por que ele existe.

O BUG QUE ISTO FECHA (achado pelo agente A2)
--------------------------------------------
Na rede aberta a demanda e um `.rou.xml` por seed. Quem escolhe o arquivo de
rotas, porem, e o `.sumocfg`: o `TrafficEnv` do maquete monta a linha de comando
do SUMO por conta propria e **nao aceita `--route-files`**. Com um `.sumocfg` so,
a Arena subia a MESMA demanda para qualquer seed - e **sem levantar erro**. O
pareamento por seed morria em silencio, que e exatamente a classe de bug que o
contrato C2 existe para impedir.

A CONVENCAO (a que a Arena ja procura)
--------------------------------------
Um `.sumocfg` por seed ao lado do canonico:

    config/maquete_aberta.sumocfg  ->  config/maquete_aberta_s42.sumocfg

Ele e IDENTICO ao canonico a menos de uma linha `<route-files>`. E gerado por
derivacao do canonico, nao por copia de um template paralelo: se
`build_rede_aberta.py` mudar o canonico (um `device.rerouting.period`, por
exemplo), os por-seed herdam na proxima geracao em vez de divergirem em silencio.

NAO VAI VERSIONADO, e o manifesto registra o sha256 dele. O `.rou.xml` que ele
aponta tambem nao vai; um cfg versionado apontando para um arquivo ausente seria
pior que nao ter cfg. `gera()` reescreve o cfg sempre que ele falta, inclusive no
caminho idempotente, e `manifesto()` recusa devolver um manifesto cujo cfg sumiu
ou mudou.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..contratos import Cenario, DemandaDivergente, sha256_arquivo


class ConfigDaSeedAusente(DemandaDivergente):
    """Nao ha `.sumocfg` para esta seed - subir o canonico rodaria OUTRA demanda.

    Subclasse de `DemandaDivergente` de proposito: quem ja tratava "o arquivo em
    disco nao e o que o manifesto descreve" trata isto pelo mesmo `except`.
    """


def caminho_config_seed(cenario: Cenario, seed: int) -> Path:
    """`config/maquete_aberta.sumocfg` -> `config/maquete_aberta_s42.sumocfg`.

    Mesma formacao de nome que `feira.arena.sumo._sumocfg_da_seed` usa para
    PROCURAR. Se as duas divergirem, a Arena cai no canonico e a demanda deixa de
    seguir a seed - por isso ha teste comparando as duas.
    """
    base = Path(cenario.sumocfg)
    return base.with_name("%s_s%d%s" % (base.stem, int(seed), base.suffix))


def sumocfg_da_seed(cenario: Cenario, seed: int) -> Path:
    """O `.sumocfg` desta seed, ou LEVANTA.

    E a checagem que pega o chamador cedo: quem pedir a seed 43 e so achar o
    canonico recebe excecao, nunca a demanda da 42. Cenario de frota persistente
    nao tem arquivo de rotas e devolve o canonico.
    """
    if cenario.modelo_demanda != "arquivo":
        return Path(cenario.sumocfg)
    alvo = caminho_config_seed(cenario, seed)
    if not alvo.exists():
        raise ConfigDaSeedAusente(
            "%s nao existe. O canonico (%s) aponta para OUTRA demanda (ou para "
            "nenhuma), entao subir ele para a seed %d daria trafego errado sem "
            "erro nenhum. Gere com: python -m feira.demanda --seeds %d"
            % (alvo.name, Path(cenario.sumocfg).name, seed, seed)
        )
    return alvo


def _linha_route_files(texto: str, rou: Path, dir_cfg: Path) -> tuple[int, str]:
    """(posicao de insercao, linha) do `<route-files>` a acrescentar ao canonico.

    Entra logo depois do `<net-file>`, herdando a indentacao dele. O caminho e
    RELATIVO ao diretorio do cfg (como o `<net-file>` do canonico ja e), com "/"
    fixo: assim o arquivo nao carrega o caminho absoluto de quem gerou e o sha256
    do manifesto significa a mesma coisa em qualquer maquina.
    """
    i = texto.index("<net-file")
    inicio_linha = texto.rfind("\n", 0, i) + 1
    indent = texto[inicio_linha:i]
    fim_linha = texto.index("\n", i) + 1
    rel = os.path.relpath(str(rou), str(dir_cfg)).replace("\\", "/")
    linha = ('%s<!-- demanda da seed: e ESTA linha que o canonico nao tem. -->\n'
             '%s<route-files value="%s"/>\n' % (indent, indent, rel))
    return fim_linha, linha


def texto_config_seed(cenario: Cenario, seed: int, rou: Path) -> str | None:
    """O conteudo do cfg da seed, derivado do canonico. `None` se ele nao existe.

    O `None` nao e defensividade vazia: a suite de conformidade da C2 exercita o
    contrato com um `Cenario` descartavel cujo `.sumocfg` nao existe (ela so quer
    provar o invariante do hash). Nesse caso nao ha canonico de onde derivar, e
    inventar um seria pior.
    """
    canonico = Path(cenario.sumocfg)
    if not canonico.exists():
        return None
    texto = canonico.read_text(encoding="utf-8")
    # `<route-files value=` e nao `<route-files`: o canonico MENCIONA a opcao num
    # comentario ("SEM <route-files>: a demanda e um .rou.xml por seed"), e casar
    # com o comentario faria o gerador recusar o proprio arquivo que ele escreveu.
    if "<route-files value" in texto:
        raise ValueError(
            "%s ja tem <route-files>. O canonico da rede aberta e, por desenho, "
            "SEM demanda: quem escolhe a demanda e o cfg da seed." % canonico.name)
    pos, linha = _linha_route_files(texto, rou, canonico.parent)
    cabecalho = (
        "<!-- GERADO por feira.demanda (seed %d) - NAO EDITAR A MAO.\n"
        "     Copia de %s com UMA linha a mais: o <route-files> desta seed.\n"
        "     Existe porque o TrafficEnv do maquete monta a linha de comando do\n"
        "     SUMO sozinho e nao aceita route-files; sem este arquivo a Arena\n"
        "     subiria a mesma demanda para toda seed, e em silencio. -->\n"
        % (seed, canonico.name))
    # A declaracao `<?xml ... ?>` TEM que ser a primeira coisa do arquivo; o
    # cabecalho entra logo depois dela. (O SUMO aceitou o arquivo invalido em
    # silencio - de novo o mesmo padrao de falha que este modulo existe para
    # matar; quem denunciou foi o ElementTree.)
    decl = texto.index('?>') + 3 if texto.lstrip().startswith('<?xml') else 0
    return texto[:decl] + cabecalho + texto[decl:pos] + linha + texto[pos:]


def escreve_config_seed(cenario: Cenario, seed: int, rou: Path) -> Path | None:
    """Escreve (ou reescreve) o cfg da seed. Devolve o caminho, ou `None`."""
    texto = texto_config_seed(cenario, seed, rou)
    if texto is None:
        return None
    alvo = caminho_config_seed(cenario, seed)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(texto, encoding="utf-8", newline="\n")
    return alvo


def confere_config_seed(cenario: Cenario, seed: int, sha_esperado: str | None) -> None:
    """Levanta se o cfg da seed sumiu ou nao e mais o que o manifesto descreve.

    `sha_esperado=None` significa "este manifesto foi gerado sem cfg" (cenario
    sintetico da suite de conformidade) e nao ha o que conferir.
    """
    if sha_esperado is None:
        return
    alvo = sumocfg_da_seed(cenario, seed)          # ja levanta se nao existir
    real = sha256_arquivo(alvo)
    if real != sha_esperado:
        raise ConfigDaSeedAusente(
            "%s nao bate com o manifesto (esperado %s, encontrado %s). Alguem "
            "editou o cfg da seed a mao, ou ele foi reescrito apontando para "
            "outra demanda (a calibracao faz isso quando roda com taxa diferente). "
            "Regenere: python -m feira.demanda --seeds %d --forcar"
            % (alvo.name, sha_esperado[:16], real[:16], seed))
