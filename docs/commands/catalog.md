# noesis catalog

The catalog records capabilities agents may use (`skill`, `agent`, `cli_tool`, `mcp_server`) in the
record store, and checks what is installed right now. Set up the store first
([record.md](record.md), `noesis store init`, which adds the `catalog` step). Every command needs
`NOESIS_NEO4J_PASSWORD`; `--help` and usage errors need nothing and never connect.

A catalog entry says what a capability is for, never that it is available. `check` and `scan` look
at the machine and store nothing.

## register, revise

```text
noesis catalog register --kind skill|agent|cli_tool|mcp_server --name <name> --purpose <text>
                        --location <text> [--declared-version <v>] [--requires <kind>:<name>]...
                        --source <kind>:<locator>... --idempotency-key <key> [--json]
noesis catalog revise <id|kind:name> --expected-revision <N> [--purpose <text>] [--declared-version <v>]
                      [--requires <kind>:<name>]... [--location <text>]
                      --source <kind>:<locator>... --idempotency-key <key> [--json]
```

- Name: 1 to 128 characters of ASCII letters, digits, `.`, `_`, `-`, `:`, starting with a letter or
  digit; case-sensitive, stored as typed (`<plugin>:<name>` for plugin artifacts, the executable name
  for a CLI tool). `--location` is where the definition is version-controlled (URL, repository path,
  `plugin@marketplace`), never an install path.
- `--requires` takes `<kind>:<name>` split at the first colon; the prerequisite need not be
  cataloged, but may not be the entry itself.
- `--source` and `--idempotency-key` work as in [record.md](record.md). Secrets in `--purpose` are
  redacted.
- `revise` is a partial update: only the options given change. `--declared-version ""` clears the declared
  version; a lone `--requires ""` clears the prerequisites; a non-empty `--requires` list replaces
  them. A revise that changes nothing writes nothing and returns the head number (a stale
  `--expected-revision` is still `KNOWLEDGE_202_REVISION_CONFLICT`).
- Result: `id`, `kind`, `name`, `revision`, `space_id`, `replayed`.

## list, show

```text
noesis catalog list [--kind <kind>] [--name-prefix <text>] [--json]
noesis catalog show <id|kind:name> [--revision <N>] [--json]
```

`list` result: `entries` (`id`, `space_id`, `kind`, `name`, `head_revision`, `purpose`,
`declared_version`, `prerequisites`, `location`). `show` adds the revision's `number`, `actor`,
`created_at` and `sources` (ids). Unknown ref, revision, or another space's entry:
`KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND`. `noesis record get <id>` also reads an entry (`type:
catalog_entry`).

## check, scan

```text
noesis catalog check [<id|kind:name>...] [--kind <kind>] [--runtime claude-code|codex]... [--json]
noesis catalog scan [--runtime claude-code|codex]... [--json]
```

Both read the store first (Neo4j down: `INTEGRATION_103`, nothing probed), then look at each
runtime and `PATH` read-only, executing nothing and reading names only. They exit 0 whenever they
ran. Without `--runtime`: the runtime of this session (Codex markers, then Claude Code markers),
else `claude-code` then `codex`. The folders read: Claude Code's `$CLAUDE_CONFIG_DIR` (default
`~/.claude`) and the project's `.claude` (working directory); Codex's `$CODEX_HOME` (default
`~/.codex`).

`check` result: `runtimes`, one block per runtime with `runtime`, `host`, `observed_at`,
`observations`, `summary` and `unreadable_kinds`, plus `next_steps`. An observation has `status`
(`available`, `unavailable`, `unknown`) and `reason`:

| Status | Reason | Meaning |
|---|---|---|
| `available` | `none` | Installed, prerequisites present. `version_drift: true` when declared and installed versions differ (still available). |
| `unavailable` | `not_installed` | No installed artifact of that kind and exact name. |
| `unavailable` | `prerequisite_missing` | `missing_prerequisites` lists them. |
| `unknown` | `probe_failed` | The runtime's folder or registry could not be read. |
| `unknown` | `kind_not_probed` | MCP servers (always) and Codex agents have no probe. |

`next_steps` names the `location` of each unavailable entry and `noesis catalog revise` for each
drifted one. `scan` result: per runtime `uncataloged` (installed, no entry), `version_drift`,
`not_installed` and `unreadable_kinds`, plus `next_steps`; it registers nothing.

## Errors

| Code | Exit | When |
|---|---|---|
| `KNOWLEDGE_061_INVALID_CATALOG_NAME` | 1 | The name breaks the grammar. |
| `KNOWLEDGE_062_INVALID_CATALOG_PREREQUISITE` | 1 | A malformed `--requires` or ref, or an entry requiring itself. |
| `KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND` | 1 | Unknown entry or revision, or another space's. |
| `KNOWLEDGE_262_CATALOG_ENTRY_ALREADY_EXISTS` | 1 | The kind and name exist in the space: `catalog revise`. |
| `KNOWLEDGE_202`, `KNOWLEDGE_203`, `KNOWLEDGE_204`, `INTEGRATION_103` | 1 | As in [record.md](record.md); 204 names the `catalog` step when `store init` has not added it. |

Exit 2 (usage, nothing read): a missing required option, no `--source`, an empty `--purpose` or
`--location`, an unknown `--kind` or `--runtime`, a non-integer `--expected-revision`.
