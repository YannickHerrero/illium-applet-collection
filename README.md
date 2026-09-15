# Winarchy applet collection

Optional, independently installed applets for [Winarchy](https://github.com/YannickHerrero/winarchy). This repository does not modify or vendor the Winarchy engine.

## Activity Monitor

[`activity-monitor/`](activity-monitor/README.md) combines the CPU and RAM bar modules into a themed Windows dashboard: real resource histories, network/disk rates, local storage and a searchable process table with identity-checked termination. A small native Rust collector runs without admin rights or a permanent service. CPU/RAM continue at a slower cadence while closed; process and I/O enumeration stop.

Build its Windows collector, then use **its separate installer**:

```sh
python3 activity-monitor/install.py --config /mnt/c/Users/<WindowsUser>/.config/winarchy
```

It backs up `bar.toml`, replaces only CPU/memory entries and leaves Claude's relay/settings alone. See its README for precise metric scopes, measured startup overhead and safe rollback instructions.

## Claude usage

`claude-usage/` displays Claude Code's **account quota**, not context-window fullness or locally estimated token costs. The initial data source is the official Claude Code statusline JSON (`rate_limits.five_hour` and `rate_limits.seven_day`).

A WSL relay preserves your existing statusline output and writes only quota percentages, reset timestamps and receipt timestamps to a Windows-readable snapshot. No OAuth tokens, cookies, API keys, transcript contents, project paths or account email are read or stored by the relay/applet. No additional inference is generated. An optional bounded CLI probe fetches Fable through Claude Code's experimental usage control API; Claude Code handles any authentication and usage request itself.

**Limits:** Claude Code must supply the fields during an active authenticated session. Merely leaving an idle CLI open does not guarantee fresh server data. Missing data never becomes 0%, expired windows never remain current, and a weekly quota never substitutes for the 5-hour bar value. The statusline source does not provide per-model quotas. A separate CLI probe supplies Fable when available; subscription badges, other model quotas and dollar spending are not fabricated.

The relay assumes one Claude account across your WSL sessions. Clear the snapshot when switching accounts. The source receipt time is not an independently verified server measurement time.

## Install

See [Claude usage setup and limitations](claude-usage/README.md). From WSL:

```sh
python3 install.py --windows-home /mnt/c/Users/<WindowsUser>
```

This preserves the current statusline, backs up settings, and adds the applet to the installed Windows bar. It never modifies the Winarchy source repository.

## Development

Claude Usage uses Python 3.11+ (standard library) for its WSL relay/setup and Windows PowerShell 5.1 for its provider. Activity Monitor uses Rust 1.89+ to build a standalone Windows executable, with Python only for installation. Both use Slint 1.12.1 views. Keep all generated data and private settings out of Git.

Atomic commits must use `YannickHerrero <yannick.herrero@proton.me>`. No remote or publication is configured automatically.

## Attribution

Independent, unofficial integration; not affiliated with Anthropic. Claude is an Anthropic trademark. The Claude silhouette comes from Simple Icons (CC0), whose declared source is claude.ai. See [icon provenance and trademark notice](claude-usage/ICON-SOURCE.md). Its color follows the active Winarchy theme.

Reference: https://code.claude.com/docs/en/statusline#rate-limit-usage
