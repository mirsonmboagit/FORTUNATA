param(
    [Parameter(Mandatory = $true)]
    [string]$ServerHost,

    [Parameter(Mandatory = $true)]
    [string]$ApiKey,

    [int]$Port = 8080,

    [string]$InstallDir = "",

    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"

function Find-ReleaseRoot {
    param([string]$StartDir)

    $current = (Resolve-Path $StartDir).Path
    while ($true) {
        if ((Test-Path (Join-Path $current "SIGEMPEManager.exe")) -or (Test-Path (Join-Path $current "config\app.json"))) {
            return $current
        }
        $parent = Split-Path $current -Parent
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) {
            throw "Nao encontrei a pasta da app a partir de: $StartDir"
        }
        $current = $parent
    }
}

$sourceRoot = Find-ReleaseRoot $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "SIGEMPEManager"
}

$resolvedInstallDir = $InstallDir
if (-not (Test-Path $resolvedInstallDir)) {
    New-Item -ItemType Directory -Force $resolvedInstallDir | Out-Null
}
$resolvedInstallDir = (Resolve-Path $resolvedInstallDir).Path

if ($sourceRoot -ne $resolvedInstallDir) {
    Copy-Item -Path (Join-Path $sourceRoot "*") -Destination $resolvedInstallDir -Recurse -Force
}

$configureScript = Join-Path $resolvedInstallDir "scripts\configure_api.ps1"
if (-not (Test-Path $configureScript)) {
    $configureScript = Join-Path $resolvedInstallDir "install\configure_api.ps1"
}
if (-not (Test-Path $configureScript)) {
    throw "Nao encontrei configure_api.ps1 na instalacao."
}

& $configureScript -Role Client -ServerHost $ServerHost -Port $Port -ApiKey $ApiKey -InstallDir $resolvedInstallDir

$exePath = Join-Path $resolvedInstallDir "SIGEMPEManager.exe"
if ((-not $NoShortcut) -and (Test-Path $exePath)) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "SIGE MPE Manager.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $exePath
    $shortcut.WorkingDirectory = $resolvedInstallDir
    $shortcut.IconLocation = $exePath
    $shortcut.Save()
    Write-Host "Atalho criado: $shortcutPath"
}

Write-Host "Manager instalado em: $resolvedInstallDir"
