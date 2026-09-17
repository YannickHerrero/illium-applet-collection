param([string]$Action = '', [switch]$FunctionsOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)

function Resolve-Executable {
    if ($env:WINARCHY_APPLET_EXECUTABLE) { return $env:WINARCHY_APPLET_EXECUTABLE }
    return Join-Path $env:LOCALAPPDATA 'Programs\Winarchy\winarchy-dictate.exe'
}
# The resident is a GUI-subsystem process: its --status answer is its exit code
# (0 loaded, 2 idle, anything else not running), not its console output.
function Invoke-Resident([string]$exe, [string]$verb) {
    $process = Start-Process -FilePath $exe -ArgumentList $verb -WindowStyle Hidden -PassThru -Wait
    return $process.ExitCode
}
function Get-ResidentMemoryMb {
    $process = Get-Process -Name 'winarchy-dictate' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $process) { return 0 }
    return [int][Math]::Round($process.WorkingSet64 / 1MB)
}
function Build-Data([int]$exitCode, [int]$memoryMb, [string]$failure) {
    $state = switch ($exitCode) { 0 { 'loaded' } 2 { 'idle' } default { 'stopped' } }
    $data = [ordered]@{
        state = $state
        bar_label = $(if ($state -eq 'loaded') { 'on' } else { '' })
        title = switch ($state) { 'loaded' { 'Model in memory' } 'idle' { 'Model unloaded' } default { 'Resident not running' } }
        detail = switch ($state) {
            'loaded' { "Ready: holding the dictate key records at once. About $memoryMb MB of RAM." }
            'idle' { "Holding the dictate key loads the model first (about 3 s). Resident uses $memoryMb MB." }
            default { 'Bind "dictate" in keybindings.toml and reload; the daemon starts winarchy-dictate.exe.' }
        }
        error = $failure
    }
    return $data
}

if ($FunctionsOnly) { return }
$failure = ''
try {
    $exe = Resolve-Executable
    if (-not (Test-Path -LiteralPath $exe)) { throw "winarchy-dictate.exe not found at $exe" }
    if ($Action -eq 'load' -or $Action -eq 'unload') {
        $code = Invoke-Resident $exe "--$Action"
        if ($code -ne 0) { $failure = "Request $Action failed (exit $code)" }
    } elseif ($Action -notin @('', 'refresh')) { throw "Unknown dictate action: $Action" }
    $status = Invoke-Resident $exe '--status'
    # Loading takes a few seconds; wait for it so the popup shows the outcome, not the transition.
    $expected = if ($Action -eq 'load') { 0 } elseif ($Action -eq 'unload') { 2 } else { $status }
    for ($i = 0; $i -lt 16 -and $status -ne $expected -and $status -in @(0, 2); $i++) {
        Start-Sleep -Milliseconds 500
        $status = Invoke-Resident $exe '--status'
    }
    $data = Build-Data $status (Get-ResidentMemoryMb) $failure
} catch {
    $data = Build-Data 1 0 $_.Exception.Message
}
$data | ConvertTo-Json -Compress
