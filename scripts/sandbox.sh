#!/usr/bin/env bash
# A disposable playground for noesis: its own vault, state, profiles and git repository.
# Nothing here touches ~/.config/noesis, your real vault, or Claude Code's settings.
#
# The sandbox is configured the way a real repository is: a committed `.noesis-config`
# selects the profile `sandbox`, which lives under the sandbox's own XDG config folder.
# Commands run from inside the sandbox, so the repository lookup is what gets exercised.
#
#   scripts/sandbox.sh init [--file PATH]   create the sandbox (idempotent); PATH = any new dir, git-initialized
#   scripts/sandbox.sh hook [live|dry-run]  simulate a Claude Code session: commit + Stop hook
#   scripts/sandbox.sh curate               run the real curator on docs/examples/work-brief.json
#   scripts/sandbox.sh shell [--file PATH]  print the lines that enter the sandbox in this shell
#   scripts/sandbox.sh clean [--file PATH]  delete the sandbox (only if it holds the sandbox marker)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SANDBOX="${SANDBOX:-$ROOT/.sandbox}"
# --file PATH (any position) points the sandbox at PATH instead of .sandbox/.
POSITIONAL=()
while [ $# -gt 0 ]; do
  case "$1" in
    --file)
      P="${2:?--file needs a path}"
      case "$P" in "~"|"~/"*) P="$HOME${P#\~}" ;; esac  # make's quoting stops the shell expanding ~
      SANDBOX="$(realpath -m "$P")"
      shift 2 ;;
    *) POSITIONAL+=("$1"); shift ;;
  esac
done
set -- ${POSITIONAL[@]+"${POSITIONAL[@]}"}
MARKER="$SANDBOX/.noesis-sandbox"
CONFIG_HOME="$SANDBOX/config"          # XDG_CONFIG_HOME for every sandbox command
PROFILE_NAME="sandbox"
ROOT_PROFILE="$CONFIG_HOME/noesis/profiles/$(basename "$SANDBOX")/$PROFILE_NAME.env"

# Run noesis from inside DIR with the sandbox's config home (never the real one).
noesis_in() {
  local dir="$1"; shift
  (cd "$dir" && XDG_CONFIG_HOME="$CONFIG_HOME" uv run --project "$ROOT" noesis "$@")
}
noesis() { noesis_in "$SANDBOX" "$@"; }

write_profile() {
  mkdir -p "$(dirname "$1")"
  cat > "$1" <<ENV
NOESIS_VAULT_DIR=$SANDBOX/vault
NOESIS_STATE_DIR=$SANDBOX/state
NOESIS_CAPTURE_MIN_FILES=1
NOESIS_CAPTURE_MIN_LINES=1
NOESIS_CAPTURE_DEBOUNCE_SECONDS=0
NOESIS_CURATOR_MODEL=haiku
NOESIS_CURATOR_MAX_BUDGET_USD=0.2
ENV
}

init() {
  # Refuse to take over a non-empty directory that is not already a sandbox.
  if [ -d "$SANDBOX" ] && [ -n "$(ls -A "$SANDBOX")" ] && [ ! -f "$MARKER" ]; then
    echo "refusing: $SANDBOX is not empty and is not a sandbox (no $MARKER). Pick a new path." >&2
    exit 1
  fi
  mkdir -p "$SANDBOX/vault" "$SANDBOX/state"
  [ -f "$MARKER" ] || : > "$MARKER"
  [ -f "$ROOT_PROFILE" ] || write_profile "$ROOT_PROFILE"
  [ -f "$SANDBOX/.noesis-config" ] || printf 'profile = %s\n' "$PROFILE_NAME" > "$SANDBOX/.noesis-config"
  if [ ! -d "$SANDBOX/.git" ]; then
    git -C "$SANDBOX" init -q
    printf 'vault/\nstate/\nconfig/\n.noesis-sandbox\nrepo-*/\nrepo-*.jsonl\n' > "$SANDBOX/.gitignore"
    printf '# noesis playground\n\nThrowaway repo for testing noesis by hand.\n' > "$SANDBOX/README.md"
    git -C "$SANDBOX" add . && git -C "$SANDBOX" -c user.name=sandbox -c user.email=sandbox@example.com \
      commit -qm "chore: init sandbox"
  fi
  echo "sandbox: $SANDBOX (profile: $ROOT_PROFILE, git: initialized)"
}

