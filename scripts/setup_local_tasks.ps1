# File: scripts/setup_local_tasks.ps1
# Creates local Windows tasks for intraday accumulation (every 60 minutes)
# and daily close (05:00 local time).
#
# Note: schtasks /TR has fragile quoting rules on Windows. We use .bat wrappers
# for each task to enforce repo cwd and Python invocation consistently.

# Review/UpdateHoja are scheduled with extra margin and also block on real close
# artifacts via scripts\wait_for_close_artifacts.py.

param(
    [string]$RepoPath = "C:\Users\Diego\lagrancrisis",
    [string]$PythonExe = "C:\Users\Diego\lagrancrisis\venv\Scripts\python.exe",
    [string]$TaskPrefix = "LGC"
)

$ErrorActionPreference = "Stop"

function New-OrReplaceTask {
    param(
        [string]$TaskName,
        [string]$Schedule,
        [string]$StartTime,
        [string]$CommandLine
    )

    $fullName = "{0}-{1}" -f $TaskPrefix, $TaskName

    # Remove task if it already exists (idempotent setup).
    try { schtasks /Delete /TN $fullName /F > $null 2>&1 } catch { }
    # Ignore error if task doesn't exist

    $args = @(
        "/Create",
        "/SC", $Schedule,
        "/TN", $fullName,
        "/TR", $CommandLine,
        "/ST", $StartTime,
        "/F"
    )

    schtasks @args | Out-Null
    Write-Output ("Task created: {0}" -f $fullName)
}

function Set-LgcTaskSettings {
    param(
        [string]$TaskName
    )

    # Ensure tasks run on laptops even when on battery and recover missed runs.
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Set-ScheduledTask -TaskName $TaskName -Settings $settings | Out-Null
}

if (-not (Test-Path $RepoPath)) {
    throw ("RepoPath does not exist: {0}" -f $RepoPath)
}

if (-not (Test-Path $PythonExe)) {
    throw ("PythonExe does not exist: {0}" -f $PythonExe)
}

$MainPy = Join-Path $RepoPath "src\main.py"
if (-not (Test-Path $MainPy)) {
    throw ("main.py does not exist: {0}" -f $MainPy)
}

Push-Location $RepoPath
try {
    $taskSchedulerLog = Get-WinEvent -ListLog "Microsoft-Windows-TaskScheduler/Operational" -ErrorAction SilentlyContinue
    if ($null -ne $taskSchedulerLog -and -not $taskSchedulerLog.IsEnabled) {
        wevtutil set-log "Microsoft-Windows-TaskScheduler/Operational" /enabled:true | Out-Null
        Write-Output "Enabled Task Scheduler Operational log"
    }

    $accumulateBat = Join-Path $RepoPath "scripts\run_intraday_accumulate.bat"
    $closeBat = Join-Path $RepoPath "scripts\run_daily_close.bat"
    
    $reviewBat = Join-Path $RepoPath "scripts\run_review.bat"
    $updateHojaBat = Join-Path $RepoPath "scripts\run_update_hoja.bat"
    $healthCheckBat = Join-Path $RepoPath "scripts\run_daily_health_check.bat"
    $intradayGuardBat = Join-Path $RepoPath "scripts\run_intraday_guard_check.bat"
    
    if (-not (Test-Path $accumulateBat)) {
        throw ("run_intraday_accumulate.bat not found: {0}" -f $accumulateBat)
    }
    if (-not (Test-Path $closeBat)) {
        throw ("run_daily_close.bat not found: {0}" -f $closeBat)
    }
    
    if (-not (Test-Path $reviewBat)) {
        throw ("run_review.bat not found: {0}" -f $reviewBat)
    }
    if (-not (Test-Path $updateHojaBat)) {
        throw ("run_update_hoja.bat not found: {0}" -f $updateHojaBat)
    }
    if (-not (Test-Path $healthCheckBat)) {
        throw ("run_daily_health_check.bat not found: {0}" -f $healthCheckBat)
    }
    if (-not (Test-Path $intradayGuardBat)) {
        throw ("run_intraday_guard_check.bat not found: {0}" -f $intradayGuardBat)
    }

    # Task A: intraday accumulation every 60 minutes.
    New-OrReplaceTask -TaskName "IntradayAccumulate" -Schedule "HOURLY" -StartTime "00:00" -CommandLine $accumulateBat
    Set-LgcTaskSettings -TaskName ("{0}-{1}" -f $TaskPrefix, "IntradayAccumulate")

    # Task B: one daily close at 05:00 local time.
    New-OrReplaceTask -TaskName "DailyClose" -Schedule "DAILY" -StartTime "05:00" -CommandLine $closeBat
    Set-LgcTaskSettings -TaskName ("{0}-{1}" -f $TaskPrefix, "DailyClose")
    
    # Task C: daily operational review at 05:30 with real artifact dependency.
    # Reads pipeline metrics/judge reports and generates daily_review.json.
    New-OrReplaceTask -TaskName "Review" -Schedule "DAILY" -StartTime "05:30" -CommandLine $reviewBat
    Set-LgcTaskSettings -TaskName ("{0}-{1}" -f $TaskPrefix, "Review")
    
    # Task D: update HOJA_OPERATIVA at 05:35 with real artifact dependency.
    # Reads daily_review.json and automatically updates operational checklist.
    New-OrReplaceTask -TaskName "UpdateHoja" -Schedule "DAILY" -StartTime "05:35" -CommandLine $updateHojaBat
    Set-LgcTaskSettings -TaskName ("{0}-{1}" -f $TaskPrefix, "UpdateHoja")

    # Task E: daily health check at 05:20.
    # Emits ALERT if any critical output is missing after the close pipeline.
    New-OrReplaceTask -TaskName "HealthCheck" -Schedule "DAILY" -StartTime "05:20" -CommandLine $healthCheckBat
    Set-LgcTaskSettings -TaskName ("{0}-{1}" -f $TaskPrefix, "HealthCheck")

    # Task F: hourly intraday guard at :10.
    # Detects scheduler refusal codes and stale intraday captures.
    New-OrReplaceTask -TaskName "IntradayGuard" -Schedule "HOURLY" -StartTime "00:10" -CommandLine $intradayGuardBat
    Set-LgcTaskSettings -TaskName ("{0}-{1}" -f $TaskPrefix, "IntradayGuard")

    Write-Output ""
    Write-Output "Utility commands:"
    Write-Output ("- List tasks: schtasks /Query /TN {0}-* /V /FO LIST" -f $TaskPrefix)
    Write-Output ("- Run accumulate now: schtasks /Run /TN {0}-IntradayAccumulate" -f $TaskPrefix)
    Write-Output ("- Run close now: schtasks /Run /TN {0}-DailyClose" -f $TaskPrefix)
    Write-Output ("- Run review now: schtasks /Run /TN {0}-Review" -f $TaskPrefix)
    Write-Output ("- Run update hoja now: schtasks /Run /TN {0}-UpdateHoja" -f $TaskPrefix)
    Write-Output ("- Run health check now: schtasks /Run /TN {0}-HealthCheck" -f $TaskPrefix)
    Write-Output ("- Run intraday guard now: schtasks /Run /TN {0}-IntradayGuard" -f $TaskPrefix)
}
finally {
    Pop-Location
}
