param(
    [switch]$Clean,
    [switch]$SkipBuild,
    [switch]$SkipChecks,
    [string]$WorkPath,
    [string]$DistPath
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

function Resolve-ProjectOutputPath {
    param([string]$PathValue, [string]$Label)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $null
    }
    $resolved = if ([System.IO.Path]::IsPathRooted($PathValue)) {
        [System.IO.Path]::GetFullPath($PathValue)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $root $PathValue))
    }
    $rootPath = [System.IO.Path]::GetFullPath($root).TrimEnd('\', '/')
    $rootPrefix = $rootPath + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label deve ficar dentro do projeto: $resolved"
    }
    return $resolved
}

$resolvedWorkPath = Resolve-ProjectOutputPath -PathValue $WorkPath -Label "WorkPath"
$resolvedDistPath = Resolve-ProjectOutputPath -PathValue $DistPath -Label "DistPath"

$pythonCandidates = @(
    (Join-Path $root ".venv\Scripts\python.exe"),
    (Join-Path $root "loja\Scripts\python.exe")
)
$pythonExecutable = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonExecutable) {
    $pythonExecutable = (Get-Command python -ErrorAction Stop).Source
}

if (-not $SkipChecks) {
    & $pythonExecutable (Join-Path $root "scripts\preflight_release.py")
    if ($LASTEXITCODE -ne 0) { throw "Preflight da release falhou." }
}

$env:KIVY_NO_FILELOG = "1"
$env:KIVY_NO_ARGS = "1"

