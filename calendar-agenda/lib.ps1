# Shared, source-independent contract and presentation helpers. Compatible with PowerShell 5.1.
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
function Write-AgendaJson($Path, $Value) {
    $temp = "$Path.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText($temp, (ConvertTo-Json -InputObject $Value -Depth 16 -Compress), (New-Object Text.UTF8Encoding($false)))
        if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temp, $Path, [System.Management.Automation.Language.NullString]::Value) }
        else { [IO.File]::Move($temp, $Path) }
    } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force } }
}
function Read-AgendaJson($Path) {
    if (Test-Path -LiteralPath $Path) { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) }
    return $null
}
function Get-AgendaWindow([datetime]$Month) {
    $first = [datetime]::new($Month.Year, $Month.Month, 1)
    $start = $first.AddDays(-(([int]$first.DayOfWeek + 6) % 7))
    return @{ start = $start; end = $start.AddDays(42) }
}
function Get-AgendaKey([string]$Connection, [string]$Id) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes("$Connection`n$Id")))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Test-AgendaMeetingUrl([string]$Url) {
    $uri = $null
    if (-not [Uri]::TryCreate($Url, [UriKind]::Absolute, [ref]$uri)) { return $false }
    return $uri.Scheme -eq 'https' -and $uri.IsDefaultPort -and -not $uri.UserInfo -and $uri.Host -in @('teams.microsoft.com', 'teams.live.com')
}
function Find-AgendaMeetingUrl([string]$Text) {
    foreach ($match in [regex]::Matches($Text, 'https://teams\.(?:microsoft\.com|live\.com)/[^\s<>"\x27]+', 'IgnoreCase')) {
        $url = [Net.WebUtility]::HtmlDecode($match.Value).TrimEnd([char[]]@(')', ']', '.', ',', ';'))
        if (Test-AgendaMeetingUrl $url) { return $url }
    }
    return ''
}
function Limit-AgendaText([string]$Text, [int]$Length = 180) {
    $text = ($Text -replace '[\x00-\x1f]', ' ').Trim()
    if ($text.Length -gt $Length) { return $text.Substring(0, $Length) + '…' }
    return $text
}
function Test-AgendaOverlap($Event, [datetime]$Start, [datetime]$End) {
    if ($Event.all_day) {
        return ([datetime]::ParseExact($Event.start, 'yyyy-MM-dd', [cultureinfo]::InvariantCulture) -lt $End -and
            [datetime]::ParseExact($Event.end, 'yyyy-MM-dd', [cultureinfo]::InvariantCulture) -gt $Start)
    }
    $a = [datetimeoffset]::Parse($Event.start).LocalDateTime
    $b = [datetimeoffset]::Parse($Event.end).LocalDateTime
    return $a -lt $End -and ($b -gt $Start -or ($a -eq $b -and $a -ge $Start))
}
function ConvertTo-AgendaView($Snapshots, $Connections, $State, $Statuses, [datetime]$Now = (Get-Date)) {
    $month = [datetime]::ParseExact($State.month, 'yyyy-MM', [cultureinfo]::InvariantCulture)
    $day = [datetime]::ParseExact($State.day, 'yyyy-MM-dd', [cultureinfo]::InvariantCulture)
    $window = Get-AgendaWindow $month
    $calendars = @(); $events = New-Object 'Collections.Generic.List[object]'; $counts = @{}
    foreach ($connection in $Connections) {
        $snapshot = $Snapshots[$connection.id]
        if ($null -eq $snapshot) { continue }
        $byCalendar = @{}
        foreach ($event in $snapshot.events) {
            if (-not $byCalendar.ContainsKey($event.calendar_id)) { $byCalendar[$event.calendar_id] = New-Object 'Collections.Generic.List[object]' }
            $byCalendar[$event.calendar_id].Add($event)
        }
        foreach ($calendar in $snapshot.calendars) {
            $key = Get-AgendaKey $connection.id $calendar.id
            $visible = $key -notin @($State.hidden)
            $color = [Convert]::ToInt32($key.Substring(0, 6), 16) % 6
            $calendars += @{ key = $key; name = (Limit-AgendaText $calendar.name 70); connection = (Limit-AgendaText $connection.name 50); visible = $visible; color = $color % 6 }
            if ($visible) {
                foreach ($event in $byCalendar[$calendar.id]) {
                    if ($event.calendar_id -eq $calendar.id) {
                        if ($event.all_day) {
                            $a = [datetime]::ParseExact($event.start, 'yyyy-MM-dd', [cultureinfo]::InvariantCulture)
                            $b = [datetime]::ParseExact($event.end, 'yyyy-MM-dd', [cultureinfo]::InvariantCulture)
                        } else {
                            $a = [datetimeoffset]::Parse($event.start).LocalDateTime
                            $b = [datetimeoffset]::Parse($event.end).LocalDateTime
                        }
                        $firstDay = $a.Date
                        if ($firstDay -lt $window.start) { $firstDay = $window.start }
                        $last = $b
                        if ($last -gt $window.end) { $last = $window.end }
                        for ($mark = $firstDay; $mark -lt $last -or ($a -eq $b -and $mark -eq $a.Date -and $mark -lt $window.end); $mark = $mark.AddDays(1)) {
                            $dateKey = $mark.ToString('yyyy-MM-dd')
                            $counts[$dateKey] = 1 + $counts[$dateKey]
                        }
                        if ($a -lt $day.AddDays(1) -and ($b -gt $day -or ($a -eq $b -and $a -ge $day))) {
                            $events.Add(@{ event = $event; key = (Get-AgendaKey $connection.id $event.id); calendar = (Limit-AgendaText $calendar.name 70); color = $color; sort_start = $a })
                        }
                    }
                }
            }
        }
    }
    $weeks = @()
    for ($w = 0; $w -lt 6; $w++) {
        $cells = @()
        for ($d = 0; $d -lt 7; $d++) {
            $date = $window.start.AddDays($w * 7 + $d)
            $count = [int]$counts[$date.ToString('yyyy-MM-dd')]
            $cells += @{ day = $date.Day; date = $date.ToString('yyyy-MM-dd'); current = $date.Month -eq $month.Month; today = $date.Date -eq $Now.Date; selected = $date.Date -eq $day.Date; count = $count }
        }
        $weeks += ,$cells
    }
    $selected = @($events.ToArray() | Sort-Object @{Expression={ -not $_.event.all_day }}, sort_start)
    $rows = @()
    foreach ($item in ($selected | Select-Object -First 40)) {
        $event = $item.event; $ongoing = $false
        if ($event.all_day) { $time = 'All day' }
        else {
            $a = [datetimeoffset]::Parse($event.start).LocalDateTime; $b = [datetimeoffset]::Parse($event.end).LocalDateTime
            $time = $a.ToString('HH:mm') + ' - ' + $b.ToString('HH:mm')
            if ($a.Date -ne $b.Date) { $time = $a.ToString('MMM d HH:mm', [cultureinfo]'en-US') + ' - ' + $b.ToString('MMM d HH:mm', [cultureinfo]'en-US') }
            $ongoing = $a -le $Now -and $b -gt $Now
        }
        $rows += @{ key = $item.key; title = (Limit-AgendaText $event.title); location = (Limit-AgendaText $event.location 100); time = $time; calendar = $item.calendar; color = $item.color; ongoing = $ongoing; join = (Test-AgendaMeetingUrl $event.meeting_url) }
    }
    $yearStart = [datetime]::new($Now.Year, 1, 1)
    $yearProgress = 100 * ($Now - $yearStart).TotalDays / ($yearStart.AddYears(1) - $yearStart).TotalDays
    $warnings = @($Statuses | Where-Object { $_.stale -or $_.message -like '*results limited*' } | ForEach-Object { $_.name + ': ' + $_.message })
    return @{ today_header = $Now.ToString('MMMM d', [cultureinfo]'en-US'); current_year = $Now.Year; year_progress = $yearProgress; notice = ($warnings -join ' / '); month = $month.ToString('MMMM yyyy', [cultureinfo]'en-US'); day = $day.ToString('dddd, MMMM d', [cultureinfo]'en-US'); weeks = $weeks; calendars = $calendars; events = $rows; statuses = @($Statuses); more = [Math]::Max(0, $selected.Count - $rows.Count); empty = $rows.Count -eq 0 }
}
