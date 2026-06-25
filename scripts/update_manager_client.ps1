param(
    [string]$InstallDir = "",
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"

function Find-ReleaseRoot {
    param([string]$StartDir)

    $current = (Resolve-Path $StartDir).Path
    while ($true) {
        if ((Test-Path (Join-Path $current "SIGEMPEManager.exe")) -and (Test-Path (Join-Path $current "config\app.json"))) {
            return $current
        }
        $parent = Split-Path $current -Parent
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) {
            throw "Nao encontrei a pasta nova da app a partir de: $StartDir"
        }
        $current = $parent
    }
}

function Read-JsonConfig {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $null
    }
    $raw = Get-Content $Path -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return $raw | ConvertFrom-Json
}

function Merge-JsonConfig {
    param(
        [string]$OldPath,
        [string]$NewPath
    )

    if ((-not (Test-Path $OldPath)) -or (-not (Test-Path $NewPath))) {
        return
    }

    $old = Read-JsonConfig $OldPath
    $new = Read-JsonConfig $NewPath
    if ($null -eq $old -or $null -eq $new) {
        return
    }

    foreach ($property in $old.PSObject.Properties) {
        if ($null -eq $new.PSObject.Properties[$property.Name]) {
            $new | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value
        } else {
            $new.($property.Name) = $property.Value
        }
    }

    $new | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $NewPath
}

function Backup-File {
    param(
        [string]$Root,
        [string]$RelativePath,
        [string]$BackupRoot
    )

    $source = Join-Path $Root $RelativePath
    if (-not (Test-Path $source)) {
        return
    }
    $target = Join-Path $BackupRoot $RelativePath
    $parent = Split-Path $target -Parent
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force $parent | Out-Null
    }
    Copy-Item -LiteralPath $source -Destination $target -Force
}

function Restore-File {
    param(
        [string]$BackupRoot,
        [string]$RelativePath,
        [string]$TargetRoot
    )

    $source = Join-Path $BackupRoot $RelativePath
    if (-not (Test-Path $source)) {
        return
    }
    $target = Join-Path $TargetRoot $RelativePath
    $parent = Split-Path $target -Parent
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force $parent | Out-Null
    }
    Copy-Item -LiteralPath $source -Destination $target -Force
}

$sourceRoot = Find-ReleaseRoot $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "SIGEMPEManager"
}

if (-not (Test-Path $InstallDir)) {
    throw "Instalacao nao encontrada: $InstallDir"
}

$installRoot = (Resolve-Path $InstallDir).Path
if ($sourceRoot -eq $installRoot) {
    Write-Host "A pasta nova e a pasta instalada sao a mesma. Nada para atualizar."
    exit 0
}

$backupRoot = Join-Path $env:TEMP ("SIGEMPEManagerUpdate_" + (Get-Date -Format "yyyyMMddHHmmss"))
New-Item -ItemType Directory -Force $backupRoot | Out-Null

$jsonConfigs = @(
    "config\app.json",
    "config\api.json",
    "config\service.json",
    "config\app_settings.json"
)

foreach ($relative in $jsonConfigs + @("config\.env")) {
    Backup-File -Root $installRoot -RelativePath $relative -BackupRoot $backupRoot
}

Copy-Item -Path (Join-Path $sourceRoot "*") -Destination $installRoot -Recurse -Force

Restore-File -BackupRoot $backupRoot -RelativePath "config\.env" -TargetRoot $installRoot
foreach ($relative in $jsonConfigs) {
    Merge-JsonConfig -OldPath (Join-Path $backupRoot $relative) -NewPath (Join-Path $installRoot $relative)
}

$exePath = Join-Path $installRoot "SIGEMPEManager.exe"
if ((-not $NoShortcut) -and (Test-Path $exePath)) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "SIGE MPE Manager.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $exePath
    $shortcut.WorkingDirectory = $installRoot
    $shortcut.IconLocation = $exePath
    $shortcut.Save()
}

Write-Host "Manager atualizado em: $installRoot"
Write-Host "Base de dados, config\\.env e configuracao da API foram preservadas."
