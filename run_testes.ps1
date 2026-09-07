<#
  run_testes.ps1 - a suite deste repo, com o interpretador certo.

  Usa o venv COMPARTILHADO (o do smart-traffic): este repo nao tem .venv proprio,
  de proposito -- ver README. A suite de contratos NAO precisa de SUMO nem torch;
  os testes que precisam se pulam sozinhos.

  Uso:
      .\run_testes.ps1              # pytest -q
      .\run_testes.ps1 -Lint        # + ruff check
      .\run_testes.ps1 -Verboso     # pytest -v
#>
param(
    [switch]$Lint,
    [switch]$Verboso
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path (Split-Path -Parent $repo) 'smart-traffic\.venv\Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Host "Interpretador nao encontrado: $py" -ForegroundColor Red
    Write-Host "Este repo usa o venv do smart-traffic (ver README)." -ForegroundColor Yellow
    exit 1
}

Push-Location $repo
try {
    if ($Lint) {
        & $py -m ruff check .
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    $argsPytest = if ($Verboso) { @('-m','pytest','-v') } else { @('-m','pytest','-q') }
    & $py @argsPytest
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
