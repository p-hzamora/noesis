# noesis record, noesis store

The record store (Neo4j, [ADR-0003](../adr/0003-knowledge-context-and-neo4j-record-store.md)):
revise knowledge, read any record, and prepare the store. Set
up the database first: [store workflow](../workflows/store.md). Every command needs
`NOESIS_NEO4J_PASSWORD` (a user-side profile or the environment); `--help` and usage errors need
nothing and never connect.

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
numeric schema version; the steps are named (`core`, `review`, `change_feed`, `knowledge_fulltext`, `retrieval_index`, `catalog`, then the steps later chunks add). Before it
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
| `KNOWLEDGE_061_INVALID_CATALOG_NAME`, `KNOWLEDGE_062_INVALID_CATALOG_PREREQUISITE`, `KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND`, `KNOWLEDGE_262_CATALOG_ENTRY_ALREADY_EXISTS` | 1 | Catalog commands: see [catalog.md](catalog.md). |

Exit 2 (usage, nothing read or written): a missing `--idempotency-key`, `--type`, `--title`,
`--subtype`, `--body` or source, a malformed `--source`, an unknown source kind or subtype.
A missing password exits 1 with `CORE_001_INVALID_CONFIGURATION` naming `NOESIS_NEO4J_PASSWORD`.
