# Dictation for Winarchy

A bar switch for the model behind [hold-to-talk dictation](https://github.com/YannickHerrero/winarchy/blob/master/docs/dictate.md): `winarchy-dictate.exe` stays resident (about 20 MB) but its speech model takes roughly 700 MB of RAM once loaded. This applet shows whether the model is in memory and loads or unloads it on request, so it only occupies RAM during sessions where you dictate.

## What it shows

The bar shows a microphone while the model is loaded and a crossed-out microphone otherwise (the provider picks the icon file, which needs Winarchy with placeholder support in the manifest's `icon`). The popup states one of:

- **Model in memory**: holding the dictate key records at once; the resident's working set is shown.
- **Model unloaded**: the key still works, the first press loads the model first (about 3 s).
- **Resident not running**: bind `dictate` in `keybindings.toml` and reload; the daemon starts the resident.

The single button loads or unloads the model. Unloading while a recording is in progress is ignored by the resident.

## How it works

The provider runs `winarchy-dictate.exe --status`, `--load` or `--unload`, which talk to the resident over its owner-only named pipe. The resident is a GUI-subsystem process, so `--status` answers through its exit code (0 loaded, 2 idle, other: not running) rather than console output. Memory comes from the process working set. Nothing is recorded, transcribed or pasted by this applet. Polling every 30 seconds costs one short process start.

Set `[settings] executable` in the installed `applet.toml` when `winarchy-dictate.exe` is not under `%LOCALAPPDATA%\Programs\Winarchy`.

## Install from WSL

```sh
cd ~/dev/winarchy-applet-collection
python3 -B dictate/install.py --windows-home /mnt/c/Users/<WindowsUser>
```

The installer refuses to overwrite an existing installation, backs up `bar.toml` under `~/.local/state/winarchy-applet-collection/backups/`, copies the applet to Windows `~/.config/winarchy/applets/dictate/` and inserts `dictate` right after `activity-monitor` in the bar's `right` array (at its end when that module is absent). Pass `--config-home` for a `WINARCHY_CONFIG_HOME` override. To remove it, delete `dictate` from the bar and remove the applet directory.

## Tests

```sh
python3 -B -m unittest discover -s dictate/tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File dictate/tests/provider.ps1
```
