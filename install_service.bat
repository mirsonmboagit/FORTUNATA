@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$cfg = Get-Content 'config/service.json' -Raw | ConvertFrom-Json; $root = (Get-Location).Path; $nssm = $cfg.nssm_path; if (-not [System.IO.Path]::IsPathRooted($nssm)) { $nssm = Join-Path $root $nssm }; $entry = $cfg.entrypoint; if (-not [System.IO.Path]::IsPathRooted($entry)) { $entry = Join-Path $root $entry }; $work = $cfg.working_directory; if (-not [System.IO.Path]::IsPathRooted($work)) { $work = Join-Path $root $work }; $stdout = $cfg.stdout_log; if (-not [System.IO.Path]::IsPathRooted($stdout)) { $stdout = Join-Path $root $stdout }; $stderr = $cfg.stderr_log; if (-not [System.IO.Path]::IsPathRooted($stderr)) { $stderr = Join-Path $root $stderr }; @($cfg.name, $cfg.display_name, $cfg.description, $nssm, $cfg.python_executable, $entry, $work, $stdout, $stderr) | ForEach-Object { $_ }"`) do (
    if not defined SERVICE_NAME (
        set "SERVICE_NAME=%%I"
    ) else if not defined DISPLAY_NAME (
        set "DISPLAY_NAME=%%I"
    ) else if not defined DESCRIPTION (
        set "DESCRIPTION=%%I"
    ) else if not defined NSSM_EXE (
        set "NSSM_EXE=%%I"
    ) else if not defined PYTHON_EXE (
        set "PYTHON_EXE=%%I"
    ) else if not defined ENTRYPOINT (
        set "ENTRYPOINT=%%I"
    ) else if not defined WORKDIR (
        set "WORKDIR=%%I"
    ) else if not defined STDOUT_LOG (
        set "STDOUT_LOG=%%I"
    ) else if not defined STDERR_LOG (
        set "STDERR_LOG=%%I"
    )
)

if "%~1"=="--dry-run" goto :dryrun

if not exist "%NSSM_EXE%" (
    echo NSSM nao encontrado: %NSSM_EXE%
    echo Coloque o nssm.exe no caminho configurado em config\service.json e volte a executar.
    exit /b 1
)

if not exist "%ENTRYPOINT%" (
    echo Entry point nao encontrado: %ENTRYPOINT%
    exit /b 1
)

if not exist "%WORKDIR%" (
    mkdir "%WORKDIR%" >nul 2>nul
)

if not exist "%ROOT_DIR%logs" (
    mkdir "%ROOT_DIR%logs" >nul 2>nul
)

"%NSSM_EXE%" install "%SERVICE_NAME%" "%PYTHON_EXE%" "%ENTRYPOINT%"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppDirectory "%WORKDIR%"
"%NSSM_EXE%" set "%SERVICE_NAME%" DisplayName "%DISPLAY_NAME%"
"%NSSM_EXE%" set "%SERVICE_NAME%" Description "%DESCRIPTION%"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStdout "%STDOUT_LOG%"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStderr "%STDERR_LOG%"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateFiles 1
"%NSSM_EXE%" set "%SERVICE_NAME%" Start SERVICE_AUTO_START

echo Servico "%SERVICE_NAME%" configurado.
exit /b 0

:dryrun
echo [DRY-RUN] SERVICE_NAME=%SERVICE_NAME%
echo [DRY-RUN] DISPLAY_NAME=%DISPLAY_NAME%
echo [DRY-RUN] DESCRIPTION=%DESCRIPTION%
echo [DRY-RUN] NSSM_EXE=%NSSM_EXE%
echo [DRY-RUN] PYTHON_EXE=%PYTHON_EXE%
echo [DRY-RUN] ENTRYPOINT=%ENTRYPOINT%
echo [DRY-RUN] WORKDIR=%WORKDIR%
echo [DRY-RUN] STDOUT_LOG=%STDOUT_LOG%
echo [DRY-RUN] STDERR_LOG=%STDERR_LOG%
exit /b 0
