# Provider fixtures: zones, sessions, totals, the stale heartbeat, the report
# and the store round-trip. The store is a temporary folder; the real history
# is never touched, and no browser is opened.
$ErrorActionPreference = 'Stop'
$provider = Join-Path $PSScriptRoot '..\time-tracker.ps1'
. $provider -FunctionsOnly
function Assert-Equal($actual, $expected, $what) {
    if ("$actual" -ne "$expected") { throw "${what}: expected '$expected', got '$actual'" }
}
function Assert-Throws([scriptblock]$block, $what) {
    try { & $block } catch { return }
    throw "${what}: expected a failure"
}
function At([string]$text) { return ConvertTo-Instant $text }

$zones = Read-Zones ''
Assert-Equal $zones.Count 2 'default zones'
Assert-Equal $zones[0].name 'Tokyo' 'Tokyo is the reference by default'
Assert-Equal (Read-Zones 'Paris|Romance Standard Time').Count 1 'a single zone'
Assert-Throws { Read-Zones 'Paris' } 'zone without identifier'
Assert-Throws { Read-Zones 'Mars|Olympus Mons Time' } 'unknown zone'

# Monday 26 October 2026, the day after Paris left summer time.
$store = New-Store
Assert-Equal (Invoke-Action $store 'refresh' (At '2026-10-26T00:00:00Z')) 'False' 'refresh while off writes nothing'
Assert-Equal (Invoke-Action $store 'stop' (At '2026-10-26T00:00:00Z')) 'False' 'stop while off writes nothing'
Assert-Equal (Invoke-Action $store 'start' (At '2026-10-26T00:30:00Z')) 'True' 'start'
Assert-Equal (Invoke-Action $store 'start' (At '2026-10-26T00:31:00Z')) 'True' 'a second start only beats'
Assert-Equal $store.sessions.Count 1 'a second start opens nothing'
Assert-Equal (Invoke-Action $store 'refresh' (At '2026-10-26T03:00:00Z')) 'True' 'refresh beats while working'
Assert-Equal (Format-Instant (Get-Open $store).seen) '2026-10-26T03:00:00Z' 'heartbeat'
Assert-Equal (Invoke-Action $store 'stop' (At '2026-10-26T03:45:00Z')) 'True' 'stop'
Assert-Equal (Get-Open $store) '' 'nothing open after stop'
[void](Invoke-Action $store 'start' (At '2026-10-26T05:00:00Z'))
[void](Invoke-Action $store 'stop' (At '2026-10-26T09:00:00Z'))
Assert-Throws { Invoke-Action $store 'pause' (At '2026-10-26T09:00:00Z') } 'unknown verb'

$data = Build-Data $store $zones (At '2026-10-26T10:00:00Z') ''
Assert-Equal $data.working 'False' 'off'
Assert-Equal $data.icon 'icon.svg' 'off icon'
Assert-Equal $data.bar_label '' 'no label while off'
Assert-Equal $data.today_seconds 26100 'today: 09:30 to 12:45 and 14:00 to 18:00 in Tokyo'
Assert-Equal $data.week_seconds 26100 'week so far'
Assert-Equal $data.weekday 'True' 'Monday counts for the week'
Assert-Equal $data.clocks[0].second_of_day 68400 'Tokyo at 19:00'
Assert-Equal $data.clocks[1].second_of_day 39600 'Paris at 11:00, winter time'
Assert-Equal $data.clocks[1].date 'Mon 26 Oct' 'Paris date'

# Tuesday, an open session.
[void](Invoke-Action $store 'start' (At '2026-10-27T00:00:00Z'))
$data = Build-Data $store $zones (At '2026-10-27T01:05:00Z') ''
Assert-Equal $data.working 'True' 'working'
Assert-Equal $data.icon 'icon-on.svg' 'working icon'
Assert-Equal $data.since '09:00' 'since, in Tokyo'
Assert-Equal $data.bar_label '1h05' 'bar label'
Assert-Equal $data.today_seconds 3900 'open session counts until now'
Assert-Equal $data.week_seconds 30000 'week adds Monday'
$json = ConvertTo-Json -InputObject $data -Depth 5 -Compress
if ($json -notmatch '"clocks":\[\{') { throw "clocks must stay a JSON array: $json" }

# The machine slept with the session open: it ends at the last heartbeat.
Assert-Equal (Close-Stale $store (At '2026-10-27T00:04:00Z')) 'False' 'a recent heartbeat keeps the session'
Assert-Equal (Close-Stale $store (At '2026-10-27T00:20:00Z')) 'True' 'a late heartbeat ends it'
Assert-Equal (Format-Instant $store.sessions[2].end) '2026-10-27T00:00:00Z' 'ended at the heartbeat'
Assert-Equal (Close-Stale $store (At '2026-10-27T00:30:00Z')) 'False' 'nothing left to end'

# Across the Tokyo midnight, Tuesday 23:00 to Wednesday 01:00.
$night = New-Store
[void](Invoke-Action $night 'start' (At '2026-10-27T14:00:00Z'))
[void](Invoke-Action $night 'stop' (At '2026-10-27T16:00:00Z'))
$segments = @(Get-Segments $night $zones[0].zone (At '2026-10-28T00:00:00Z'))
Assert-Equal $segments.Count 2 'split at midnight'
Assert-Equal (Get-Seconds $segments[0]) 3600 'Tuesday part'
Assert-Equal $segments[1].day.ToString('yyyy-MM-dd') '2026-10-28' 'Wednesday part'

