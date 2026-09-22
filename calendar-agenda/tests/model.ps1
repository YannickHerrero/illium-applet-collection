# Synthetic provider-contract checks; no Outlook, network, private cache or UI.
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\..\lib.ps1"
function Check($condition, $message) { if (-not $condition) { throw $message } }
$connections = @([pscustomobject]@{ id = 'fixture'; name = 'Fixture' })
$state = [pscustomobject]@{ month = '2026-09'; day = '2026-09-10'; hidden = @() }
$events = @(
    [pscustomobject]@{ id = 'span'; calendar_id = 'cal'; title = 'Multi-day'; location = ''; all_day = $true; start = '2026-09-10'; end = '2026-09-12'; meeting_url = '' },
    [pscustomobject]@{ id = 'later'; calendar_id = 'cal'; title = 'Later'; location = ''; all_day = $true; start = '2026-09-20'; end = '2026-09-21'; meeting_url = '' }
)
$snapshots = @{ fixture = [pscustomobject]@{ calendars = @([pscustomobject]@{ id = 'cal'; name = 'Fixture' }); events = $events } }
$view = ConvertTo-AgendaView $snapshots $connections $state @() ([datetime]'2026-09-12')
Check ($view.days.Count -eq 42) 'Expected six weeks'
Check ($view.day_index -eq 11 -and $view.today_index -eq 13) 'Wrong selected/today index'
Check ($view.days[11].count -eq 1 -and $view.days[12].count -eq 1 -and $view.days[13].count -eq 0) 'All-day end must be exclusive'
Check ($view.days[21].events[0].title -eq 'Later') 'Non-selected days must be available locally'
$state.hidden = @((Get-AgendaKey 'fixture' 'cal'))
$hidden = ConvertTo-AgendaView $snapshots $connections $state @() ([datetime]'2026-09-12')
Check ($hidden.days[11].count -eq 0) 'Hidden calendar leaked'
# Large Unicode rows force bounded truncation, while every day retains metadata.
foreach ($day in $view.days) {
    $day.events = @(1..8 | ForEach-Object { @{ title = ([string][char]0x65e5) * 180; key = 'fixture' } })
    $day.count = 8; $day.more = 0
}
$json = ConvertTo-AgendaJson $view
Check ([Text.Encoding]::UTF8.GetByteCount($json) -le 60000) 'Exceeded runtime output limit'
$decoded = $json | ConvertFrom-Json
Check ($decoded.days.Count -eq 42) 'Truncation removed dates'
foreach ($day in $decoded.days) { Check (($day.events.Count + $day.more) -eq $day.count) 'Wrong truncation count' }
Write-Output 'Calendar model: six weeks, visibility, exclusive dates and bounded Unicode JSON passed'
