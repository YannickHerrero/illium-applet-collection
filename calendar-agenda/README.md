# Calendar Agenda

An optional, read-only, multisource agenda for Illium. It has its **own bar icon**;
the built-in `calendar` applet and the date/clock click are never replaced.

The first connector reads **classic Outlook for Windows via COM**. The monthly grid,
daily agenda, per-calendar checkboxes, connection status and cache are source-independent.
Proton Calendar is **not implemented**: its supported access methods and privacy
implications still need investigation. Proton Mail Bridge does not supply calendar access.

## Requirements

- Illium with external PowerShell applet providers and Slint 1.12.1 views.
- Windows PowerShell 5.1 (included in Windows).
- Classic Outlook, with a working profile/default calendar. The new Outlook alone
  does not expose this COM API. Enterprise security policy can restrict COM/body access.
- Python 3.11+ in WSL for installation only.

No administrator rights, Scoop package, Graph application, Azure CLI token, WSL relay,
permanent helper service or additional PowerShell module is needed at runtime.
Outlook may start in the background when the applet loads; this applet never calls
`Outlook.Quit()` or changes an appointment. Initial Outlook setup/security prompts
must be handled in Outlook itself. A timeout never means an empty calendar.

## Install or update

From the collection repository, in WSL:

```sh
python3 -B calendar-agenda/install.py --windows-home /mnt/c/Users/<WindowsUser>
```

Alternatively use `--config-home /path/to/.config/illium`.
The installer backs up `bar.toml` and an existing applet outside the watched config
folder, then adds `calendar-agenda` before `wifi` in the right section (or at its end).
An existing reference in any section stays where it is. Repeating an unchanged
installation does nothing. Updates replace managed applet files, preserve extra
files and the existing `applet.toml` settings (including a custom `attach = "clock"`,
refresh interval and popup size), and never touch another applet. Stop editing those files during installation.
A multiline `right` array requires manually adding `calendar-agenda` first.

## Use

- Click the new agenda icon, not the existing date.
- The header shows today's local date and progress through the current year (including
  leap years). The percentage is completed whole percent; browsing another month does
  not change this indicator.
