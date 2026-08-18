param(
    [string]$ServerHost = "",
    [int]$Port = 0,
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path

function Get-EnvValue {
    param([string]$Path, [string]$Name)

    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    $prefix = "$Name="
    foreach ($line in Get-Content -LiteralPath $Path) {
        $candidate = $line.Trim()
        if ($candidate.StartsWith("export ")) { $candidate = $candidate.Substring(7).Trim() }
        if ($candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $candidate.Substring($prefix.Length).Trim().Trim('"')
        }
    }
    return ""
}

function Test-InsecureApiKey {
    param([string]$Value)
    $normalized = ([string]$Value).Trim().ToLowerInvariant()
    return @("", "1", "123", "123456", "joe123", "changeme", "change-me", "your_api_key_here", "troque-esta-chave") -contains $normalized
}

function Get-PreferredServerIp {
    try {
        $addresses = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
            Where-Object {
                $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
                -not $_.IPAddressToString.StartsWith("127.")
            } |
            ForEach-Object { $_.IPAddressToString }
        foreach ($prefix in @("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")) {
            $match = $addresses | Where-Object { $_.StartsWith($prefix) } | Select-Object -First 1
            if ($match) { return $match }
        }
        return $addresses | Select-Object -First 1
    } catch {
        return ""
    }
}

$envPath = Join-Path $root "config\.env"
$apiKey = Get-EnvValue -Path $envPath -Name "API_KEY"
if (Test-InsecureApiKey $apiKey) {
    throw "Nao encontrei uma chave segura. Execute ATIVAR_API.bat e inicie a API antes de gerar o ficheiro."
}

$apiConfigPath = Join-Path $root "config\api.json"
$apiConfig = if (Test-Path -LiteralPath $apiConfigPath) {
    Get-Content -LiteralPath $apiConfigPath -Raw | ConvertFrom-Json
} else {
    [pscustomobject]@{}
}
if ($Port -lt 1 -or $Port -gt 65535) {
    $configuredPort = 8080
    if ($apiConfig -and $apiConfig.PSObject.Properties["port"] -and $apiConfig.port) {
        $configuredPort = [int]$apiConfig.port
    }
    $Port = $configuredPort
}
if ([string]::IsNullOrWhiteSpace($ServerHost)) {
    $ServerHost = Get-PreferredServerIp
}
if ([string]::IsNullOrWhiteSpace($ServerHost)) {
    throw "Nao foi possivel descobrir o IP do servidor. Execute com -ServerHost IP_DO_SERVIDOR."
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "SIGEMPELigacao.json"
}
$parent = Split-Path -Path $OutputPath -Parent
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}

$payload = [ordered]@{
    app = "SIGE MPE"
    server_host = $ServerHost
    port = $Port
    api_base_url = "http://$ServerHost`:$Port"
    api_key = $apiKey
    created_at = (Get-Date).ToString("s")
}
$payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Ficheiro de ligacao criado: $OutputPath" -ForegroundColor Green
Write-Host "Copie este ficheiro apenas para computadores autorizados." -ForegroundColor Yellow
