param([string]$Action = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
. "$PSScriptRoot\lib.ps1"
if (-not $env:LOCALAPPDATA) { throw 'Windows LOCALAPPDATA is required.' }
$runtime = Join-Path $env:LOCALAPPDATA 'Winarchy\calendar-agenda'
[void][IO.Directory]::CreateDirectory($runtime)
$mutex = New-Object Threading.Mutex($false, ('Local\WinarchyAgenda-' + (Get-AgendaKey 'runtime' $runtime)))
$locked = $false
$jobs = @()
try {
    try { $locked = $mutex.WaitOne(100) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw 'Agenda is already refreshing.' }
    $configPath = Join-Path $runtime 'connections.json'
    $config = Read-AgendaJson $configPath
    if ($null -eq $config) {
        $config = [pscustomobject]@{ version = 1; connections = @([pscustomobject]@{ id = 'outlook-default'; name = 'Outlook'; provider = 'outlook'; enabled = $true }) }
        Write-AgendaJson $configPath $config
    }
    if ($config.version -ne 1 -or @($config.connections).Count -gt 8) { throw 'Invalid agenda configuration (version 1, at most 8 connections).' }
    $ids = @{}
    foreach ($connection in $config.connections) {
        if ($connection.id -notmatch '^[a-zA-Z0-9_-]{1,48}$' -or $ids.ContainsKey($connection.id)) { throw 'Connection IDs must be unique letters, digits, underscores or hyphens.' }
        $ids[$connection.id] = $true
    }
    $connections = @($config.connections | Where-Object { $_.enabled })
    $now = Get-Date
    $statePath = Join-Path $runtime 'state.json'
    $state = Read-AgendaJson $statePath
    if ($null -eq $state) { $state = [pscustomobject]@{ month = $now.ToString('yyyy-MM'); day = $now.ToString('yyyy-MM-dd'); hidden = @() } }
    $force = $Action -eq 'refresh'
    $joinKey = ''
    switch -Regex ($Action) {
        '^month (-?1)$' {
            $month = [datetime]::ParseExact($state.month, 'yyyy-MM', [cultureinfo]::InvariantCulture).AddMonths([int]$Matches[1])
            $state.month = $month.ToString('yyyy-MM'); $state.day = $month.ToString('yyyy-MM-dd')
        }
        '^show-all$' { $state.hidden = @() }
        '^today$' { $state.month = $now.ToString('yyyy-MM'); $state.day = $now.ToString('yyyy-MM-dd') }
        '^day (\d{4}-\d{2}-\d{2})$' {
            $date = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd', [cultureinfo]::InvariantCulture)
            $state.day = $date.ToString('yyyy-MM-dd')
        }
        '^toggle ([a-f0-9]{64})$' {
            $key = $Matches[1]
            if ($key -in @($state.hidden)) { $state.hidden = @($state.hidden | Where-Object { $_ -ne $key }) }
            else { $state.hidden = @($state.hidden) + $key }
        }
        '^join ([a-f0-9]{64})$' { $joinKey = $Matches[1] }
        '^(|refresh)$' { }
        default { throw 'Unknown agenda action.' }
    }
    Write-AgendaJson $statePath $state
    $window = Get-AgendaWindow ([datetime]::ParseExact($state.month, 'yyyy-MM', [cultureinfo]::InvariantCulture))
    $start = $window.start.ToString('yyyy-MM-dd'); $end = $window.end.ToString('yyyy-MM-dd')
    $snapshots = @{}; $statuses = @(); $errors = @{}
    # Only one month's range is kept per connection. Remove disabled/deleted caches and old failed-run files.
    foreach ($file in Get-ChildItem -LiteralPath $runtime -Filter 'cache-*.json') {
        $id = $file.BaseName.Substring(6)
        if ($id -notin @($connections | ForEach-Object { $_.id }) -or $file.LastWriteTimeUtc -lt [datetime]::UtcNow.AddDays(-7)) { Remove-Item -LiteralPath $file.FullName -Force }
    }
    Get-ChildItem -LiteralPath $runtime -Filter 'job-*' | Where-Object { $_.LastWriteTimeUtc -lt [datetime]::UtcNow.AddMinutes(-5) } | Remove-Item -Force
    $watch = [Diagnostics.Stopwatch]::StartNew()
    foreach ($connection in $connections) {
        $cachePath = Join-Path $runtime ('cache-' + $connection.id + '.json')
        $signature = Get-AgendaKey 'config' (ConvertTo-Json $connection -Compress -Depth 8)
        $fresh = $false
        try {
            $cache = Read-AgendaJson $cachePath
            if ($null -ne $cache -and $cache.signature -eq $signature -and $cache.snapshot.version -eq 1) {
                $snapshot = $cache.snapshot
                if ($snapshot.range_start -eq $start -and $snapshot.range_end -eq $end) {
                    $fresh = ([datetime]::UtcNow - [datetimeoffset]::Parse($snapshot.fetched_at).UtcDateTime).TotalMinutes -lt 5
                    $snapshots[$connection.id] = $snapshot
                }
            }
        } catch { $snapshots.Remove($connection.id); $fresh = $false }
        $snapshot = $snapshots[$connection.id]
        # UI-only actions don't trigger network/COM refreshes when a matching cache exists.
        if (($fresh -and -not $force) -or (($Action -match '^(toggle|day|join) ' -or $Action -eq 'show-all') -and $null -ne $snapshot)) { continue }
        $prefix = Join-Path $runtime ('job-' + [guid]::NewGuid().ToString('N'))
        $request = "$prefix-request.json"; $result = "$prefix-result.json"
        Write-AgendaJson $request @{ connection = $connection; start = $start; end = $end }
        $process = New-Object Diagnostics.Process
        $process.StartInfo.FileName = Join-Path $PSHOME 'powershell.exe'
        $process.StartInfo.Arguments = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + "$PSScriptRoot\worker.ps1" + '" -Request "' + $request + '" -Result "' + $result + '"'
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        try {
            [void]$process.Start()
            $jobs += @{ process = $process; request = $request; result = $result; connection = $connection; signature = $signature; cache = $cachePath }
        } catch {
            $process.Dispose(); Remove-Item -LiteralPath $request -Force
            $errors[$connection.id] = 'Calendar worker could not start.'
        }
    }
    # Parallel sources share one deadline, comfortably below Winarchy's 20 second limit.
    foreach ($job in $jobs) {
        $remaining = [Math]::Max(0, 11000 - [int]$watch.ElapsedMilliseconds)
        $finished = $job.process.WaitForExit($remaining)
        if (-not $finished) {
            try { if (-not $job.process.HasExited) { $job.process.Kill() } } catch { }
            $errors[$job.connection.id] = 'Calendar timed out. Check Outlook and its security prompts.'
            continue
        }
        $result = $null
        try { $result = Read-AgendaJson $job.result } catch { }
        if ($null -ne $result -and $result.ok) {
            $snapshots[$job.connection.id] = $result.snapshot
            Write-AgendaJson $job.cache @{ signature = $job.signature; snapshot = $result.snapshot }
        } else { $errors[$job.connection.id] = 'Calendar unavailable. Check Outlook and its security prompts.' }
    }
    foreach ($connection in $connections) {
        $snapshot = $snapshots[$connection.id]
        $message = 'No cached events'; $stale = $true
        if ($null -ne $snapshot) {
            $stamp = [datetimeoffset]::Parse($snapshot.fetched_at).LocalDateTime
            $message = 'Read locally ' + $stamp.ToString('MMM d HH:mm', [cultureinfo]'en-US')
            $stale = ($now - $stamp).TotalMinutes -ge 5
            if ($snapshot.truncated) { $message += ' - results limited' }
        }
        if ($errors.ContainsKey($connection.id)) { $message = $errors[$connection.id] + ' ' + $message; $stale = $true }
        $statuses += @{ name = (Limit-AgendaText $connection.name 50); message = $message; stale = $stale }
    }
    if ($joinKey) {
        foreach ($connection in $connections) {
            $snapshot = $snapshots[$connection.id]
            if ($null -eq $snapshot) { continue }
            foreach ($event in $snapshot.events) {
                if ((Get-AgendaKey $connection.id $event.id) -eq $joinKey -and (Test-AgendaMeetingUrl $event.meeting_url)) {
                    # Use the Windows URL handler without a shell or command interpolation.
                    $info = New-Object Diagnostics.ProcessStartInfo
                    $info.FileName = $event.meeting_url; $info.UseShellExecute = $true
                    [void][Diagnostics.Process]::Start($info)
                }
            }
        }
    }
    $view = ConvertTo-AgendaView $snapshots $connections $state $statuses
    $json = ConvertTo-Json $view -Depth 16 -Compress
    while ([Text.Encoding]::UTF8.GetByteCount($json) -gt 60000 -and $view.events.Count -gt 0) {
        $view.events = @($view.events | Select-Object -SkipLast 1); $view.more++
        $json = ConvertTo-Json $view -Depth 16 -Compress
    }
    if ([Text.Encoding]::UTF8.GetByteCount($json) -gt 60000) { throw 'Too many calendars to display. Disable a connection.' }
    [Console]::WriteLine($json)
} catch {
    # Do not expose private configuration, event values or raw COM exception messages.
    [Console]::Error.WriteLine('Calendar Agenda failed. Check its private configuration or reset its cache.')
    exit 1
} finally {
    foreach ($job in $jobs) {
        try { if (-not $job.process.HasExited) { $job.process.Kill() }; [void]$job.process.WaitForExit(500) } catch { }
        $job.process.Dispose()
        foreach ($path in @($job.request, $job.result)) { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue } }
    }
    if ($locked) { [void]$mutex.ReleaseMutex() }; $mutex.Dispose()
}