# One transcript line in Claude Code's JSONL format.
line() { python3 -c 'import json,sys; print(json.dumps({"message": json.loads(sys.argv[1])}))' "$1"; }

hook() {
  local mode="${1:-dry-run}" session="sandbox-$(date +%s)" repo="$SANDBOX/repo-$RANDOM"
  init
  mkdir -p "$repo" && git -C "$repo" init -q
  # The simulated repo selects the same profile, through its own .noesis-config.
  printf 'profile = %s\n' "$PROFILE_NAME" > "$repo/.noesis-config"
  write_profile "$CONFIG_HOME/noesis/profiles/$(basename "$repo")/$PROFILE_NAME.env"
  printf 'def lookup(token):\n    return CACHE.get(token)\n' > "$repo/app.py"
  printf '# demo\nTTL cache for tokens.\n' > "$repo/README.md"
  git -C "$repo" add . && git -C "$repo" -c user.name=sandbox -c user.email=sandbox@example.com \
    commit -qm "feat: add TTL cache for token lookups"
  local transcript="$repo.jsonl"
  {
    line '{"role":"user","content":"login is slow; cache token lookups"}'
    line '{"role":"assistant","content":[{"type":"text","text":"I chose an in-process TTL cache over Redis: single instance, no shared state. Gotcha: evict tokens on logout or they stay valid until the TTL expires."}]}'
    line '{"role":"assistant","content":[{"type":"tool_use","name":"Write","input":{"file_path":"app.py"}}]}'
    line '{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"git add . && git commit -m \"feat: add TTL cache\""}}]}'
  } > "$transcript"

  echo "== 1. switch capture on ($mode) for session $session"
  noesis_in "$repo" capture on --session "$session" --mode "$mode"
  echo "== 2. PostToolUse hook after the commit (what Claude Code sends on stdin)"
  printf '{"session_id":"%s","hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"git commit -m x"},"cwd":"%s","transcript_path":"%s"}' \
    "$session" "$repo" "$transcript" | noesis_in "$repo" hook claude-code
  echo "== 3. Stop hook at the end of the turn"
  printf '{"session_id":"%s","hook_event_name":"Stop","cwd":"%s","transcript_path":"%s"}' \
    "$session" "$repo" "$transcript" | noesis_in "$repo" hook claude-code
  if [ "$mode" = live ]; then
    echo "== waiting for the detached curator (up to 90s)..."
    for _ in $(seq 90); do
      find "$SANDBOX/state/capture/briefs/$session" -name '*.result.json' -size +0 2>/dev/null | grep -q . && break
      sleep 1
    done
  fi
  echo "== 4. journal"
  noesis capture runs --session "$session"
  echo "== 5. notes in the sandbox vault"
  noesis notes list
}

case "${1:-}" in
  init) init ;;
  hook) hook "${2:-dry-run}" ;;
  curate) init && noesis notes curate --brief-file "$ROOT/docs/examples/work-brief.json" ;;
  shell)
    init >/dev/null
    echo "cd $SANDBOX && export XDG_CONFIG_HOME=$CONFIG_HOME" ;;
  clean)
    if [ ! -f "$MARKER" ]; then
      echo "refusing: $SANDBOX has no $MARKER, so it is not a sandbox. Not deleting." >&2
      exit 1
    fi
    rm -rf "$SANDBOX" && echo "removed $SANDBOX" ;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
