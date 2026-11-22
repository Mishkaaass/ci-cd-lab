#requires -Version 5.1
<#
.SYNOPSIS
    Launch the OpsBoard Linux demo on Windows through Ubuntu WSL 2.
.DESCRIPTION
    Checks WSL and passes this checkout to a bounded setup script in Ubuntu.
    No automatic Windows feature changes, Docker Desktop installation, or
    PowerShell elevation. Existing Docker data and Kubernetes PVC are preserved.
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-showcase.ps1
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-showcase.ps1 -Distribution Ubuntu-24.04
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$Distribution = ''
)

$ErrorActionPreference = 'Stop'

function Stop-OpsBoard([string]$Message) {
    Write-Host "`nSETUP NEEDED: $Message" -ForegroundColor Yellow
    exit 1
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Stop-OpsBoard 'This launcher is for Windows PowerShell. On Linux use bash scripts/showcase.sh.'
}

$wslCommand = Get-Command 'wsl.exe' -ErrorAction SilentlyContinue
if (-not $wslCommand) {
    Stop-OpsBoard 'Install WSL 2 and Ubuntu first (PowerShell as Administrator: wsl --install -d Ubuntu; reboot if requested).'
}

$wslTarget = @()
if ($Distribution) { $wslTarget = @('-d', $Distribution) }

Write-Host ''
Write-Host 'OpsBoard | Windows reviewer setup' -ForegroundColor Cyan
Write-Host 'Linux runtime: WSL 2. Container runtime: Docker Desktop.'
Write-Host 'No Windows services, features or Docker data will be changed by this script.'
Write-Host ''

# Convert a Windows checkout path to WSL path without constructing shell commands
# from user-controlled input. Arguments are passed separately to wsl.exe.
$repoRoot = Split-Path -Parent $PSScriptRoot
$linuxRepoRoot = & wsl.exe @wslTarget --exec wslpath '-u' '-a' $repoRoot 2>&1
if ($LASTEXITCODE -ne 0) {
    Stop-OpsBoard ('WSL/Ubuntu is not ready. Run wsl --install -d Ubuntu, restart if requested, ' +
                   'open Ubuntu once to create its Linux user, and retry. ' + ($linuxRepoRoot -join ' '))
}
$linuxRepoRoot = ($linuxRepoRoot | Select-Object -First 1).Trim()
if (-not $linuxRepoRoot.StartsWith('/')) {
    Stop-OpsBoard 'Could not translate the checkout path into a WSL path.'
}

$linuxScript = "$linuxRepoRoot/scripts/wsl-showcase.sh"
Write-Host 'One-time Linux dependencies will be checked inside WSL.'
Write-Host 'If a password is requested, enter the UBUNTU password in THIS terminal.'
Write-Host 'The OpsBoard web interface never accepts your Windows or sudo password.'
Write-Host ''
Write-Host 'After READY appears, open http://127.0.0.1:18002/ in your Windows browser.' -ForegroundColor Cyan
Write-Host 'Leave this terminal running. Ctrl+C stops the demo launcher.'
Write-Host ''

& wsl.exe @wslTarget --exec bash $linuxScript $linuxRepoRoot
$code = $LASTEXITCODE
if ($code -ne 0) {
    Stop-OpsBoard "WSL demo exited with code $code. Read the setup instructions above."
}
