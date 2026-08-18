param(
    [string]$AppRoot = "",
    [switch]$ApplyClient,
    # Mantido apenas para dar uma mensagem clara a automatizacoes antigas.
    [switch]$ApplyServer,
    [string]$ServerHost = "",
    [int]$Port = 8080,
    [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"

function Find-AppRoot {
    param([string]$StartDir)

    if ([string]::IsNullOrWhiteSpace($StartDir)) {
        $StartDir = $PSScriptRoot
    }

    $current = (Resolve-Path -LiteralPath $StartDir).Path
    while ($true) {
        if (Test-Path -LiteralPath (Join-Path $current "config\app.json")) {
            return $current
        }
        $parent = Split-Path -Path $current -Parent
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) {
            throw "Nao encontrei config\app.json a partir de: $StartDir"
        }
        $current = $parent
    }
}

function Read-JsonConfig {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]@{}
    }
    $raw = Get-Content -LiteralPath $Path -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return [pscustomobject]@{}
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

    $parent = Split-Path -Path $Path -Parent
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $Object | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-EnvValue {
    param(
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    $prefix = "$Name="
    foreach ($line in Get-Content -LiteralPath $Path) {
        $candidate = $line.Trim()
        if ($candidate.StartsWith("export ")) {
            $candidate = $candidate.Substring(7).Trim()
        }
        if ($candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $candidate.Substring($prefix.Length).Trim().Trim('"')
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

    $parent = Split-Path -Path $Path -Parent
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    $prefix = "$Name="
    $updated = $false
    $newLines = @()
    if (Test-Path -LiteralPath $Path) {
        foreach ($line in Get-Content -LiteralPath $Path) {
            $candidate = $line.Trim()
            if ($candidate.StartsWith("export ")) {
                $candidate = $candidate.Substring(7).Trim()
            }
            if ($candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                $newLines += "$Name=$Value"
                $updated = $true
            } else {
                $newLines += $line
            }
        }
    }
    if (-not $updated) {
        if ($newLines.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($newLines[-1])) {
            $newLines += ""
        }
        $newLines += "$Name=$Value"
    }
    $newLines | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Test-InsecureApiKey {
    param([string]$Value)

    $normalized = ([string]$Value).Trim().ToLowerInvariant()
    return @("", "1", "123", "123456", "joe123", "changeme", "change-me", "your_api_key_here", "troque-esta-chave") -contains $normalized
}

function Get-ConfigPaths {
    param([string]$Root)

    $configDir = Join-Path $Root "config"
    return @{
        App = Join-Path $configDir "app.json"
        Env = Join-Path $configDir ".env"
    }
}

function Get-ApiBaseUrl {
    param(
        [string]$ServerHost,
        [int]$SelectedPort
    )

    $hostValue = ([string]$ServerHost).Trim()
    if ([string]::IsNullOrWhiteSpace($hostValue)) {
        throw "Informe o IP ou nome do servidor."
    }
    if ($SelectedPort -lt 1 -or $SelectedPort -gt 65535) {
        throw "Porta invalida: $SelectedPort"
    }

    $hostValue = $hostValue -replace '^https?://', ''
    $hostValue = $hostValue.TrimEnd('/')
    if ($hostValue.Contains('/') -or $hostValue.Contains('?') -or $hostValue.Contains('#')) {
        throw "Informe apenas o IP ou nome do servidor, sem caminho."
    }
    if ($hostValue.Contains(':') -and -not $hostValue.StartsWith('[')) {
        $hostValue = "[$hostValue]"
    }
    return "http://$hostValue`:$SelectedPort"
}

function Test-ApiConnection {
    param(
        [string]$BaseUrl,
        [string]$Key
    )

    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/health" -Headers @{ "X-API-KEY" = $Key } -TimeoutSec 8
    } catch {
        throw "Nao foi possivel contactar a API em $BaseUrl. Confirme o servidor, a rede, a porta e a chave. Detalhe: $($_.Exception.Message)"
    }
    if (-not $response -or -not [bool]$response.ok) {
        throw "A API respondeu sem confirmar o estado de saude."
    }
    return $true
}

function Configure-Client {
    param(
        [string]$Root,
        [string]$ServerHost,
        [int]$SelectedPort,
        [string]$Key
    )

    if (Test-InsecureApiKey $Key) {
        throw "Informe a chave de ligacao gerada pela instalacao LojaAPI."
    }
    $baseUrl = Get-ApiBaseUrl -ServerHost $ServerHost -SelectedPort $SelectedPort
    $paths = Get-ConfigPaths $Root
    $appConfig = Read-JsonConfig $paths.App
    Set-JsonValue $appConfig "db_mode" "remote_strict"
    Set-JsonValue $appConfig "api_base_url" $baseUrl
    Set-JsonValue $appConfig "api_key" ""
    Set-JsonValue $appConfig "timeout" 10
    Save-JsonConfig $paths.App $appConfig
    Set-EnvValue $paths.Env "API_KEY" $Key
    Set-EnvValue $paths.Env "API_BASE_URL" $baseUrl
    Set-EnvValue $paths.Env "DB_MODE" "remote_strict"
    Set-EnvValue $paths.Env "API_PORT" ([string]$SelectedPort)
    return $baseUrl
}

function Get-AppExe {
    param([string]$Root)

    foreach ($name in @("SIGEMPEAdmin.exe", "SIGEMPEManager.exe")) {
        $path = Join-Path $Root $name
        if (Test-Path -LiteralPath $path) {
            return (Resolve-Path -LiteralPath $path).Path
        }
    }
    return ""
}

function Get-SavedConnection {
    param([string]$Root)

    $paths = Get-ConfigPaths $Root
    $appConfig = Read-JsonConfig $paths.App
    $baseUrl = Get-EnvValue $paths.Env "API_BASE_URL"
    if ([string]::IsNullOrWhiteSpace($baseUrl)) {
        $baseUrl = [string]$appConfig.api_base_url
    }
    $key = Get-EnvValue $paths.Env "API_KEY"
    $host = ""
    $savedPort = 8080
    try {
        if (-not [string]::IsNullOrWhiteSpace($baseUrl)) {
            $uri = [Uri]$baseUrl
            $host = $uri.Host
            if ($uri.Port -gt 0) { $savedPort = $uri.Port }
        }
    } catch {
    }
    return [pscustomobject]@{ Host = $host; Port = $savedPort; Key = $key }
}

if ($ApplyServer) {
    throw "A API e preparada apenas no pacote LojaAPI. Ative LojaAPI no servidor e depois use este assistente para ligar o cliente."
}

if ($ApplyClient) {
    $root = Find-AppRoot $AppRoot
    $baseUrl = Get-ApiBaseUrl -ServerHost $ServerHost -SelectedPort $Port
    Test-ApiConnection -BaseUrl $baseUrl -Key $ApiKey | Out-Null
    Configure-Client -Root $root -ServerHost $ServerHost -SelectedPort $Port -Key $ApiKey | Out-Null
    Write-Host "Cliente configurado e testado: $baseUrl"
    exit 0
}

$root = Find-AppRoot $AppRoot
$saved = Get-SavedConnection $root

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = "SIGE MPE - Ligar cliente"
$form.Size = New-Object System.Drawing.Size(760, 500)
$form.MinimumSize = New-Object System.Drawing.Size(720, 470)
$form.StartPosition = "CenterScreen"
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

$title = New-Object System.Windows.Forms.Label
$title.Text = "Ligar este cliente a LojaAPI"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(18, 16)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "A API e instalada separadamente no servidor principal. Este assistente apenas liga este computador a ela."
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(20, 48)
$form.Controls.Add($subtitle)

$rootLabel = New-Object System.Windows.Forms.Label
$rootLabel.Text = "Pasta do cliente: $root"
$rootLabel.AutoEllipsis = $true
$rootLabel.Size = New-Object System.Drawing.Size(700, 20)
$rootLabel.Location = New-Object System.Drawing.Point(20, 76)
$form.Controls.Add($rootLabel)

$info = New-Object System.Windows.Forms.Label
$info.Text = "1. No servidor, ative o pacote LojaAPI.  2. Gere o ficheiro SIGEMPELigacao.json.  3. Copie-o para este computador e importe-o abaixo."
$info.AutoEllipsis = $true
$info.Size = New-Object System.Drawing.Size(700, 35)
$info.Location = New-Object System.Drawing.Point(20, 105)
$form.Controls.Add($info)

$clientBox = New-Object System.Windows.Forms.GroupBox
$clientBox.Text = "Ligacao ao servidor"
$clientBox.Location = New-Object System.Drawing.Point(20, 150)
$clientBox.Size = New-Object System.Drawing.Size(700, 155)
$form.Controls.Add($clientBox)

$hostLabel = New-Object System.Windows.Forms.Label
$hostLabel.Text = "IP/nome do servidor:"
$hostLabel.AutoSize = $true
$hostLabel.Location = New-Object System.Drawing.Point(16, 30)
$clientBox.Controls.Add($hostLabel)

$hostInput = New-Object System.Windows.Forms.TextBox
$hostInput.Text = $saved.Host
$hostInput.Location = New-Object System.Drawing.Point(150, 26)
$hostInput.Size = New-Object System.Drawing.Size(210, 24)
$clientBox.Controls.Add($hostInput)

$portLabel = New-Object System.Windows.Forms.Label
$portLabel.Text = "Porta:"
$portLabel.AutoSize = $true
$portLabel.Location = New-Object System.Drawing.Point(380, 30)
$clientBox.Controls.Add($portLabel)

$portInput = New-Object System.Windows.Forms.NumericUpDown
$portInput.Minimum = 1
$portInput.Maximum = 65535
$portInput.Value = if ($saved.Port -gt 0) { $saved.Port } else { 8080 }
$portInput.Location = New-Object System.Drawing.Point(430, 26)
$portInput.Size = New-Object System.Drawing.Size(90, 24)
$clientBox.Controls.Add($portInput)

$keyLabel = New-Object System.Windows.Forms.Label
$keyLabel.Text = "Chave de ligacao:"
$keyLabel.AutoSize = $true
$keyLabel.Location = New-Object System.Drawing.Point(16, 66)
$clientBox.Controls.Add($keyLabel)

$keyInput = New-Object System.Windows.Forms.TextBox
$keyInput.Text = $saved.Key
$keyInput.Location = New-Object System.Drawing.Point(150, 62)
$keyInput.Size = New-Object System.Drawing.Size(470, 24)
$clientBox.Controls.Add($keyInput)

$importButton = New-Object System.Windows.Forms.Button
$importButton.Text = "Importar ficheiro"
$importButton.Location = New-Object System.Drawing.Point(18, 108)
$importButton.Size = New-Object System.Drawing.Size(140, 32)
$clientBox.Controls.Add($importButton)

$saveButton = New-Object System.Windows.Forms.Button
$saveButton.Text = "Testar e guardar"
$saveButton.Location = New-Object System.Drawing.Point(168, 108)
$saveButton.Size = New-Object System.Drawing.Size(140, 32)
$clientBox.Controls.Add($saveButton)

$openButton = New-Object System.Windows.Forms.Button
$openButton.Text = "Abrir app"
$openButton.Location = New-Object System.Drawing.Point(318, 108)
$openButton.Size = New-Object System.Drawing.Size(110, 32)
$clientBox.Controls.Add($openButton)

$status = New-Object System.Windows.Forms.TextBox
$status.Multiline = $true
$status.ReadOnly = $true
$status.ScrollBars = "Vertical"
$status.Location = New-Object System.Drawing.Point(20, 325)
$status.Size = New-Object System.Drawing.Size(700, 95)
$form.Controls.Add($status)

function Add-Status {
    param([string]$Text)
    $status.AppendText("$(Get-Date -Format 'HH:mm:ss')  $Text`r`n")
}

Add-Status "Pronto para ligar o cliente. A configuracao so e guardada depois do teste da API."

$importButton.Add_Click({
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter = "Ficheiro de ligacao (*.json)|*.json|Todos os ficheiros (*.*)|*.*"
    $dialog.Title = "Escolher ficheiro SIGEMPELigacao.json"
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return }
    try {
        $payload = Get-Content -LiteralPath $dialog.FileName -Raw | ConvertFrom-Json
        if ($payload.server_host) {
            $hostInput.Text = [string]$payload.server_host
        } elseif ($payload.api_base_url) {
            $uri = [Uri]([string]$payload.api_base_url)
            $hostInput.Text = $uri.Host
        } else {
            throw "O ficheiro nao contem o endereco do servidor."
        }
        if ($payload.port) { $portInput.Value = [int]$payload.port }
        if ($payload.api_key) { $keyInput.Text = [string]$payload.api_key }
        Add-Status "Ficheiro de ligacao importado."
    } catch {
        Add-Status "Erro ao importar: $($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Ficheiro invalido", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    }
})

$saveButton.Add_Click({
    try {
        $hostValue = $hostInput.Text.Trim()
        $portValue = [int]$portInput.Value
        $keyValue = $keyInput.Text.Trim()
        $baseUrl = Get-ApiBaseUrl -ServerHost $hostValue -SelectedPort $portValue
        Test-ApiConnection -BaseUrl $baseUrl -Key $keyValue | Out-Null
        Configure-Client -Root $root -ServerHost $hostValue -SelectedPort $portValue -Key $keyValue | Out-Null
        Add-Status "Ligacao validada e guardada: $baseUrl"
        [System.Windows.Forms.MessageBox]::Show("Ligacao guardada com sucesso.", "Cliente configurado", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
    } catch {
        Add-Status "Erro: $($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Erro ao ligar cliente", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    }
})

$openButton.Add_Click({
    $exe = Get-AppExe $root
    if (-not $exe) {
        $message = "Nao encontrei SIGEMPEAdmin.exe ou SIGEMPEManager.exe."
        Add-Status $message
        [System.Windows.Forms.MessageBox]::Show($message, "App nao encontrada", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
        return
    }
    Start-Process -FilePath $exe -WorkingDirectory $root | Out-Null
    Add-Status "App aberta."
})

[void]$form.ShowDialog()
