# Windows-only integration tests with synthetic caches and unsupported providers. Never opens Outlook.
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { 'Skipped: Windows PowerShell is required.'; exit 0 }
. "$PSScriptRoot\..\lib.ps1"
function Assert($Condition, $Message) { if (-not $Condition) { throw $Message } }
$originalLocal = $env:LOCALAPPDATA
$temp = Join-Path ([IO.Path]::GetTempPath()) ('agenda-fixture-' + [guid]::NewGuid().ToString('N'))
$runtime = Join-Path $temp 'Winarchy\calendar-agenda'
[void][IO.Directory]::CreateDirectory($runtime)
try {
    $env:LOCALAPPDATA = $temp
    $now = Get-Date; $window = Get-AgendaWindow $now
    $connections = @([pscustomobject]@{id='fresh';name='Fresh';provider='fixture-unsupported';enabled=$true}, [pscustomobject]@{id='stale';name='Stale';provider='fixture-unsupported';enabled=$true})
    $config = @{version=1;connections=$connections}
    Write-AgendaJson (Join-Path $runtime 'connections.json') $config
    foreach ($connection in $connections) {
        $fetched = [datetime]::UtcNow
        if ($connection.id -eq 'stale') { $fetched = $fetched.AddHours(-1) }
        $snapshot = @{version=1;connection_id=$connection.id;fetched_at=$fetched.ToString('o');range_start=$window.start.ToString('yyyy-MM-dd');range_end=$window.end.ToString('yyyy-MM-dd');truncated=$false;calendars=@(@{id='cal';name='Fixture'});events=@(@{id='event';calendar_id='cal';title='Synthetic';location='';start=$now.ToString('yyyy-MM-dd');end=$now.AddDays(1).ToString('yyyy-MM-dd');all_day=$true;meeting_url=''})}
        Write-AgendaJson (Join-Path $runtime ('cache-' + $connection.id + '.json')) @{signature=(Get-AgendaKey 'config' (ConvertTo-Json $connection -Compress -Depth 8));snapshot=$snapshot}
    }
    function Invoke-FixtureAgenda([string]$Action = '') {
        $raw = & "$PSHOME\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\..\agenda.ps1" $Action
        Assert ($LASTEXITCODE -eq 0) 'agenda process failed'
        return ($raw | ConvertFrom-Json)
    }
    $data = Invoke-FixtureAgenda
    Assert ($data.events.Count -eq 2) 'failed refresh must preserve its matching cached range'
    Assert (-not $data.statuses[0].stale -and $data.statuses[1].stale) 'fresh and failed sources isolated'
    $color = $data.calendars[0].color
    $filtered = Invoke-FixtureAgenda ('toggle ' + $data.calendars[1].key)
    Assert ($filtered.events.Count -eq 1) 'cached filter'
    $persisted = Invoke-FixtureAgenda
    Assert (-not $persisted.calendars[1].visible) 'visibility persisted across provider processes'
    # A corrupt source cache must not discard the other source.
    Write-AgendaJson (Join-Path $runtime 'cache-stale.json') @{unexpected='fixture'}
    $partial = Invoke-FixtureAgenda
    Assert ($partial.events.Count -eq 1 -and $partial.calendars.Count -eq 1) 'corrupt cache isolated'
    Assert ($partial.calendars[0].color -eq $color) 'source color stable'
    $next = Invoke-FixtureAgenda 'month 1'
    Assert ($next.events.Count -eq 0 -and $next.calendars.Count -eq 0) 'wrong-range cache never displayed'
    $connections[1].enabled = $false
    Write-AgendaJson (Join-Path $runtime 'connections.json') $config
    $disabled = Invoke-FixtureAgenda 'today'
    Assert ($disabled.statuses.Count -eq 1 -and -not (Test-Path (Join-Path $runtime 'cache-stale.json'))) 'disabled source cache removed'
    'Orchestration fixture tests passed.'
} finally {
    $env:LOCALAPPDATA = $originalLocal
    Remove-Item -LiteralPath $temp -Recurse -Force
}