# The weekend never counts for the week; last week neither.
$weekend = New-Store
[void](Invoke-Action $weekend 'start' (At '2026-10-23T00:00:00Z'))
[void](Invoke-Action $weekend 'stop' (At '2026-10-23T01:00:00Z'))
[void](Invoke-Action $weekend 'start' (At '2026-10-31T00:00:00Z'))
[void](Invoke-Action $weekend 'stop' (At '2026-10-31T02:00:00Z'))
$data = Build-Data $weekend $zones (At '2026-10-31T03:00:00Z') ''
Assert-Equal $data.weekday 'False' 'Saturday'
Assert-Equal $data.today_seconds 7200 'Saturday still counts for the day'
Assert-Equal $data.week_seconds 0 'nor Saturday nor last Friday counts for the week'

# The report: a day per reference date, times in every zone.
$report = Build-Report $store $zones (At '2026-10-27T02:00:00Z')
Assert-Equal $report.days.Count 1 'the zero-length session leaves no day'
$monday = $report.days[0]
Assert-Equal $monday.date '2026-10-26' 'report day'
Assert-Equal $monday.seconds 26100 'report day total'
Assert-Equal $monday.sessions[0].from 570 'starts at 09:30'
Assert-Equal $monday.sessions[0].to 765 'ends at 12:45'
Assert-Equal $monday.sessions[0].times[1].start '01:30' 'Paris start'
Assert-Equal (Format-Span (At '2026-10-25T23:00:00Z') ([DateTime]'2026-10-26') $zones[1].zone) '00:00' 'same day'
Assert-Equal (Format-Span (At '2026-10-25T22:00:00Z') ([DateTime]'2026-10-26') $zones[1].zone) '23:00 Sun' 'previous day is named'
Assert-Equal (Format-Span (At '2026-10-26T15:00:00Z') ([DateTime]'2026-10-26') $zones[0].zone) '00:00' 'the midnight ending a day'
[void](Invoke-Action $weekend 'start' (At '2026-10-31T05:00:00Z'))
$ongoing = Build-Report $weekend $zones (At '2026-10-31T05:30:00Z')
Assert-Equal $ongoing.days[1].sessions[1].ongoing 'True' 'the open session is flagged'

$root = Join-Path ([IO.Path]::GetTempPath()) ("illium-time-tracker-tests-" + [Guid]::NewGuid().ToString('N'))
try {
    $path = Join-Path $root 'nested\sessions.json'
    Write-Store $path $weekend
    $reread = Read-Store $path
    Assert-Equal $reread.sessions.Count 3 'round-trip count'
    Assert-Equal (Format-Instant $reread.sessions[0].start) '2026-10-23T00:00:00Z' 'round-trip start'
    Assert-Equal (Format-Instant $reread.sessions[2].seen) '2026-10-31T05:00:00Z' 'round-trip heartbeat'
    Assert-Equal $reread.sessions[2].end '' 'round-trip open session'
    Assert-Equal (Read-Store (Join-Path $root 'missing.json')).sessions.Count 0 'missing store starts empty'
    Assert-Equal @(Get-ChildItem -LiteralPath (Split-Path -Parent $path) -Filter '*.tmp').Count 0 'no leftover temporary file'
    if ([IO.File]::ReadAllBytes($path)[0] -eq 0xEF) { throw 'the store must be written without a BOM' }
    $single = New-Store
    [void](Invoke-Action $single 'start' (At '2026-10-26T00:00:00Z'))
    Write-Store $path $single
    if ([IO.File]::ReadAllText($path) -notmatch '"sessions":\s*\[') { throw 'one session must stay a JSON array' }

    [IO.File]::WriteAllText($path, '{"version":1,"sessions":[{"start":"yesterday","end":null}]}')
    Assert-Throws { Read-Store $path } 'corrupt store'
    Assert-Equal ([IO.File]::ReadAllText($path)) '{"version":1,"sessions":[{"start":"yesterday","end":null}]}' 'a corrupt store is left untouched'

    $page = Join-Path $root 'report.html'
    $sample = Build-Report $store $zones (At '2026-10-27T02:00:00Z')
    $sample.zones = [object[]]@('Tokyo</script>', 'Paris')
    Write-Report (Join-Path $PSScriptRoot '..\report.html') $page $sample
    $html = [IO.File]::ReadAllText($page)
    if ($html.Contains('/*DATA*/null')) { throw 'the report data was not injected' }
    if ($html.Contains('Tokyo</script>')) { throw 'the report data must not close its script' }

    # Whole-script run, the way Illium invokes it.
    $env:ILLIUM_APPLET_STORE = Join-Path $root 'live.json'
    $run = {
        param($action)
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = 'powershell.exe'
        $info.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$provider`" $action"
        $info.UseShellExecute = $false
        $info.RedirectStandardOutput = $true
        $info.StandardOutputEncoding = New-Object Text.UTF8Encoding($false)
        $child = [Diagnostics.Process]::Start($info)
        $output = $child.StandardOutput.ReadToEnd()
        $child.WaitForExit()
        if ($child.ExitCode -ne 0) { throw "provider exited with $($child.ExitCode)" }
        return $output | ConvertFrom-Json
    }
    $first = & $run ''
    Assert-Equal $first.working 'False' 'live off'
    Assert-Equal $first.clocks.Count 2 'live clocks'
    Assert-Equal (& $run 'start').working 'True' 'live start'
    Assert-Equal (& $run 'refresh').working 'True' 'live refresh'
    $stopped = & $run 'stop'
    Assert-Equal $stopped.working 'False' 'live stop'
    Assert-Equal $stopped.error '' 'live run without error'
    Assert-Equal (Read-Store $env:ILLIUM_APPLET_STORE).sessions.Count 1 'live history'
    Assert-Equal (& $run 'pause').error 'Unknown time tracker action: pause' 'live failure is shown'
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\ILLIUM_APPLET_STORE -ErrorAction SilentlyContinue
}
Write-Output 'time tracker provider fixtures OK'
