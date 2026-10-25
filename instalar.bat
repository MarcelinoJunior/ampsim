@echo off
rem Instalador do AmpSim: duplo-clique aqui.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
echo.
pause
