@echo off
setlocal
cd /d "%~dp0"

echo.
echo ==========================================
echo   Ativacao simples da API da Loja
echo ==========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\ativar_api.ps1"

echo.
pause
