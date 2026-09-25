# Provider fixtures: action parsing, list mutations and the store round-trip.
# The store is a temporary folder; the real task file is never touched.
$ErrorActionPreference = 'Stop'
$provider = Join-Path $PSScriptRoot '..\todo.ps1'
. $provider -FunctionsOnly
function Assert-Equal($actual, $expected, $what) {
    if ("$actual" -ne "$expected") { throw "${what}: expected '$expected', got '$actual'" }
}
function Assert-Throws([scriptblock]$block, $what) {
    try { & $block } catch { return }
    throw "${what}: expected a failure"
}

Assert-Equal (Read-Action '')[0] 'refresh' 'empty action'
Assert-Equal (Read-Action 'refresh')[0] 'refresh' 'plain action'
$parsed = Read-Action '["add","buy [milk], \"today\""]'
Assert-Equal $parsed[0] 'add' 'json verb'
Assert-Equal $parsed[1] 'buy [milk], "today"' 'json argument keeps delimiters'
Assert-Throws { Read-Action '["add","a","b"]' } 'over-long action'

$store = New-Store
Assert-Equal (Invoke-Action $store 'add' '  Hello from Omado  ') 'changed' 'add'
Assert-Equal $store.tasks[0].text 'Hello from Omado' 'added text is trimmed'
Assert-Equal $store.tasks[0].id '1' 'first id'
Assert-Equal (Invoke-Action $store 'add' 'Complete Creational patterns') 'changed' 'second add'
Assert-Equal (Invoke-Action $store 'add' '   ') '' 'blank add is ignored'
Assert-Equal (Invoke-Action $store 'add' ('x' * 201)) 'A task is at most 200 characters' 'over-long text'
Assert-Equal $store.tasks.Count 2 'task count'

Assert-Equal (Invoke-Action $store 'toggle' '2') 'changed' 'toggle'
Assert-Equal $store.tasks[1].done 'True' 'toggled done'
Assert-Equal (Invoke-Action $store 'toggle' '99') '' 'unknown id is ignored'
Assert-Equal (Invoke-Action $store 'delete' '99') '' 'unknown delete is ignored'
Assert-Throws { Invoke-Action $store 'wipe' '' } 'unknown verb'

$data = Build-Data $store ''
Assert-Equal $data.bar_label '1' 'bar label counts what remains'
Assert-Equal $data.remaining 1 'remaining'
Assert-Equal $data.done 1 'done'
$json = ConvertTo-Json -InputObject $data -Depth 5 -Compress
if ($json -notmatch '"tasks":\[\{') { throw "tasks must stay a JSON array: $json" }
Assert-Equal (Build-Data (New-Store) '').remaining 0 'empty remaining'
Assert-Equal (Build-Data (New-Store) '').bar_label '' 'empty bar label'

Assert-Equal (Invoke-Action $store 'clear-completed' '') 'changed' 'clear completed'
Assert-Equal $store.tasks.Count 1 'clear leaves what remains'
Assert-Equal (Invoke-Action $store 'clear-completed' '') '' 'clear is idempotent'
Assert-Equal (Build-Data $store '').remaining 1 'remaining after clear'
Assert-Equal (Invoke-Action $store 'toggle' '1') 'changed' 'toggle the last one'
Assert-Equal (Build-Data $store '').remaining 0 'nothing left open'

$root = Join-Path ([IO.Path]::GetTempPath()) ("illium-todo-tests-" + [Guid]::NewGuid().ToString('N'))
try {
    $path = Join-Path $root 'nested\tasks.json'
    Write-Store $path $store
    $reread = Read-Store $path
    Assert-Equal $reread.tasks.Count 1 'round-trip count'
    Assert-Equal $reread.tasks[0].text 'Hello from Omado' 'round-trip text'
    Assert-Equal $reread.tasks[0].done 'True' 'round-trip flag'
    Assert-Equal $reread.next_id $store.next_id 'round-trip next id'
    Assert-Equal (Read-Store (Join-Path $root 'missing.json')).tasks.Count 0 'missing store starts empty'
    Assert-Equal @(Get-ChildItem -LiteralPath (Split-Path -Parent $path) -Filter '*.tmp').Count 0 'no leftover temporary file'

    $unicode = New-Store
    [void](Invoke-Action $unicode 'add' 'Écrire la rétrospective — 日本語')
    Write-Store $path $unicode
    Assert-Equal (Read-Store $path).tasks[0].text 'Écrire la rétrospective — 日本語' 'unicode round-trip'
    $bytes = [IO.File]::ReadAllBytes($path)
    if ($bytes[0] -eq 0xEF) { throw 'the store must be written without a BOM' }

    [IO.File]::WriteAllText($path, 'not json at all')
    Assert-Throws { Read-Store $path } 'corrupt store'
    Assert-Equal ([IO.File]::ReadAllText($path)) 'not json at all' 'a corrupt store is left untouched'

    # A store whose next_id lags behind its ids must not reuse one.
    [IO.File]::WriteAllText($path, '{"version":1,"next_id":1,"tasks":[{"id":"7","text":"kept","done":false}]}')
    $recovered = Read-Store $path
    Assert-Equal $recovered.next_id 8 'next id follows the highest id'
    [void](Invoke-Action $recovered 'add' 'fresh')
    Assert-Equal $recovered.tasks[1].id '8' 'new id after recovery'

    # Whole-script run, the way Illium invokes it.
    $env:ILLIUM_APPLET_STORE = Join-Path $root 'live.json'
    # Illium spawns the provider through the Windows API with a command line
    # it escapes itself; PowerShell 5.1's own native-command call mangles quoted
    # JSON, so the child is started the same way Illium starts it.
    $run = {
        param($action)
        $quoted = '"' + $action.Replace('"', '\"') + '"'
        $info = New-Object Diagnostics.ProcessStartInfo
        $info.FileName = 'powershell.exe'
        $info.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$provider`" $quoted"
        $info.UseShellExecute = $false
        $info.RedirectStandardOutput = $true
        $info.StandardOutputEncoding = New-Object Text.UTF8Encoding($false)
        $child = [Diagnostics.Process]::Start($info)
        $output = $child.StandardOutput.ReadToEnd()
        $child.WaitForExit()
        if ($child.ExitCode -ne 0) { throw "provider exited with $($child.ExitCode)" }
        return $output
    }
    Assert-Equal (& $run '' | ConvertFrom-Json).tasks.Count 0 'live empty'
    Assert-Equal (& $run '["add","Hello from Omado"]' | ConvertFrom-Json).remaining 1 'live add'
    $second = & $run '["add","Complete Creational patterns"]' | ConvertFrom-Json
    Assert-Equal $second.tasks.Count 2 'live second add'
    Assert-Equal (& $run '["toggle","2"]' | ConvertFrom-Json).remaining 1 'live toggle'
    Assert-Equal (& $run '["delete","1"]' | ConvertFrom-Json).remaining 0 'live delete'
    $cleared = & $run '["clear-completed"]' | ConvertFrom-Json
    Assert-Equal $cleared.tasks.Count 0 'live clear'
    Assert-Equal $cleared.remaining 0 'live count after clear'
    Assert-Equal $cleared.error '' 'live run without error'
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\ILLIUM_APPLET_STORE -ErrorAction SilentlyContinue
}
Write-Output 'todo provider fixtures OK'
