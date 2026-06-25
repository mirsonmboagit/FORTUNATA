param(
    [string]$AppRoot = "",
    [switch]$ApplyServer,
    [switch]$ApplyClient,
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

    $current = (Resolve-Path "$StartDir").Path
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

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Quote-CommandArg {
    param([string]$Value)
    if ($null -eq $Value) {
        return '""'
    }
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Invoke-ElevatedSelf {
    param(
        [string]$Root,
        [int]$SelectedPort
    )

    # Escapar as aspas internas para o bloco -Command
    $escapedScript = $PSCommandPath -replace "'", "''"
    $escapedRoot   = $Root          -replace "'", "''"

    $argList = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"& { & '$escapedScript' -AppRoot '$escapedRoot' -ApplyServer -Port $SelectedPort }`""

    $process = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs -Wait -PassThru
    return $process.ExitCode
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

function Get-ConfigPaths {
    param([string]$Root)
    $configDir = Join-Path $Root "config"
    return @{
        ConfigDir = $configDir
        App = Join-Path $configDir "app.json"
        Api = Join-Path $configDir "api.json"
        Env = Join-Path $configDir ".env"
    }
}

function Get-LocalIPv4Addresses {
    $addresses = @()
    try {
        $addresses = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
            Where-Object {
                $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
                -not $_.IPAddressToString.StartsWith("127.")
            } |
            ForEach-Object { $_.IPAddressToString }
    } catch {
        $addresses = @()
    }

    return @($addresses | Select-Object -Unique)
}

function Get-PreferredServerIp {
    $addresses = Get-LocalIPv4Addresses
    foreach ($prefix in @("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")) {
        $match = $addresses | Where-Object { $_.StartsWith($prefix) } | Select-Object -First 1
        if ($match) {
            return $match
        }
    }
    if ($addresses.Count -gt 0) {
        return $addresses[0]
    }
    return "IP_DO_SERVIDOR"
}

function Configure-Server {
    param(
        [string]$Root,
        [int]$SelectedPort
    )

    $paths = Get-ConfigPaths $Root
    if ($SelectedPort -lt 1 -or $SelectedPort -gt 65535) {
        throw "Porta invalida: $SelectedPort"
    }

    $existingKey = Get-EnvValue $paths.Env "API_KEY"
    if (Test-InsecureApiKey $existingKey) {
        $existingKey = ""
    }
    $key = if ($existingKey) { $existingKey } else { New-ApiKey }

    $appConfig = Read-JsonConfig $paths.App
    Set-JsonValue $appConfig "db_mode" "hybrid"
    Set-JsonValue $appConfig "api_base_url" "http://127.0.0.1:$SelectedPort"
    Set-JsonValue $appConfig "api_key" ""
    Set-JsonValue $appConfig "timeout" 10
    Save-JsonConfig $paths.App $appConfig

    $apiConfig = Read-JsonConfig $paths.Api
    Set-JsonValue $apiConfig "host" "0.0.0.0"
    Set-JsonValue $apiConfig "port" $SelectedPort
    if ($null -eq $apiConfig.PSObject.Properties["runner"]) {
        Set-JsonValue $apiConfig "runner" "waitress"
    }
    Save-JsonConfig $paths.Api $apiConfig

    Set-EnvValue $paths.Env "API_KEY" $key
    Set-EnvValue $paths.Env "API_BASE_URL" "http://127.0.0.1:$SelectedPort"
    Set-EnvValue $paths.Env "DB_MODE" "hybrid"
    Set-EnvValue $paths.Env "API_HOST" "0.0.0.0"
    Set-EnvValue $paths.Env "API_PORT" ([string]$SelectedPort)

    return $key
}

function Configure-Client {
    param(
        [string]$Root,
        [string]$Host,
        [int]$SelectedPort,
        [string]$Key
    )

    if ([string]::IsNullOrWhiteSpace($Host)) {
        throw "Informe o IP ou nome do servidor."
    }
    if ($SelectedPort -lt 1 -or $SelectedPort -gt 65535) {
        throw "Porta invalida: $SelectedPort"
    }
    if (Test-InsecureApiKey $Key) {
        throw "Informe a chave de ligacao gerada no servidor."
    }

    $baseUrl = "http://$Host`:$SelectedPort"
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

function Test-ApiConnection {
    param(
        [string]$BaseUrl,
        [string]$Key
    )

    $headers = @{ "X-API-KEY" = $Key }
    $health = Invoke-RestMethod -Uri "$BaseUrl/health" -Headers $headers -TimeoutSec 5
    return [bool]$health.ok
}

function Get-ApiExe {
    param([string]$Root)
    $apiExe = Join-Path $Root "SIGEMPEAPI.exe"
    if (Test-Path $apiExe) {
        return $apiExe
    }
    return ""
}

function Start-ApiProcess {
    param([string]$Root)

    $apiExe = Get-ApiExe $Root
    if (-not $apiExe) {
        return $false
    }

    Start-Process -FilePath $apiExe -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
    Start-Sleep -Milliseconds 900
    return $true
}

function Register-ApiStartupTask {
    param([string]$Root)

    $apiExe = Get-ApiExe $Root
    if (-not $apiExe) {
        return $false
    }

    $taskName = "SIGEMPEAPI"
    $userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $escapedApiExe = $apiExe.Replace("'", "''")
    $escapedRoot = $Root.Replace("'", "''")
    $hiddenStartCommand = "Start-Process -FilePath '$escapedApiExe' -WorkingDirectory '$escapedRoot' -WindowStyle Hidden"
    $encodedCommand = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($hiddenStartCommand))
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand $encodedCommand"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Description "Inicia a API do SIGE MPE quando o utilizador entra no Windows." -Force | Out-Null
    return $true
}

function Enable-ApiFirewall {
    param([int]$SelectedPort)

    $ruleName = "Loja API $SelectedPort"
    netsh advfirewall firewall delete rule name="$ruleName" | Out-Null
    netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$SelectedPort | Out-Null
}

function Save-ConnectionFile {
    param(
        [string]$Root,
        [string]$Host,
        [int]$SelectedPort,
        [string]$Key
    )

    $desktop = [Environment]::GetFolderPath("Desktop")
    $path = Join-Path $desktop "SIGEMPELigacao.json"
    $payload = [ordered]@{
        app = "SIGE MPE"
        server_host = $Host
        port = $SelectedPort
        api_base_url = "http://$Host`:$SelectedPort"
        api_key = $Key
        created_at = (Get-Date).ToString("s")
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $path
    return $path
}

function Get-AppExe {
    param([string]$Root)
    foreach ($name in @("SIGEMPEAdmin.exe", "SIGEMPEManager.exe")) {
        $path = Join-Path $Root $name
        if (Test-Path $path) {
            return $path
        }
    }
    return ""
}

function Apply-ServerSetup {
    param(
        [string]$Root,
        [int]$SelectedPort
    )

    $key = Configure-Server -Root $Root -SelectedPort $SelectedPort
    Enable-ApiFirewall -SelectedPort $SelectedPort
    $startupRegistered = Register-ApiStartupTask -Root $Root
    $started = Start-ApiProcess -Root $Root
    return [ordered]@{
        ApiKey = $key
        StartupRegistered = $startupRegistered
        Started = $started
    }
}

if ($ApplyServer) {
    $root = Find-AppRoot $AppRoot
    $result = Apply-ServerSetup -Root $root -SelectedPort $Port
    Write-Host ($result | ConvertTo-Json -Depth 5)
    exit 0
}

if ($ApplyClient) {
    $root = Find-AppRoot $AppRoot
    $baseUrl = Configure-Client -Root $root -Host $ServerHost -SelectedPort $Port -Key $ApiKey
    Test-ApiConnection -BaseUrl $baseUrl -Key $ApiKey | Out-Null
    Write-Host "Cliente configurado: $baseUrl"
    exit 0
}

$root = Find-AppRoot $AppRoot
$paths = Get-ConfigPaths $root
$existingKeyForUi = Get-EnvValue $paths.Env "API_KEY"
$preferredIp = Get-PreferredServerIp
$localIps = Get-LocalIPv4Addresses
if ($localIps.Count -eq 0) {
    $localIpText = "Nenhum IP de rede encontrado."
} else {
    $localIpText = ($localIps -join "   ")
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$font = New-Object System.Drawing.Font("Segoe UI", 9)
$titleFont = New-Object System.Drawing.Font("Segoe UI", 13, [System.Drawing.FontStyle]::Bold)
$smallFont = New-Object System.Drawing.Font("Segoe UI", 8)

$form = New-Object System.Windows.Forms.Form
$form.Text = "SIGE MPE - Assistente de Ligacao"
$form.Size = New-Object System.Drawing.Size(760, 610)
$form.StartPosition = "CenterScreen"
$form.MinimumSize = New-Object System.Drawing.Size(740, 570)
$form.Font = $font

$title = New-Object System.Windows.Forms.Label
$title.Text = "Assistente de ligacao do SIGE MPE"
$title.Font = $titleFont
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(18, 16)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "Configure o servidor principal ou ligue este computador ao servidor por cliques."
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(20, 48)
$form.Controls.Add($subtitle)

$rootLabel = New-Object System.Windows.Forms.Label
$rootLabel.Text = "Pasta da app: $root"
$rootLabel.AutoEllipsis = $true
$rootLabel.Size = New-Object System.Drawing.Size(700, 20)
$rootLabel.Location = New-Object System.Drawing.Point(20, 76)
$form.Controls.Add($rootLabel)

$serverBox = New-Object System.Windows.Forms.GroupBox
$serverBox.Text = "1. Este computador e o servidor principal"
$serverBox.Location = New-Object System.Drawing.Point(20, 110)
$serverBox.Size = New-Object System.Drawing.Size(700, 165)
$form.Controls.Add($serverBox)

$ipLabel = New-Object System.Windows.Forms.Label
$ipLabel.Text = "IP deste computador para os clientes:"
$ipLabel.AutoSize = $true
$ipLabel.Location = New-Object System.Drawing.Point(16, 28)
$serverBox.Controls.Add($ipLabel)

$ipValue = New-Object System.Windows.Forms.TextBox
$ipValue.Text = $preferredIp
$ipValue.Location = New-Object System.Drawing.Point(230, 24)
$ipValue.Size = New-Object System.Drawing.Size(145, 24)
$serverBox.Controls.Add($ipValue)

$serverPortLabel = New-Object System.Windows.Forms.Label
$serverPortLabel.Text = "Porta:"
$serverPortLabel.AutoSize = $true
$serverPortLabel.Location = New-Object System.Drawing.Point(390, 28)
$serverBox.Controls.Add($serverPortLabel)

$serverPort = New-Object System.Windows.Forms.NumericUpDown
$serverPort.Minimum = 1
$serverPort.Maximum = 65535
$serverPort.Value = $Port
$serverPort.Location = New-Object System.Drawing.Point(440, 24)
$serverPort.Size = New-Object System.Drawing.Size(90, 24)
$serverBox.Controls.Add($serverPort)

$serverIpsLabel = New-Object System.Windows.Forms.Label
$serverIpsLabel.Text = "IPs encontrados: $localIpText"
$serverIpsLabel.AutoEllipsis = $true
$serverIpsLabel.Size = New-Object System.Drawing.Size(650, 20)
$serverIpsLabel.Location = New-Object System.Drawing.Point(16, 55)
$serverIpsLabel.Font = $smallFont
$serverBox.Controls.Add($serverIpsLabel)

$serverKeyLabel = New-Object System.Windows.Forms.Label
$serverKeyLabel.Text = "Chave de ligacao:"
$serverKeyLabel.AutoSize = $true
$serverKeyLabel.Location = New-Object System.Drawing.Point(16, 84)
$serverBox.Controls.Add($serverKeyLabel)

$serverKey = New-Object System.Windows.Forms.TextBox
$serverKey.Text = $existingKeyForUi
$serverKey.Location = New-Object System.Drawing.Point(130, 80)
$serverKey.Size = New-Object System.Drawing.Size(400, 24)
$serverKey.ReadOnly = $true
$serverBox.Controls.Add($serverKey)

$serverApply = New-Object System.Windows.Forms.Button
$serverApply.Text = "Preparar servidor"
$serverApply.Location = New-Object System.Drawing.Point(18, 118)
$serverApply.Size = New-Object System.Drawing.Size(150, 32)
$serverBox.Controls.Add($serverApply)

$serverSave = New-Object System.Windows.Forms.Button
$serverSave.Text = "Guardar ficheiro para clientes"
$serverSave.Location = New-Object System.Drawing.Point(178, 118)
$serverSave.Size = New-Object System.Drawing.Size(205, 32)
$serverBox.Controls.Add($serverSave)

$serverCopy = New-Object System.Windows.Forms.Button
$serverCopy.Text = "Copiar chave"
$serverCopy.Location = New-Object System.Drawing.Point(393, 118)
$serverCopy.Size = New-Object System.Drawing.Size(110, 32)
$serverBox.Controls.Add($serverCopy)

$clientBox = New-Object System.Windows.Forms.GroupBox
$clientBox.Text = "2. Este computador e cliente"
$clientBox.Location = New-Object System.Drawing.Point(20, 290)
$clientBox.Size = New-Object System.Drawing.Size(700, 155)
$form.Controls.Add($clientBox)

$clientHostLabel = New-Object System.Windows.Forms.Label
$clientHostLabel.Text = "IP/nome do servidor:"
$clientHostLabel.AutoSize = $true
$clientHostLabel.Location = New-Object System.Drawing.Point(16, 30)
$clientBox.Controls.Add($clientHostLabel)

$clientHost = New-Object System.Windows.Forms.TextBox
$clientHost.Text = ""
$clientHost.Location = New-Object System.Drawing.Point(150, 26)
$clientHost.Size = New-Object System.Drawing.Size(190, 24)
$clientBox.Controls.Add($clientHost)

$clientPortLabel = New-Object System.Windows.Forms.Label
$clientPortLabel.Text = "Porta:"
$clientPortLabel.AutoSize = $true
$clientPortLabel.Location = New-Object System.Drawing.Point(360, 30)
$clientBox.Controls.Add($clientPortLabel)

$clientPort = New-Object System.Windows.Forms.NumericUpDown
$clientPort.Minimum = 1
$clientPort.Maximum = 65535
$clientPort.Value = $Port
$clientPort.Location = New-Object System.Drawing.Point(410, 26)
$clientPort.Size = New-Object System.Drawing.Size(90, 24)
$clientBox.Controls.Add($clientPort)

$clientKeyLabel = New-Object System.Windows.Forms.Label
$clientKeyLabel.Text = "Chave:"
$clientKeyLabel.AutoSize = $true
$clientKeyLabel.Location = New-Object System.Drawing.Point(16, 65)
$clientBox.Controls.Add($clientKeyLabel)

$clientKey = New-Object System.Windows.Forms.TextBox
$clientKey.Text = ""
$clientKey.Location = New-Object System.Drawing.Point(150, 61)
$clientKey.Size = New-Object System.Drawing.Size(350, 24)
$clientBox.Controls.Add($clientKey)

$clientImport = New-Object System.Windows.Forms.Button
$clientImport.Text = "Importar ficheiro"
$clientImport.Location = New-Object System.Drawing.Point(18, 105)
$clientImport.Size = New-Object System.Drawing.Size(135, 32)
$clientBox.Controls.Add($clientImport)

$clientApply = New-Object System.Windows.Forms.Button
$clientApply.Text = "Testar e guardar"
$clientApply.Location = New-Object System.Drawing.Point(163, 105)
$clientApply.Size = New-Object System.Drawing.Size(135, 32)
$clientBox.Controls.Add($clientApply)

$openApp = New-Object System.Windows.Forms.Button
$openApp.Text = "Abrir app"
$openApp.Location = New-Object System.Drawing.Point(308, 105)
$openApp.Size = New-Object System.Drawing.Size(100, 32)
$clientBox.Controls.Add($openApp)

$status = New-Object System.Windows.Forms.TextBox
$status.Multiline = $true
$status.ReadOnly = $true
$status.ScrollBars = "Vertical"
$status.Location = New-Object System.Drawing.Point(20, 465)
$status.Size = New-Object System.Drawing.Size(700, 82)
$form.Controls.Add($status)

function Add-Status {
    param([string]$Text)
    $status.AppendText("$(Get-Date -Format 'HH:mm:ss')  $Text`r`n")
}

Add-Status "Pronto. Escolha servidor principal ou cliente."
if (-not (Get-ApiExe $root)) {
    Add-Status "Aviso: SIGEMPEAPI.exe ainda nao existe neste pacote. Gere o pacote novamente para servidor sem Python instalado."
}

$serverApply.Add_Click({
    try {
        $selectedPort = [int]$serverPort.Value
        if (-not (Test-IsAdmin)) {
            $answer = [System.Windows.Forms.MessageBox]::Show(
                "O Windows vai pedir permissao para liberar a porta no firewall e preparar o arranque automatico da API.",
                "Permissao necessaria",
                [System.Windows.Forms.MessageBoxButtons]::OKCancel,
                [System.Windows.Forms.MessageBoxIcon]::Information
            )
            if ($answer -ne [System.Windows.Forms.DialogResult]::OK) {
                Add-Status "Operacao cancelada pelo utilizador."
                return
            }
            $exitCode = Invoke-ElevatedSelf -Root $root -SelectedPort $selectedPort
            if ($exitCode -ne 0) {
                throw "A configuracao elevada terminou com codigo $exitCode."
            }
        } else {
            $result = Apply-ServerSetup -Root $root -SelectedPort $selectedPort
        }

        # Ler sempre a chave actualizada do .env depois da configuracao
        $freshKey = Get-EnvValue $paths.Env "API_KEY"
        $serverKey.Text = $freshKey

        Add-Status "Servidor preparado em http://$($ipValue.Text):$selectedPort."
        try {
            if (Test-ApiConnection -BaseUrl "http://127.0.0.1:$selectedPort" -Key $freshKey) {
                Add-Status "Teste local OK. A API respondeu."
            }
        } catch {
            Add-Status "Aviso: API ainda nao respondeu (pode estar a iniciar). Tente novamente em alguns segundos."
        }
    } catch {
        Add-Status "Erro: $($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Erro ao preparar servidor", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    }
})

$serverSave.Add_Click({
    try {
        $key = $serverKey.Text.Trim()
        if (Test-InsecureApiKey $key) {
            throw "Prepare o servidor primeiro para gerar a chave."
        }
        $path = Save-ConnectionFile -Root $root -Host $ipValue.Text.Trim() -SelectedPort ([int]$serverPort.Value) -Key $key
        Add-Status "Ficheiro criado: $path"
        [System.Windows.Forms.MessageBox]::Show("Ficheiro criado no Ambiente de Trabalho:`r`n$path", "Ficheiro de ligacao", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
    } catch {
        Add-Status "Erro: $($_.Exception.Message)"
    }
})

$serverCopy.Add_Click({
    if (-not [string]::IsNullOrWhiteSpace($serverKey.Text)) {
        [System.Windows.Forms.Clipboard]::SetText($serverKey.Text)
        Add-Status "Chave copiada."
    }
})

$clientImport.Add_Click({
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter = "Ficheiro de ligacao (*.json)|*.json|Todos os ficheiros (*.*)|*.*"
    $dialog.Title = "Escolher ficheiro de ligacao"
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        try {
            $payload = Get-Content $dialog.FileName -Raw | ConvertFrom-Json
            if ($payload.server_host) {
                $clientHost.Text = [string]$payload.server_host
            } elseif ($payload.api_base_url) {
                $uri = [Uri]([string]$payload.api_base_url)
                $clientHost.Text = $uri.Host
            }
            if ($payload.port) {
                $clientPort.Value = [int]$payload.port
            }
            if ($payload.api_key) {
                $clientKey.Text = [string]$payload.api_key
            }
            Add-Status "Ficheiro importado."
        } catch {
            Add-Status "Erro ao importar ficheiro: $($_.Exception.Message)"
        }
    }
})

$clientApply.Add_Click({
    try {
        $hostValue = $clientHost.Text.Trim()
        $portValue = [int]$clientPort.Value
        $keyValue = $clientKey.Text.Trim()
        $baseUrl = Configure-Client -Root $root -Host $hostValue -SelectedPort $portValue -Key $keyValue
        if (Test-ApiConnection -BaseUrl $baseUrl -Key $keyValue) {
            Add-Status "Ligacao OK. Este computador vai consumir $baseUrl."
            [System.Windows.Forms.MessageBox]::Show("Ligacao guardada com sucesso.", "Cliente configurado", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
        }
    } catch {
        Add-Status "Erro: $($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Erro ao ligar cliente", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    }
})

$openApp.Add_Click({
    $exe = Get-AppExe $root
    if ($exe) {
        Start-Process -FilePath $exe -WorkingDirectory $root | Out-Null
        Add-Status "App aberta."
    } else {
        Add-Status "Nao encontrei SIGEMPEAdmin.exe ou SIGEMPEManager.exe."
    }
})

[void]$form.ShowDialog()
