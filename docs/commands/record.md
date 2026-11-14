# noesis record, noesis store

The record store (Neo4j, [ADR-0003](../adr/0003-knowledge-context-and-neo4j-record-store.md)):
capture knowledge and experiences, revise knowledge, read any record, and prepare the store. Set
up the database first: [store workflow](../workflows/store.md). Every command needs
`NOESIS_NEO4J_PASSWORD` (a user-side profile or the environment); `--help` and usage errors need
nothing and never connect.

## record capture

```text
noesis record capture --type knowledge  --title <text> --body <text|-> --subtype <slug>
                      (--source <kind>:<locator> | --source-id <id>)...
                      [--project <key>] [--tag <tag>]... --idempotency-key <key> [--json]
noesis record capture --type experience --body <text|-> [--subtype observation|outcome|failure]
                      (--source <kind>:<locator> | --source-id <id>)...
                      [--project <key>] [--occurred <ISO 8601>] [--session <id>]
                      [--environment <text>] --idempotency-key <key> [--json]
```

- `--idempotency-key` is required. The same key with the same request returns the first record and
  writes nothing (`result.replayed: true`); the same key with a different request fails with
  `KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED`. Choose the key deterministically from the work (for
  example `<session>-<commit sha>-decision`), so a retry repeats it.
- `--body -` reads the text from stdin. A body is never read implicitly, so a command cannot hang
  waiting for input.
- `--source` takes `<kind>:<locator>`, split at the first colon. Kinds: `file_version`
  (`vault://<vault_key>/<relative path>`), `commit` (full sha), `agent_session` (session id), `url`,
  `work_brief` (submission key). `--source-id <ULID>` cites a source that is already in the store
  (it must be in the active space: `KNOWLEDGE_205_REFERENCE_NOT_IN_SPACE`). Both repeat; at least
  one source is required for both record types.
- `--project` defaults to the name of the git repository of the working directory (a linked
  worktree uses its main repository); outside a repository the record is space-wide. An unknown
  project is created.
- Secrets in `--title` and `--body` are redacted before storing.
- The actor is not an option: it is `agent` (named `claude-code`, `codex` or the harness name, with
  its session when the harness exposes one) whenever a harness marker is in the environment
  (`CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `AI_AGENT`, `CODEX_THREAD_ID`, `CODEX_SESSION_ID`,
  `NOESIS_SESSION_ID`), otherwise the `user` (login name).
- Result: `record_id`, `record_type`, `revision`, `status` (`proposed`; knowledge only), `space_id`,
  `project_id`, `replayed`.

## record revise

```text
noesis record revise <id> --expected-revision <N> --idempotency-key <key>
                     [--title <text>] [--body <text|->] [--source ...] [--source-id <id>]... [--json]
```

Appends revision N+1 to proposed, graph-owned knowledge; what you leave out keeps its value.
A stale `--expected-revision` fails with `KNOWLEDGE_202_REVISION_CONFLICT`: run `record get`,
re-apply the change, retry with a new key. An experience (or any record that is not revisable)
fails with `KNOWLEDGE_207_RECORD_NOT_REVISABLE`. Result: `record_id`, `revision`, `status`,
`space_id`, `replayed`.

## record get

```text
noesis record get <id> [--revision <N>] [--json]
```

Any record of the active space by id (`KNOWLEDGE_201_RECORD_NOT_FOUND` for an unknown id, a
revision that does not exist, or another space's record). Result: the record with `type`, `space_id`,
`project_id`, `subtype`, `status`, `ownership`, `head_revision`, `applicability`, `actor`,
`revision` (the requested one, the head by default, with its `title`, `body`, `actor`, `sources`),
`sources`, `occurred_at`, `session`, `environment`, `created_at`, `updated_at`.

## store init

```text
noesis store init [--json]
```

Applies every registered schema step once and ensures the default space
(`NOESIS_KNOWLEDGE_SPACE`, default `personal`). It is idempotent. Result: `applied_steps` (this
call), `already_applied_steps` and `default_space` (`id`, `key`, `name`, `created`). There is no
numeric schema version; the steps are named (`core`, then the steps later chunks add). Before it
runs, the other commands fail with `KNOWLEDGE_204_STORE_NOT_INITIALISED`, naming the missing steps.

## Errors

| Code | Exit | When |
|---|---|---|
| `INTEGRATION_103_GRAPH_STORE_UNAVAILABLE` | 1 | Neo4j unreachable or connection lost. When `metadata.commit_outcome` is `unknown`, retry with the same idempotency key. |
| `INTEGRATION_104_GRAPH_STORE_AUTHENTICATION_FAILED` | 1 | Wrong `NOESIS_NEO4J_USER` or `NOESIS_NEO4J_PASSWORD`. |
| `INTEGRATION_105_GRAPH_STORE_BUSY` | 1 | Transient (deadlock, lock timeout); retry with the same key. |
| `INTEGRATION_106_GRAPH_STORE_CONSTRAINT_VIOLATED` | 1 | A uniqueness rule was broken outside the handled races (a defect). |
| `INTEGRATION_107_GRAPH_STORE_QUERY_FAILED` | 1 | The store rejected a query (a defect, not an outage). |
| `KNOWLEDGE_201_RECORD_NOT_FOUND` | 1 | Unknown id or revision, or another space's record. |
| `KNOWLEDGE_202_REVISION_CONFLICT` | 1 | Stale `--expected-revision`. |
| `KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED` | 1 | Same key, different request. |
| `KNOWLEDGE_204_STORE_NOT_INITIALISED` | 1 | A schema step is missing: run `noesis store init`. |
| `KNOWLEDGE_205_REFERENCE_NOT_IN_SPACE` | 1 | A `--source-id` is not in the active space. |
| `KNOWLEDGE_207_RECORD_NOT_REVISABLE` | 1 | `revise` on an experience, or on knowledge that is no longer proposed. |
| `KNOWLEDGE_208_SPACE_NOT_FOUND` | 1 | The configured space does not exist: run `noesis store init`. |

Exit 2 (usage, nothing read or written): a missing `--idempotency-key`, `--type`, `--title`,
`--subtype`, `--body` or source, a malformed `--source`, an unknown source kind or subtype.
A missing password exits 1 with `CORE_001_INVALID_CONFIGURATION` naming `NOESIS_NEO4J_PASSWORD`.