- The popup is 440 logical pixels wide and keeps a stable height from
  `popup.height` (820 by default, further limited by Illium to the monitor).
  Only the event list scrolls; selecting a date never moves the controls.
  All 42 days are supplied in one bounded snapshot. Day selection and Today within
  the grid are immediate local interactions, even while a source is refreshing.
  Every opening selects today's local date and returns the event list to the top,
  regardless of the previously browsed day or month. Calendar filters are preserved.
  The grid is Sunday-first, with ISO week labels
  (the week containing each row's Thursday) and up to three source-colored event dots
  per day. Previous/next month sit **below** the grid; Today is beside the day's count.
- Calendar chips are compact checkboxes: click to filter **both** daily rows and month
  markers, or click All to restore every calendar. Drag the chip row horizontally when
  it overflows. Choices persist; hiding never disconnects or deletes a calendar.
  Multiple connections retain their names in chip labels. Colors are stable and
  derived exclusively from the theme (colors can repeat).
- Cards fit their content: a title-only event takes 32px, with extra space only for a
  location or meeting action. The UI uses JetBrainsMono NFM when installed (for example
  via the user's Scoop font pack), with the system fallback otherwise; no font is bundled.
- The refresh arrow forces a read (it dims while busy). Opening the popup requests cached data or a refresh when
  older than five minutes. Background polling also happens every five minutes.
- Join meeting opens the validated Teams HTTPS link via Windows' registered URL
  handler; the browser/Teams decides whether to open the app. This button does not
  edit or accept a meeting. Other meeting services are not enabled yet.

Times are local Windows times; all-day end dates are exclusive. The connector expands
recurrences inside the displayed **42-day grid**, including Outlook's modified and
removed occurrences, rather than treating recurring series as individual meetings.
Overlapping events that start before the grid/day are included. Invitations duplicated
across providers are intentionally not merged.

Healthy sources have no persistent status footer. Failures, stale data and limited
results produce a compact warning below the header. Any `Read locally` time in a
warning is when we read Outlook, **not proof that Outlook synchronized with Exchange**.
A failed source retains its matching cached range; other sources remain usable. Navigation to an uncached range never displays
an old month's events as if they belonged to the new month. While the popup stays open, selection stays on the
chosen date until you choose another day/Today, including across midnight and refreshes.
Closing and reopening returns to today's local date.

## Connections and private state

Created on first use, outside Illium's watched configuration tree:

```text
%LOCALAPPDATA%\Illium\calendar-agenda\
  connections.json
  state.json
  cache-<connection-id>.json
```

Default `connections.json`:

```json
{
  "version": 1,
  "connections": [
    { "id": "outlook-default", "name": "Outlook", "provider": "outlook", "enabled": true }
  ]
}
```

One connection represents an Outlook **store within the current Windows user's
Outlook profile**. It discovers the store's calendars (default first, then a bounded
folder traversal). It does not log into another Outlook profile or Microsoft account.
To add another already configured store, add a connection with a unique ID and its
Outlook `StoreID` as `store_id`. Omit `store_id` to use the default store. Store IDs
are private, machine/profile-specific identifiers; never commit your configuration.
Shared calendars are only included if accessible through the configured store's
folder tree; discovery of every Exchange shared/delegated mailbox is not promised.
Do not configure the same store twice unless you want duplicate results.

IDs must be 1–48 letters, digits, underscores or hyphens. Up to eight configured
connections are accepted. Set `enabled` to `false` to disconnect a source; refresh
to apply changes. Unsupported providers return an error; provider names cannot load
arbitrary scripts. Secrets/OAuth tokens do not belong in this file.

Caches contain event titles, times, locations, calendar names and optional meeting
URLs. They inherit the Windows user profile's access controls; they are **not an
additional encrypted vault**. No event bodies, attendees, passwords or access tokens
are persisted. Do not synchronize or share this directory. Exception details are
not recorded because Outlook errors can contain private data.

Only one range is kept per connection. Caches older than seven days, disabled/deleted
source caches, and abandoned worker files are removed on subsequent provider runs.
This is not a background retention service: uninstalling/stopping the applet stops
cleanup too. Delete the runtime directory to erase all cached events and settings.

## Bounds and failure isolation

Each source runs in a short-lived Windows PowerShell worker. All workers share an
11-second deadline, rather than stacking one timeout per source; only those workers
are terminated, never Outlook. The caller remains below Illium's 20-second provider
budget in normal operation. Cold Outlook startup or a security prompt can time out:
open Outlook and refresh again. A named mutex protects private state from overlapping
provider processes.

Per connection: at most 200 visited folders, depth 12, 24 calendars, and 1,200
occurrences. The status says `results limited` if a bound is reached. One day shows
at most 40 rows and indicates omitted rows. The output is additionally reduced below
60,000 UTF-8 bytes to stay below Illium's 64 KiB limit. There is no unbounded recurrence
`Count` call. Remote/slow Outlook folders can still make that connection unavailable.

## Connector contract (v1)

`worker.ps1` explicitly dispatches provider names to connectors. A connector accepts
one connection and a local `[start, end)` range and returns:

```text
version: 1
connection_id, fetched_at (UTC), range_start/range_end (local dates), truncated
calendars: [{ id, name }]
events: [{ id, calendar_id, title, start, end, all_day, location, meeting_url }]
```

Timed start/end values are ISO 8601 with offsets (Outlook emits UTC). All-day values
are `YYYY-MM-DD` dates, never UTC timestamps. Event IDs identify **occurrences**, not
only series. The aggregator qualifies calendar and event identities with the connection
ID, then derives opaque UI keys. It never deduplicates across connections. Visibility
and colors use these stable calendar keys; a checkbox is not a connector setting.
Connectors return plain data, not UI labels or executable actions.

A future Proton/ICS connector can implement this contract without changing the view.
Its authentication, refresh cadence and permission model must be designed when that
access mechanism has been verified, not inferred from the Outlook implementation.
For now only Teams URLs on `teams.microsoft.com` / `teams.live.com`, HTTPS/default port,
without embedded credentials, are launchable. Arbitrary connector URLs are not executed.

## Tests

No private calendar is read by the default tests:

```sh
python3 -B -m unittest discover -s calendar-agenda/tests -p 'test_*.py'
pwsh -NoProfile -File calendar-agenda/tests/provider.ps1
pwsh -NoProfile -File calendar-agenda/tests/model.ps1
pwsh -NoProfile -File calendar-agenda/tests/outlook.ps1
xvfb-run -a python3 calendar-agenda/tests/preview.py /tmp/calendar-agenda-preview
```

Run the provider and Outlook fixture tests with **Windows PowerShell 5.1** too.
On Windows, also run `powershell -NoProfile -ExecutionPolicy Bypass -File
calendar-agenda/tests/orchestration.ps1`: synthetic caches verify stale-source
isolation, persisted filters, corrupt caches, range changes and disabled-source
cleanup without opening Outlook. The preview requires
`slint-viewer` 1.12.1 and Pillow (development only), renders synthetic dark/light,
Akane, 125%/150% scale, empty, busy and failed-source data, and never launches Outlook.
It checks that nine compact cards fit, numeric locations survive fractional scaling,
checkbox/month/meeting/All callbacks, local day/Today interactions, and that busy
provider-backed controls reject clicks without disabling local day selection.
Native window dimensions are checked for empty/small/large agendas, the deferred
stable opening geometry and a custom lower height ceiling.
Set `CALENDAR_AGENDA_FONT_DIR` to a local directory with JetBrainsMono NFM font files
for previews matching Windows; this does not install or bundle the fonts.
`tests/live.py` is an explicit opt-in read-only smoke test from WSL on a configured
Windows machine. It stages scripts and runtime files in a temporary Windows folder,
prints only counts/status/timing, removes its cache, and never installs the applet or
opens a meeting link. Outlook itself may start or synchronize during the test.

```sh
python3 -B calendar-agenda/tests/live.py --windows-home /mnt/c/Users/<WindowsUser>
```

## Uninstall / rollback

1. Remove only `calendar-agenda` from your bar arrays.
2. Delete `%USERPROFILE%\.config\illium\applets\calendar-agenda`.
3. Optionally delete `%LOCALAPPDATA%\Illium\calendar-agenda` (private cache/settings).

For an update rollback, copy the applet from the printed backup path. Restore the
backed-up `bar.toml` only if you have made no subsequent bar changes; otherwise remove
just the new entry manually. The built-in calendar needs no restoration.

Independent, unofficial Outlook/Teams integration. The SVG icon is original artwork.
