# Herdr for Winarchy

A read-only Winarchy applet showing the [herdr](https://herdr.dev) servers running in WSL and every agent inside them: which one needs an answer, which one finished while you were looking elsewhere, which ones are still working. Nothing in the popup focuses, stops or deletes anything.

Inspired by [jankeesvw/omarchy-herdr](https://github.com/jankeesvw/omarchy-herdr), MIT. The session and agent aggregation follows its data script; the window matching, pinning and session actions have no Winarchy equivalent and were left out. No upstream QML, scripts or assets are bundled; the icon is an original drawing.

## What it shows

The bar carries the number of running herdr servers, prefixed with `!` when at least one agent is waiting on you, and nothing when no server runs.

The popup lists one card per **herdr workspace** of the running server (this applet assumes a single herdr session per machine):

- the workspace label as title, with its number and tab count underneath
- the loudest state of its agents (**1 needs you**, **2 done**, **1 working**, **ready**, or **no agents**) and their count
- every agent of that workspace with its terminal title and state, ordered needs you, done, working, ready

A stopped session, if any, is one muted card named after it (`default` reads **Shared session**, a numeric name reads **Workspace N**), showing the labels saved in its `session.json` or **nothing saved**.

States are herdr's own: `blocked` (**needs you**) means herdr recognised a question or approval on screen, `done` means work finished in a pane you have not focused since, `idle` is written **ready**. Those two attention states are drawn bold and washed in red or green; working uses the theme accent. A running server that does not answer its socket shows **no answer**.

The list refreshes every 15 seconds while the popup is closed and every 3 seconds while it is open.

## How it works

```text
herdr session list --json  +  herdr api snapshot (one per running server)
  -> herdr-agents.sh (bash + jq, in WSL)
  -> wsl.exe -d <distribution> -- bash <script>   (Winarchy provider, every poll)
  -> Winarchy icon, label and popup
```

Winarchy runs the script through `wsl.exe` from Windows, off the UI thread; a poll costs well under a second with the WSL VM up. The script only reads herdr's CLI output and `session.json` files, prints bounded JSON and never writes anywhere. Workspace labels and agent titles are drawn as plain text, never handed to a shell. Titles are trimmed of herdr's leading spinner glyphs so they stay in one column.

Requires `herdr` and `jq` in the WSL distribution. `~/.local/bin` is added to the script's PATH because `wsl.exe` starts a non-interactive shell.

## Install from WSL

```sh
cd ~/dev/winarchy-applet-collection
python3 -B herdr/install.py --windows-home /mnt/c/Users/<WindowsUser>
```

Pass `--config-home` for a Windows `WINARCHY_CONFIG_HOME` override and `--distribution` when herdr runs in another distribution than the current one. The installer refuses to overwrite an existing installation, backs up `bar.toml` under `~/.local/state/winarchy-applet-collection/backups/`, copies the script to `~/.local/share/winarchy-applets/herdr/` in WSL, copies the applet to Windows `~/.config/winarchy/applets/herdr/` with the distribution and absolute script path in its manifest, then appends `herdr` to the bar's `right` array. Other bar entries and comments are preserved; a multiline array is refused instead of reformatted. No Winarchy rebuild or restart is needed.

To remove it, delete `herdr` from the bar, then remove the applet directory and the WSL script directory. Restore the backed-up `bar.toml` only if no other bar edits were made since.

For upgrades, replace the installed `view.slint`, `icon.svg` and the WSL script; keep the installed `applet.toml`, which carries your distribution and path.

## Tests

```sh
python3 -B -m unittest discover -s herdr/tests -v
xvfb-run -a python3 -B herdr/tests/preview.py /tmp/herdr-preview
```

Script tests run against a fake `herdr` on PATH; the preview requires Slint viewer 1.12.1 and Pillow for development only and never runs the provider.
