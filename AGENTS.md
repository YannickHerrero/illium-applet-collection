# Working on this collection

- Never modify the sibling Winarchy repository for collection tasks.
- Make one atomic commit per logical change.
- Commit only as YannickHerrero <yannick.herrero@proton.me>; check both author and committer.
- Do not read or copy Claude credentials, cookies or transcripts. The base quotas come from official statusline fields. Fable may be queried through Claude Code's experimental get_usage control API with skip_behaviors=true, hooks/MCP/tools disabled, no prompt and bounded execution. Never replace this with direct OAuth calls.
- Preserve existing statusline output and user settings. Back up configuration before installation.
- Keep private runtime data, caches and backups outside the repository and outside Winarchy's watched configuration tree.
- User-facing applet strings are English. Preserve Unicode in user data.
