@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual em .venv ...
    python -m venv .venv || goto :erro
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :erro
)

set SD_ENABLE_ASIO=1
".venv\Scripts\python.exe" -m ampsim
if errorlevel 1 pause
exit /b

:erro
echo.
echo Falha ao preparar o ambiente. Verifique se o Python 3.11+ esta instalado e no PATH.
echo Se o erro mencionar "nome do arquivo muito grande", mova a pasta para um caminho curto (ex.: C:\Github\ampsim).
pause
exit /b 1
