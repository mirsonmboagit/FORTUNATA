param(
    [switch]$Clean,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$env:KIVY_NO_FILELOG = "1"
$env:KIVY_NO_ARGS = "1"

function Copy-OptionalScannerPackages {
    param([string]$TargetRoot)

    $pythonTag = ""
    $pythonSites = @()
    try {
        $pythonOutput = python -c "import site, sys; print('PYTAG=cp%d%d' % sys.version_info[:2]); print('\n'.join(dict.fromkeys(site.getsitepackages() + [site.getusersitepackages()])))"
        foreach ($line in $pythonOutput) {
            if ($line -like "PYTAG=*") {
                $pythonTag = $line.Substring(6)
            } elseif ($line -and (Test-Path $line)) {
                $pythonSites += (Resolve-Path $line).Path
            }
        }
    } catch {
        $pythonSites = @()
    }

    $backupSites = @()
    foreach ($relativeSite in @(
        "loja\Lib\site-packages",
        "loja_bak_pre_kivymd_restore\Lib\site-packages",
        "loja_legacy\Lib\site-packages",
        "loja_py314_broken_20260325\Lib\site-packages"
    )) {
        $site = Join-Path $root $relativeSite
        if (Test-Path $site) {
            $backupSites += (Resolve-Path $site).Path
        }
    }

    $candidateSites = @()
    foreach ($site in ($pythonSites + $backupSites)) {
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

        if ($scannerSite -eq $numpySite) {
            Write-Host "Scanner por camera incluido a partir de: $scannerSite"
        } else {
            Write-Host "Scanner por camera incluido: cv2/pyzbar de $scannerSite; numpy de $numpySite"
        }
        return
    }

    if (-not $scannerSite) {
        Write-Host "Scanner por camera nao incluido: cv2/pyzbar nao encontrados nos ambientes locais."
    } elseif (-not $numpySite) {
        if ($pythonTag) {
            Write-Host "Scanner por camera nao incluido: numpy compativel com $pythonTag nao encontrado."
        } else {
            Write-Host "Scanner por camera nao incluido: numpy nao encontrado."
        }
    }
}

if ($Clean) {
    foreach ($folder in @("build\admin_app", "dist\SIGEMPEAdmin")) {
        $target = Join-Path $root $folder
        if (Test-Path $target) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
}

if (-not $SkipBuild) {
    python -m PyInstaller --noconfirm admin_app.spec
}

$dist = Join-Path $root "dist\SIGEMPEAdmin"
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

Copy-OptionalScannerPackages -TargetRoot $dist

$distAppConfigPath = Join-Path $dist "config\app.json"
if (Test-Path $distAppConfigPath) {
    $distAppConfig = Get-Content $distAppConfigPath -Raw | ConvertFrom-Json
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
  Clique em "Preparar servidor" e depois em "Guardar ficheiro para clientes".

Nos computadores cliente:
  Clique em "Importar ficheiro" e depois em "Testar e guardar".

Guia completo:
  install\INSTALACAO_ADMIN.md
"@

$readme | Set-Content -Encoding UTF8 (Join-Path $dist "LEIA-ME-ADMIN.txt")

Write-Host "Build pronto em: $dist"
Write-Host "Copie a pasta SIGEMPEAdmin inteira para os outros computadores."
