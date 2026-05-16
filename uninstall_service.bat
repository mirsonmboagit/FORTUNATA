@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$cfg = Get-Content 'config/service.json' -Raw | ConvertFrom-Json; $root = (Get-Location).Path; $nssm = $cfg.nssm_path; if (-not [System.IO.Path]::IsPathRooted($nssm)) { $nssm = Join-Path $root $nssm }; @($cfg.name, $nssm) | ForEach-Object { $_ }"`) do (
    if not defined SERVICE_NAME (
        set "SERVICE_NAME=%%I"
    ) else if not defined NSSM_EXE (
        set "NSSM_EXE=%%I"
    )
)

if "%~1"=="--dry-run" goto :dryrun

if not exist "%NSSM_EXE%" (
    echo NSSM nao encontrado: %NSSM_EXE%
    echo Coloque o nssm.exe no caminho configurado em config\service.json e volte a executar.
    exit /b 1
)

"%NSSM_EXE%" stop "%SERVICE_NAME%"
"%NSSM_EXE%" remove "%SERVICE_NAME%" confirm

echo Servico "%SERVICE_NAME%" removido.
exit /b 0

:dryrun
echo [DRY-RUN] SERVICE_NAME=%SERVICE_NAME%
echo [DRY-RUN] NSSM_EXE=%NSSM_EXE%
exit /b 0
