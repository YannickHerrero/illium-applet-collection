# Output contract v1: calendars + occurrences in [start, end); never writes Outlook data.
function Release-OutlookObject($Object) {
    if ($null -ne $Object -and [Runtime.InteropServices.Marshal]::IsComObject($Object)) {
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($Object)
    }
}
function New-OutlookApplication { return (New-Object -ComObject Outlook.Application) }
function Get-OutlookSnapshot($Connection, [datetime]$Start, [datetime]$End) {
    $app = $null; $session = $null; $store = $null; $root = $null; $default = $null; $stores = $null
    $calendars = New-Object 'Collections.Generic.List[object]'
    $events = New-Object 'Collections.Generic.List[object]'
    $budget = @{ folders = 0; truncated = $false }
    try {
        $app = New-OutlookApplication
        $session = $app.GetNamespace('MAPI')
        if ($Connection.PSObject.Properties['store_id'] -and $Connection.store_id) {
            $stores = $session.Stores
            $store = $stores.Item([string]$Connection.store_id)
        } else { $store = $session.DefaultStore }
        $root = $store.GetRootFolder()
        $default = $store.GetDefaultFolder(9)
        # Default calendar first; bounded traversal finds other calendars in this store.
        $seen = @{}
        function Read-OutlookCalendar($Folder) {
            $id = [string]$Folder.EntryID
            if ($seen.ContainsKey($id)) { return }
            $seen[$id] = $true
            if ($calendars.Count -ge 24) { $budget.truncated = $true; return }
            $calendars.Add(@{ id = $id; name = (Limit-AgendaText ([string]$Folder.Name) 70) })
            $items = $null; $restricted = $null; $item = $null
            try {
                $items = $Folder.Items
                $items.Sort('[Start]')
                $items.IncludeRecurrences = $true
                # Outlook Jet date filters require the Windows user's local date format.
                $a = $Start.ToString('g', [cultureinfo]::CurrentCulture)
                $b = $End.ToString('g', [cultureinfo]::CurrentCulture)
                $filter = "[Start] < '$b' AND [End] >= '$a'"
                $restricted = $items.Restrict($filter)
                $item = $restricted.GetFirst()
                while ($null -ne $item) {
                    if ($events.Count -ge 1200) { $budget.truncated = $true; break }
                    if ($item.Class -eq 26) {
                        $allDay = [bool]$item.AllDayEvent
                        if ($allDay) {
                            $startValue = ([datetime]$item.Start).ToString('yyyy-MM-dd')
                            $endValue = ([datetime]$item.End).ToString('yyyy-MM-dd')
                        } else {
                            $startValue = ([datetime]$item.StartUTC).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [cultureinfo]::InvariantCulture)
                            $endValue = ([datetime]$item.EndUTC).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [cultureinfo]::InvariantCulture)
                        }
                        $location = [string]$item.Location
                        $event = @{ id = ([string]$item.EntryID + ':' + $startValue); calendar_id = $id; title = (Limit-AgendaText ([string]$item.Subject)); start = $startValue; end = $endValue; all_day = $allDay; location = (Limit-AgendaText $location 100); meeting_url = '' }
                        if (Test-AgendaOverlap $event $Start $End) {
                            $event.meeting_url = Find-AgendaMeetingUrl $location
                            if (-not $event.meeting_url) { $event.meeting_url = Find-AgendaMeetingUrl ([string]$item.Body) }
                            $events.Add($event)
                        }
                    }
                    Release-OutlookObject $item; $item = $null
                    $item = $restricted.GetNext()
                }
            } finally { Release-OutlookObject $item; Release-OutlookObject $restricted; Release-OutlookObject $items }
        }
        function Visit-OutlookFolder($Folder, [int]$Depth) {
            if ($budget.folders -ge 200 -or $Depth -gt 12) { $budget.truncated = $true; return }
            $budget.folders++
            if ($Folder.DefaultItemType -eq 1) { Read-OutlookCalendar $Folder }
            $children = $null
            try {
                $children = $Folder.Folders
                for ($i = 1; $i -le $children.Count; $i++) {
                    if ($budget.folders -ge 200) { $budget.truncated = $true; break }
                    $child = $null
                    try { $child = $children.Item($i); Visit-OutlookFolder $child ($Depth + 1) }
                    finally { Release-OutlookObject $child }
                }
            } finally { Release-OutlookObject $children }
        }
        Read-OutlookCalendar $default
        Visit-OutlookFolder $root 0
        return @{ version = 1; connection_id = $Connection.id; fetched_at = [datetime]::UtcNow.ToString('o'); range_start = $Start.ToString('yyyy-MM-dd'); range_end = $End.ToString('yyyy-MM-dd'); calendars = @($calendars.ToArray()); events = @($events.ToArray()); truncated = $budget.truncated }
    } finally {
        foreach ($obj in @($default, $root, $store, $stores, $session, $app)) { Release-OutlookObject $obj }
        # Never call Outlook.Quit(): Outlook belongs to the user.
    }
}
