@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "PROJECT_PYTHON=%PROJECT_ROOT%\loja\Scripts\python.exe"
cd /d "%PROJECT_ROOT%"

if not exist "%PROJECT_PYTHON%" (
    echo Nao foi encontrado o Python do projeto: %PROJECT_PYTHON%
    pause
    exit /b 1
)

"%PROJECT_PYTHON%" scripts\emissor_licencas_automatico.py
echo.
echo O emissor automatico terminou. Leia a mensagem acima antes de fechar.
pause
