# =============================================================================
# Registers a Windows Task Scheduler job that runs JobBot daily at 8:30 AM.
#
# Run this ONCE, in PowerShell, from the JobBot folder:
#     powershell -ExecutionPolicy Bypass -File .\setup_schedule.ps1
#
# The task runs ONLY when you are logged in (Playwright opens a real Chrome
# window, which needs your interactive desktop session).
#
# To remove it later:
#     Unregister-ScheduledTask -TaskName "JobBotDaily" -Confirm:$false
# =============================================================================

$ErrorActionPreference = "Stop"

$TaskName   = "JobBotDaily"
$ProjectDir = "D:\JobBot"
$Python     = "$ProjectDir\.venv\Scripts\python.exe"
$Script     = "run_daily.py"
$RunTime    = "08:30"          # 8:30 AM local time

if (-not (Test-Path $Python)) {
    Write-Error "Python venv not found at $Python. Create the venv first."
}

# Create logs folder.
$LogDir = Join-Path $ProjectDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# Action: cd into the project, run the pipeline, append stdout+stderr to a log.
$Cmd = "cd /d `"$ProjectDir`" && `"$Python`" $Script >> `"$LogDir\daily.log`" 2>&1"
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $Cmd" -WorkingDirectory $ProjectDir

# Trigger: every day at 8:30 AM.
$Trigger = New-ScheduledTaskTrigger -Daily -At $RunTime

# Run in the current interactive user session (needed for the visible browser).
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Be resilient: allow start on battery, retry once on failure.
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 10) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

# Replace any existing task with the same name.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings `
    -Description "JobBot: scrape Naukri, auto-apply, and email a status report." | Out-Null

Write-Host "✅ Scheduled task '$TaskName' created — runs daily at $RunTime."
Write-Host "   Logs: $LogDir\daily.log"
Write-Host "   Test now:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "   Remove:    Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
