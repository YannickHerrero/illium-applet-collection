# Fake Outlook object model: never creates COM, opens Outlook, or reads a profile.
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\..\lib.ps1"
. "$PSScriptRoot\..\connectors\outlook.ps1"
function Assert($Condition, $Message) { if (-not $Condition) { throw $Message } }
class FixtureItems {
    [object[]]$Rows
    [bool]$IncludeRecurrences = $false
    [string]$Sorted
    [string]$Filter
    [int]$Index = 0
    FixtureItems([object[]]$Rows) { $this.Rows = $Rows }
    [void]Sort([string]$Property) { $this.Sorted = $Property }
    [object]Restrict([string]$Filter) {
        if ($this.Sorted -ne '[Start]' -or -not $this.IncludeRecurrences) { throw 'Sort and expand BEFORE Restrict' }
        $this.Filter = $Filter
        return $this
    }
    [object]GetFirst() { $this.Index = 0; return $this.GetNext() }
    [object]GetNext() {
        if ($this.Index -ge $this.Rows.Length) { return $null }
        $value = $this.Rows[$this.Index]; $this.Index++; return $value
    }
    # Intentionally no Count property: recurring collections may have infinite Count.
}
class FixtureFolders {
    [object[]]$Rows
    [int]$Count
    FixtureFolders([object[]]$Rows) { $this.Rows = $Rows; $this.Count = $Rows.Length }
    [object]Item([int]$Index) { return $this.Rows[$Index - 1] }
}
function Appointment($Id, $Start, $End, $AllDay = $false) {
    return [pscustomobject]@{ EntryID=$Id; Class=26; Subject='Synthetic meeting'; Start=[datetime]$Start; End=[datetime]$End; StartUTC=[datetime]$Start; EndUTC=[datetime]$End; AllDayEvent=$AllDay; Location='Room'; Body='Join https://teams.microsoft.com/l/meetup-join/fixture' }
}
$rows = @(
    (Appointment 'series' '2026-09-01T09:00' '2026-09-01T10:00'),
    (Appointment 'series' '2026-09-08T11:00' '2026-09-08T12:00'), # modified occurrence, same series ID
    (Appointment 'overnight' '2026-08-30T23:00' '2026-09-02T09:00'),
    (Appointment 'exclusive' '2026-08-30' '2026-08-31' $true), # ends at range start: excluded
    (Appointment 'holiday' '2026-09-10' '2026-09-12' $true)
)
$rows[1].Location = 'https://teams.microsoft.com/l/meetup-join/' + ('x' * 160)
$items = [FixtureItems]::new($rows)
$calendar = [pscustomobject]@{EntryID='calendar';Name='Fixture';DefaultItemType=1;Items=$items;Folders=[FixtureFolders]::new(@())}
$rootFolder = [pscustomobject]@{DefaultItemType=0;Folders=[FixtureFolders]::new(@($calendar))}
$store = [pscustomobject]@{Root=$rootFolder;Calendar=$calendar}
$store | Add-Member ScriptMethod GetRootFolder { return $this.Root }
$store | Add-Member ScriptMethod GetDefaultFolder { param($Kind); if($Kind -ne 9){throw 'Calendar only'}; return $this.Calendar }
$session = [pscustomobject]@{DefaultStore=$store}
$script:fixtureApp = [pscustomobject]@{Session=$session}
$script:fixtureApp | Add-Member ScriptMethod GetNamespace { param($Name); return $this.Session }
function New-OutlookApplication { return $script:fixtureApp }
$connection = [pscustomobject]@{id='fixture';provider='outlook'}
$start = [datetime]'2026-08-31'; $end = [datetime]'2026-10-12'
$originalCulture = [threading.thread]::CurrentThread.CurrentCulture
try {
    foreach ($culture in @('en-US', 'fr-FR')) {
        [threading.thread]::CurrentThread.CurrentCulture = [cultureinfo]$culture
        $result = Get-OutlookSnapshot $connection $start $end
        Assert ($result.events.Count -eq 4) 'occurrences and overlap filtering'
        Assert ($result.calendars.Count -eq 1) 'default calendar must not be visited twice'
        Assert ($result.events[0].id -ne $result.events[1].id) 'occurrence identity includes its start'
        Assert ($result.events[0].meeting_url -eq 'https://teams.microsoft.com/l/meetup-join/fixture') 'meeting URL extraction'
        Assert ($result.events[1].meeting_url -eq $rows[1].Location) 'extract full link before truncating display location'
        Assert ($result.events[3].start -eq '2026-09-10' -and $result.events[3].end -eq '2026-09-12') 'all-day date contract'
        Assert ($result.events[0].start.EndsWith('Z')) 'timed UTC contract'
        Assert ($items.Filter.Contains($start.ToString('g')) -and $items.Filter.Contains($end.ToString('g'))) 'localized bounded Jet filter'
        Assert (-not $result.truncated) 'small fixture must not be truncated'
    }
    $many = @(); for($i=0;$i -lt 1201;$i++){ $many += Appointment "event-$i" '2026-09-01T09:00' '2026-09-01T10:00' }
    $calendar.Items = [FixtureItems]::new($many)
    $bounded = Get-OutlookSnapshot $connection $start $end
    Assert ($bounded.truncated -and $bounded.events.Count -eq 1200) 'bounded expansion and explicit truncation'
} finally { [threading.thread]::CurrentThread.CurrentCulture = $originalCulture }
'Outlook connector fixture tests passed.'
