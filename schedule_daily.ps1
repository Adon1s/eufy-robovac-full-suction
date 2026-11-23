<#
Registers (or removes) a Windows scheduled task that runs full_power.py once a day.

  .\schedule_daily.ps1 -Rooms 1,2              daily at 02:00, room 1 then room 2
  .\schedule_daily.ps1 -Rooms 2,1 -Time 03:30  another order / time
  .\schedule_daily.ps1 -Remove                 delete the task
  Start-ScheduledTask "eufy full-power clean"  run it right now (to test)

What the task does each day:
  - runs full_power.py hidden (no window); everything goes to full_power.log next to this file
  - cleans each room starting from 100%; a room that reaches 80% is sent home and skipped
    (not retried, because a restart re-cleans the same part); the log tells you to split it
  - gives up after 6 hours if it cannot finish (robot off its dock, Wi-Fi down, ...)
  - wakes the PC if it is asleep and keeps it awake until done
  - runs only while you are signed in to Windows (a locked screen is fine)
  - a missed run (PC off at that time) is skipped, not run later in the day
Run this script again after moving the folder, so the task points at the new location.
#>
param(
    [string[]]$Rooms,
    [string]$Time = "02:00",
    [string]$TaskName = "eufy full-power clean",
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    "Removed scheduled task '$TaskName'."
    return
}

if (-not $Rooms) { throw "Give the room IDs to clean, e.g.  .\schedule_daily.ps1 -Rooms 1,2  (find them with probe_rooms.py)" }
$here = $PSScriptRoot
if (-not (Test-Path "$here\robot_config.json")) { throw "robot_config.json not found - run  python get_local_key.py  first" }
$roomList = ($Rooms -join ",") -replace "\s", ""
$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found next to $python" }

$arguments = "-I `"$here\full_power.py`" --rooms $roomList --start-now --max-retries 0 --too-big skip --give-up-after 6"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -WakeToRun -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "RoboVac L60: clean rooms $roomList one at a time between 100% and 80% battery. Log: $here\full_power.log" `
    -Force | Out-Null

$info = Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo
"Scheduled task '$TaskName' registered: daily at $Time, rooms $roomList."
"Runs: $pythonw $arguments"
"Next run: $($info.NextRunTime)"
