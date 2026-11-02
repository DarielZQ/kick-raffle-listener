# Crea el entorno virtual e instala todo. Uso: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[cuda,loopback,toast,autojoin,dev]"

if (-not (Test-Path config.toml)) { Copy-Item config.example.toml config.toml; Write-Host "Creado config.toml" }
# Comando global "raffle-listener" (WindowsApps ya está en el PATH del usuario)
$launcher = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\raffle-listener.cmd"
$target = Join-Path (Get-Location).Path "raffle-listener.cmd"
Set-Content -Path $launcher -Encoding ascii -Value "@echo off`r`ncall `"$target`" %*"
Write-Host "Listo. Abre un CMD y escribe: raffle-listener"
