param(
    [ValidateSet("Server", "Client")]
    [string]$Role = "Client",

    [string]$ServerHost = "",

    [int]$Port = 8080,

    [string]$ApiKey = "",

    [switch]$GenerateApiKey,

    [switch]$TestConnection,

    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

function Find-AppRoot {
    param([string]$StartDir)

    $current = (Resolve-Path $StartDir).Path
    while ($true) {
        if (Test-Path (Join-Path $current "config\app.json")) {
            return $current
        }
        $parent = Split-Path $current -Parent
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) {
            throw "Nao encontrei config\app.json a partir de: $StartDir"
        }
        $current = $parent
    }
}

function Read-JsonConfig {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return New-Object PSObject
    }

    $raw = Get-Content $Path -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return New-Object PSObject
    }

    return $raw | ConvertFrom-Json
}

function Set-JsonValue {
    param(
        [object]$Object,
        [string]$Name,
        [object]$Value
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    } else {
        $Object.$Name = $Value
    }
}

function Save-JsonConfig {
    param(
        [string]$Path,
        [object]$Object
    )

    $parent = Split-Path $Path -Parent
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force $parent | Out-Null
    }

    $Object | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $Path
}

function Get-EnvValue {
    param(
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path $Path)) {
        return ""
    }

    $prefix = "$Name="
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith("export ")) {
            $trimmed = $trimmed.Substring(7).Trim()
        }
        if ($trimmed.StartsWith($prefix)) {
            return $trimmed.Substring($prefix.Length)
        }
    }
    return ""
}

function Set-EnvValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )

    $parent = Split-Path $Path -Parent
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force $parent | Out-Null
    }

    $lines = @()
    if (Test-Path $Path) {
        $lines = @(Get-Content $Path)
    }

    $prefix = "$Name="
    $updated = $false
    $newLines = @()

    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        $candidate = $trimmed
        if ($candidate.StartsWith("export ")) {
            $candidate = $candidate.Substring(7).Trim()
        }

        if ($candidate.StartsWith($prefix)) {
            $newLines += "$Name=$Value"
            $updated = $true
        } else {
            $newLines += $line
        }
    }

    if (-not $updated) {
        if ($newLines.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($newLines[-1])) {
            $newLines += ""
        }
        $newLines += "$Name=$Value"
    }

    $newLines | Set-Content -Encoding UTF8 $Path
}

function New-ApiKey {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Test-InsecureApiKey {
    param([string]$Value)

    $normalized = ([string]$Value).Trim().ToLowerInvariant()
    return @("", "1", "123", "123456", "joe123", "changeme", "change-me", "your_api_key_here", "troque-esta-chave") -contains $normalized
}

if ($InstallDir) {
    $root = (Resolve-Path $InstallDir).Path
} else {
    $root = Find-AppRoot $PSScriptRoot
}

$configDir = Join-Path $root "config"
$appConfigPath = Join-Path $configDir "app.json"
$apiConfigPath = Join-Path $configDir "api.json"
$envPath = Join-Path $configDir ".env"

if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Porta invalida: $Port"
}

$generatedKey = $false
$existingKey = Get-EnvValue $envPath "API_KEY"

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    if ($GenerateApiKey -or $Role -eq "Server") {
        if (-not $GenerateApiKey -and -not (Test-InsecureApiKey $existingKey)) {
            $ApiKey = $existingKey
        } else {
            $ApiKey = New-ApiKey
            $generatedKey = $true
        }
    } elseif (-not (Test-InsecureApiKey $existingKey)) {
        $ApiKey = $existingKey
    } else {
        throw "Informe -ApiKey com a mesma chave configurada no computador servidor."
    }
}

if (Test-InsecureApiKey $ApiKey) {
    throw "API_KEY insegura. Use uma chave forte ou execute com -GenerateApiKey no servidor."
}

if ($Role -eq "Server") {
    if ([string]::IsNullOrWhiteSpace($ServerHost)) {
        $ServerHost = "0.0.0.0"
    }
    $baseUrl = "http://127.0.0.1:$Port"
    $dbMode = "hybrid"
} else {
    if ([string]::IsNullOrWhiteSpace($ServerHost)) {
        throw "Informe -ServerHost com o IP ou nome do computador onde a API esta a correr."
    }
    $baseUrl = "http://$ServerHost`:$Port"
    $dbMode = "remote_strict"
}

$appConfig = Read-JsonConfig $appConfigPath
Set-JsonValue $appConfig "db_mode" $dbMode
Set-JsonValue $appConfig "api_base_url" $baseUrl
Set-JsonValue $appConfig "api_key" ""
Set-JsonValue $appConfig "timeout" 10
Save-JsonConfig $appConfigPath $appConfig

if ($Role -eq "Server") {
    $apiConfig = Read-JsonConfig $apiConfigPath
    Set-JsonValue $apiConfig "host" $ServerHost
    Set-JsonValue $apiConfig "port" $Port
    if ($null -eq $apiConfig.PSObject.Properties["runner"]) {
        Set-JsonValue $apiConfig "runner" "waitress"
    }
    Save-JsonConfig $apiConfigPath $apiConfig
}

Set-EnvValue $envPath "API_KEY" $ApiKey
Set-EnvValue $envPath "API_BASE_URL" $baseUrl
Set-EnvValue $envPath "DB_MODE" $dbMode
Set-EnvValue $envPath "API_PORT" ([string]$Port)
if ($Role -eq "Server") {
    Set-EnvValue $envPath "API_HOST" $ServerHost
}

Write-Host "Configuracao da API atualizada."
Write-Host "Pasta: $root"
Write-Host "Modo: $Role"
Write-Host "Base URL: $baseUrl"
Write-Host "DB_MODE: $dbMode"
Write-Host "API_KEY: configurada ($($ApiKey.Length) caracteres)"

if ($generatedKey) {
    Write-Host ""
    Write-Host "API_KEY gerada para o servidor. Copie esta chave para os computadores cliente:"
    Write-Host $ApiKey
}

if ($TestConnection) {
    $headers = @{ "X-API-KEY" = $ApiKey }
    try {
        $health = Invoke-RestMethod -Uri "$baseUrl/health" -Headers $headers -TimeoutSec 5
        if ($health.ok) {
            Write-Host "Teste OK: API respondeu em $baseUrl."
        } else {
            Write-Host "A API respondeu, mas indicou falha."
        }
    } catch {
        Write-Host "Teste falhou: $($_.Exception.Message)"
        if ($Role -eq "Client") {
            Write-Host "Confirme IP do servidor, firewall, porta $Port e API_KEY."
        }
    }
}
