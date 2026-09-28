<#
  run_feira.ps1 - O COMANDO DO DIA DA FEIRA. Um só.

  Sobe a projecao com o preset `--feira` e, junto, a TELA PADRAO: os dois bracos
  (rede neural e timer fixo) rodando ao vivo enquanto ninguem joga. Eles descem
  sozinhos quando alguem aperta ESPACO e voltam quando a rodada acaba.

  Depois de subir, abra a URL que ele imprime na tela do projetor e aperte F.

  Uso:
      .\run_feira.ps1                     # o dia da feira
      .\run_feira.ps1 -Porta 8080
      .\run_feira.ps1 -Ensaio             # sem a tela padrao (so o jogo; poupa CPU)
      .\run_feira.ps1 -SoProjecao         # so a tela padrao, sem jogo (vitrine)
      .\run_feira.ps1 -Extra '--ritmo 1'  # repassa qualquer flag do script

  O que o preset liga (ver scripts\projecao_servidor.py, funcao main):
      --entrada web        o teclado e lido pela PAGINA projetada (foco no navegador)
      --abortar operador   o ESPACO do visitante nao aborta; Esc 3x em 1,5 s aborta
      --resultado-s 7      a tela de resultado fica 7 s e volta sozinha ao ocioso
      --ranking-validade 30  uma marca conta 30 min no quadro (rotatividade)
      --ritmo 2            120 s simulados em 60 s de relogio (so apresentacao)
      --ocioso             a tela padrao, com os dois bracos ao vivo
      --grava results/jogo  cada rodada gravada, para replay e auditoria

  TECLAS DO VISITANTE
      ocioso   digite o apelido -> ENTER -> ESPACO   (ou so ESPACO = Visitante N)
      rodada   Q W E R / A S D F / Z X C V  = os 12 semaforos

  TECLAS DO OPERADOR (na pagina)
      F tela cheia   I regua de bancada   H hud   T grade   R girar   M espelhar
      setas alinhar  + - zoom   , . tamanho do texto   0 reset
#>
param(
    [int]$Porta = 8080,
    [switch]$Ensaio,
    [switch]$SoProjecao,
    [string]$Extra = ''
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path (Split-Path -Parent $repo) 'smart-traffic\.venv\Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Host "Interpretador nao encontrado: $py" -ForegroundColor Red
    Write-Host "Este repo usa o venv do smart-traffic (ver README, 'Instalacao')." -ForegroundColor Yellow
    exit 1
}
if (-not $env:SUMO_HOME) {
    Write-Host "SUMO_HOME nao esta no ambiente - o SUMO nao vai subir." -ForegroundColor Red
    Write-Host "Instale o SUMO e defina SUMO_HOME (ver README, 'Pre-requisitos')." -ForegroundColor Yellow
    exit 1
}

$argumentos = @('scripts\projecao_servidor.py', '--feira', '--porta', $Porta)
if ($Ensaio)     { $argumentos += '--sem-ocioso' }
if ($SoProjecao) { $argumentos += '--so-servidor' }
if ($Extra)      { $argumentos += $Extra.Split(' ') }

Push-Location $repo
try {
    & $py @argumentos
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
