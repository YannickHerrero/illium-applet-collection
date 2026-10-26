# Time tracker for Illium

A work-session switch in the bar, with the clocks of the places you work between and a history page in the browser. Nothing leaves the machine.

## What it shows

The bar icon turns into a play sign while you work, slowly fading in and out so you can tell at a glance that time is being counted, with today's total beside it; while you are off, it is a still stopwatch without text. The fading uses the manifest's `pulse` key, which needs an Illium build that knows it: older builds reject the manifest.

The popup holds:

- **One clock per configured zone**, with its date. Tokyo and Paris by default.
- **Today** and **This week, Mon-Fri**, both counting live while a session is open. The week is the Monday to Friday of the current week; weekend work counts for its day, never for the week.
- **Start working / Stop working.**
- **Open history ↗**, which writes the history page and opens it in the default browser: totals, then each week (Mon-Fri total, and the total with the weekend when you worked one), then each day newest first with a 24-hour timeline and every session in every zone. Hover a bar of the timeline for its times.

Colors come from the active Illium theme; the history page follows the Windows light or dark mode.

## Time zones

Set `[settings] zones` in the installed `applet.toml`, as `City|Windows time zone identifier` separated by semicolons, the same format as Illium's built-in timezones applet:

```toml
zones = "Tokyo|Tokyo Standard Time;Paris|Romance Standard Time"
```

The **first** zone is the reference: it decides which day and which week a session counts for, and the timeline of the history page is drawn in it. A session running across its midnight is split between the two days. Back home, a single zone is enough: `zones = "Paris|Romance Standard Time"`. Changing the zones never rewrites the history, which is kept in UTC; the history page is simply drawn again in the new reference zone. `tzutil /l` lists the Windows identifiers.

## How it works

Sessions live in `%LOCALAPPDATA%\illium-applet-collection\time-tracker\sessions.json`, outside Illium's watched configuration tree, as UTC start and end times:

```json
{ "version": 1, "sessions": [ { "start": "2026-10-26T00:30:00Z", "end": "2026-10-26T03:45:00Z" } ] }
```

The file is written whole to a temporary file beside it, then moved over the previous one, so an interrupted write leaves the old history intact. A file the provider cannot parse is reported in the popup and left alone. The history page is written beside it as `report.html` each time you open it.

The PowerShell provider runs every minute, and that run doubles as a heartbeat: an open session records the last minute it was seen. When the provider finds an open session whose heartbeat is more than 5 minutes old (the machine slept or was shut down, or Illium was not running), it ends that session at its last heartbeat and leaves the tracker off: the time in the gap is unknown, so it is not counted, and you start a new session when you are back. A restart of Illium shorter than that keeps the session going.

The view sends `start` or `stop` rather than a toggle, so a click on a popup showing a stale state cannot invert it, and it answers the click before the provider does. Between two runs it advances the clocks and totals itself, one second at a time.

Set `[settings] store` to keep the history elsewhere, a synchronised folder for instance.

## Install from WSL

```sh
cd ~/dev/illium-project/illium-applet-collection
python3 -B time-tracker/install.py --windows-home /mnt/c/Users/<WindowsUser>
```

The installer refuses to overwrite an existing installation, backs up `bar.toml` under `~/.local/state/illium-applet-collection/backups/`, copies the applet to Windows `~/.config/illium/applets/time-tracker/` and puts `time-tracker` in the bar's `right` array, just after the drawer chevron (first when there is no drawer). Pass `--config-home` for a `ILLIUM_CONFIG_HOME` override. To remove it, delete `time-tracker` from the bar and remove the applet directory; the history survives, since it lives outside the configuration.

## Tests

```sh
python3 -B -m unittest discover -s time-tracker/tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File time-tracker/tests/provider.ps1
xvfb-run -a python3 time-tracker/tests/preview.py /tmp/time-tracker-preview   # optional, renders the view
```

The provider fixtures cover the zones, start/stop/refresh, today and week totals (weekend and previous week excluded, Paris winter time), the stale heartbeat, the split at midnight, the history page data and its injection into the page, the store round-trip (no BOM, no leftover temporary file, a corrupt file left alone) and whole-script runs started the way Illium starts them. No browser is opened.
