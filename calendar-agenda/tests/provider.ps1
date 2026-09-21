$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\..\lib.ps1"
function Assert($Condition, $Message) { if (-not $Condition) { throw $Message } }
$meeting = 'https://teams.microsoft.com/l/meetup-join/abc?x=1&y=2'
Assert (Test-AgendaMeetingUrl $meeting) 'valid Teams link'
foreach ($bad in @('http://teams.microsoft.com/a', 'https://teams.microsoft.com.evil.test/a', 'https://teams.microsoft.com@evil.test/a', 'file:///C:/Windows', 'https://teams.microsoft.com:8443/a', 'https://user@teams.microsoft.com/a')) {
    Assert (-not (Test-AgendaMeetingUrl $bad)) "unsafe URL accepted: $bad"
}
Assert ((Find-AgendaMeetingUrl "Join <$meeting>") -eq $meeting) 'URL extraction'
Assert ((Get-AgendaKey 'one' 'same') -ne (Get-AgendaKey 'two' 'same')) 'cross-source identity'
$connections = @([pscustomobject]@{id='work';name='Work'}, [pscustomobject]@{id='home';name='Home'})
$state = [pscustomobject]@{ month='2026-09';day='2026-09-12';hidden=@() }
$calendar = @{id='main';name='Calendar'}
$event = @{id='occurrence';calendar_id='main';title='Réunion 日本語';location='Room';all_day=$true;start='2026-09-12';end='2026-09-13';meeting_url=$meeting}
$snapshots = @{work=@{calendars=@($calendar);events=@($event)};home=@{calendars=@($calendar);events=@($event)}}
$view = ConvertTo-AgendaView $snapshots $connections $state @() ([datetime]'2026-09-12T12:00:00')
Assert ($view.today_header -eq 'September 12' -and $view.current_year -eq 2026) 'header uses today, not selected calendar date'
Assert ([math]::Abs($view.year_progress - (254.5 / 365 * 100)) -lt 0.00001) 'elapsed current year includes time of day'
Assert ($view.notice -eq '') 'healthy sources need no persistent status footer'
$yearStartView = ConvertTo-AgendaView @{} @() $state @() ([datetime]'2024-01-01T00:00:00')
Assert ($yearStartView.year_progress -eq 0 -and $yearStartView.current_year -eq 2024) 'new year resets progress'
$leapView = ConvertTo-AgendaView @{} @() $state @() ([datetime]'2024-07-02T00:00:00')
Assert ($leapView.year_progress -eq 50 -and $leapView.today_header -eq 'July 2') 'leap year has 366 days and header ignores browsed month'
$yearEndView = ConvertTo-AgendaView @{} @() $state @() ([datetime]'2024-12-31T23:59:59')
Assert ($yearEndView.year_progress -lt 100 -and $yearEndView.year_progress -gt 99) 'progress does not reach 100 early'
Assert ($view.events.Count -eq 2) 'must not deduplicate across sources'
Assert ($view.weeks.Count -eq 6 -and $view.weeks[0].Count -eq 7) '42 cell grid'
Assert ($view.weeks[0][0].date -eq '2026-08-30') 'reference layout uses a Sunday-first grid'
Assert (($view.week_numbers -join ',') -eq '36,37,38,39,40,41') 'ISO week labels use Thursday of each row'
Assert ($view.day_short -eq 'SAT, SEP 12' -and $view.day_count -eq 2 -and $view.all_visible) 'compact day heading and all-selected state'
Assert ($view.calendars[0].label -eq 'Work / Calendar') 'multiple connections retain source identity on chips'
$boundaryState = [pscustomobject]@{month='2021-01';day='2021-01-01';hidden=@()}
$boundary = ConvertTo-AgendaView @{} @() $boundaryState @()
Assert ($boundary.week_numbers[0] -eq 53 -and $boundary.week_numbers[1] -eq 1) 'ISO week numbering across new year'
Assert ($boundary.weeks[0][0].markers.Count -eq 0) 'empty days never emit null markers'
Assert ($view.events[0].title -eq 'Réunion 日本語') 'Unicode preserved'
Assert ($view.events[0].key -ne $view.events[1].key) 'qualified occurrence identities'
$state.hidden = @((Get-AgendaKey 'home' 'main'))
$view = ConvertTo-AgendaView $snapshots $connections $state @()
Assert ($view.events.Count -eq 1) 'checkbox filters agenda'
$cell = @($view.weeks | ForEach-Object { $_ } | Where-Object { $_.date -eq '2026-09-12' })[0]
Assert ($cell.count -eq 1 -and $cell.markers.Count -eq 1) 'checkbox filters month markers'
Assert (-not $view.all_visible) 'partial selection clears All indicator'
Assert (-not (Test-AgendaOverlap $event ([datetime]'2026-09-13') ([datetime]'2026-09-14'))) 'all-day exclusive end'
$timed = @{all_day=$false;start='2026-09-11T23:00:00+00:00';end='2026-09-13T02:00:00+00:00'}
Assert (Test-AgendaOverlap $timed ([datetime]'2026-09-12') ([datetime]'2026-09-13')) 'multi-day overlap'
$instant = @{all_day=$false;start=([datetimeoffset]::new([datetime]'2026-09-12T12:00:00')).ToString('o');end=([datetimeoffset]::new([datetime]'2026-09-12T12:00:00')).ToString('o')}
Assert (Test-AgendaOverlap $instant ([datetime]'2026-09-12') ([datetime]'2026-09-13')) 'zero-duration event'
$dst = @{all_day=$false;start='2026-03-29T01:30:00+01:00';end='2026-03-29T03:30:00+02:00'}
Assert (([datetimeoffset]::Parse($dst.end) - [datetimeoffset]::Parse($dst.start)).TotalHours -eq 1) 'DST offset semantics'
$state.hidden = @((Get-AgendaKey 'home' 'main'), (Get-AgendaKey 'work' 'main'))
$view = ConvertTo-AgendaView $snapshots $connections $state @()
Assert ($view.empty -and $view.events.Count -eq 0) 'all sources hidden'
$state.hidden = @()
$view = ConvertTo-AgendaView @{work=$snapshots.work} $connections $state @(@{name='Home';message='Unavailable';stale=$true})
Assert ($view.events.Count -eq 1 -and $view.statuses[0].stale) 'source failure isolation'
Assert ($view.notice -eq 'Home: Unavailable') 'source failures remain visible without a footer'
$limited = ConvertTo-AgendaView @{} @() $state @(@{name='Work';message='Read locally - results limited';stale=$false})
Assert ($limited.notice -like '*results limited*') 'truncation remains visible without a footer'
$colorBefore = $view.calendars[0].color
$withOther = ConvertTo-AgendaView $snapshots $connections $state @()
Assert ($colorBefore -eq $withOther.calendars[0].color) 'colors stable across connection failures'
$many = @(); for ($i=0; $i -lt 55; $i++) { $copy = $event.Clone(); $copy.id = "event-$i"; $many += $copy }
$large = ConvertTo-AgendaView @{work=@{calendars=@($calendar);events=$many}} $connections $state @()
Assert ($large.events.Count -eq 40 -and $large.more -eq 15) 'daily row cap reports omitted items'
$marked = @($large.weeks | ForEach-Object { $_ } | Where-Object { $_.date -eq '2026-09-12' })[0]
Assert ($marked.count -eq 55 -and $marked.markers.Count -eq 3) 'at most three event dots per day without losing the total count'
$emptySnapshot = ConvertTo-AgendaView @{work=@{calendars=@($calendar);events=@()}} $connections $state @()
Assert ($emptySnapshot.empty -and $emptySnapshot.calendars.Count -eq 1) 'empty calendars remain selectable'
$timedRows = @()
foreach ($clock in @('11:00', '09:30', '10:00')) {
    $start = [datetimeoffset]::new([datetime]("2026-09-12T" + $clock))
    $timedRows += [pscustomobject]@{id=$clock;calendar_id='main';title='Synthetic';location='';all_day=$false;start=$start.ToString('o');end=$start.AddMinutes(30).ToString('o');meeting_url=''}
}
foreach ($ordering in @($timedRows, @($timedRows[2], $timedRows[1], $timedRows[0]))) {
    $sorted = ConvertTo-AgendaView @{work=@{calendars=@($calendar);events=@($ordering)+@($event)}} $connections $state @()
    Assert (($sorted.events.time -join ',') -eq 'All day,09:30 - 10:00,10:00 - 10:30,11:00 - 11:30') 'all-day first, then chronological regardless of connector order'
}
$temp = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N') + '.json')
try {
    Write-AgendaJson $temp @{value='first'}
    Write-AgendaJson $temp @{value='é雪'}
    Assert ((Read-AgendaJson $temp).value -eq 'é雪') 'atomic Unicode JSON replacement'
} finally { Remove-Item -LiteralPath $temp -Force }
'Provider contract tests passed.'
