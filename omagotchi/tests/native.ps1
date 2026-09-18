param([Parameter(Mandatory=$true)][string]$Provider)
$ErrorActionPreference = 'Stop'
$Provider = (Resolve-Path $Provider).Path
$directory = Join-Path ([IO.Path]::GetTempPath()) ('omagotchi-test-' + [guid]::NewGuid().ToString('N'))
$previous = $env:WINARCHY_APPLET_STATE_DIR
$env:WINARCHY_APPLET_STATE_DIR = $directory
function Assert($ok, $message) { if (-not $ok) { throw $message } }
function Run([string]$action = 'refresh') {
    $raw = & $Provider $action
    Assert ($LASTEXITCODE -eq 0) "Provider failed: $action"
    return ($raw | ConvertFrom-Json)
}
function Read-State { return (Get-Content -Raw (Join-Path $directory 'state.json') | ConvertFrom-Json) }
function Write-State($state) { [IO.File]::WriteAllText((Join-Path $directory 'state.json'), ($state | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false))) }
try {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $egg = Run
    Assert ($egg.form -eq 'egg' -and $egg.ready) 'First run must create an egg'
    $state = Read-State
    Assert ($state.session -match '^\d+:\d+$') 'Missing parent identity'
    Assert ($state.last_ms -gt 0) 'Missing unbiased uptime'
    $firstSession = $state.session
    $again = Run
    Assert ((Read-State).session -eq $firstSession) 'Same parent must retain session identity'
    Assert ($again.generation -eq 1) 'Refresh must not reset generation'
    $state = Read-State
    $state.form = 'child'; $state.age_minutes = 70; $state.needs = @(80,80,80,80,80)
    Write-State $state
    $fed = Run 'feed'
    Assert ($fed.needs[0] -le 46 -and $fed.animation -eq 'eat') 'Feed must update and persist'
    $washed = Run 'wash 20'
    Assert ($washed.needs[1] -le 61) 'Wash must apply a bounded gesture'
    $played = Run 'play'
    Assert ($played.needs[3] -le 56) 'Room play must relieve boredom'
    $petted = Run 'pet'
    Assert ($petted.needs[4] -le 71) 'Petting must relieve loneliness'
    # A new parent identity or a long provider gap must not add wall-clock age.
    $state = Read-State; $age = $state.age_minutes
    $state.session = 'another-run'; $state.last_ms = 1; Write-State $state
    $null = Run
    Assert ((Read-State).age_minutes -eq $age) 'New session incorrectly aged the pet'
    $state = Read-State; $state.last_ms = 1; Write-State $state
    $null = Run
    Assert ((Read-State).age_minutes -eq $age) 'Long gap incorrectly aged the pet'
    $state = Read-State; $state.form = 'adult_ace'; $state.age_minutes = 1510; Write-State $state
    $new = Run 'farewell 1'
    Assert ($new.form -eq 'egg' -and $new.generation -eq 2) 'Farewell must start the next generation'
    [IO.File]::WriteAllText((Join-Path $directory 'state.json'), 'broken')
    $recovered = Run
    Assert ($recovered.form -eq 'egg' -and $recovered.notice) 'Corrupt save must recover visibly'
    Assert (@(Get-ChildItem $directory -Filter 'state-corrupt-*.json').Count -eq 1) 'Exact corrupt save must be preserved'
    Assert ((Get-Content -Raw (Get-ChildItem $directory -Filter 'state-corrupt-*.json')[0].FullName) -eq 'broken') 'Backup was changed'
    Assert (-not (Test-Path (Join-Path $directory 'state.pending'))) 'Atomic save left a temporary file'
    Write-Output "Native fixtures passed (isolated save, no real pet touched); total $($watch.ElapsedMilliseconds) ms"
} finally {
    $env:WINARCHY_APPLET_STATE_DIR = $previous
    if (Test-Path $directory) { Remove-Item -Recurse -Force $directory }
}
