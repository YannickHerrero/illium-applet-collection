# Activity Monitor for Illium

A standalone Windows applet combining the CPU and memory bar modules, with an Overview dashboard and a searchable Processes table. English UI, native Unicode process names, current Illium theme colors, software-rendered step graphs. No changes to Illium source, no persistent service, no network requests and no administrator elevation.

Inspired by [stappmus/omarchy-activity-monitor](https://github.com/stappmus/omarchy-activity-monitor), MIT, reference revision `b25a98c7ff2a688ab74d86d2be42249e2db2f9cf` (v2.1.1). This is an independent Rust/Slint Windows implementation, not a wrapper around its Linux scripts. No upstream scripts, binaries or assets are bundled. The icon is an original drawing. The existing Illium process sampler also informed the API choices; creation-time checks and unavailable-value handling are implemented independently here.

## Features

- Bar: **CPU used % · physical RAM used %** (not free RAM).
- Overview: CPU/RAM graphs for the last 60 seconds, memory used/available/total, uptime, network and disk read/write rates, fixed-volume free space and the three busiest processes.
- Processes: name, PID, CPU and working set; CPU/memory descending or name/PID ascending sorting; Unicode search; up to 80 matching rows, with the matched and sampled counts shown. Narrow the search to find a process outside those 80 rows.
- A click selects, never kills. End task requires a separate confirmation, pins PID **and creation time**, then opens one handle and revalidates identity/critical status before terminating that same handle. Illium and the collector are blocked, as are critical processes and a conservative list of essential Windows names. Access denied never triggers elevation. Unsaved work can be lost.
- Open Task Manager is an explicit alternative for operations Windows does not allow here.

Keys: `1` Overview, `2` Processes, `/` search, Enter applies the search and leaves the input, `j`/`k` or arrows move the selection, `x` asks to end the selected process, Enter confirms that dialog, `r` refreshes. Escape cancels confirmation/leaves search before closing the popup. Typing into search is picked up by the next poll; it does not start a process per keystroke.

The 580×650 logical-pixel popup scrolls when Illium fits it to a smaller work area. The table also scrolls. Confirmation covers the content and is cleared on dismissal.

## Metric definitions and limitations

- **CPU:** `GetSystemTimes` busy-time deltas, normalized to 0–100% of the machine. Process CPU uses `GetProcessTimes`, elapsed monotonic time and logical processor count. Windows Task Manager can display frequency-adjusted utility instead, so exact percentages may differ. Hosts with more than 64 logical processors currently show global CPU as unavailable rather than incorrectly reporting one processor group.
- **RAM:** physical total minus available (`GlobalMemoryStatusEx`). This is not committed virtual memory or Linux cache accounting. Per-process memory is the working set: shared pages mean rows must not be summed to obtain global usage.
- **Network:** `GetIfTable2` counters for exactly one up, physical Ethernet/Wi-Fi interface. By default, the lowest interface index wins; the selected alias is displayed. This is **not** automatic default-route discovery or a claim of Internet connectivity. Set `interface` to an exact alias when multiple adapters are up. Virtual adapters, VPNs and WSL virtual switches are not added to physical traffic again. Includes all traffic on that adapter, not only application payload.
- **Disk:** `IOCTL_DISK_PERFORMANCE` for the configured Windows `PhysicalDrive` number, default **0**, explicitly identified in the popup. Not a sum of overlapping volumes and not process I/O (which could include pipes). No automatic enabling/disabling of counters, drivers or privileged fallback. An unsupported/inaccessible device shows `—`.
- **Storage:** drive-letter volumes of type fixed/local, refreshed at most once per minute while open. Removable/network drives are not queried. Permissions/quotas can affect accessibility.
- **WSL:** these are Windows-host statistics. Linux processes appear through host VM processes such as `vmmemWSL`; individual Linux `claude`/`node` processes are not enumerated.
- No GPU, temperatures, watts, detailed CPU topology or WSL per-process integration in this version.

First samples, counter resets, changed adapter identities or configured disk numbers, inaccessible processes and gaps longer than 12 seconds produce unavailable rates, not invented zeros. Graph x positions use actual timestamps; gaps are not bridged. Process identity includes creation time so PID reuse cannot inherit old CPU deltas. Display names are bounded to 96 Unicode characters plus an ellipsis; search uses the complete sampled executable name. Command lines, credentials, memory contents and transcripts are never read.

## Collection and overhead

Closed: the normal five-second provider interval reads CPU/RAM only. Open: the view requests detailed sampling two seconds after the provider becomes idle. No overlapping work or accumulating timer actions; no privileged helper or permanent daemon. Resource deltas, a bounded process snapshot and up to 60 history observations persist under:

```text
%LOCALAPPDATA%\Illium\cache\activity-monitor\state.json
```

The directory inherits the user's profile permissions. State is bounded to 4 MiB, locked across configuration generations and atomically replaced. Output is capped at 60 KiB, below Illium's 64 KiB limit. Corrupt/obsolete cache data is discarded. `ILLIUM_APPLET_CACHE_PATH` can select a separate **directory** for tests.

Read-only diagnostics: `activity-monitor.exe --diagnose` reports per-collector microseconds, without process names. Each normal response also includes `collector_ms` (not shown in the popup). On the development machine the native work took roughly 1–3 ms for a basic read and 15–55 ms for a detailed read. **End-to-end process launch was much slower**, commonly around one second and occasionally over ten seconds in native fixture runs. The two-second interval is therefore not a guaranteed sampling period. Rates/graphs use measured time, and a slower launch never blocks Illium's UI. PDH disk queries were deliberately rejected after measuring >1 second of initialization alone; the direct disk query took below a millisecond.

## Build and install

Requires Rust 1.89+ to build. The installed executable requires no Rust, Python or PowerShell runtime.

On Windows, from `collector/`:

```powershell
cargo build --release --locked
```

From WSL with cargo-xwin and the same cross toolchain used for Illium:

```sh
cd activity-monitor/collector
PATH="$HOME/.local/llvm19/bin:$PATH" cargo xwin build \
  --target x86_64-pc-windows-msvc --release --locked
cd ..
python3 -B install.py --config /mnt/c/Users/YOUR_USER/.config/illium
```

Use the actual Windows `ILLIUM_CONFIG_HOME` if overridden. Python 3.11+ is only needed for this WSL installer. It validates the PE architecture, stages the complete applet outside the watched configuration tree, writes an absolute Windows provider command, saves `bar.toml` under `~/.local/state/illium-applet-collection/backups/activity-install-*`, then replaces CPU/memory entries with one `activity-monitor` at the first replaced position. Other bar entries, comments outside the changed arrays, theme, wallpaper and Claude configuration remain untouched. Complex/multiline arrays are refused instead of reformatted. An existing applet is never overwritten. No Illium rebuild/restart is needed.

For a manual Windows installation, copy `applet.toml`, `view.slint`, `icon.svg`, `README.md`, `LICENSE` and the built `activity-monitor.exe` to the applet directory. Set `command` to the executable's **absolute Windows path**, back up `bar.toml`, then replace its `cpu`/`memory` entries with `activity-monitor`.

Optional manifest settings:

```toml
[settings]
interface = "Wi-Fi" # exact alias; empty means first up physical interface
# Windows disk number, not a volume letter
disk = 0
```

For upgrades, back up the whole installed directory first. Preserve its absolute command and any chosen interface/disk settings. Do not run the fresh installer over an existing installation.

To undo a fresh installation: remove `activity-monitor` from the bar and restore the previous CPU/memory entries, then remove the applet directory. Restore the backed-up whole `bar.toml` only if no other bar edits have been made since. The private cache can then be deleted separately.

## Tests

```sh
cd activity-monitor/collector
cargo test --locked
PATH="$HOME/.local/llvm19/bin:$PATH" cargo xwin clippy \
  --target x86_64-pc-windows-msvc --all-targets --locked -- -D warnings
cd ..
python3 -B -m unittest discover -s tests -v
xvfb-run -a python3 -B tests/preview.py /tmp/activity-preview
```

Preview fixtures require Slint viewer 1.12.1 and Pillow for development only. They exercise dark/light, the long process table at 100%/150% scale, unavailable data, confirmation and a reduced popup size, with no provider execution. X11/XTest interaction in the disposable Xvfb display verifies row selection and the keyboard confirmation shortcut; a pixel assertion ensures graphs actually render. Slint's software renderer does not render `Path`; graphs intentionally use axis-aligned rectangles, not silently invisible path items.

Run `tests/native.ps1 -Collector <exe>` on Windows for bounded read-only live fixtures (dedicated temporary cache). To additionally test termination, build `cargo ... build --example sleeper`, then pass `-Sleeper <sleeper.exe>`. **Only that newly spawned disposable child is ever terminated.** Tests also simulate stale PID creation data and ensure the child survives the rejected action; no existing user process is killed.
