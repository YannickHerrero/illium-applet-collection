param([string]$Provider = (Join-Path $PSScriptRoot '../claude-usage.ps1'))
$ErrorActionPreference = 'Stop'
. $Provider -FunctionsOnly
function Assert($condition, [string]$message) { if (-not $condition) { throw $message } }
$now = 1800000000
function Snapshot($five, $week) { [pscustomobject]@{schema=1;source='claude-code-statusline';windows=[pscustomobject]@{five_hour=$five;seven_day=$week}} }
$five = [pscustomobject]@{used_percentage=34;resets_at=$now+9000;received_at=$now}
$week = [pscustomobject]@{used_percentage=68;resets_at=$now+300000;received_at=$now}
$data = Build-Data (Snapshot $five $week) $now
Assert ($data.bar_label -eq '34%') 'Bar must show the 5-hour quota'
Assert ($data.windows.Count -eq 2) 'Both windows'
Assert ($data.windows[0].pace -eq '16 pts under') 'Linear reference, not a forecast'
Assert ($data.windows[0].resets -eq 'Resets in 2h 30m') 'Reset duration'
Assert ((Build-Data (Snapshot $null $week) $now).bar_label -eq '—') 'Weekly must never replace session quota'
Assert ((Build-Data (Snapshot $five $week) ($now+601)).bar_label -eq '~34%') 'Stale marker'
Assert ((Build-Data (Snapshot $five $week) ($now+9000)).bar_label -eq '—') 'Expired session is unknown, not zero'
$five.used_percentage=0
Assert ((Build-Data (Snapshot $five $null) $now).bar_label -eq '0%') 'Zero is a valid value'
foreach ($bad in @($true,'34',-1,101,[double]::NaN)) {
    $five.used_percentage=$bad
    Assert ((Build-Data (Snapshot $five $null) $now).windows.Count -eq 0) 'Invalid percentages must be rejected'
}
Assert ((Build-Data $null $now).windows.Count -eq 0) 'Missing snapshot'
Assert ((Remaining 1) -eq 'Resets in 1m') 'Ceil the remaining minute'
Assert ((Remaining 90061) -eq 'Resets in 1d 1h') 'Long duration'
$five.used_percentage=34
$fable = [pscustomobject]@{schema=1;source='claude-code-usage';window=[pscustomobject]@{used_percentage=54;resets_at=$now+400000;received_at=$now}}
$data = Build-Data (Snapshot $five $week) $now $fable
Assert ($data.windows.Count -eq 3 -and $data.windows[2].label -eq 'Fable · Weekly') 'Fable is a separate third row'
Assert ($data.windows[2].used -eq '54%' -and $data.bar_label -eq '34%') 'Fable must not replace the five-hour bar'
Assert ((Build-Data $null $now $fable).bar_label -eq '—') 'Fable-only does not imply a session percentage'
Assert ((Build-Data (Snapshot $five $week) ($now+601) $fable).windows[2].used -eq '~54%') 'Unverified Fable data becomes stale'
$fable.schema=99
Assert ((Build-Data (Snapshot $five $week) $now $fable).windows.Count -eq 2) 'Invalid Fable metadata does not break other quotas'
Write-Output 'Claude provider fixtures passed (no credentials or network access).'
