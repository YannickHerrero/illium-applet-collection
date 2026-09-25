# Winagotchi for Illium

An independent, **entirely silent** port of [SLcode777/omagotchi](https://github.com/SLcode777/omagotchi): a tiny pixel companion in your bar, with a themed, animated room. No Illium engine changes, Qt/Quickshell, PowerShell runtime, permanent service, network requests, system modification or administrator rights. Original MIT sprites and attribution: [SOURCES.md](SOURCES.md), [LICENSE](LICENSE).

## Your companion

Click its bar icon to open the room. Five need gauges run from **0 (fine) to 100 (needs care)**:

- **Feed** restores 35 hunger points.
- **Wash** enables scrubbing: hold the mouse over the pet, rub it, then release. A gesture restores up to 25 dirt points. Click **Done washing** or Escape to leave wash mode. Unfinished gestures are discarded on popup dismissal.
- **Click the pet** to cuddle: restores 10 loneliness points. Babies also regain 10 fun points.
- **Play**, available from childhood, restores 25 boredom points and costs 3 energy points. It replaces desktop roaming in this room-only version.
- **Sleep** happens automatically at 60 fatigue or above on the next active-minute tick. Sleeping recovers 2.2 energy points per minute; the pet wakes at 5 fatigue. Care wakes it, and a still-tired pet settles again at the next tick.

Care commits immediately; the short eating/playing/bubble animation is visual feedback, not a transaction waiting for the animation to end. The popup disables new care while an action is pending. A wash gesture sends one bounded command on release, never one process per mouse movement.

### Work day mode

Enable work day mode only in `applets/winagotchi/applet.toml`:

```toml
[settings]
work_day = "true"
```

Illium hot-reloads this configuration. Set `"false"` (the default), or remove the setting, to disable it. Configuration overrides the value in existing pet saves on every provider invocation; there is no interface toggle or schedule label.

Activity is limited to **Monday–Friday, 09:00–18:00**, using Windows local time. Outside those hours (including weekends), age, all needs and stage care freeze. The pet displays its sleeping sprite (eggs stay eggs); this is a pause, not fatigue recovery. Nothing catches up in the morning. Care controls are disabled during the pause; disable the setting to interact outside the schedule.

The option applies across generations. It does not undo an existing evolution: an adult gremlin remains a gremlin until you start a new generation with **Let it go…**. During work hours, normal care is still needed. Schedule boundaries may discard up to one polling interval of activity, rather than charge unattended time.

Growth counts **active minutes**, not time since installation:

| Stage | Total active age | Branch |
|---|---:|---|
| Egg | 0–5 min | No needs yet |
| Baby | 5–70 min | Frequent naps |
| Child | 70–550 min | Loves playing |
| Teen | 550–1510 min | Neat if previous stage care ≥55, otherwise scruffy |
| Adult | From 1510 min | Ace, easygoing or gremlin, based on teen form/care |

Care is the stage average of `100 − highest need`. A neat teen becomes ace at ≥75 care, easygoing at ≥40, otherwise gremlin. A scruffy teen can reach easygoing at ≥75, otherwise gremlin. Evolution resets the care average and shows a dismissible message. Adults can **Let it go…**: a confirmation starts a fresh egg in the next generation. Confirmation pins that generation and is cleared when the popup closes. There is no death mechanic.

Sprites, emotes and decorations follow the active Illium theme. Animation runs only while the popup is visible. The current engine displays a static first-frame icon in the bar, changing with form/sleep state; its fixed 14px icon can look softer than the pixelated popup. No middle-click action or animated bar extension is installed.

## Time, saves and safety

Illium starts the native provider directly every **30 seconds**, plus on opening and care actions. The process reads/updates a tiny save and exits. There is no resident pet process.

The Windows provider uses `QueryUnbiasedInterruptTime` (uptime excluding sleep/hibernation), and the parent process PID **plus creation time** to identify an Illium run. It accumulates elapsed active time between observations:

- Closing the popup does not stop growth.
- Restarting Illium does not charge offline time.
- Sleep/hibernation does not advance age or needs.
- Gaps over 90 seconds between provider observations are treated as absence, with no catch-up. Keep the manifest's 30-second cadence. Long scheduling stalls or removing the applet temporarily may undercount active time; a removal/re-add under 90 seconds can count that short gap.
- Fractional active minutes survive normal restarts. No Windows idle-time detection: leaving an awake, running Illium unattended still counts, except outside the enabled Work day schedule.

Private data lives **outside the repository and Illium's watched config tree**:

```text
%LOCALAPPDATA%\Illium\winagotchi\state.json
%LOCALAPPDATA%\Illium\winagotchi\state.lock
```

The profile's inherited permissions apply. An OS-held exclusive file lock serializes providers, including configuration reload races, and is released on process exit/crash. Writes flush to a temporary file and atomically replace the save. Reads are bounded to 64 KiB and values are validated. Corrupt/oversized saves are renamed to `state-corrupt-<timestamp>-<pid>.json`, never silently overwritten; a fresh egg shows a recovery notice. Unknown future save versions and I/O errors leave the original untouched and report an error. Review recovery files before deleting them; no automatic backup cleanup occurs.

To back up the pet, exit Illium and copy its state directory. Restore with Illium stopped. Existing Linux Omagotchi saves are **not** automatically imported. For isolated tests only, `ILLIUM_APPLET_STATE_DIR` selects an absolute state directory; never point it at the watched config tree.

No sound assets, sound settings, playback calls or system notifications are included. No package inventory or update probing: hunger and dirt use upstream's base rates. No window enumeration, climbing or roaming overlay in this version.

## Build and install

Build once with Rust 1.89+; the installed applet needs no Rust or Python runtime.

On Windows, from `provider/`:

```powershell
cargo build --release --locked
```

From WSL with cargo-xwin and Illium's cross-toolchain:

```sh
cd winagotchi/provider
PATH="$HOME/.local/llvm19/bin:$PATH" cargo xwin build \
  --target x86_64-pc-windows-msvc --release --locked
cd ..
python3 -B install.py --windows-home /mnt/c/Users/YOUR_USER
```

For a custom `ILLIUM_CONFIG_HOME`, use `--config /mnt/c/path/to/illium` instead. Optional `--binary` selects an already-built Windows x86-64 executable; `--windows-config` overrides `wslpath -w` conversion. The installer requires Python 3.11+.

The installer:

1. Validates the provider's Windows PE architecture and bar configuration.
2. Backs up the exact `bar.toml` to `~/.local/state/illium-applet-collection/backups/winagotchi-install-*`.
3. Stages the complete applet outside the watched config tree, then publishes `applets/winagotchi/`.
4. Sets an absolute Windows executable path and inserts `winagotchi` immediately before `workspaces` in the bar's `left` array (at the start if no workspace group is configured).

**Bar placement requires an Illium build that honors the workspace group's configured position.** Older builds always render workspaces first, regardless of the TOML order. Update the engine separately; this installer never modifies it.

Existing modules, unrelated files, comments outside the changed array and settings are preserved. Multiline/complex left arrays require manual installation rather than risky reformatting. Existing applet installations are never overwritten. No Illium source files, theme, wallpaper or other applet settings are changed. Illium hot-reloads; no engine rebuild is needed.

For a manual Windows install, copy `applet.toml`, `view.slint`, `sprites.slint`, `assets/`, all root-level PNGs, `README.md`, `LICENSE`, `SOURCES.md` and the built `winagotchi.exe` into `%USERPROFILE%\.config\illium\applets\winagotchi\`. Edit `command` in `applet.toml` to the executable's absolute Windows path using a valid TOML string. Back up `bar.toml`, then use `left = ["winagotchi", "workspaces"]` (retaining any other configured modules). **Do not copy `provider/target`, tests or private state.**

For upgrades, exit Illium, back up the installed applet and state outside the config tree, then replace the applet files as a set, retaining its absolute command and any settings. The fresh installer intentionally refuses upgrades.

To uninstall, remove `winagotchi` from `bar.toml`, then remove its applet directory. Keep the private state to resume later, or delete it separately to start over. Restore the entire backed-up bar only if no later unrelated bar changes would be lost.

## Renaming an existing Omagotchi installation

The initial Windows port was named `omagotchi`. The pet save format has not changed. To migrate without losing progress:

1. Exit Illium cleanly and wait for any provider process to finish.
2. Back up `bar.toml`, the installed `applets/omagotchi/` folder and `%LOCALAPPDATA%\Illium\omagotchi\` outside the watched configuration tree.
3. Install the new applet files manually as above in `applets/winagotchi/`, with the new executable's absolute path in its manifest.
4. Copy the old `state.json` unchanged into `%LOCALAPPDATA%\Illium\winagotchi\`. Do not overwrite an existing new-name save; resolve that conflict explicitly first. No lock file needs copying.
5. Replace the old bar reference with `winagotchi`, immediately before `workspaces` in `left`, and remove the old applet directory only after backing it up.
6. Restart Illium and verify the same generation, form and age. Retain the old state and backups until satisfied.

The fresh installer refuses a configured/installed `omagotchi` rather than silently creating a second pet. This is a Windows-port rename, not an importer for the original Linux save format. Upstream attribution remains Omagotchi.

## Tests

```sh
cd provider
cargo test --locked
cargo clippy --all-targets --locked -- -D warnings
PATH="$HOME/.local/llvm19/bin:$PATH" cargo xwin clippy \
  --target x86_64-pc-windows-msvc --all-targets --locked -- -D warnings
cd ..
python3 -B -m unittest discover -s tests -v
xvfb-run -a python3 -B tests/preview.py /tmp/winagotchi-preview
```

Rendering fixtures use Slint viewer **1.12.1**, Pillow and X11/XTest, in a disposable Xvfb display. They render all eight forms, light/dark themes, 100/150/200% scaling, a reduced popup, provider errors, wash mode and confirmation. They check visible animation/closed animation, sprite pixels, one-shot petting, scrub batching and generation-pinned farewell without running a provider. Screenshots stay in the chosen temporary output directory.

On Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests/native.ps1 -Provider <absolute-path-to-winagotchi.exe>
```

Native fixtures use a fresh temporary state directory and never read or modify a real pet. They exercise the actual Windows clock/parent identity, atomic saves and gameplay/recovery. Physical suspend/resume and interactive integration in a live Illium bar still deserve a manual smoke test; automated tests simulate session changes and time gaps rather than suspending the workstation.

`tools/generate-sprites.py` regenerates the checked-in static Slint image lookup. Slint image URLs must be literals; no paths received from a save are evaluated by the view.
