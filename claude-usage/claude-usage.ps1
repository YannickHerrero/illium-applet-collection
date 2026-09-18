param([string]$Action = '', [switch]$FunctionsOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)

function Test-Number($value) {
    if ($value -isnot [int] -and $value -isnot [long] -and $value -isnot [double] -and $value -isnot [decimal]) { return $false }
    return -not ([double]::IsNaN($value) -or [double]::IsInfinity($value))
}
function Remaining([double]$seconds) {
    if ($seconds -le 0) { return 'Window reset; awaiting update' }
    $minutes = [long][Math]::Ceiling($seconds / 60)
    if ($minutes -ge 1440) { return "Resets in $([Math]::Floor($minutes / 1440))d $([Math]::Floor(($minutes % 1440) / 60))h" }
    if ($minutes -ge 60) { return "Resets in $([Math]::Floor($minutes / 60))h $($minutes % 60)m" }
    return "Resets in ${minutes}m"
}
function Build-Data($snapshot, [long]$now, $fable = $null) {
    $data = [ordered]@{ bar_label = '—'; message = 'Waiting for Claude Code usage data'; updated = 'No quota snapshot yet'; windows = @(); error = '' }
    if ($null -eq $snapshot -and $null -eq $fable) { return $data }
    if ($null -ne $snapshot -and ($snapshot.schema -ne 1 -or $snapshot.source -ne 'claude-code-statusline')) { throw 'Unsupported quota snapshot format' }
    $latest = 0
    foreach ($definition in @(@('five_hour', 'Session · 5h', 18000), @('seven_day', 'Weekly', 604800), @('fable', 'Fable · Weekly', 604800))) {
        $key, $title, $duration = $definition
        $item = if ($key -eq 'fable') {
            if ($null -ne $fable -and $fable.schema -eq 1 -and $fable.source -eq 'claude-code-usage') { $fable.window } else { $null }
        } else { $snapshot.windows.$key }
        if ($null -eq $item -or -not (Test-Number $item.used_percentage) -or -not (Test-Number $item.resets_at) -or -not (Test-Number $item.received_at)) { continue }
        $used = [double]$item.used_percentage
        $reset = [double]$item.resets_at
        $received = [double]$item.received_at
        if ($used -lt 0 -or $used -gt 100 -or $reset -gt $now + 691200 -or $received -gt $now + 60 -or $received -lt 0) { continue }
        $age = [Math]::Max(0, $now - $received)
        $fresh = $age -le 600 -and $reset -gt $now
        $percentage = $used.ToString('0.#', [Globalization.CultureInfo]::InvariantCulture) + '%'
        $elapsed = [Math]::Max(0, [Math]::Min(100, (1 - ($reset - $now) / $duration) * 100))
        $difference = [int][Math]::Round($used - $elapsed)
        $pace = if (-not $fresh) { 'Last known quota' } elseif ([Math]::Abs($difference) -le 3) { 'On linear pace' } elseif ($difference -gt 0) { "$difference pts ahead" } else { "$(-$difference) pts under" }
        $row = [ordered]@{ label = $title; value = $used; used = $(if ($fresh) { $percentage } else { "~$percentage" }); resets = (Remaining ($reset - $now)); reset_time = [DateTimeOffset]::FromUnixTimeSeconds([long]$reset).ToLocalTime().ToString('ddd HH:mm', [Globalization.CultureInfo]::InvariantCulture); pace = $pace; pace_value = $elapsed; fresh = $fresh; ahead = $fresh -and $difference -gt 3 }
        $data.windows += $row
        $latest = [Math]::Max($latest, $received)
        if ($key -eq 'five_hour') {
            if ($reset -le $now) { $data.message = 'Session window reset; waiting for Claude Code' }
            elseif ($fresh) { $data.bar_label = $percentage; $data.message = 'From active Claude Code sessions on WSL' }
            else { $data.bar_label = $percentage; $data.message = 'Stale quota; waiting for a new CLI update' }
        }
    }
    if ($latest -gt 0) {
        $ageMinutes = [Math]::Floor([Math]::Max(0, $now - $latest) / 60)
        $time = [DateTimeOffset]::FromUnixTimeSeconds([long]$latest).ToLocalTime().ToString('HH:mm')
        $data.updated = "Last CLI update $time · ${ageMinutes}m ago"
    }
    return $data
}

function Read-Snapshot([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    # Share delete access so WSL can atomically replace a snapshot while we read.
    $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try {
        if ($stream.Length -gt 8192) { throw 'Quota snapshot exceeds 8 KiB' }
        $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8)
        try { return ($reader.ReadToEnd() | ConvertFrom-Json) } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
}

if ($FunctionsOnly) { return }
try {
    if ($Action -eq 'open') { Start-Process 'https://claude.ai/settings/usage' }
    elseif ($Action -notin @('', 'refresh')) { throw 'Unknown Claude usage action' }
    $cache = if ($env:WINARCHY_APPLET_CACHE_PATH) { $env:WINARCHY_APPLET_CACHE_PATH } else { Join-Path $env:LOCALAPPDATA 'Winarchy/cache/claude-usage/snapshot.json' }
    $snapshot = Read-Snapshot $cache
    # An unavailable experimental source must never break the main two quotas.
    $fable = $null
    try { $fable = Read-Snapshot (Join-Path (Split-Path $cache) 'fable.json') } catch { }
    $data = Build-Data $snapshot ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) $fable
} catch {
    $data = Build-Data $null 0
    $data.message = 'Quota snapshot unavailable'
    $data.error = $_.Exception.Message
}
$data | ConvertTo-Json -Compress -Depth 5
