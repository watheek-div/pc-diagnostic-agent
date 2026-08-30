# uninstall.ps1 - Remove the PC Diagnostic Agent service and files.
#
# Run from an elevated PowerShell prompt.
# By default preserves collected data; pass -PurgeData to delete everything.

param([switch]$PurgeData)

$ErrorActionPreference = "Stop"

$InstallDir = "C:\ProgramData\PCDiagnosticAgent"
$BinDir = Join-Path $InstallDir "bin"
$Exe = Join-Path $BinDir "pcdiag.exe"

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Error "This script must be run as Administrator."
    exit 1
}

if (Test-Path $Exe) {
    Write-Host "Stopping service..."
    & $Exe service stop 2>$null

    Write-Host "Removing service..."
    & $Exe service remove
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Service removal returned a non-zero exit code."
    }
} else {
    Write-Host "pcdiag.exe not found; removing any stale service registration..."
    sc.exe delete PCDiagnosticAgent 2>$null
}

if ($PurgeData) {
    Write-Host "Purging data directory..."
    Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "Keeping data in $InstallDir (use -PurgeData to delete)."
}

Write-Host "Uninstall complete."