function Copy-RequiredScannerPackages {
    param(
        [string]$TargetRoot,
        [string]$PythonExecutable
    )

    $pythonTag = ""
    $pythonSites = @()
    try {
        $pythonOutput = & $PythonExecutable -c "import cv2, numpy, pyzbar; from pyzbar.pyzbar import decode; from pyzbar.wrapper import ZBarSymbol; import site, sys; print('PYTAG=cp%d%d' % sys.version_info[:2]); print('\n'.join(dict.fromkeys(site.getsitepackages() + [site.getusersitepackages()])))"
        if ($LASTEXITCODE -ne 0) {
            throw "As dependencias obrigatorias do scanner nao podem ser importadas."
        }
        foreach ($line in $pythonOutput) {
            if ($line -like "PYTAG=*") {
                $pythonTag = $line.Substring(6)
            } elseif ($line -and (Test-Path $line)) {
                $pythonSites += (Resolve-Path $line).Path
            }
        }
    } catch {
        throw "Falha ao validar as dependencias do scanner: $($_.Exception.Message)"
    }

    $candidateSites = @()
    foreach ($site in $pythonSites) {
        if ($site -and ($candidateSites -notcontains $site)) {
            $candidateSites += $site
        }
    }

    $scannerSite = $null
    foreach ($site in $candidateSites) {
        if ((Test-Path (Join-Path $site "cv2")) -and (Test-Path (Join-Path $site "pyzbar"))) {
            $scannerSite = $site
            break
        }
    }

    $numpySite = $null
    foreach ($site in $candidateSites) {
        $numpyPath = Join-Path $site "numpy"
        if (-not (Test-Path $numpyPath)) {
            continue
        }

        $matchesPython = $true
        if ($pythonTag) {
            $matchesPython = $false
            foreach ($coreFolder in @("_core", "core")) {
                $corePath = Join-Path $numpyPath $coreFolder
                if (-not (Test-Path $corePath)) {
                    continue
                }
                $nativeModule = Get-ChildItem $corePath -Filter "_multiarray_umath.$pythonTag-*.pyd" -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($nativeModule) {
                    $matchesPython = $true
                    break
                }
            }
        }

        if ($matchesPython) {
            $numpySite = $site
            break
        }
    }

    if ($scannerSite -and $numpySite) {
        foreach ($package in @("cv2", "pyzbar")) {
            $packagePath = Join-Path $scannerSite $package
            if (Test-Path $packagePath) {
                Copy-Item -Path $packagePath -Destination $TargetRoot -Recurse -Force
            }
        }
        foreach ($package in @("numpy", "numpy.libs")) {
            $packagePath = Join-Path $numpySite $package
            if (Test-Path $packagePath) {
                Copy-Item -Path $packagePath -Destination $TargetRoot -Recurse -Force
            }
        }
        foreach ($metadataFilter in @("opencv_python*.dist-info", "pyzbar*.dist-info")) {
            Get-ChildItem $scannerSite -Directory -Filter $metadataFilter -ErrorAction SilentlyContinue |
                ForEach-Object { Copy-Item -Path $_.FullName -Destination $TargetRoot -Recurse -Force }
        }
        Get-ChildItem $numpySite -Directory -Filter "numpy*.dist-info" -ErrorAction SilentlyContinue |
            ForEach-Object { Copy-Item -Path $_.FullName -Destination $TargetRoot -Recurse -Force }

        $requiredFiles = @(
            (Join-Path $TargetRoot "cv2\cv2.pyd"),
            (Join-Path $TargetRoot "pyzbar\libzbar-64.dll"),
            (Join-Path $TargetRoot "pyzbar\libiconv.dll")
        )
        foreach ($requiredFile in $requiredFiles) {
            if (-not (Test-Path $requiredFile)) {
                throw "Ficheiro obrigatorio do scanner ausente: $requiredFile"
            }
        }
        if (-not (Get-ChildItem (Join-Path $TargetRoot "cv2") -Filter "opencv_videoio_ffmpeg*.dll" -ErrorAction SilentlyContinue | Select-Object -First 1)) {
            throw "Backend de camera OpenCV ausente do pacote do scanner."
        }
        if (-not (Get-ChildItem (Join-Path $TargetRoot "numpy\_core") -Filter "_multiarray_umath*.pyd" -ErrorAction SilentlyContinue | Select-Object -First 1)) {
            throw "Biblioteca principal do NumPy ausente do pacote do scanner."
        }
        foreach ($requiredFile in @(
            (Join-Path $TargetRoot "_internal\cv2\cv2.pyd"),
            (Join-Path $TargetRoot "_internal\pyzbar\libzbar-64.dll"),
            (Join-Path $TargetRoot "_internal\pyzbar\libiconv.dll")
        )) {
            if (-not (Test-Path $requiredFile)) {
                throw "Biblioteca interna obrigatoria do scanner ausente: $requiredFile"
            }
        }
        if (-not (Get-ChildItem (Join-Path $TargetRoot "_internal\cv2") -Filter "opencv_videoio_ffmpeg*.dll" -ErrorAction SilentlyContinue | Select-Object -First 1)) {
            throw "Backend interno de camera OpenCV ausente do executavel."
        }

        if ($scannerSite -eq $numpySite) {
            Write-Host "Scanner por camera incluido a partir de: $scannerSite"
        } else {
            Write-Host "Scanner por camera incluido: cv2/pyzbar de $scannerSite; numpy de $numpySite"
        }
        return
    }

    throw "Scanner por camera nao incluido: cv2, pyzbar ou numpy compativel nao encontrado."
}

