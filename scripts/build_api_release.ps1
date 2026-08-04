param(
    [switch]$Clean,
    [switch]$SkipBuild,
    [switch]$SkipChecks,
    [string]$WorkPath,
    [string]$ReleasePath
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$pythonCandidates = @(
    (Join-Path $root ".venv\Scripts\python.exe"),
    (Join-Path $root "loja\Scripts\python.exe")
)
$pythonExecutable = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonExecutable) {
    $pythonExecutable = (Get-Command python -ErrorAction Stop).Source
}

if (-not $SkipChecks) {
    & $pythonExecutable (Join-Path $root "scripts\preflight_release.py")
    if ($LASTEXITCODE -ne 0) { throw "Preflight da release falhou." }
}

if ($Clean) {
    foreach ($folder in @("build\LojaAPI", "dist\LojaAPI", "dist\LojaAPI_Instalador")) {
        $target = Join-Path $root $folder
        if (Test-Path $target) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
}

if (-not $SkipBuild) {
    $pyInstallerArgs = @("--noconfirm", "--log-level", "WARN")
    if ($WorkPath) {
        $pyInstallerArgs += @("--workpath", $WorkPath)
    }
    $pyInstallerArgs += (Join-Path $root "scripts\packaging\LojaAPI.spec")
    & $pythonExecutable -m PyInstaller @pyInstallerArgs
}

$exe = Join-Path $root "dist\LojaAPI.exe"
if (-not (Test-Path $exe)) {
    $exe = Join-Path $root "dist\LojaAPI\LojaAPI.exe"
}
if (-not (Test-Path $exe)) {
    $exe = Join-Path $root "dist\MerceariaAdmin\LojaAPI.exe"
}
if (-not (Test-Path $exe)) {
    throw "Executavel da API nao encontrado depois do build."
}

$release = if ($ReleasePath) {
    if ([System.IO.Path]::IsPathRooted($ReleasePath)) {
        [System.IO.Path]::GetFullPath($ReleasePath)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $root $ReleasePath))
    }
} else {
    Join-Path $root "dist\LojaAPI_Instalador"
}
# O instalador nunca reutiliza conteudo antigo: isso evita levar .env,
# bases reais, WAL/SHM ou temporarios de uma compilacao anterior.
$resolvedDist = [System.IO.Path]::GetFullPath((Join-Path $root "dist"))
$resolvedRelease = [System.IO.Path]::GetFullPath($release)
if (-not $resolvedRelease.StartsWith($resolvedDist + [System.IO.Path]::DirectorySeparatorChar)) {
    throw "Destino de release inseguro: $resolvedRelease"
}
if (Test-Path $resolvedRelease) {
    Remove-Item -LiteralPath $resolvedRelease -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $release | Out-Null
foreach ($folder in @("config", "database", "data", "logs")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $release $folder) | Out-Null
}

Copy-Item -Force $exe (Join-Path $release "LojaAPI.exe")
Copy-Item -Force (Join-Path $root "ATIVAR_API.bat") (Join-Path $release "ATIVAR_API.bat")
Copy-Item -Force (Join-Path $root "INICIAR_API.bat") (Join-Path $release "INICIAR_API.bat")
Copy-Item -Force (Join-Path $root "COMO_ATIVAR_API.txt") (Join-Path $release "COMO_ATIVAR_API.txt")
Copy-Item -Force (Join-Path $root "VERSION") (Join-Path $release "VERSION")

New-Item -ItemType Directory -Force -Path (Join-Path $release "scripts\windows") | Out-Null
Copy-Item -Force (Join-Path $root "scripts\windows\ativar_api.ps1") (Join-Path $release "scripts\windows\ativar_api.ps1")

foreach ($file in @("config\api.json", "config\app.json", "config\service.json", "config\app_settings.json")) {
    $source = Join-Path $root $file
    if (Test-Path $source) {
        $target = Join-Path $release $file
        New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
        Copy-Item -Force $source $target
    }
}

# Configuracao de producao sem chave embutida. No primeiro arranque o sistema
# gera config\.env e cria uma base vazia no destino.
$releaseAppConfigPath = Join-Path $release "config\app.json"
$releaseAppConfig = Get-Content $releaseAppConfigPath -Raw | ConvertFrom-Json
$releaseAppConfig.app_env = "production"
$releaseAppConfig.db_mode = "local"
$releaseAppConfig.db_path = "database/inventory.db"
$releaseAppConfig.api_base_url = "http://127.0.0.1:8080"
$releaseAppConfig.api_key = ""
$releaseAppConfig | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $releaseAppConfigPath

$nssmCandidates = @(
    (Join-Path $root "nssm.exe"),
    (Join-Path $root "..\nssm-2.24\win64\nssm.exe")
)
foreach ($candidate in $nssmCandidates) {
    if (Test-Path $candidate) {
        Copy-Item -Force $candidate (Join-Path $release "nssm.exe")
        break
    }
}

$readme = @"
LOJA API - INSTALADOR PROFISSIONAL

Este pacote nao precisa de Python instalado.
Nao contem dados de clientes nem uma chave API predefinida.
No primeiro arranque sao criadas uma base vazia e uma chave segura locais.

Como ativar:
1. Copie esta pasta inteira para o computador.
2. Clique com o botao direito em ATIVAR_API.bat.
3. Escolha Executar como administrador.

Depois disso a API fica instalada como servico do Windows:
  LojaAPI

Endereco local:
  http://127.0.0.1:8080

Para iniciar manualmente, use:
  INICIAR_API.bat
"@

$readme | Set-Content -Encoding UTF8 (Join-Path $release "LEIA-ME.txt")

Write-Host "Pacote pronto em: $release"
Write-Host "Copie a pasta $(Split-Path -Leaf $release) inteira para o outro computador."
