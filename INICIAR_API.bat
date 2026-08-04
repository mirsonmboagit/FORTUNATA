@echo off
setlocal
cd /d "%~dp0"

if exist "LojaAPI.exe" (
    echo A iniciar a API em http://127.0.0.1:8080 ...
    "%~dp0LojaAPI.exe"
    pause
    exit /b %ERRORLEVEL%
)

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "loja\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0loja\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo A iniciar a API em http://127.0.0.1:8080 ...
"%PYTHON_EXE%" server\run_api.py
pause
