# Agent Orchestrator for Winarchy

A read-only Winarchy applet listing every coding agent visible from WSL in one place: the agents running in [herdr](https://herdr.dev) panes and the [Multica](https://multica.ai) agents currently working on a task. The bar tells you how many need an answer or are working; the popup lets you filter by state. Nothing in the popup focuses, cancels or kills anything.

Inspired by [meviusisback/agent-orchestr](https://github.com/meviusisback/agent-orchestr) for Omarchy, MIT. Its status vocabulary, filter tabs and secret redaction are followed; the Hyprland window switching, process termination, transcript parsing and the OMP, Hermes, Grok and Orca sources have no Winarchy equivalent here and were left out. The static fallback icons are original drawings. The animated Glitchcat atlas and state mapping come from [OmaPets](https://github.com/yesmeck/OmaPets); see [ATTRIBUTION.md](ATTRIBUTION.md) and [OMAPETS-LICENSE](OMAPETS-LICENSE).

This applet is independent of the `herdr/` applet of this collection, which shows herdr workspaces; both can be installed side by side.

## What it shows

Glitchcat replaces the bar icon and reacts to the agents: resting, working, waiting for input, celebrating a completion, or reacting to an explicit failure. The label remains the number of agents needing you, otherwise the number working, otherwise empty. Clicking the pet still opens the existing agent list. If the sprite pack cannot load, the original state-dependent SVG icons are used.

The popup has a headline (**2 agents need you**, **3 agents working**, **7 agents idle**), one line per source with its reachability, then filter tabs (**All**, **Working**, **Needs you**, **Done**, **Idle**) and one card per agent:

- the agent name (Claude, Pi, Codex for herdr; the Multica agent's name such as Yuqi) and a HERDR or MULTICA tag
- the title: herdr's terminal title, or the Multica issue identifier and title
- a detail line: the working directory and herdr workspace, or the Multica task kind and elapsed time
- the state: **needs you**, **working**, **done** or **ready**

States map onto each source's own words. Herdr: `blocked` is **needs you**, `done` means a pane finished while unfocused, `idle` reads **ready**. Multica shows only the agents whose task is `running`, always as **working**: queued, waiting, finished and failed tasks and resting agents are left out, so a Multica agent appears exactly while it works. Multica has no "question pending" task state: an agent that asks you something posts a comment and its task completes, which makes it disappear from the list.

Cards are ordered needs you, working, done, ready. The list refreshes every 3 seconds, independently of the local animation (one frame every 140 ms).

## Pet state events

The provider also emits `pet_state`: `idle`, `working`, `waiting`, `success`, or
`error`. Waiting takes precedence over every reaction. Observed working/waiting
agents that transition to done produce a five-second success reaction; explicit
Multica failures produce an eight-second error reaction. Otherwise the pet works
while any agent works, or rests. Simultaneous failures take precedence over
successes. Polling means a transient reaction expires on the next collected
snapshot after its deadline.

Herdr identity is its session and pane ID; Multica identity is server, workspace
and task ID. The first snapshot is a baseline, not a burst of celebrations.
Disappearing agents and unreachable sources do not imply success or failure.
A polling gap over 30 seconds resets the baseline. Very short tasks that begin
and end between polls can be missed. Multica `completed` means the task ended,
not necessarily that the agent's broader goal succeeded; pending questions
cannot be inferred from that status.

Only hashed identities, statuses and timestamps are atomically persisted, with
mode 0600, in `~/.local/state/winarchy-applet-collection/agent-orchestrator/pet.json`.
No prompts, transcripts, titles, credentials or project paths are cached.
An unreadable/corrupt cache resets the baseline; an unwritable cache disables
transient reactions without breaking the list. Terminal Multica results drive
reactions but remain excluded from popup cards. No agent hooks are installed.

## How it works

```text
herdr sockets (~/.config/herdr/herdr.sock, sessions/*/herdr.sock): session.snapshot
Multica local server (~/.multica/config.json): GET /api/agent-task-snapshot, /api/agents, /api/issues/<id>
  -> agents.py (Python 3 standard library, in WSL)
  -> wsl.exe -d <distribution> -- python3 <script>   (Winarchy provider, every poll)
  -> Winarchy icon, label and popup
```

The collector talks to herdr through the same socket API as `herdr api snapshot`, and to Multica through the same REST endpoints, headers and token as the `multica` CLI. It reads `~/.multica/config.json` for the server URL, workspace id and token; the token is only sent to that server and never written or printed. One snapshot call returns the workspace's active tasks; only the running ones are kept, and at most eight issue titles are fetched per poll. One poll takes about 0.2 s inside WSL.

Everything shown is plain text: control characters and spinner glyphs are stripped, Multica mention links are reduced to their label, and API keys, GitHub tokens, AWS keys and bearer tokens are redacted before display. Titles are cut at 160 characters, the list at 60 cards, and the output stays under Winarchy's 64 KiB provider limit.

A herdr server that does not answer, a stopped Multica daemon or a missing configuration turn the matching source line red or grey; the other source keeps working. A collector failure is shown in the popup instead of an empty list.

Requires `python3` in the WSL distribution. No herdr or Multica CLI is needed at poll time.

## Sprite packs

Requires Winarchy's animated applet support (commit `01aa606` or later).
`applet.toml` selects `sprite = "glitchcat.toml"`. The pack declares its PNG,
frame dimensions, grid, cadence, display height and state-to-animation mapping.
Winarchy knows nothing about Glitchcat specifically. Multiple packs can live
side by side in the applet folder: copy another pack and its PNG, then change
that one filename to switch. Configuration hot reload applies the change.
There is no pet picker or downloader yet.

Glitchcat is rendered in its original colors with nearest-neighbor sampling.
Its 28px logical display height is clamped to the available bar content height.
Use `display_height` in the pack to adjust it. There are no runtime image
conversion dependencies. To disable animation, remove `sprite` from the applet
manifest; the provider, counters and popup still work normally.

## Install from WSL

Upgrade/rebuild Winarchy first. Older builds reject the `sprite` manifest key;
remove that line if you need to keep using an older build with static icons.

```sh
cd ~/dev/winarchy-applet-collection
python3 -B agent-orchestrator/install.py --windows-home /mnt/c/Users/<WindowsUser>
```

Pass `--config-home` for a Windows `WINARCHY_CONFIG_HOME` override and `--distribution` when herdr and Multica run in another distribution than the current one. The installer refuses to overwrite an existing installation, backs up `bar.toml` under `~/.local/state/winarchy-applet-collection/backups/`, copies the collector to `~/.local/share/winarchy-applets/agent-orchestrator/` in WSL, copies the applet to Windows `~/.config/winarchy/applets/agent-orchestrator/` with the distribution and absolute script path in its manifest, then appends `agent-orchestrator` to the bar's `right` array. Other bar entries and comments are preserved; a multiline array is refused instead of reformatted. Once Winarchy supports sprites, installing or switching a pack needs no further rebuild or restart.

To remove it, delete `agent-orchestrator` from the bar, then remove the applet directory and the WSL script directory. Restore the backed-up `bar.toml` only if no other bar edits were made since.

For upgrades, back up the installed applet outside Winarchy's configuration tree,
then replace `view.slint`, the three SVG files, `glitchcat.toml`, `glitchcat.png`,
`ATTRIBUTION.md`, `OMAPETS-LICENSE`, and the WSL `agents.py` script. Keep the
installed `applet.toml`, which carries your distribution and absolute script path;
add `sprite = "glitchcat.toml"` and change `interval` to `"3s"` at its top level.
Do not overwrite your provider command with the repository example.

## Tests

```sh
python3 -B -m unittest discover -s agent-orchestrator/tests -v
xvfb-run -a python3 -B agent-orchestrator/tests/preview.py /tmp/agent-orchestrator-preview
xvfb-run -a python3 -B agent-orchestrator/tests/preview_pet.py /tmp/pet-preview --shell-ui ../winarchy/ui/shell.slint
```

Collector tests run against a fake herdr socket and a fake Multica HTTP server in the test process; the previews require Slint viewer 1.12.1 and Pillow for development only and never run the collector. The pet preview uses the actual Winarchy bar and verifies changing frames at 1x, 1.5x and 2x scaling.
