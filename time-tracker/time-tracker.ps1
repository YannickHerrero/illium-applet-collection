param([string]$Action = '', [switch]$FunctionsOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)

$script:Invariant = [Globalization.CultureInfo]::InvariantCulture
# The provider runs every minute, so an older heartbeat means the machine
# slept or shut down, or Illium stopped, while a session was open.
$script:StaleAfter = [TimeSpan]::FromMinutes(5)
$script:DefaultZones = 'Tokyo|Tokyo Standard Time;Paris|Romance Standard Time'

function Resolve-Store {
    if ($env:ILLIUM_APPLET_STORE) { return $env:ILLIUM_APPLET_STORE }
    return Join-Path $env:LOCALAPPDATA 'illium-applet-collection\time-tracker\sessions.json'
}
# The first zone is the reference: it decides which day and week a session
# belongs to.
function Read-Zones([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { $text = $script:DefaultZones }
    $zones = @(foreach ($entry in $text.Split(';')) {
        if (-not $entry.Trim()) { continue }
        $parts = $entry.Split('|', 2)
        if ($parts.Count -ne 2) { throw "Expected City|Windows time zone identifier, got '$entry'" }
        [ordered]@{ name = $parts[0].Trim(); zone = [TimeZoneInfo]::FindSystemTimeZoneById($parts[1].Trim()) }
    })
    if ($zones.Count -eq 0) { throw 'No time zone configured' }
    return , $zones
}
function ConvertTo-Instant($value) {
    # PowerShell 7 reads ISO strings as DateTime; Windows PowerShell keeps text.
    if ($value -is [DateTime]) { return [DateTimeOffset]::new($value.ToUniversalTime()) }
    return [DateTimeOffset]::Parse([string]$value, $script:Invariant, [Globalization.DateTimeStyles]::AssumeUniversal).ToUniversalTime()
}
function Format-Instant([DateTimeOffset]$instant) {
    return $instant.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", $script:Invariant)
}
function Format-Clock([DateTimeOffset]$instant, $zone, [string]$pattern) {
    return [TimeZoneInfo]::ConvertTime($instant, $zone).ToString($pattern, $script:Invariant)
}
# An HH:MM clock of the given day in a zone, as an instant.
function ConvertFrom-Clock([string]$text, [DateTime]$day, $zone) {
    if ($text -notmatch '^\s*(\d{1,2}):(\d{2})\s*$' -or [int]$Matches[1] -gt 23 -or [int]$Matches[2] -gt 59) {
        throw "Expected a time as HH:MM, got '$text'"
    }
    $local = $day.AddHours([int]$Matches[1]).AddMinutes([int]$Matches[2])
    return [DateTimeOffset][TimeZoneInfo]::ConvertTimeToUtc($local, $zone)
}
# The view sends its arguments as one JSON array; a bare verb also works.
function Read-Action([string]$text) {
    if (-not $text.StartsWith('[')) { return , @($text) }
    # Windows PowerShell emits the array as one object: assign before wrapping.
    $parts = ConvertFrom-Json -InputObject $text
    $parts = [object[]]@($parts)
    if ($parts.Count -eq 0 -or @($parts | Where-Object { $_ -isnot [string] }).Count) { throw 'Invalid time tracker action' }
    return , $parts
}

function New-Store { return [ordered]@{ version = 1; sessions = @() } }
function Read-Store([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return New-Store }
    $raw = [IO.File]::ReadAllText($path)
    if (-not $raw.Trim()) { return New-Store }
    # A corrupt history is reported, never silently replaced.
    try {
        $parsed = ConvertFrom-Json -InputObject $raw
        $sessions = @(foreach ($entry in @($parsed.sessions)) {
            if ($null -eq $entry) { continue }
            [ordered]@{
                start = ConvertTo-Instant $entry.start
                end = $(if ($entry.end) { ConvertTo-Instant $entry.end } else { $null })
                seen = $(if ($entry.seen) { ConvertTo-Instant $entry.seen } else { $null })
            }
        })
    } catch { throw "Session file unreadable: $path" }
    return [ordered]@{ version = 1; sessions = $sessions }
}
function Write-Store([string]$path, $store) {
    $directory = Split-Path -Parent $path
    if ($directory -and -not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    $sessions = [object[]]@(foreach ($session in $store.sessions) {
        $entry = [ordered]@{ start = Format-Instant $session.start; end = $null }
        if ($session.end) { $entry.end = Format-Instant $session.end } else { $entry.seen = Format-Instant $session.seen }
        $entry
    })
    $json = ConvertTo-Json -InputObject ([ordered]@{ version = 1; sessions = $sessions }) -Depth 4
    $temporary = "$path.$PID.tmp"
    try {
        [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $temporary -Destination $path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}
function Get-Open($store) {
    if ($store.sessions.Count -eq 0) { return $null }
    $last = $store.sessions[$store.sessions.Count - 1]
    if ($last.end) { return $null }
    return $last
}
# Ends an open session at its last heartbeat when the provider stopped running
# for a while: the gap is unknown, so it is not counted. Returns whether the
# store changed.
function Close-Stale($store, [DateTimeOffset]$now) {
    $open = Get-Open $store
    if (-not $open) { return $false }
    $seen = if ($open.seen) { $open.seen } else { $open.start }
    if ($now - $seen -le $script:StaleAfter) { return $false }
    $open.end = $seen
    return $true
}
# Today's sessions in the reference zone, by their position in the store.
function Get-Today($store, $zone, [DateTimeOffset]$now) {
    $today = [TimeZoneInfo]::ConvertTime($now, $zone).Date
    for ($index = 0; $index -lt $store.sessions.Count; $index++) {
        $session = $store.sessions[$index]
        if ([TimeZoneInfo]::ConvertTime($session.start, $zone).Date -eq $today) {
            [pscustomobject]@{ index = $index; session = $session }
        }
    }
}
function Get-TodaySession($store, $zone, [DateTimeOffset]$now, [string]$text) {
    $index = 0
    if (-not [int]::TryParse($text, [ref]$index)) { throw "Expected a session number, got '$text'" }
    $found = @(Get-Today $store $zone $now | Where-Object { $_.index -eq $index })
    if ($found.Count -ne 1) { throw 'That session is no longer today''s; reopen the popup' }
    return $found[0].session
}
# Replaces a session's bounds, both given as HH:MM of today in the reference
# zone; an empty end keeps the session open. Future or overlapping times are
# refused, so an edit cannot count the same minute twice.
function Set-Session($store, $session, $zone, [DateTimeOffset]$now, [string]$startText, [string]$endText) {
    $today = [TimeZoneInfo]::ConvertTime($now, $zone).Date
    $start = ConvertFrom-Clock $startText $today $zone
    $end = $null
    if ($endText.Trim()) {
        $end = ConvertFrom-Clock $endText $today $zone
        if ($end -le $start) { throw 'The end must come after the start' }
        if ($end -gt $now) { throw 'The end is still to come' }
    } elseif ($session.end -or $session -ne (Get-Open $store)) {
        throw 'An end is needed; only the running session can stay open'
    }
    if ($start -gt $now) { throw 'The start is still to come' }
    $until = if ($end) { $end } else { $now }
    foreach ($other in $store.sessions) {
        if ($other -eq $session) { continue }
        $otherEnd = if ($other.end) { $other.end } else { $now }
        if ($start -lt $otherEnd -and $other.start -lt $until) {
            throw ('Overlaps the session from ' + (Format-Clock $other.start $zone 'HH:mm'))
        }
    }
    $session.start = $start
    $session.end = $end
    if (-not $end) { $session.seen = $now }
}
# Returns whether the store changed. `start` and `stop` rather than a toggle,
# so a click on a stale popup cannot invert the state. `edit`, `add` and
# `delete` fix today's history after a forgotten click.
function Invoke-Action($store, [string]$verb, [DateTimeOffset]$now, $zone = $null, [string[]]$arguments = @()) {
    $open = Get-Open $store
    switch ($verb) {
        { $_ -in @('', 'refresh') } {
            if (-not $open) { return $false }
            $open.seen = $now
            return $true
        }
        'start' {
            if ($open) { $open.seen = $now; return $true }
            $store.sessions = @($store.sessions) + , ([ordered]@{ start = $now; end = $null; seen = $now })
            return $true
        }
        'stop' {
            if (-not $open) { return $false }
            $open.end = $now
            return $true
        }
        'edit' {
            if ($arguments.Count -lt 3) { throw 'edit needs a session, a start and an end' }
            $session = Get-TodaySession $store $zone $now $arguments[0]
            Set-Session $store $session $zone $now $arguments[1] $arguments[2]
            return $true
        }
        'add' {
            if ($arguments.Count -lt 2) { throw 'add needs a start and an end' }
            $session = [ordered]@{ start = $now; end = $now; seen = $null }
            Set-Session $store $session $zone $now $arguments[0] $arguments[1]
            $store.sessions = @(@($store.sessions) + , $session | Sort-Object { $_.start })
            return $true
        }
        'delete' {
            if ($arguments.Count -lt 1) { throw 'delete needs a session' }
            $session = Get-TodaySession $store $zone $now $arguments[0]
            $store.sessions = @($store.sessions | Where-Object { $_ -ne $session })
            return $true
        }
        default { throw "Unknown time tracker action: $verb" }
    }
}

# Sessions cut at each midnight of the reference zone, an open one running
# until now.
function Get-Segments($store, $zone, [DateTimeOffset]$now) {
    foreach ($session in $store.sessions) {
        $end = if ($session.end) { $session.end } else { $now }
        $cursor = $session.start
        while ($cursor -lt $end) {
            $day = [TimeZoneInfo]::ConvertTime($cursor, $zone).Date
            $midnight = [DateTimeOffset][TimeZoneInfo]::ConvertTimeToUtc($day.AddDays(1), $zone)
            $stop = if ($end -lt $midnight) { $end } else { $midnight }
            [pscustomobject]@{ day = $day; start = $cursor; end = $stop; ongoing = (-not $session.end) -and $stop -eq $end }
            $cursor = $stop
        }
    }
}
function Get-Seconds($segment) { return [int][Math]::Floor(($segment.end - $segment.start).TotalSeconds) }

function Build-Data($store, $zones, [DateTimeOffset]$now, [string]$failure) {
    $reference = $zones[0].zone
    $today = [TimeZoneInfo]::ConvertTime($now, $reference).Date
    $monday = $today.AddDays(-(([int]$today.DayOfWeek + 6) % 7))
    $friday = $monday.AddDays(4)
    $todaySeconds = 0
    $weekSeconds = 0
    foreach ($segment in @(Get-Segments $store $reference $now)) {
        $seconds = Get-Seconds $segment
        if ($segment.day -eq $today) { $todaySeconds += $seconds }
        if ($segment.day -ge $monday -and $segment.day -le $friday) { $weekSeconds += $seconds }
    }
    $open = Get-Open $store
    $sessions = [object[]]@(foreach ($entry in @(Get-Today $store $reference $now)) {
        [ordered]@{
            index = $entry.index
            start = Format-Clock $entry.session.start $reference 'HH:mm'
            end = $(if ($entry.session.end) { Format-Clock $entry.session.end $reference 'HH:mm' } else { '' })
        }
    })
    $clocks = [object[]]@(foreach ($entry in $zones) {
        $local = [TimeZoneInfo]::ConvertTime($now, $entry.zone)
        [ordered]@{
            name = $entry.name
            second_of_day = [int][Math]::Floor($local.TimeOfDay.TotalSeconds)
            date = $local.ToString('ddd dd MMM', $script:Invariant)
        }
    })
    return [ordered]@{
        icon = $(if ($open) { 'icon-on.svg' } else { 'icon.svg' })
        # Illium counts it up in the bar between two runs.
        timer_seconds = $(if ($open) { $todaySeconds } else { $null })
        working = [bool]$open
        since = $(if ($open) { Format-Clock $open.start $reference 'HH:mm' } else { '' })
        # The view keeps counting between two runs only on a weekday.
        weekday = $today -le $friday
        clocks = $clocks
        # Today's sessions in the reference zone, editable from the popup.
        today = $sessions
        today_seconds = $todaySeconds
        week_seconds = $weekSeconds
        error = $failure
    }
}

function Build-Report($store, $zones, [DateTimeOffset]$now) {
    $reference = $zones[0].zone
    $days = [ordered]@{}
    foreach ($segment in @(Get-Segments $store $reference $now)) {
        $seconds = Get-Seconds $segment
        if ($seconds -le 0) { continue }
        $key = $segment.day.ToString('yyyy-MM-dd', $script:Invariant)
        if (-not $days.Contains($key)) { $days[$key] = [ordered]@{ date = $key; seconds = 0; sessions = @() } }
        $times = [object[]]@(foreach ($entry in $zones) {
            [ordered]@{ zone = $entry.name; start = (Format-Span $segment.start $segment.day $entry.zone); end = (Format-Span $segment.end $segment.day $entry.zone) }
        })
        $days[$key].seconds += $seconds
        $days[$key].sessions = @($days[$key].sessions) + , ([ordered]@{
            # Minutes after the reference midnight, for the day's timeline.
            from = ([TimeZoneInfo]::ConvertTime($segment.start, $reference).DateTime - $segment.day).TotalMinutes
            to = ([TimeZoneInfo]::ConvertTime($segment.end, $reference).DateTime - $segment.day).TotalMinutes
            seconds = $seconds
            ongoing = $segment.ongoing
            times = $times
        })
    }
    foreach ($day in $days.Values) { $day.sessions = [object[]]$day.sessions }
    return [ordered]@{
        generated = Format-Clock $now $reference 'yyyy-MM-dd HH:mm'
        zones = [object[]]@($zones | ForEach-Object { $_.name })
        days = [object[]]@($days.Values)
    }
}
# A time on another date than the reference day carries that weekday.
function Format-Span([DateTimeOffset]$instant, [DateTime]$day, $zone) {
    $local = [TimeZoneInfo]::ConvertTime($instant, $zone)
    $text = $local.ToString('HH:mm', $script:Invariant)
    if ($local.Date -ne $day -and -not ($local.Date -eq $day.AddDays(1) -and $local.TimeOfDay -eq [TimeSpan]::Zero)) {
        $text += ' ' + $local.ToString('ddd', $script:Invariant)
    }
    return $text
}
function Write-Report([string]$template, [string]$path, $report) {
    $json = (ConvertTo-Json -InputObject $report -Depth 8 -Compress).Replace('</', '<\/')
    $html = [IO.File]::ReadAllText($template).Replace('/*DATA*/null', $json)
    [IO.File]::WriteAllText($path, $html, (New-Object Text.UTF8Encoding($false)))
}

if ($FunctionsOnly) { return }
$store = $null
$zones = $null
$now = [DateTimeOffset]::UtcNow
try {
    $zones = Read-Zones $env:ILLIUM_APPLET_ZONES
    $path = Resolve-Store
    $store = Read-Store $path
    $changed = Close-Stale $store $now
    $parts = Read-Action $Action
    $verb = $parts[0]
    $arguments = [string[]]@($parts | Select-Object -Skip 1)
    if ($verb -eq 'report') {
        $directory = Split-Path -Parent $path
        if (-not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
        # Written beside the history, never into the applet folder, whose
        # changes make Illium reload the configuration.
        $report = Join-Path $directory 'report.html'
        Write-Report (Join-Path $PSScriptRoot 'report.html') $report (Build-Report $store $zones $now)
        Start-Process -FilePath $report
    } elseif (Invoke-Action $store $verb $now $zones[0].zone $arguments) {
        $changed = $true
    }
    if ($changed) { Write-Store $path $store }
    $data = Build-Data $store $zones $now ''
} catch {
    $message = $_.Exception.Message
    if (-not $zones) { $zones = Read-Zones '' }
    $data = Build-Data $(if ($store) { $store } else { New-Store }) $zones $now $message
}
ConvertTo-Json -InputObject $data -Depth 5 -Compress
