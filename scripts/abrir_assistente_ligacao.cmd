@echo off
setlocal EnableExtensions

set "START_DIR=%~dp0"
set "WIZARD=%START_DIR%install\setup_connection_wizard.ps1"

if not exist "%WIZARD%" (
    set "WIZARD=%START_DIR%scripts\setup_connection_wizard.ps1"
)

if not exist "%WIZARD%" (
    set "WIZARD=%START_DIR%setup_connection_wizard.ps1"
)

if not exist "%WIZARD%" (
    echo Nao encontrei o assistente de ligacao.
    echo Procure por install\setup_connection_wizard.ps1 dentro da pasta da app.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%WIZARD%" -AppRoot "%START_DIR%"
if errorlevel 1 (
    echo O assistente terminou com erro.
    pause
)
