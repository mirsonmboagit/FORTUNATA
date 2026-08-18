@echo off
setlocal
cd /d "%~dp0"

echo.
echo ==========================================
echo   Gerar ficheiro de ligacao para clientes
echo ==========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\gerar_ligacao_cliente.ps1" %*

echo.
pause
