@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "PROJECT_PYTHON=%PROJECT_ROOT%\loja\Scripts\python.exe"
cd /d "%PROJECT_ROOT%"

if not exist "%PROJECT_PYTHON%" (
    echo.
    echo Nao foi encontrado o Python do projeto em:
    echo %PROJECT_PYTHON%
    echo.
    pause
    exit /b 1
)

"%PROJECT_PYTHON%" scripts\superadmin_terminal.py
set "SUPERADMIN_EXIT=%ERRORLEVEL%"
if not "%SUPERADMIN_EXIT%"=="0" (
    echo.
    echo O terminal terminou com erro. Leia a mensagem acima antes de fechar.
)
echo.
pause
endlocal
