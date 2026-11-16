# `noesis curate`

Turn work into records of the knowledge store (Neo4j), and retry what failed. Flow:
[curate workflow](../workflows/curate.md). The store must be initialised (`noesis store init`,
see [record.md](record.md)).

| Command | Does | Arguments and options |
|---|---|---|
| `curate brief` | Ask the curator what in a work brief is worth keeping, then store it as records: `experience` and `knowledge` proposals whose sources are the brief's commits and session. Running it again on the same work writes nothing new. | `--brief-file <file>` (required, work-brief JSON, see [example](../examples/work-brief.json)); `--max-attempts <n>` curator runs before giving up (default 2); `--park / --no-park` park the brief when every attempt fails (default park); `--no-related` skip the related-record lookup (the curator gets none); `--dry-run` judge and show the outcomes, write and park nothing |
| `curate apply` | Store candidates you wrote as records, without calling the curator. Any flawed entry fails the whole call before anything is written; the redacted payload is kept so it can be fixed and applied again. | `--decisions-file <file\|->` (required, JSON `{"candidates": [...]}`, the curator's entry shape; `-` reads stdin); `--session <id>` recorded as a source (default: the session of the running agent harness); `--commit <sha>` repeatable; `--dry-run` |
| `curate retry <ticket>` | Retry a parked curation from the stage it failed at, in the foreground. A saved plan is never judged again, and steps already written return their original ids. | `ticket` from `curate parked`; `--all` retries every parked ticket, but only lists them until `--yes` is also given (exit 1 if any retry fails again) |
| `curate parked` | List submissions whose curation failed and wait for `retry`, oldest first. It reads only the local inbox, so it works with the store down. | |

Every command takes `--json`.

## Results

`brief`, `apply` and `retry` print one result per submission. With `--json`, under `result`:

| Field | Meaning |
|---|---|
| `ticket` | Inbox ticket; `null` on a dry run |
| `submission_key` | Stable key of the submission; the same work gives the same key |
| `dry_run`, `replayed` | `replayed` is true when the plan was registered before this invocation |
| `items[]` | One per candidate, in plan order: `ordinal` (from 1, never shifts; a skipped candidate keeps its place), `candidate`, `kind`, `outcome` (`recorded`, `proposed`, `revised`, `successor_proposed`, `skipped`), `record_id`, `type`, `revision`, `status`, `target_record_id`, `assertion_ids`, `reason` |
| `sources[]` | The sources every write cites: `work_brief`, `commit`, `agent_session` |
| `related_lookup` | `state` (`used` or `disabled`) and `pending_changes` (index lag) |

`curate parked --json` prints `{"parked": [{ticket, stage, reason, repository, parked_at,
age_seconds}]}`; `curate retry --all` prints `{executed, tickets[], failed}`.

## Defaults and limits

- Capture never accepts: curated records are proposals (`status: proposed`) until a person
  reviews them (`noesis review ...`).
- A second process on the same ticket waits up to 10 seconds for its lock, then fails with
  `KNOWLEDGE_142`.
- The old Notes state (`<state dir>/notes/parked` and `apply-failed`) is **not** migrated.
  Drain it with the previous noesis version (`notes parked`, `notes retry`) before upgrading.

## Settings

| Variable | Default | |
|---|---|---|
| `NOESIS_CURATOR_CLAUDE_BIN` | `claude` | the Claude Code executable |
| `NOESIS_CURATOR_MODEL` | empty | model alias or id; empty uses Claude Code's default |
| `NOESIS_CURATOR_MAX_BUDGET_USD` | `0.5` | spend cap of one run |
| `NOESIS_CURATOR_TIMEOUT_SECONDS` | `300` | time limit of one run |
| `NOESIS_CURATOR_RETRY_SECONDS` | `30` | pause before the automatic retry |
| `NOESIS_CURATOR_RELATED_LOOKUP` | `required` | `required` parks the brief when the lookup cannot answer; `off` gives the curator no related records |
| `NOESIS_CURATOR_SYSTEM_PROMPT_FILE` | unset | your own system prompt instead of the packaged one |

## Errors

| Code | When | Do |
|---|---|---|
| `KNOWLEDGE_141_CURATOR_FAILED` | the curator is missing, timed out, failed or answered something unusable | check `NOESIS_CURATOR_CLAUDE_BIN`, then `curate retry` |
| `KNOWLEDGE_142_CURATION_INBOX_FAILED` | the local inbox cannot be read, written or locked | check the state dir; retry |
| `KNOWLEDGE_241_CURATION_FAILED` | curation failed and its ticket is parked (metadata names the ticket and cause) | fix the cause, then `curate retry <ticket>` |
| `KNOWLEDGE_242_PARKED_CURATION_NOT_FOUND` | no ticket has that id | `curate parked` |
| `KNOWLEDGE_243_CURATION_REJECTED` | an `apply` payload has flawed entries; nothing was written | fix the entries and apply again |
| `KNOWLEDGE_244_BRIEF_ALREADY_INGESTED` | the plan is registered in the store but its local plan is gone | nothing new to write; check the records |
| `KNOWLEDGE_245_RELATED_LOOKUP_UNAVAILABLE` | the lookup is required and cannot answer | `noesis index sync`, or `--no-related` / `NOESIS_CURATOR_RELATED_LOOKUP=off` |
| `INTERFACE_001_INVALID_WORK_BRIEF` | the brief file does not match the contract | fix the file |
