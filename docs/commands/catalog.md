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
`declared_version`, `prerequisites`, `location`, `capabilities`, `manifest_digest`, `origin`).
`origin` is `registered` for an entry stated by hand and `discovered` for one `catalog sync` made;
`manifest_digest` is the hash of the manifest it was synced from (absent for hand-made entries).
`show` adds the revision's `number`, `actor`,
`created_at` and `sources` (ids). Unknown ref, revision, or another space's entry:
`KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND`. `noesis record get <id>` also reads an entry (`type:
catalog_entry`).

## check, scan

```text
noesis catalog check [<id|kind:name>...] [--kind <kind>] [--runtime claude-code|codex]... [--json]
noesis catalog scan [--runtime claude-code|codex]... [--json]
```

Both read the store first (Neo4j down: `INTEGRATION_103`, nothing probed), then look at each
runtime and `PATH` read-only, executing nothing and reading each manifest's frontmatter only. They exit 0 whenever they
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

## sync

```text
noesis catalog sync [--runtime claude-code|codex]... [--dry-run] [--json]
```

Registers and revises catalog entries for the skills and agents the runtimes have installed, so
search can use their stored description and prerequisites. It reads the store first (Neo4j down:
`INTEGRATION_103`, nothing probed), then each runtime read-only; same folders and runtime default
as `check` and `scan`. It never deletes or retires an entry.

Per installed artifact it reads the manifest's frontmatter (first 16 KiB, YAML safe load): the
`description`, the optional `metadata.noesis.requires` (a list of `<kind>:<name>`) and a `sha256`
of the whole file. The body is never stored. An unreadable or oversize frontmatter leaves the
description empty (the purpose becomes `(no description)` on a new entry) and the digest is still
computed.

| Entry in the catalog | Action |
|---|---|
| none | `registered`: `origin: discovered`, `--location` of the form `<runtime>:<name>`, prerequisites from `requires`, a `manifest` source holding the digest. |
| same digest, description and version | `unchanged`. |
| different digest, description or version | `revised` (a new revision; a hand-made entry keeps its `origin` and, when the manifest declares none, its prerequisites). |
| the artifact is no longer installed | listed in `not_installed`; the entry and its history stay. |

An artifact whose name breaks the catalog name grammar, or whose manifest cannot be read at all,
is listed in `skipped` with a `reason` (`invalid_name`, `manifest_unreadable`; `write_conflict`
when a concurrent write got there first) and does not fail the command. A second run with nothing
changed writes nothing. When two runtimes have the same name, one entry is kept; it counts as
`unchanged` in the second runtime, and does not flip between their copies.

`--dry-run` reports the same decisions without writing (`entry_id` and `revision` stay null).
Each write uses the idempotency key `catalog-sync:<runtime>:<kind>:<name>:<digest>` (a revise adds
`:r<head revision>`). Result: `dry_run`, `runtimes` (per runtime `runtime`, `host`, `observed_at`,
`registered[]`, `revised[]`, `unchanged` (a count), `not_installed[]`, `skipped[]`,
`unreadable_kinds[]`) and `next_steps`. It exits 0 whenever it ran.

## Errors

| Code | Exit | When |
|---|---|---|
| `KNOWLEDGE_061_INVALID_CATALOG_NAME` | 1 | The name breaks the grammar. |
| `KNOWLEDGE_062_INVALID_CATALOG_PREREQUISITE` | 1 | A malformed `--requires` or ref, or an entry requiring itself. |
| `KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND` | 1 | Unknown entry or revision, or another space's. |
| `KNOWLEDGE_262_CATALOG_ENTRY_ALREADY_EXISTS` | 1 | The kind and name exist in the space: `catalog revise`. |
| `KNOWLEDGE_202`, `KNOWLEDGE_203`, `KNOWLEDGE_204`, `INTEGRATION_103` | 1 | As in [record.md](record.md); 204 names the `catalog` step when `store init` has not added it. |

Exit 2 (usage, nothing read): a missing required option, no `--source`, an empty `--purpose` or
`--location`, an unknown `--kind` or `--runtime` (also for `sync`), a non-integer `--expected-revision`.
