# build.ps1 - Build a standalone Windows executable with PyInstaller.
#
# Requires Python 3.12+ on the build machine (the customer does NOT need it).
# Output: dist\pcdiag\pcdiag.exe  (+ _internal support files)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Venv = Join-Path $Root ".venv"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    Write-Host "Creating virtual environment..."
    python -m venv $Venv
}
$Python = Join-Path $Venv "Scripts\python.exe"

Write-Host "Installing dependencies..."
& $Python -m pip install --quiet --upgrade pip
& $Python -m pip install --quiet -r requirements.txt
& $Python -m pip install --quiet pyinstaller

Write-Host "Running tests..."
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Error "Tests failed; aborting build."
    exit 1
}

Write-Host "Building with PyInstaller..."
& $Python -m PyInstaller --noconfirm --clean --name pcdiag `
    --paths $Root `
    --hidden-import win32evtlog `
    --hidden-import win32evtlogutil `
    --hidden-import win32service `
    --hidden-import win32serviceutil `
    --hidden-import win32event `
    --hidden-import win32timezone `
    --hidden-import servicemanager `
    pcdiag.py

Copy-Item -Path (Join-Path $Root "config.yaml") -Destination (Join-Path $Root "dist\pcdiag\config.yaml") -Force

Write-Host ""
Write-Host "Build complete: $Root\dist\pcdiag\pcdiag.exe"
