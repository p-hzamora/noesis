#!/usr/bin/env bash
# A disposable playground for noesis: its own vault, state, config and git repository.
# Nothing here touches ~/.config/noesis, your real vault, or Claude Code's settings.
#
#   scripts/sandbox.sh init                 create .sandbox/ (idempotent)
#   scripts/sandbox.sh hook [live|dry-run]  simulate a Claude Code session: commit + Stop hook
#   scripts/sandbox.sh curate               run the real curator on docs/examples/work-brief.json
#   scripts/sandbox.sh shell                print the env line to use noesis against the sandbox
#   scripts/sandbox.sh clean                delete .sandbox/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SANDBOX="${SANDBOX:-$ROOT/.sandbox}"
ENV_FILE="$SANDBOX/noesis.env"
noesis() { uv run --project "$ROOT" noesis --env-file "$ENV_FILE" "$@"; }

init() {
  mkdir -p "$SANDBOX/vault" "$SANDBOX/state"
  [ -f "$ENV_FILE" ] || cat > "$ENV_FILE" <<ENV
NOESIS_VAULT_DIR=$SANDBOX/vault
NOESIS_STATE_DIR=$SANDBOX/state
NOESIS_CAPTURE_MIN_FILES=1
NOESIS_CAPTURE_MIN_LINES=1
NOESIS_CAPTURE_DEBOUNCE_SECONDS=0
NOESIS_CURATOR_MODEL=haiku
NOESIS_CURATOR_MAX_BUDGET_USD=0.2
ENV
  echo "sandbox: $SANDBOX (config: $ENV_FILE)"
}

# One transcript line in Claude Code's JSONL format.
line() { python3 -c 'import json,sys; print(json.dumps({"message": json.loads(sys.argv[1])}))' "$1"; }

hook() {
  local mode="${1:-dry-run}" session="sandbox-$(date +%s)" repo="$SANDBOX/repo-$RANDOM"
  init
  mkdir -p "$repo" && git -C "$repo" init -q
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
  noesis capture on --session "$session" --mode "$mode"
  echo "== 2. PostToolUse hook after the commit (what Claude Code sends on stdin)"
  printf '{"session_id":"%s","hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"git commit -m x"},"cwd":"%s","transcript_path":"%s"}' \
    "$session" "$repo" "$transcript" | noesis hook claude-code
  echo "== 3. Stop hook at the end of the turn"
  printf '{"session_id":"%s","hook_event_name":"Stop","cwd":"%s","transcript_path":"%s"}' \
    "$session" "$repo" "$transcript" | noesis hook claude-code
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
  noesis knowledge list
}

case "${1:-}" in
  init) init ;;
  hook) hook "${2:-dry-run}" ;;
  curate) init && noesis knowledge curate --brief-file "$ROOT/docs/examples/work-brief.json" ;;
  shell) init >/dev/null && echo "export NOESIS_ENV_FILE=$ENV_FILE" ;;
  clean) rm -rf "$SANDBOX" && echo "removed $SANDBOX" ;;
  *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