if ($Clean) {
    $cleanFolders = @(
        $(if ($resolvedWorkPath) { $resolvedWorkPath } else { Join-Path $root "build\admin_app" }),
        $(if ($resolvedDistPath) { $resolvedDistPath } else { Join-Path $root "dist\SIGEMPEAdmin" })
    )
    foreach ($target in $cleanFolders) {
        if (Test-Path $target) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
}

if (-not $SkipBuild) {
    $pyInstallerArgs = @("--noconfirm", "--log-level", "WARN")
    if ($resolvedWorkPath) {
        $pyInstallerArgs += @("--workpath", $resolvedWorkPath)
    }
    if ($resolvedDistPath) {
        $pyInstallerArgs += @("--distpath", $resolvedDistPath)
    }
    $pyInstallerArgs += (Join-Path $root "scripts\packaging\admin_app.spec")
    & $pythonExecutable -m PyInstaller @pyInstallerArgs
    if ($LASTEXITCODE -ne 0) { throw "Empacotamento do Administrador falhou." }
}

$distRoot = if ($resolvedDistPath) { $resolvedDistPath } else { Join-Path $root "dist" }
$dist = Join-Path $distRoot "SIGEMPEAdmin"
if (-not (Test-Path $dist)) {
    throw "Build nao encontrado em: $dist"
}

$internal = Join-Path $dist "_internal"
foreach ($folder in @("assets", "config", "locales")) {
    $sourceFolder = Join-Path $internal $folder
    if (Test-Path $sourceFolder) {
        Copy-Item -Path $sourceFolder -Destination $dist -Recurse -Force
    }
}

$cacheSource = Join-Path $internal "data\cache"
if (Test-Path $cacheSource) {
    $cacheTarget = Join-Path $dist "data\cache"
    if (-not (Test-Path $cacheTarget)) {
        New-Item -ItemType Directory -Force $cacheTarget | Out-Null
    }
    Copy-Item -Path (Join-Path $cacheSource "*") -Destination $cacheTarget -Recurse -Force
}

foreach ($folder in @("admin", "user", "utils", "manager")) {
    $sourceFolder = Join-Path $internal $folder
    $targetFolder = Join-Path $dist $folder
    if (Test-Path $sourceFolder) {
        if (-not (Test-Path $targetFolder)) {
            New-Item -ItemType Directory -Force $targetFolder | Out-Null
        }
        Copy-Item -Path (Join-Path $sourceFolder "*.kv") -Destination $targetFolder -Force -ErrorAction SilentlyContinue
    }
}

Copy-RequiredScannerPackages -TargetRoot $dist -PythonExecutable $pythonExecutable

if (Get-ChildItem -LiteralPath $dist -File -Filter "SIGEMPEAPI.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1) {
    throw "O pacote do Administrador nao pode incluir SIGEMPEAPI.exe. Use o pacote LojaAPI no servidor."
}

$distAppConfigPath = Join-Path $dist "config\app.json"
if (Test-Path $distAppConfigPath) {
    $distAppConfig = Get-Content $distAppConfigPath -Raw | ConvertFrom-Json
    $distAppConfig.app_env = "production"
    $distAppConfig.db_mode = "remote_strict"
    $distAppConfig.api_base_url = "http://127.0.0.1:8080"
    $distAppConfig.api_key = ""
    $distAppConfig | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $distAppConfigPath
}

$installDir = Join-Path $dist "install"
if (-not (Test-Path $installDir)) {
    New-Item -ItemType Directory -Force $installDir | Out-Null
}

Copy-Item -Force (Join-Path $root "scripts\configure_api.ps1") (Join-Path $installDir "configure_api.ps1")
Copy-Item -Force (Join-Path $root "scripts\install_admin_client.ps1") (Join-Path $installDir "install_admin_client.ps1")
Copy-Item -Force (Join-Path $root "scripts\update_admin_client.ps1") (Join-Path $installDir "update_admin_client.ps1")
Copy-Item -Force (Join-Path $root "scripts\setup_connection_wizard.ps1") (Join-Path $installDir "setup_connection_wizard.ps1")
Copy-Item -Force (Join-Path $root "scripts\abrir_assistente_ligacao.cmd") (Join-Path $installDir "abrir_assistente_ligacao.cmd")
Copy-Item -Force (Join-Path $root "scripts\abrir_assistente_ligacao.cmd") (Join-Path $dist "Configurar Ligacao.cmd")
Copy-Item -Force (Join-Path $root "docs\INSTALACAO_ADMIN.md") (Join-Path $installDir "INSTALACAO_ADMIN.md")
Copy-Item -Force (Join-Path $root "VERSION") (Join-Path $dist "VERSION")

foreach ($file in @("install_service.bat", "update_service.bat", "uninstall_service.bat")) {
    $stale = Join-Path $installDir $file
    if (Test-Path $stale) {
        Remove-Item -LiteralPath $stale -Force
    }
}

$readme = @"
SIGE MPE ADMIN

Executavel:
  SIGEMPEAdmin.exe

Configuracao por cliques:
  Abra "Configurar Ligacao.cmd"

No servidor principal:
  Depois de activar a API, execute "GERAR_LIGACAO_CLIENTE.bat" na pasta LojaAPI.

Nos computadores cliente:
  Clique em "Importar ficheiro" e depois em "Testar e guardar".

Guia completo:
  install\INSTALACAO_ADMIN.md
"@

$readme | Set-Content -Encoding UTF8 (Join-Path $dist "LEIA-ME-ADMIN.txt")

Write-Host "Build pronto em: $dist"
Write-Host "Copie a pasta SIGEMPEAdmin inteira para os outros computadores."
