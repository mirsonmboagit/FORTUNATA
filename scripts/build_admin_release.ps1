param(
    [switch]$Clean,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$env:KIVY_NO_FILELOG = "1"
$env:KIVY_NO_ARGS = "1"

if ($Clean) {
    foreach ($folder in @("build\admin_app", "dist\MerceariaAdmin")) {
        $target = Join-Path $root $folder
        if (Test-Path $target) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
}

if (-not $SkipBuild) {
    python -m PyInstaller --noconfirm admin_app.spec
}

$dist = Join-Path $root "dist\MerceariaAdmin"
if (-not (Test-Path $dist)) {
    throw "Build nao encontrado em: $dist"
}

$internal = Join-Path $dist "_internal"
foreach ($folder in @("assets", "config", "locales")) {
    $sourceFolder = Join-Path $internal $folder
    if (Test-Path $sourceFolder) {
        Copy-Item -Path $sourceFolder -Destination $dist -Recurse -Force
    }
}

$cacheSource = Join-Path $internal "data\cache"
if (Test-Path $cacheSource) {
    $cacheTarget = Join-Path $dist "data\cache"
    if (-not (Test-Path $cacheTarget)) {
        New-Item -ItemType Directory -Force $cacheTarget | Out-Null
    }
    Copy-Item -Path (Join-Path $cacheSource "*") -Destination $cacheTarget -Recurse -Force
}

foreach ($folder in @("admin", "user", "utils", "manager")) {
    $sourceFolder = Join-Path $internal $folder
    $targetFolder = Join-Path $dist $folder
    if (Test-Path $sourceFolder) {
        if (-not (Test-Path $targetFolder)) {
            New-Item -ItemType Directory -Force $targetFolder | Out-Null
        }
        Copy-Item -Path (Join-Path $sourceFolder "*.kv") -Destination $targetFolder -Force -ErrorAction SilentlyContinue
    }
}

$distAppConfigPath = Join-Path $dist "config\app.json"
if (Test-Path $distAppConfigPath) {
    $distAppConfig = Get-Content $distAppConfigPath -Raw | ConvertFrom-Json
    $distAppConfig.db_mode = "remote_strict"
    $distAppConfig.api_base_url = "http://127.0.0.1:8080"
    $distAppConfig.api_key = ""
    $distAppConfig | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $distAppConfigPath
}

$installDir = Join-Path $dist "install"
if (-not (Test-Path $installDir)) {
    New-Item -ItemType Directory -Force $installDir | Out-Null
}

Copy-Item -Force (Join-Path $root "scripts\configure_api.ps1") (Join-Path $installDir "configure_api.ps1")
Copy-Item -Force (Join-Path $root "scripts\install_admin_client.ps1") (Join-Path $installDir "install_admin_client.ps1")
Copy-Item -Force (Join-Path $root "docs\INSTALACAO_ADMIN.md") (Join-Path $installDir "INSTALACAO_ADMIN.md")

foreach ($file in @("install_service.bat", "update_service.bat", "uninstall_service.bat")) {
    $stale = Join-Path $installDir $file
    if (Test-Path $stale) {
        Remove-Item -LiteralPath $stale -Force
    }
}

$readme = @"
MERCEARIA ADMIN

Executavel:
  MerceariaAdmin.exe

Antes de usar em outro computador, configure a API:
  .\install\configure_api.ps1 -Role Client -ServerHost IP_DO_SERVIDOR -ApiKey "CHAVE_DA_API"

Guia completo:
  install\INSTALACAO_ADMIN.md
"@

$readme | Set-Content -Encoding UTF8 (Join-Path $dist "LEIA-ME-ADMIN.txt")

Write-Host "Build pronto em: $dist"
Write-Host "Copie a pasta MerceariaAdmin inteira para os outros computadores."
