param(
    [string]$ReleaseName = "",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

function Assert-ReleasePath {
    param([string]$Path)

    $resolved = [System.IO.Path]::GetFullPath($Path)
    $base = [System.IO.Path]::GetFullPath((Join-Path $root "dist\releases")).TrimEnd('\', '/')
    $prefix = $base + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Destino de release inseguro: $resolved"
    }
    return $resolved
}

function Assert-Exists {
    param([string]$Path, [string]$Description)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description ausente: $Path"
    }
}

function Assert-ClientPackage {
    param(
        [string]$Root,
        [string]$ExeName,
        [string]$UpdateScript
    )

    foreach ($relative in @(
        $ExeName,
        "config\app.json",
        $UpdateScript,
        "_internal\cv2\cv2.pyd",
        "_internal\pyzbar\libzbar-64.dll",
        "_internal\pyzbar\libiconv.dll"
    )) {
        Assert-Exists -Path (Join-Path $Root $relative) -Description "Ficheiro obrigatorio do cliente"
    }
    if (-not (Get-ChildItem -LiteralPath (Join-Path $Root "_internal\cv2") -Filter "opencv_videoio_ffmpeg*.dll" -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        throw "Backend OpenCV de camera ausente em $Root"
    }
    if (-not (Get-ChildItem -LiteralPath (Join-Path $Root "numpy\_core") -Filter "_multiarray_umath*.pyd" -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        throw "Modulo nativo NumPy ausente em $Root"
    }

    $config = Get-Content -LiteralPath (Join-Path $Root "config\app.json") -Raw | ConvertFrom-Json
    if ($config.app_env -ne "production" -or $config.db_mode -ne "remote_strict" -or -not [string]::IsNullOrWhiteSpace([string]$config.api_key)) {
        throw "Configuracao de producao invalida em $Root"
    }

    foreach ($forbidden in @("SIGEMPEAPI.exe", "LojaAPI.exe", "inventory.db", ".env")) {
        if (Get-ChildItem -LiteralPath $Root -Recurse -File -Filter $forbidden -ErrorAction SilentlyContinue | Select-Object -First 1) {
            throw "O pacote cliente contem ficheiro proibido ($forbidden): $Root"
        }
    }
}

function Assert-ApiPackage {
    param([string]$Root)

    foreach ($relative in @(
        "LojaAPI.exe",
        "ATIVAR_API.bat",
        "INICIAR_API.bat",
        "ACTUALIZAR_API.bat",
        "GERAR_LIGACAO_CLIENTE.bat",
        "scripts\windows\ativar_api.ps1",
        "scripts\windows\actualizar_api.ps1",
        "scripts\windows\gerar_ligacao_cliente.ps1",
        "config\app.json"
    )) {
        Assert-Exists -Path (Join-Path $Root $relative) -Description "Ficheiro obrigatorio da API"
    }
    $config = Get-Content -LiteralPath (Join-Path $Root "config\app.json") -Raw | ConvertFrom-Json
    if ($config.app_env -ne "production" -or $config.db_mode -ne "local" -or -not [string]::IsNullOrWhiteSpace([string]$config.api_key)) {
        throw "Configuracao de producao invalida no pacote da API"
    }
    foreach ($forbidden in @("database\inventory.db", "config\.env", "database\inventory.db-wal", "database\inventory.db-shm")) {
        if (Test-Path -LiteralPath (Join-Path $Root $forbidden)) {
            throw "O pacote da API contem dados de runtime: $forbidden"
        }
    }
}

$version = (Get-Content -LiteralPath (Join-Path $root "VERSION") -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($ReleaseName)) {
    $ReleaseName = "SIGE-MPE-$version-$(Get-Date -Format 'yyyyMMdd')"
}
if ($ReleaseName -notmatch '^[A-Za-z0-9._-]+$') {
    throw "ReleaseName so pode conter letras, numeros, ponto, hifen e underscore."
}

$releaseRelative = "dist\releases\$ReleaseName"
$workRelative = "build\releases\$ReleaseName"
$releaseRoot = Assert-ReleasePath -Path (Join-Path $root $releaseRelative)
$workRoot = [System.IO.Path]::GetFullPath((Join-Path $root $workRelative))
$workBase = [System.IO.Path]::GetFullPath((Join-Path $root "build\releases")).TrimEnd('\', '/')
if (-not $workRoot.StartsWith($workBase + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Destino de build inseguro: $workRoot"
}

if ($Clean) {
    foreach ($path in @($releaseRoot, $workRoot)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}
New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
New-Item -ItemType Directory -Force -Path $workRoot | Out-Null

$pythonCandidates = @(
    (Join-Path $root ".venv\Scripts\python.exe"),
    (Join-Path $root "loja\Scripts\python.exe")
)
$pythonExecutable = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExecutable) {
    $pythonExecutable = (Get-Command python -ErrorAction Stop).Source
}

Write-Host "== Preflight ==" -ForegroundColor Cyan
& $pythonExecutable (Join-Path $root "scripts\preflight_release.py")
if ($LASTEXITCODE -ne 0) { throw "Preflight da release falhou." }

Write-Host "== Gestor ==" -ForegroundColor Cyan
& (Join-Path $root "scripts\build_manager_release.ps1") -Clean -SkipChecks `
    -WorkPath "$workRelative\manager" -DistPath "$releaseRelative\Manager"
if ($LASTEXITCODE -ne 0) { throw "Build do Gestor falhou." }

Write-Host "== Administrador ==" -ForegroundColor Cyan
& (Join-Path $root "scripts\build_admin_release.ps1") -Clean -SkipChecks `
    -WorkPath "$workRelative\admin" -DistPath "$releaseRelative\Administrador"
if ($LASTEXITCODE -ne 0) { throw "Build do Administrador falhou." }

Write-Host "== API ==" -ForegroundColor Cyan
& (Join-Path $root "scripts\build_api_release.ps1") -Clean -SkipChecks `
    -WorkPath "$workRelative\api" -DistPath "$releaseRelative\API\_build" `
    -ReleasePath "$releaseRelative\API\LojaAPI"
if ($LASTEXITCODE -ne 0) { throw "Build da API falhou." }

$apiStaging = Join-Path $releaseRoot "API\_build"
if (Test-Path -LiteralPath $apiStaging) {
    Remove-Item -LiteralPath $apiStaging -Recurse -Force
}

$managerRoot = Join-Path $releaseRoot "Manager\SIGEMPEManager"
$adminRoot = Join-Path $releaseRoot "Administrador\SIGEMPEAdmin"
$apiRoot = Join-Path $releaseRoot "API\LojaAPI"
Assert-ClientPackage -Root $managerRoot -ExeName "SIGEMPEManager.exe" -UpdateScript "install\update_manager_client.ps1"
Assert-ClientPackage -Root $adminRoot -ExeName "SIGEMPEAdmin.exe" -UpdateScript "install\update_admin_client.ps1"
Assert-ApiPackage -Root $apiRoot

$readme = @"
SIGE MPE $version - RELEASE LIMPA

Pastas entregues:
  Manager\SIGEMPEManager       Cliente de vendas
  Administrador\SIGEMPEAdmin   Cliente administrativo
  API\LojaAPI                  Servidor e base de dados

Instalacao correcta:
1. Instale e ative LojaAPI no servidor principal.
2. Execute GERAR_LIGACAO_CLIENTE.bat na pasta LojaAPI.
3. Importe SIGEMPELigacao.json em cada cliente com Configurar Ligacao.cmd.

O manifesto SHA-256 permite conferir a integridade de todos os ficheiros.
"@
$readme | Set-Content -LiteralPath (Join-Path $releaseRoot "LEIA-ME-RELEASE.txt") -Encoding UTF8

$manifestPath = Join-Path $releaseRoot "MANIFESTO-SHA256.csv"
$manifest = Get-ChildItem -LiteralPath $releaseRoot -Recurse -File |
    Where-Object { $_.FullName -ne $manifestPath } |
    Sort-Object FullName |
    ForEach-Object {
        $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
        [pscustomobject]@{
            Path = $_.FullName.Substring($releaseRoot.Length).TrimStart('\', '/')
            SizeBytes = $_.Length
            SHA256 = $hash.Hash
        }
    }
$manifest | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8

Write-Host "Release validada em: $releaseRoot" -ForegroundColor Green
