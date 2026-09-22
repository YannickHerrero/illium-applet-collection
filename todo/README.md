# Todo for Winarchy

A local task list in the bar: add a task, tick it off, delete it. Nothing leaves the machine, and nothing runs between clicks.

## What it shows

The bar icon carries the number of tasks still open, and nothing at all once they are all done. The popup holds three parts.

**A text field.** Type and press Enter, or click `+`. It takes the keyboard focus when the popup opens, so you can add a task without touching the mouse.

**The list.** Clicking the box ticks a task off, which mutes it and crosses it out; the bin on the right deletes it. The list scrolls and keeps the order you added tasks in.

**A Clear completed footer**, shown only while something is ticked off, with the count of completed tasks facing it.

Colors come from the active Winarchy theme, so switching theme repaints the applet with the rest of the bar.

## How it works

The provider owns the list and prints all of it on every run. The view asks it to `add`, `toggle`, `delete` or `clear-completed`, and Winarchy passes those arguments as a JSON array, so a task may hold quotes, brackets or any Unicode without an escaping convention of its own.

Tasks live in `%LOCALAPPDATA%\winarchy-applet-collection\todo\tasks.json`, outside Winarchy's watched configuration tree, so writing one never triggers a configuration reload. The provider writes the whole list to a temporary file beside it, then moves that file over the previous one, so an interrupted write leaves the old list intact. The file is UTF-8 without a BOM; edit it by hand if you like, while the popup is closed.

Every task carries an identifier the provider assigns. An action naming an unknown identifier does nothing instead of falling on a neighbour, so a popup showing a stale list cannot tick off the wrong task. A list holds at most 200 tasks of at most 200 characters. When the provider cannot parse the task file, it says so in the popup and leaves the file alone rather than starting an empty list over it.

Nothing but this popup writes the list, so the provider runs when you open it, on each action, and every 10 minutes otherwise.

Each action starts a PowerShell process, which takes a few hundred milliseconds, so the list answers the click first and the provider afterwards: a ticked task crosses out at once, a deleted one leaves, a typed one appears greyed until it comes back with an identifier. The view counts the actions it is still owed an answer for and drops that overlay only once none is left, so a burst of clicks does not flicker back to the old state. Clicks during a run are queued by Winarchy, up to eight, rather than dropped.

Set `[settings] store` in the installed `applet.toml` to keep the task file elsewhere, a synchronised folder for instance.

## Install from WSL

```sh
cd ~/dev/winarchy-applet-collection
python3 -B todo/install.py --windows-home /mnt/c/Users/<WindowsUser>
```

The installer refuses to overwrite an existing installation, backs up `bar.toml` under `~/.local/state/winarchy-applet-collection/backups/`, copies the applet to Windows `~/.config/winarchy/applets/todo/` and puts `todo` first in the bar's `drawer` array, behind the chevron. A bar without a drawer gets it in `right` instead, before `claude-usage`, or at the end when that module is absent. Pass `--config-home` for a `WINARCHY_CONFIG_HOME` override. To remove it, delete `todo` from the bar and remove the applet directory; the task file survives, since it lives outside the configuration.

## Keyboard

The popup takes the keyboard focus, as the Wi-Fi panel does, so the global Alt chords pause while it is open. Escape closes it and clears the draft; Enter adds the typed task.

## Tests

```sh
python3 -B -m unittest discover -s todo/tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File todo/tests/provider.ps1
xvfb-run -a python3 todo/tests/preview.py /tmp/todo-preview   # optional, renders the view
```

The preview renders six fixtures, one of them mid-flight with a ticked, a deleted and a typed task, since the optimistic state is otherwise only visible on the desktop. The provider fixtures cover action parsing, the list mutations, the store round-trip (Unicode, no BOM, no leftover temporary file, a corrupt file left alone, identifiers never reused) and a whole-script run started the way Winarchy starts it.
