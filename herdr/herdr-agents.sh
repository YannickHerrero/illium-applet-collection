#!/bin/bash
# herdr-agents.sh: every herdr session and the agents inside it, as one JSON
# object for the Winarchy view. Read-only: it never focuses, stops or deletes
# anything, and it ignores any action argument Winarchy appends.
#
# Winarchy runs it through `wsl.exe`, so it starts from a non-interactive shell
# without the user's PATH additions; herdr's default install location is added
# here.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

# Ceilings on what other processes may hand this script: a wedged server, a
# session.json somebody grew by accident or more sessions than anyone meant to
# keep must not decide how much memory the poll costs.
SESSIONS_BYTE_CAP=$((2 * 1024 * 1024))
SNAPSHOT_BYTE_CAP=$((2 * 1024 * 1024))
SESSION_FILE_CAP=$((1 * 1024 * 1024))
TOTAL_BYTE_CAP=$((8 * 1024 * 1024))
SESSION_COUNT_CAP=200
AGENT_COUNT_CAP=500

json_string() {
  printf '%s' "${1-}" | jq -Rs .
}

fail() {
  printf '{"ok":false,"error":%s,"bar_label":"","title":"Herdr","sessions":[]}\n' "$(json_string "$1")"
  exit 0
}

# Measured rather than read off an exit status: under pipefail a `head` that
# closes the pipe early makes a good read look like a failure.
over_byte_cap() {
  [ "$(printf '%s' "$1" | wc -c)" -gt "$2" ]
}

