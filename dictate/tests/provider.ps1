# Read-only fixtures for the provider's data shaping; never starts the resident.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\dictate.ps1') -FunctionsOnly
function Assert-Equal($actual, $expected, $what) {
    if ("$actual" -ne "$expected") { throw "${what}: expected '$expected', got '$actual'" }
}
$loaded = Build-Data 0 731 ''
Assert-Equal $loaded.state 'loaded' 'loaded state'
Assert-Equal $loaded.bar_label 'on' 'loaded label'
if ($loaded.detail -notmatch '731 MB') { throw 'loaded detail lacks memory' }
$idle = Build-Data 2 21 ''
Assert-Equal $idle.state 'idle' 'idle state'
Assert-Equal $idle.bar_label '' 'idle label'
$stopped = Build-Data 1 0 'boom'
Assert-Equal $stopped.state 'stopped' 'stopped state'
Assert-Equal $stopped.error 'boom' 'error passthrough'
Write-Output 'dictate provider fixtures OK'
