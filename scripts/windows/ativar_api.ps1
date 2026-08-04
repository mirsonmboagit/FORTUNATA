param(
    [switch]$NoService
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

function Write-Step($message) {
    Write-Host ""
    Write-Host "== $message ==" -ForegroundColor Cyan
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-Python {
    $candidates = @(
        (Join-Path $root ".venv\Scripts\python.exe"),
        (Join-Path $root "loja\Scripts\python.exe"),
        "python"
    )
    foreach ($candidate in $candidates) {
        try {
            & $candidate --version *> $null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {
        }
    }
    throw "Python nao encontrado. Instale Python 3.11 ou copie a pasta do sistema completa."
}

function Find-ApiExe {
    $candidates = @(
        (Join-Path $root "LojaAPI.exe"),
        (Join-Path $root "SIGEMPEAPI.exe"),
        (Join-Path $root "dist\LojaAPI\LojaAPI.exe"),
        (Join-Path $root "dist\MerceariaAdmin\LojaAPI.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }
    return $null
}

function Find-Nssm {
    $candidates = @(
        (Join-Path $root "nssm.exe"),
        (Join-Path $root "scripts\windows\nssm.exe"),
        (Join-Path $root "..\nssm-2.24\win64\nssm.exe"),
        "nssm.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -eq "nssm.exe") {
            $cmd = Get-Command nssm.exe -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
        } elseif (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }
    return $null
}

$apiExe = Find-ApiExe
$appParameters = ""
if ($apiExe) {
    Write-Step "Usar executavel profissional"
    $application = $apiExe
    Write-Host "Executavel encontrado: $application"
} else {
    Write-Step "Preparar Python"
    $python = Find-Python
    if (-not (Test-Path (Join-Path $root ".venv\Scripts\python.exe")) -and $python -eq "python") {
        Write-Host "A criar ambiente local .venv..."
        & $python -m venv ".venv"
        $python = Join-Path $root ".venv\Scripts\python.exe"
    }

    & $python -m pip install --upgrade pip
    if (Test-Path "requirements-runtime.txt") {
        & $python -m pip install -r requirements-runtime.txt
    } elseif (Test-Path "requirements.txt") {
        & $python -m pip install -r requirements.txt
    }

    Write-Step "Testar API"
    & $python -c "import server.app; print('API OK')"
    if ($LASTEXITCODE -ne 0) {
        throw "A API falhou no teste. Veja a mensagem acima."
    }

    $application = $python
    $appParameters = "-m server.run_api"
}

Write-Step "Criar atalho simples"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Iniciar API da Loja.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $root "INICIAR_API.bat"
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
$shortcut.Save()
Write-Host "Atalho criado no Ambiente de Trabalho: Iniciar API da Loja"

if ($NoService) {
    Write-Host "Servico Windows ignorado por pedido."
    exit 0
}

$nssm = Find-Nssm
if (-not $nssm) {
    Write-Host ""
    Write-Host "NSSM nao encontrado. A API pode ser iniciada pelo atalho no Ambiente de Trabalho." -ForegroundColor Yellow
    Write-Host "Para iniciar automaticamente com o Windows, coloque nssm.exe nesta pasta e execute ATIVAR_API.bat como Administrador."
    exit 0
}

if (-not (Test-Admin)) {
    Write-Host ""
    Write-Host "Para corrigir/iniciar o servico automaticamente, clique com o botao direito em ATIVAR_API.bat e escolha 'Executar como administrador'." -ForegroundColor Yellow
    Write-Host "Mesmo assim, ja deixei o atalho simples criado para iniciar a API manualmente."
    exit 0
}

Write-Step "Configurar servico Windows"
$serviceName = "LojaAPI"
$stdoutLog = Join-Path $root "logs\lojaapi-stdout.log"
$stderrLog = Join-Path $root "logs\lojaapi-stderr.log"
New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null

$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if (-not $existing) {
    if ($appParameters) {
        & $nssm install $serviceName $application $appParameters
    } else {
        & $nssm install $serviceName $application
    }
} else {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $nssm stop $serviceName 2>$null
    $ErrorActionPreference = $previousErrorActionPreference
}

& $nssm set $serviceName Application $application
& $nssm set $serviceName AppParameters $appParameters
& $nssm set $serviceName AppDirectory $root
& $nssm set $serviceName DisplayName "LojaAPI"
& $nssm set $serviceName Description "API local da Loja"
& $nssm set $serviceName AppStdout $stdoutLog
& $nssm set $serviceName AppStderr $stderrLog
& $nssm set $serviceName AppRotateFiles 1
& $nssm set $serviceName Start SERVICE_AUTO_START

sc.exe config $serviceName obj= LocalSystem | Out-Host
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $nssm start $serviceName
$startExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($startExitCode -ne 0) {
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if (-not $service -or $service.Status -ne "Running") {
        throw "Nao foi possivel iniciar o servico $serviceName. Veja logs\lojaapi-stderr.log."
    }
}

Write-Host ""
Write-Host "API ativada com sucesso. Endereco local: http://127.0.0.1:8080" -ForegroundColor Green
