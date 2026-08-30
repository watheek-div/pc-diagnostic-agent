# install.ps1 - Install the PC Diagnostic Agent and its Windows service.
#
# Run from an elevated PowerShell prompt.
# Copies the built executable to ProgramData, installs the auto-start service,
# starts it and runs a health check.

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Root "dist\pcdiag"
$InstallDir = "C:\ProgramData\PCDiagnosticAgent"
$BinDir = Join-Path $InstallDir "bin"
$Exe = Join-Path $BinDir "pcdiag.exe"

if (-not (Test-Path (Join-Path $Source "pcdiag.exe"))) {
    Write-Error "pcdiag.exe not found at $(Join-Path $Source 'pcdiag.exe'). Run build.ps1 first."
    exit 1
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Error "This script must be run as Administrator."
    exit 1
}

Write-Host "1. Creating directories..."
New-Item -ItemType Directory -Force -Path $InstallDir, $BinDir, `
    (Join-Path $InstallDir "data"), (Join-Path $InstallDir "logs"), `
    (Join-Path $InstallDir "reports") | Out-Null

Write-Host "2. Copying executable..."
Copy-Item -Path (Join-Path $Source "*") -Destination $BinDir -Recurse -Force

Write-Host "3. Installing Windows service..."
& $Exe service install
if ($LASTEXITCODE -ne 0) {
    Write-Error "Service installation failed."
    exit 1
}

Write-Host "4. Starting service..."
& $Exe service start
if ($LASTEXITCODE -ne 0) {
    Write-Error "Service start failed."
    exit 1
}

Write-Host "5. Verifying service status..."
Start-Sleep -Seconds 3
& $Exe status

Write-Host "6. Health check..."
& $Exe health

Write-Host ""
Write-Host "Installation complete."
