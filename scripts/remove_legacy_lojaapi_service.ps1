[CmdletBinding()]
param(
    [switch]$Purge
)

$ErrorActionPreference = "Stop"

if (-not $Purge) {
    throw "Operação protegida. Execute novamente com -Purge para remover apenas o serviço legado LojaAPI deste projecto."
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$expectedApplication = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "dist\MerceariaAdmin\LojaAPI.exe"))
$serviceName = "LojaAPI"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)

if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Esta remoção requer uma consola PowerShell aberta como Administrador."
}

$service = Get-CimInstance Win32_Service -Filter "Name='$serviceName'" -ErrorAction SilentlyContinue
if ($service) {
    if ($service.PathName -notmatch "(?i)nssm\.exe") {
        throw "O serviço '$serviceName' não corresponde ao serviço legado esperado (NSSM). Nenhuma alteração foi efectuada."
    }

    $nssmMatch = [regex]::Match($service.PathName, '(?i)^\s*"?(.+?nssm\.exe)"?(?:\s|$)')
    if (-not $nssmMatch.Success) {
        throw "Nao foi possivel interpretar o executavel NSSM do servico legado: $($service.PathName)"
    }
    $nssmPath = $nssmMatch.Groups[1].Value.Trim('"')
    if (-not (Test-Path -LiteralPath $nssmPath -PathType Leaf)) {
        throw "Não foi possível localizar o NSSM associado ao serviço legado: $nssmPath"
    }

    $configuredApplication = ((& $nssmPath get $serviceName Application | Out-String) -replace "`0", "").Trim()
    if ([System.IO.Path]::GetFullPath($configuredApplication) -ne $expectedApplication) {
        throw "O serviço '$serviceName' não aponta para o executável legado esperado. Nenhuma alteração foi efectuada."
    }

    & $nssmPath remove $serviceName confirm
    if ($LASTEXITCODE -ne 0) {
        throw "O NSSM não conseguiu remover o serviço legado '$serviceName'."
    }
    Write-Output "Serviço legado '$serviceName' removido."
}
else {
    Write-Output "O serviço legado '$serviceName' já não existe."
}

$task = Get-ScheduledTask -TaskName $serviceName -ErrorAction SilentlyContinue
if ($task) {
    $actions = @($task.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join "`n"
    if ($actions -notmatch [regex]::Escape($expectedApplication)) {
        throw "A tarefa '$serviceName' não aponta para o executável legado esperado. Nenhuma alteração foi efectuada."
    }
    Unregister-ScheduledTask -TaskName $serviceName -Confirm:$false
    Write-Output "Tarefa agendada legada '$serviceName' removida."
}

$legacyPackage = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "dist\MerceariaAdmin"))
$projectPrefix = $projectRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if (-not $legacyPackage.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Path $legacyPackage -Leaf) -ne "MerceariaAdmin") {
    throw "Destino legado inesperado: $legacyPackage"
}
if (Test-Path -LiteralPath $legacyPackage) {
    Remove-Item -LiteralPath $legacyPackage -Recurse -Force
    if (Test-Path -LiteralPath $legacyPackage) {
        throw "Nao foi possivel remover o pacote legado: $legacyPackage"
    }
    Write-Output "Pacote legado removido: $legacyPackage"
}
