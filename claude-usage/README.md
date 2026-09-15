# Claude usage applet

English-language Winarchy panel for the official Claude Code statusline quota fields. The bar shows **5-hour account quota used**, not context utilization. The popup shows 5-hour and weekly quotas, reset times, a linear pace marker and source freshness.

## Requirements

- Winarchy with external Slint applets and Unicode system-font rendering.
- Windows PowerShell 5.1 (built in).
- Python 3.11+ under WSL, using only the standard library.
- An authenticated Claude Code session that actually emits `rate_limits`. Documentation lists Pro/Max and supported gateway accounts; organization-managed accounts must be checked on real data. No subscription type is inferred from a local credential file.
- One Claude account across participating WSL sessions. This integration does not inspect account identities.

The applet and relay do not read authentication files, refresh tokens, scrape Desktop cookies, scan transcripts, send prompts or make authenticated HTTP requests. They do not require an Anthropic API key, Node.js, a paid API balance, an administrator shell or a new daemon.

## Install from WSL

```sh
cd ~/dev/winarchy-applet-collection
python3 install.py --windows-home /mnt/c/Users/<WindowsUser>
```

If Windows uses `WINARCHY_CONFIG_HOME`, pass its WSL-visible path with `--config-home`. If Claude Code uses another configuration folder, pass `--claude-home` (the installer also respects `CLAUDE_CONFIG_DIR`). The default Windows local-app-data location is assumed; for a redirected profile, configure the relay's `cache` and the applet's `[settings] cache_path` to the same Windows-readable file.

The installer:

1. Refuses to overwrite an existing applet/relay.
2. Backs up Claude settings and the bar configuration under `~/.local/state/winarchy-applet-collection/backups/` with private permissions.
3. Copies the complete applet to Windows `~/.config/winarchy/applets/claude-usage/`.
4. Copies `bridge.py` to `~/.local/share/winarchy-applets/claude-usage/` in WSL.
5. Wraps the current Claude statusline command, preserving its options and exact stdout/exit status.
6. Adds only `claude-usage` to the bar's right-hand array. All other settings are retained.

No Winarchy repository changes, rebuild, daemon restart or token copying are needed. A single-line `right` array is required for automatic bar editing; other layouts fail safely and can be configured manually. Concurrent settings edits cancel setup; failed live writes are rolled back when the files still match the installer's own writes.

Use a Claude Code session normally after setup. Active sessions may pick up settings automatically; restart a session if it still uses the previous statusline command. The applet shows `—` until real quota fields arrive. No demo data is installed as live usage.

## Data flow and freshness

```text
Claude Code statusline JSON
  -> WSL relay (whitelisted quota fields only)
  -> %LOCALAPPDATA%/Winarchy/cache/claude-usage/snapshot.json
  -> PowerShell provider (local read every 30 seconds)
  -> Winarchy icon, label and popup
```

The cache is deliberately outside the watched Winarchy configuration. Concurrent relay writes are serialized and published atomically. Unchanged values write at most once per minute; a changed quota can publish immediately. Missing fields do not make a previous reading look fresh. Receipt timestamps are maintained separately for each window.

- A snapshot receipt is **not** an independent server measurement. Claude Code can resend a cached reading. Simply leaving an idle CLI open does not force new server data.
- After ten minutes without a valid update, values are marked `~` and the panel explains that they are stale.
- Once the 5-hour reset passes, the bar returns to `—` until another valid reading arrives; it does not invent a fresh 0%.
- The weekly window never substitutes for a missing session value.
- **Reload snapshot** / `r` rereads the local file. It does not request new quotas from Anthropic.
- **Open usage page** opens `https://claude.ai/settings/usage` in the default browser.

The pace marker compares percentage consumed with the elapsed fraction of a 5-hour/7-day window. The +/-3 point tolerance is a display convention, not an Anthropic limit or forecast. Weekly and session quotas overlap; do not add them together.

This documented source supplies neither model-specific rows nor a dollar balance/extra-usage budget. The applet therefore does not fabricate Sonnet/Opus/Fable rows, a subscription badge or a financial section.

## Troubleshooting / removal

If the bar remains `—`, verify that the selected Claude Code session exposes `rate_limits` and that its settings use the installed relay. A context-window percentage is not a substitute. No login or credential extraction should be added as an automatic fallback.

On account changes, close old-account sessions and delete only the snapshot before using the new account. Otherwise an old session could still publish values; this first version intentionally does not support multiple accounts.

For removal, restore only the original `statusLine` entry from the settings backup (preserving unrelated subsequent settings), remove `claude-usage` from the bar, then remove the applet directory, relay directory and its quota cache. Do not blindly restore an entire old settings/bar file over newer edits.

Installed relay/applet files are copies. Git edits do not silently change your live installation. For updates, back up the installed folders and replace the corresponding code files; do not rerun the initial installer over an existing setup.

## Tests

```sh
python3 -B -m unittest discover -s claude-usage/tests -v
```

On Windows (no authentication or network calls):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File claude-usage/tests/provider.ps1
```

Optional Linux UI smoke tests require `slint-viewer` 1.12.1, Xvfb and Pillow, for development only:

```sh
xvfb-run -a python3 -B claude-usage/tests/preview.py /tmp/claude-applet-preview
```

References:
- https://code.claude.com/docs/en/statusline#rate-limit-usage
- https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use
