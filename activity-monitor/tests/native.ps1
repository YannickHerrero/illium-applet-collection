param([Parameter(Mandatory=$true)][string]$Collector, [string]$Sleeper = '')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$directory=Join-Path $env:TEMP ('activity-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $directory | Out-Null
$previous=$env:WINARCHY_APPLET_CACHE_PATH
$env:WINARCHY_APPLET_CACHE_PATH=Join-Path $directory 'cache'
$exe=Join-Path $directory 'activity-monitor.exe'
Copy-Item -LiteralPath $Collector -Destination $exe
$child=$null
function Assert($condition,$message) { if(-not $condition) { throw $message } }
function Invoke-Collector([string]$argument='') {
    # Use the same no-console, direct executable model as Winarchy. Quote one
    # argv entry, including backslashes before quotes, without invoking a shell.
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$exe; $start.UseShellExecute=$false; $start.CreateNoWindow=$true
    $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
    $start.StandardOutputEncoding=New-Object Text.UTF8Encoding($false)
    if($argument) { $start.Arguments='"'+[regex]::Replace($argument,'(\\*)"','$1$1\"')+'"' }
    $p=New-Object Diagnostics.Process; $p.StartInfo=$start
    $watch=[Diagnostics.Stopwatch]::StartNew()
    try {
        Assert ($p.Start()) 'Could not start collector'
        $stdout=$p.StandardOutput.ReadToEndAsync();$stderr=$p.StandardError.ReadToEndAsync()
        if(-not $p.WaitForExit(15000)) { $p.Kill();throw 'Collector exceeded 15 seconds' }
        Assert ($p.ExitCode -eq 0) ($stderr.Result)
        Assert ([Text.Encoding]::UTF8.GetByteCount($stdout.Result) -lt 61440) 'Output is too large'
        $watch.Stop()
        $data=$stdout.Result|ConvertFrom-Json
        Write-Host "Collector wall=$($watch.ElapsedMilliseconds)ms internal=$($data.collector_ms)ms"
        return $data
    } finally { $p.Dispose() }
}
function Action($verb,$query='',$sort='cpu',$target='') { return (ConvertTo-Json -InputObject @($verb,$query,$sort,$target) -Compress) }
try {
    $first=Invoke-Collector
    Assert ($first.cpu -eq '—') 'First CPU reading must be unavailable, not fabricated'
    Assert ($first.ram -match '^\d+%$') 'RAM must be measured'
    Start-Sleep -Seconds 2
    $second=Invoke-Collector 'sample'
    Assert ($second.cpu -match '^\d+%$') 'CPU needs two samples'
    Assert ($second.processes.Count -gt 0 -and $second.processes.Count -le 80) 'Bounded process rows'
    Assert ($second.disk_name -eq 'Physical disk 0' -or $second.disk_name -eq 'Disk unavailable') 'Disk scope must be explicit'
    Start-Sleep -Seconds 2
    $third=Invoke-Collector 'sample'
    Assert ($third.cpu_chart.Count -gt 0) 'Graph segments should be available'
    $cache=Join-Path $env:WINARCHY_APPLET_CACHE_PATH 'state.json'
    $before=Get-Content -LiteralPath $cache -Raw|ConvertFrom-Json
    $null=Invoke-Collector
    $after=Get-Content -LiteralPath $cache -Raw|ConvertFrom-Json
    Assert ($before.processes_at -eq $after.processes_at -and $before.raw.io_at -eq $after.raw.io_at) 'Closed mode must not sample processes or I/O'
    $filtered=Invoke-Collector (Action 'sample' 'zzzz-no-process-match' 'name')
    Assert ($filtered.processes.Count -eq 0) 'Search should filter all rows'
    $filtered=Invoke-Collector (Action 'sample' 'a"b\c' 'name')
    Assert ($filtered.processes.Count -eq 0) 'Quoted action must remain one argument'
    Set-Content -LiteralPath $cache -Value '{broken'
    $recovered=Invoke-Collector
    Assert ($recovered.cpu -eq '—') 'Corrupt state must recover without a fake CPU value'

    if($Sleeper) {
        # Only this disposable test child is ever terminated. Unicode validates
        # native enumeration, JSON output and filtering without renaming real apps.
        $fixture=Join-Path $directory 'activity-fixture-é.exe'
        Copy-Item -LiteralPath $Sleeper -Destination $fixture
        $start=New-Object Diagnostics.ProcessStartInfo
        $start.FileName=$fixture;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
        $child=[Diagnostics.Process]::Start($start)
        $found=Invoke-Collector (Action 'sample' ([string]$child.Id))
        $row=@($found.processes|Where-Object {$_.pid -eq [string]$child.Id})[0]
        Assert ($row.name -eq 'activity-fixture-é.exe' -and $row.can_end) 'Fixture identity/Unicode not preserved'
        $parts=$row.key.Split(':'); $wrong=$parts[0]+':'+([long]$parts[1]+1).ToString()
        # Simulate PID reuse in this private test cache: the adapter must reject
        # the stale creation time even though the cached row says it is safe.
        $stale=Get-Content -LiteralPath $cache -Raw|ConvertFrom-Json
        foreach($process in $stale.processes) { if($process.pid -eq $child.Id) { $process.born=[long]$parts[1]+1 } }
        [IO.File]::WriteAllText($cache,($stale|ConvertTo-Json -Depth 10 -Compress),(New-Object Text.UTF8Encoding($false)))
        $bad=Invoke-Collector (Action 'end' '' 'cpu' $wrong)
        Assert (-not $child.HasExited) 'Wrong creation time must never terminate a process'
        Assert ($bad.notice -match 'expired|changed') 'Rejected identity must be explained'
        $ended=Invoke-Collector (Action 'end' '' 'cpu' $row.key)
        Assert ($child.WaitForExit(3000)) 'Selected disposable fixture should be terminated'
        Assert ($ended.notice -match '^Ended activity-fixture') 'Termination result missing'
        Write-Output 'Disposable-child termination fixtures passed.'
    }
    Write-Output 'Native Activity Monitor fixtures passed.'
} finally {
    if($child) { if(-not $child.HasExited) {$child.Kill();$child.WaitForExit()};$child.Dispose() }
    $env:WINARCHY_APPLET_CACHE_PATH=$previous
    Remove-Item -LiteralPath $directory -Recurse -Force
}