valid_session_name() {
  [[ "${1-}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]
}

readable_file() {
  [[ -f "$1" && ! -L "$1" ]]
}

# `--session` is left off for the default session: passing it by name would
# address a named session that happens to be called "default".
snapshot_for() {
  local name="$1" is_default="$2" out
  if [[ $is_default == true ]]; then
    out=$(herdr api snapshot 2>/dev/null | head -c "$((SNAPSHOT_BYTE_CAP + 1))") || true
  else
    out=$(herdr --session "$name" api snapshot 2>/dev/null | head -c "$((SNAPSHOT_BYTE_CAP + 1))") || true
  fi
  [[ -n $out ]] || return 1
  over_byte_cap "$out" "$SNAPSHOT_BYTE_CAP" && return 1
  printf '%s' "$out"
}

# A stopped session has no server to ask, but herdr keeps its layout in
# session.json, which still names the workspaces and their directories.
saved_labels_for() {
  local dir="$1"
  readable_file "$dir/session.json" || return 1
  over_byte_cap "$(head -c "$((SESSION_FILE_CAP + 1))" -- "$dir/session.json" 2>/dev/null || true)" \
    "$SESSION_FILE_CAP" && return 1
  jq -c --arg home "$HOME" '[.workspaces[]?
      | (.custom_name
         // (if (.identity_cwd // "") == $home then "~"
             else (.identity_cwd // "" | split("/") | last) end))
      | select(. != null and . != "")]
    | unique' -- "$dir/session.json" 2>/dev/null
}

main() {
  local tool
  for tool in herdr jq; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is not installed in WSL"
  done

  local sessions_json
  sessions_json=$(herdr session list --json 2>/dev/null | head -c "$((SESSIONS_BYTE_CAP + 1))") || true
  [[ -n $sessions_json ]] || fail "could not reach herdr"
  over_byte_cap "$sessions_json" "$SESSIONS_BYTE_CAP" && fail "session list too large to read safely"

  # Snapshots and saved labels are collected as name-keyed objects assembled as
  # text: one jq start per session would cost more than everything else here,
  # and valid_session_name has already refused anything but letters, digits,
  # dot, dash and underscore in the key.
  local snapshots='' saved='' name is_default running dir snap labels
  local seen=0
  while IFS=$'\t' read -r name is_default running dir; do
    [[ -n $name ]] || continue
    valid_session_name "$name" || continue
    (( seen >= SESSION_COUNT_CAP )) && continue
    (( ${#snapshots} + ${#saved} > TOTAL_BYTE_CAP )) && continue
    seen=$(( seen + 1 ))
    if [[ $running == true ]]; then
      snap=$(snapshot_for "$name" "$is_default") || continue
      snapshots+="${snapshots:+,}\"$name\":$snap"
      continue
    fi
    labels=$(saved_labels_for "$dir") || continue
    [[ -n $labels ]] || continue
    saved+="${saved:+,}\"$name\":$labels"
  done < <(printf '%s' "$sessions_json" |
    jq -r '.sessions[]? | "\(.name)\t\(.default // false)\t\(.running // false)\t\(.session_dir // "")"' 2>/dev/null)
  snapshots="{$snapshots}"
  saved="{$saved}"
  printf '%s' "$snapshots" | jq -e . >/dev/null 2>&1 || snapshots='{}'
  printf '%s' "$saved" | jq -e . >/dev/null 2>&1 || saved='{}'

  printf '%s' "$sessions_json" | jq -c \
    --argjson snapshots "$snapshots" \
    --argjson saved "$saved" \
    --argjson agentCap "$AGENT_COUNT_CAP" '
    def rank: if . == "blocked" then 0 elif . == "done" then 1
              elif . == "working" then 2 elif . == "idle" then 3 else 4 end;
    # herdr'"'"'s words, except that "idle" is the ordinary resting state and
    # reads like a fault, and "blocked" says what to do about it.
    def word: if . == "blocked" then "needs you" elif . == "idle" then "ready" else . end;
    def plural($n; $one): "\($n) \($one)" + (if $n == 1 then "" else "s" end);
    # herdr puts a spinner glyph in front of a working agent'"'"'s title, so the
    # same task would move left and right as it ticks over.
    def clean: (sub("^[^0-9A-Za-z\u00C0-\u024F\u0370-\u03FF]+"; "") | sub("^\\s+"; "") | sub("\\s+$"; "")) as $s
               | if $s == "" then . else $s end;
    def display: if . == "default" then "Shared session"
                 elif test("^[0-9]{1,3}$") then "Workspace \(.)"
                 else . end;
    [.sessions[]?
     | select(.name | type == "string" and test("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"))
     | .name as $name
     | (.running // false) as $running
     | ($running and ($snapshots | has($name))) as $answered
     | (($snapshots[$name].result.snapshot) // {}) as $snap
     | ($snap.agents // []) as $agents
     | ([$agents[] | .agent_status // "unknown"] | map(rank) | min // 4) as $loudest
     | ([$agents[] | select(.agent_status == "blocked")] | length) as $blocked
     | ([$agents[] | select(.agent_status == "done")] | length) as $done
     | ([$agents[] | select(.agent_status == "working")] | length) as $working
     | {
         name: $name,
         display: ($name | display),
         running: $running,
         is_default: (.default // false),
         agent_total: ($agents | length),
         blocked: $blocked,
         done: $done,
         working: $working,
         agent_count: (if $answered then plural($agents | length; "agent") else "" end),
         summary_state: (if $running | not then "stopped"
                         elif $answered | not then "unreachable"
                         elif $loudest == 0 then "blocked"
                         elif $loudest == 1 then "done"
                         elif $loudest == 2 then "working"
                         elif ($agents | length) == 0 then "empty"
                         else "idle" end),
         summary: (if $running | not then "stopped"
                   elif $answered | not then "no answer"
                   elif $loudest == 0 then "\($blocked) needs you"
                   elif $loudest == 1 then "\($done) done"
                   elif $loudest == 2 then "\($working) working"
                   elif ($agents | length) == 0 then "no agents"
                   else "ready" end),
         projects: ((if $running
                     then (($snap.workspaces // []) | map(.label // "") | map(select(length > 0)) | unique)
                     else ($saved[$name] // []) end)
                    | if length == 0 then (if $running then "" else "nothing saved" end)
                      else join("  ·  ") end),
         agents: ($agents
                  | map({title: ((.terminal_title_stripped // .terminal_title // "") | clean),
                         status: (.agent_status // "unknown"),
                         label: ((.agent_status // "unknown") | word)})
                  | map(select(.title != ""))
                  | sort_by(.status | rank)
                  | .[0:$agentCap])
       }]
    | sort_by([(if .is_default then 0 else 1 end), (if .running then 0 else 1 end), (.name | ascii_downcase)])
    | ([.[] | select(.running)] | length) as $servers
    | ([.[] | .agent_total] | add // 0) as $agents
    | ([.[] | .blocked] | add // 0) as $blocked
    | {ok: true,
       error: "",
       bar_label: (if $servers == 0 then "" elif $blocked > 0 then "!\($servers)" else "\($servers)" end),
       title: "Herdr (\(plural($servers; "server")), \(plural($agents; "agent")))",
       sessions: (map(del(.agent_total, .blocked, .done, .working)))}
  ' 2>/dev/null || fail "unexpected output from herdr"
}

main
