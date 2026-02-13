#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Install GhostLogic Black Box Agent on Windows.
.DESCRIPTION
    Creates a Python venv, copies agent files, installs config,
    and registers a Scheduled Task to run on boot.
#>

param(
    [string]$TenantKey = "",
    [string]$BlackboxUrl = "https://api.ghostlogic.tech",
    [switch]$DemoMode
)

$ErrorActionPreference = "Stop"

$InstallDir = "C:\Program Files\GhostLogic\Agent"
$ConfigDir  = "C:\ProgramData\GhostLogic"
$ConfigFile = "$ConfigDir\agent-config.json"
$LogDir     = "$ConfigDir\logs"
$TaskName   = "GhostLogicAgent"
$VenvDir    = "$InstallDir\venv"

Write-Host ""
Write-Host "=== GhostLogic Black Box Agent Installer ===" -ForegroundColor Cyan
Write-Host ""

# --- Check Python ---
$pythonCmd = $null
foreach ($candidate in @("python3", "python", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $pythonCmd = $candidate
                Write-Host "[OK] Found $ver ($candidate)" -ForegroundColor Green
                break
            }
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "[ERROR] Python 3.10+ is required. Install from https://python.org" -ForegroundColor Red
    exit 1
}

# --- Find repo root (where this script lives: install/windows/) ---
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent (Split-Path -Parent $ScriptDir)

if (-not (Test-Path "$RepoRoot\agent\__main__.py")) {
    Write-Host "[ERROR] Cannot find agent source at $RepoRoot\agent\" -ForegroundColor Red
    exit 1
}

# --- Stop existing task if running (safe upgrade) ---
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "[*] Stopping existing agent task ..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# --- Create directories ---
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ConfigDir  | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir     | Out-Null

# --- Create venv ---
Write-Host "[*] Creating Python venv at $VenvDir ..."
& $pythonCmd -m venv $VenvDir
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to create venv" -ForegroundColor Red
    exit 1
}

# --- Copy agent source ---
Write-Host "[*] Copying agent files ..."
$AgentDest = "$InstallDir\agent"
if (Test-Path $AgentDest) { Remove-Item -Recurse -Force $AgentDest }
Copy-Item -Recurse "$RepoRoot\agent" $AgentDest

# --- Write config ---
if (-not (Test-Path $ConfigFile)) {
    $demoValue = if ($DemoMode) { $true } else { $true }  # default demo on for MVP
    if (-not $DemoMode -and $TenantKey) { $demoValue = $false }

    $config = @{
        blackbox_url         = $BlackboxUrl
        tenant_key           = $TenantKey
        agent_id             = [guid]::NewGuid().ToString()
        collect_interval_secs = 5
        seal_interval_secs   = 60
        demo_mode            = $demoValue
        log_dir              = $LogDir
        log_max_hours        = 24
    }
    $config | ConvertTo-Json -Depth 4 | Set-Content $ConfigFile -Encoding UTF8
    Write-Host "[OK] Config written to $ConfigFile" -ForegroundColor Green

    # Restrict config permissions to Administrators + SYSTEM only
    $acl = Get-Acl $ConfigFile
    $acl.SetAccessRuleProtection($true, $false)
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        "BUILTIN\Administrators", "FullControl", "Allow")
    $acl.AddAccessRule($rule)
    $rule2 = New-Object System.Security.AccessControl.FileSystemAccessRule(
        "NT AUTHORITY\SYSTEM", "FullControl", "Allow")
    $acl.AddAccessRule($rule2)
    Set-Acl $ConfigFile $acl
} else {
    Write-Host "[*] Config already exists at $ConfigFile — not overwriting" -ForegroundColor Yellow
}

# --- Register Scheduled Task ---
Write-Host "[*] Registering Scheduled Task: $TaskName ..."

$pythonExe = "$VenvDir\Scripts\python.exe"
$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument "-m agent --config `"$ConfigFile`"" `
    -WorkingDirectory $InstallDir

$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Remove existing if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "GhostLogic Black Box Agent — endpoint telemetry"

Write-Host "[OK] Scheduled Task registered" -ForegroundColor Green

# --- Start it now ---
Write-Host "[*] Starting agent ..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

$task = Get-ScheduledTask -TaskName $TaskName
$state = $task.State
if ($state -eq "Running") {
    Write-Host "[OK] Agent is running" -ForegroundColor Green
} else {
    Write-Host "[WARN] Task state: $state — check logs at $LogDir" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Installation Complete ===" -ForegroundColor Cyan
Write-Host "Config:  $ConfigFile"
Write-Host "Logs:    $LogDir"
Write-Host "Agent:   $InstallDir"
Write-Host ""
if (-not $TenantKey) {
    Write-Host "Edit $ConfigFile to set your tenant_key." -ForegroundColor Yellow
    Write-Host "Then restart: Start-ScheduledTask -TaskName $TaskName" -ForegroundColor Yellow
}
Write-Host ""
