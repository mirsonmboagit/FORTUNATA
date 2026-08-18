param(
    [switch]$Purge,
    [string]$Name = "qa_release_1.1.0_20260811"
)

$ErrorActionPreference = "Stop"

if (-not $Purge) {
    throw "Use -Purge para confirmar a limpeza da copia temporaria de QA."
}
if ($Name -notmatch '^qa_release_[A-Za-z0-9._-]+$') {
    throw "Nome de QA inesperado: $Name"
}

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$tempRoot = (Resolve-Path -LiteralPath (Join-Path $projectRoot "temp")).Path.TrimEnd('\', '/')
$target = [System.IO.Path]::GetFullPath((Join-Path $tempRoot $Name))
$prefix = $tempRoot + [System.IO.Path]::DirectorySeparatorChar

if (-not $target.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Destino QA fora da pasta temporaria: $target"
}
if ((Split-Path -Path $target -Leaf) -ne $Name) {
    throw "Destino QA inesperado: $target"
}
if (-not (Test-Path -LiteralPath $target)) {
    Write-Output "Copia QA ja removida: $target"
    exit 0
}

$lockedProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine -like "*$target*"
}
if ($lockedProcesses) {
    $ids = ($lockedProcesses | ForEach-Object { $_.ProcessId }) -join ", "
    throw "Existem processos QA activos ($ids). A limpeza foi cancelada."
}

Remove-Item -LiteralPath $target -Recurse -Force
if (Test-Path -LiteralPath $target) {
    throw "Nao foi possivel remover a copia QA: $target"
}

Write-Host "Copia QA removida: $target" -ForegroundColor Green
