#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Uninstall GhostLogic Black Box Agent from Windows.
#>

$TaskName   = "GhostLogicAgent"
$InstallDir = "C:\Program Files\GhostLogic\Agent"
$ConfigDir  = "C:\ProgramData\GhostLogic"

Write-Host ""
Write-Host "=== GhostLogic Agent Uninstaller ===" -ForegroundColor Cyan
Write-Host ""

# --- Stop and remove Scheduled Task ---
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "[*] Stopping task ..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] Task removed" -ForegroundColor Green
} else {
    Write-Host "[*] Task not found — skipping" -ForegroundColor Yellow
}

# --- Remove install directory ---
if (Test-Path $InstallDir) {
    Write-Host "[*] Removing $InstallDir ..."
    Remove-Item -Recurse -Force $InstallDir
    Write-Host "[OK] Removed" -ForegroundColor Green
} else {
    Write-Host "[*] Install dir not found — skipping" -ForegroundColor Yellow
}

# --- Config and logs: ask user ---
if (Test-Path $ConfigDir) {
    $answer = Read-Host "Remove config and logs at $ConfigDir? (y/N)"
    if ($answer -eq "y" -or $answer -eq "Y") {
        Remove-Item -Recurse -Force $ConfigDir
        Write-Host "[OK] Config and logs removed" -ForegroundColor Green
    } else {
        Write-Host "[*] Config and logs preserved at $ConfigDir" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== Uninstall Complete ===" -ForegroundColor Cyan
Write-Host ""
