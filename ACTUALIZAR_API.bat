@echo off
setlocal
cd /d "%~dp0"

echo.
echo ==========================================
echo   Atualizacao segura da API da Loja
echo ==========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\actualizar_api.ps1" %*

echo.
pause
