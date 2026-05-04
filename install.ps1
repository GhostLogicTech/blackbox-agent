#Requires -RunAsAdministrator
# ============================================================
# INSTALL — Registers Task Scheduler jobs for agent + watchdog
# Run ONCE as Administrator.
# ============================================================

$ScriptDir = $PSScriptRoot
$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) { $PythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $PythonExe) {
    Write-Host "ERROR: Python not found in PATH" -ForegroundColor Red
    exit 1
}

Write-Host "Using Python: $PythonExe" -ForegroundColor Cyan

# --- Task 1: Agent (runs at startup, restarts on failure) ---
$ConfigPath = Join-Path $ScriptDir "agent-config.json"
$agentAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m agent --foreground --config `"$ConfigPath`"" `
    -WorkingDirectory $ScriptDir

$agentTrigger = New-ScheduledTaskTrigger -AtStartup
$agentSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 999 `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -MultipleInstances IgnoreNew

$agentPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask `
    -TaskName "GhostLogicMonitor" `
    -Action $agentAction `
    -Trigger $agentTrigger `
    -Settings $agentSettings `
    -Principal $agentPrincipal `
    -Description "GhostLogic system monitor agent — 21 collectors, D1 storage" `
    -Force

Write-Host "[OK] Registered: GhostLogicMonitor (at startup, auto-restart)" -ForegroundColor Green

# --- Task 2: Watchdog (every 2 minutes) ---
$watchdogAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$ScriptDir\watchdog.py`"" `
    -WorkingDirectory $ScriptDir

$watchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 2) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$watchdogSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

$watchdogPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask `
    -TaskName "GhostLogicWatchdog" `
    -Action $watchdogAction `
    -Trigger $watchdogTrigger `
    -Settings $watchdogSettings `
    -Principal $watchdogPrincipal `
    -Description "Watchdog — restarts GhostLogicMonitor if it dies" `
    -Force

Write-Host "[OK] Registered: GhostLogicWatchdog (every 2 minutes)" -ForegroundColor Green

# --- Start agent now ---
Start-ScheduledTask -TaskName "GhostLogicMonitor"
Write-Host ""
Write-Host "Agent started! Logs at: $ScriptDir\logs\" -ForegroundColor Cyan
Write-Host "Offline queue: $ScriptDir\queue\" -ForegroundColor Cyan
