param([Parameter(Mandatory=$true)][string]$Request, [Parameter(Mandatory=$true)][string]$Result)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib.ps1"
try {
    $requestData = Read-AgendaJson $Request
    $connection = $requestData.connection
    # Explicit dispatch, never execute a provider path supplied by configuration.
    switch ($connection.provider) {
        'outlook' {
            . "$PSScriptRoot\connectors\outlook.ps1"
            $snapshot = Get-OutlookSnapshot $connection ([datetime]::ParseExact($requestData.start, 'yyyy-MM-dd', [cultureinfo]::InvariantCulture)) ([datetime]::ParseExact($requestData.end, 'yyyy-MM-dd', [cultureinfo]::InvariantCulture))
        }
        default { throw 'Unsupported provider' }
    }
    Write-AgendaJson $Result @{ ok = $true; snapshot = $snapshot }
} catch {
    # Exception messages can contain mailbox names or meeting data. Never persist them.
    Write-AgendaJson $Result @{ ok = $false; error = 'Calendar unavailable. Check Outlook and its security prompts.' }
}
