param([string]$Action = '', [switch]$FunctionsOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)

$script:MaxTasks = 200
$script:MaxLength = 200

function Resolve-Store {
    if ($env:WINARCHY_APPLET_STORE) { return $env:WINARCHY_APPLET_STORE }
    return Join-Path $env:LOCALAPPDATA 'winarchy-applet-collection\todo\tasks.json'
}
# Winarchy sends a single-argument action as plain text and a multi-argument
# one as a JSON array, which keeps quotes, delimiters and Unicode intact.
function Read-Action([string]$text) {
    if (-not $text) { return , @('refresh', '') }
    if ($text.StartsWith('[')) {
        # ConvertFrom-Json emits the array as one object, so it is assigned before being counted.
        $parts = ConvertFrom-Json -InputObject $text
        if ($parts.Count -lt 1 -or $parts.Count -gt 2 -or @($parts | Where-Object { $_ -isnot [string] }).Count) { throw 'Invalid todo action' }
        return , @($parts[0], $(if ($parts.Count -ge 2) { $parts[1] } else { '' }))
    }
    return , @($text, '')
}
function New-Store { return [ordered]@{ version = 1; next_id = 1; tasks = @() } }
function Read-Store([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return New-Store }
    $raw = [IO.File]::ReadAllText($path)
    if (-not $raw.Trim()) { return New-Store }
    # A corrupt store is reported, never silently replaced with an empty list.
    try { $parsed = ConvertFrom-Json -InputObject $raw } catch { throw "Task file unreadable: $path" }
    $tasks = @()
    foreach ($entry in @($parsed.tasks)) {
        if ($null -eq $entry -or -not $entry.id -or $null -eq $entry.text) { continue }
        $tasks += [ordered]@{ id = [string]$entry.id; text = [string]$entry.text; done = [bool]$entry.done }
    }
    $next = 1
    if ($parsed.next_id -as [int]) { $next = [int]$parsed.next_id }
    foreach ($task in $tasks) { if (($task.id -as [int]) -and [int]$task.id -ge $next) { $next = [int]$task.id + 1 } }
    return [ordered]@{ version = 1; next_id = $next; tasks = $tasks }
}
function Write-Store([string]$path, $store) {
    $directory = Split-Path -Parent $path
    if ($directory -and -not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    $store.tasks = [object[]]@($store.tasks)
    $temporary = "$path.$PID.tmp"
    try {
        [IO.File]::WriteAllText($temporary, (ConvertTo-Json -InputObject $store -Depth 5), (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $temporary -Destination $path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}
# Returns the refusal to show, or an empty string; the store is written only
# when the list actually changed.
function Invoke-Action($store, [string]$verb, [string]$argument) {
    switch ($verb) {
        { $_ -in @('', 'refresh') } { return '' }
        'add' {
            $text = $argument.Trim()
            if (-not $text) { return '' }
            if ($text.Length -gt $script:MaxLength) { return "A task is at most $($script:MaxLength) characters" }
            if ($store.tasks.Count -ge $script:MaxTasks) { return "The list holds at most $($script:MaxTasks) tasks" }
            $store.tasks = @($store.tasks) + , ([ordered]@{ id = [string]$store.next_id; text = $text; done = $false })
            $store.next_id = [int]$store.next_id + 1
            return 'changed'
        }
        'toggle' {
            $task = @($store.tasks | Where-Object { $_.id -eq $argument }) | Select-Object -First 1
            # A popup showing a stale list must not act on another task.
            if (-not $task) { return '' }
            $task.done = -not $task.done
            return 'changed'
        }
        'delete' {
            $remaining = @($store.tasks | Where-Object { $_.id -ne $argument })
            if ($remaining.Count -eq $store.tasks.Count) { return '' }
            $store.tasks = $remaining
            return 'changed'
        }
        'clear-completed' {
            $remaining = @($store.tasks | Where-Object { -not $_.done })
            if ($remaining.Count -eq $store.tasks.Count) { return '' }
            $store.tasks = $remaining
            return 'changed'
        }
        default { throw "Unknown todo action: $verb" }
    }
}
function Build-Data($store, [string]$failure) {
    $tasks = @($store.tasks)
    $remaining = @($tasks | Where-Object { -not $_.done }).Count
    $done = $tasks.Count - $remaining
    # The view words the count itself, so an optimistic list is not contradicted
    # by a sentence written before the click.
    return [ordered]@{
        bar_label = $(if ($remaining -gt 0) { [string]$remaining } else { '' })
        remaining = $remaining
        done = $done
        tasks = [object[]]$tasks
        error = $failure
    }
}

if ($FunctionsOnly) { return }
$store = $null
try {
    $path = Resolve-Store
    $parts = Read-Action $Action
    $store = Read-Store $path
    $outcome = Invoke-Action $store $parts[0] $parts[1]
    if ($outcome -eq 'changed') {
        Write-Store $path $store
        $outcome = ''
    }
    $data = Build-Data $store $outcome
} catch {
    # A failed action still shows the list that was read, not an empty one.
    $data = Build-Data $(if ($store) { $store } else { New-Store }) $_.Exception.Message
}
ConvertTo-Json -InputObject $data -Depth 5 -Compress
