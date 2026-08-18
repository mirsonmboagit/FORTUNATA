param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Find-Nssm {
    $candidates = @(
        (Join-Path $sourceRoot "nssm.exe"),
        "nssm.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -eq "nssm.exe") {
            $command = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($command) { return $command.Source }
        } elseif (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }
    return $null
}

function Read-JsonConfig([string]$Path) {
    if (-not (Test-Path $Path)) { return $null }
    $raw = Get-Content $Path -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    return $raw | ConvertFrom-Json
}

function Merge-JsonConfig([string]$OldPath, [string]$NewPath) {
    $old = Read-JsonConfig $OldPath
    $new = Read-JsonConfig $NewPath
    if ($null -eq $old -or $null -eq $new) { return }
    foreach ($property in $old.PSObject.Properties) {
        if ($null -eq $new.PSObject.Properties[$property.Name]) {
            $new | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value
        } else {
            $new.($property.Name) = $property.Value
        }
    }
    $new | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $NewPath
}

$nssm = Find-Nssm
$service = Get-Service -Name "LojaAPI" -ErrorAction SilentlyContinue
if ([string]::IsNullOrWhiteSpace($InstallDir) -and $nssm -and $service) {
    $candidate = (& $nssm get LojaAPI AppDirectory 2>$null | Select-Object -First 1)
    if ($candidate -and (Test-Path $candidate)) { $InstallDir = $candidate }
}
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Read-Host "Indique a pasta da API instalada a atualizar"
}
if ([string]::IsNullOrWhiteSpace($InstallDir) -or -not (Test-Path $InstallDir)) {
    throw "Pasta da API instalada nao encontrada."
}

$installRoot = (Resolve-Path $InstallDir).Path
if ($installRoot -eq $sourceRoot) {
    Write-Host "Esta ja e a pasta da nova versao. Nada para atualizar."
    exit 0
}
if (-not (Test-Path (Join-Path $sourceRoot "LojaAPI.exe"))) {
    throw "A nova versao nao contem LojaAPI.exe."
}

$wasRunning = $service -and $service.Status -eq "Running"
if ($service) {
    Stop-Service -Name "LojaAPI" -Force -ErrorAction Stop
    $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))
}

$backupRoot = Join-Path $env:TEMP ("LojaAPIUpdate_" + (Get-Date -Format "yyyyMMddHHmmss"))
New-Item -ItemType Directory -Force $backupRoot | Out-Null
$configFiles = @("config\app.json", "config\api.json", "config\service.json", "config\app_settings.json", "config\.env")
foreach ($relative in $configFiles) {
    $source = Join-Path $installRoot $relative
    if (Test-Path $source) {
        $target = Join-Path $backupRoot $relative
        New-Item -ItemType Directory -Force (Split-Path $target -Parent) | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
}

Copy-Item -Path (Join-Path $sourceRoot "*") -Destination $installRoot -Recurse -Force
foreach ($relative in @("config\.env")) {
    $backup = Join-Path $backupRoot $relative
    if (Test-Path $backup) {
        $target = Join-Path $installRoot $relative
        New-Item -ItemType Directory -Force (Split-Path $target -Parent) | Out-Null
        Copy-Item -LiteralPath $backup -Destination $target -Force
    }
}
foreach ($relative in @("config\app.json", "config\api.json", "config\service.json", "config\app_settings.json")) {
    Merge-JsonConfig (Join-Path $backupRoot $relative) (Join-Path $installRoot $relative)
}

if ($service -and $wasRunning) {
    Start-Service -Name "LojaAPI" -ErrorAction Stop
}

Write-Host "API atualizada em: $installRoot" -ForegroundColor Green
Write-Host "Base de dados, chave e configuracoes existentes foram preservadas."
