@echo off
rem Arranca el bot de contraseñas de los sorteos. Uso: raffle-listener [-v]
cd /d "%~dp0"
title Raffle Listener
if not exist ".venv\Scripts\python.exe" (
    echo Falta el entorno virtual. Ejecuta primero: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
    pause
    exit /b 1
)
if not exist "config.toml" copy /y config.example.toml config.toml >nul
".venv\Scripts\python.exe" -m raffle_listener %*
if errorlevel 1 pause
