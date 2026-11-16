# Recall

`noesis recall "task"` prepares a read-only briefing from Knowledge and Experience
records in the active space. It uses lexical search and live graph neighbours; semantic
search is optional and currently absent. It never synchronises an index or opens a source
file for evidence.

```sh
noesis recall "build a Python DDD CLI" --project demo
noesis recall "build a Python DDD CLI" --project demo --no-synthesis --json
noesis recall "review persistence" --runtime claude-code --runtime codex --limit 20
```

`--project` defaults to the git repository name. Unknown or unresolved projects produce
space-wide results and a warning. `--limit` is 1–50 (default 10). Runtime selection is
explicit flags, then the current agent session, then both supported runtimes.

`--no-synthesis` returns a deterministic digest and needs no model. Otherwise an isolated
Claude CLI process synthesizes redacted evidence, with no tools, MCP servers, settings
sources or saved session. A model failure exits 1 with `RETRIEVAL_102_BRIEFING_RUN_FAILED`
and suggests `--no-synthesis`; there is no silent fallback. Empty evidence exits 0.
Usage errors exit 2 and do not load settings or contact the store.

The JSON envelope contains `synthesis` (`briefing`, `digest`, `no_evidence`), `scope`,
`records`, `constraints`, `decisions`, `context`, `unconfirmed`, `unsupported`, `tools`,
`tools_state`, `index`, `capabilities`, `warnings` and `next_steps`.
Every supported section item cites an exact `{record_id, revision}` body successfully read
from the graph. Citations demonstrate a read, not that a claim follows from the source.
Unknown or wrong-revision citations go to `unsupported`; proposed or superseded guidance
cannot support authoritative constraints or decisions. Whole bodies that exceed the evidence
budget, disappear or change during the bounded consistency check are omitted with reasons.
This check is not a database snapshot guarantee.

Text explicitly labels PROPOSED and SUPERSEDED records. Proposed `origin:migrated` records
suggest `noesis review accept --tag origin:migrated --all --yes`; recall never runs it.
Recommendations come only from scoped live `recommends` assertions attached to evidence.
Each runtime observation is retained; only observed `available` makes a tool usable.
Unknown or unprobed tools are not verified. Missing capabilities are explicit; a store
failure always fails the command, including during availability preparation.

Source-sharing, incoming/outgoing LINKS_TO and EMBEDS discover candidates without implying
endorsement. Accepted supersession can add a separately cited terminal successor and preserve
backlinks, with original targets and paths retained in `records[].discovery`. Traversal is
bounded to eight supersession hops and fifty visited records per seed, with diagnostics for
cycles or exhausted budgets. Edges are never rewritten and outgoing links are not inherited.

Settings (all positive numeric values):

| Variable | Default |
| --- | --- |
| `NOESIS_RETRIEVAL_BRIEFING_TIMEOUT_SECONDS` | `60` |
| `NOESIS_RETRIEVAL_BRIEFING_MAX_BUDGET_USD` | `0.50` |
| `NOESIS_RETRIEVAL_BRIEFING_MAX_EVIDENCE_CHARS` | `24000` |
| `NOESIS_RETRIEVAL_BRIEFING_CLAUDE_BIN` | `claude` |

The character budget counts combined redacted titles and whole bodies. Secret masking is a
best-effort safety net. Model input excludes discovery metadata and store credentials.

Discovery is deliberately conservative on very dense graphs: the adapter over-fetches at most
50 combined distinct targets per search seed before successor expansion, then applies the
requested final target limit. It reports incomplete discovery if that combined query budget
is exceeded. A further 400-path expansion budget per seed bounds highly connected supersession
DAGs; exhausting it reports a warning and does not guess a terminal. These safety bounds can
omit otherwise relevant successor-derived candidates; they never create authoritative claims.
