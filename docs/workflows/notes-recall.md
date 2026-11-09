# `notes recall TASK`

Prepares an agent (or a person) for a task from what the vault already knows. noesis searches
the notes, reads the best ones in full, and has an agent write a **briefing**: what to respect,
what was decided and why, the traps, the open questions, and which notes say so. It is read-only
and never writes to the vault.

```mermaid
sequenceDiagram
    autonumber
    participant Cmd as notes recall
    participant H as RecallNotesHandler
    participant Q as RecallQueryBuilder (service)
    participant RR as INoteReadRepository<br/>(NOESIS_SEARCH_BACKEND)
    participant Pol as RecallRankingPolicy (domain)
    participant M as SecretRedactor / BriefingGrounder (services)
    participant A as IRecallAgent<br/>(NOESIS_RECALL_RUNTIME)

    Cmd->>Cmd: area from --repo/--area; else the whole vault, preferring the cwd git repository's notes
    Cmd->>H: RecallNotesQuery(task, area, prefer_area, limit, budget_tokens, synthesize)
    H->>Q: task
    Q-->>H: one query per keyword (else NoRecallTermsError NOTES_204, exit 1)
    loop each query
        H->>RR: search(query, area, min(limit*3, 10))
        RR-->>H: notes in engine order (+ backend)
    end
    H->>H: merge by reciprocal rank, rarer keywords weigh more
    H->>Pol: rank(candidates, today)
    Pol-->>H: paths, most useful first
    alt no candidate
        H-->>Cmd: synthesis "no_evidence", no agent call
    else --no-synthesis
        H-->>Cmd: RecallDigestDto, trimmed to the budget, no model
    else synthesis (default)
        loop top `limit` paths
            H->>RR: read_note(path, area)
            RR-->>H: the whole note (an unreadable one becomes a warning)
        end
        H->>M: mask secrets, cut each note to its share of the input limit
        H->>A: brief(task, notes, target_tokens)
        A-->>H: draft briefing (RecallAgentFailedError NOTES_103 on failure)
        H->>M: check every citation against the notes read
        H-->>Cmd: RecallDigestDto(briefing, entries, warnings)
    end
```

## What you get

Default output is the briefing as Markdown, then the notes it was written from:

```
# Recall briefing: <task>

<summary>

## Constraints          one bullet per rule, each ending with [`path`, ...]
## Decisions
## Gotchas
## Context
## Open questions
## Inferences (the agent's reasoning; the notes do not state these)
## Unsupported (dropped from the sections above: no valid citation)
## Not covered by the notes
## Notes read
```

- Constraints, decisions, gotchas and context each cite the notes that state them. noesis checks
  every cited path against the notes that were actually read. A path that was not read is removed,
  and a statement left with no valid citation moves to **Unsupported** instead of staying in a
  grounded section.
- **Inferences** are the agent's own conclusions; they are labelled as such and cite the notes
  they build on, if any.
- **Not covered** says what the task needs that the notes do not hold. The agent is told to say so
  rather than fill the gap.
- The text mode footer (`model:`, `considered N, omitted M`, `backend:`, `warning:` lines) tells
  you how the briefing was made.

## Finding the notes

Obsidian's search (`search_simple`) only returns notes that contain **every** word of the query
(checked against a live vault: the whole task sentence found nothing, `cv-generator` alone found
24 notes). So recall does not send the sentence. It:

1. Keeps keywords of 3+ letters without stopwords. A hyphenated name such as `cv-generator` is kept
   whole and also split (`cv-generator`, `generator`); at most 12 queries, earliest first.
2. Searches each keyword on its own (up to `min(limit*3, 10)` hits each).
3. Merges the hits by reciprocal rank. Each query counts for `1 / hits`, so a keyword few notes
   contain outweighs a generic one, and a note found by several keywords rises.
4. Re-ranks with the policy below and takes the top `--limit`.

| Signal | Effect |
|---|---|
| Kind | gotcha = decision > glossary > run; a note with no kind is neutral |
| Recency | halves every 90 days of `updated`, never below a floor; an unknown date gets the floor |
| Origin | manual outranks auto |

Ties break by merged rank, then path. A note is only down-weighted, never dropped.

## What the agent can see and do

- **Nothing but what noesis sends.** noesis reads the notes through the search backend, masks
  secrets, and passes their text on stdin. The agent runs with no tools, no MCP servers, no user or
  project settings, no hooks, no saved session and a spend cap (`--tools ""`,
  `--strict-mcp-config`, `--setting-sources ""`, `--no-session-persistence`,
  `--max-budget-usd`). It cannot search, read or write anything else.
- **Scope.** With `--repo`/`--area`, only notes under that folder are read. Without them the whole
  vault is searched and notes under the cwd repository rank first (outside a git repository there
  is no preference); a scoped search that finds nothing says which folder it searched in
  `warnings`. `read_note` refuses `..`, absolute paths, hidden folders, non-Markdown files,
  anything outside the area when one is set, and a symlink that leaves the vault.
- **Secrets.** Private-key blocks, well-known token shapes (`sk-…`, `ghp_…`, `AKIA…`, `xox…`),
  bearer tokens and `password|secret|token|api_key = value` assignments become `[REDACTED]` before
  sending, and the count is reported as a warning. This is a safety net, not a guarantee: a secret
  with no recognisable shape or name passes. `NOESIS_OBSIDIAN_MCP_TOKEN` is removed from the
  agent's environment.
- **Untrusted text.** Notes are data; the packaged instructions tell the agent not to obey them,
  and a note cannot close its own `<note>` block. With no tools, an injected note can at worst
  skew the briefing, which is why citations are checked.
- **Bounded work.** At most `--limit` notes (1..20, default 5), `NOESIS_RECALL_MAX_INPUT_CHARS`
  (default 60000) shared among them (a longer note is cut, with a marker and a warning),
  `NOESIS_RECALL_TIMEOUT_SECONDS` (120), `NOESIS_RECALL_MAX_BUDGET_USD` (0.25), and one agent call.
  `--budget-tokens` (default 1000, `0` for no target) is the length the agent is asked to aim for;
  it is an instruction, not a hard cut, so a briefing can exceed it.

## The agent's instructions

The reusable prompt is a packaged Markdown file, separate from any briefing:
[`recall_system.md`](../../src/noesis/bounded_context/notes/infrastructure/outbound/recall/prompts/recall_system.md).
It defines the inputs, the fields, and the grounding rules (cite exact paths, write only what the
notes say, keep names and numbers verbatim, label inferences, report gaps, never repeat secrets).
`default_recall_system_prompt()` loads it. There is no setting to replace it yet.

## Choosing the runtime, model and effort

Two separate settings, both in `.env` / the environment ([`.env.example`](../../.env.example)):

| Variable | Meaning |
|---|---|
| `NOESIS_RECALL_RUNTIME` | The program that runs the agent. Only `claude-cli` (headless Claude Code, `claude -p`) exists. New runtimes implement `IRecallAgent` and add a case in `build_recall_agent`. |
| `NOESIS_RECALL_MODEL` | Model handed to the runtime verbatim; empty uses the runtime's default. noesis keeps no model list. |
| `NOESIS_RECALL_EFFORT` | Effort handed to the runtime verbatim; empty uses the runtime's default. |
| `NOESIS_RECALL_CLAUDE_BIN`, `_MAX_BUDGET_USD`, `_TIMEOUT_SECONDS`, `_MAX_INPUT_CHARS` | Run limits. |

Example (Claude Haiku 5.5, low effort):

```bash
NOESIS_RECALL_MODEL=claude-haiku-5-5
NOESIS_RECALL_EFFORT=low
```

Verified against Claude Code 2.1.294: `claude -p --model claude-haiku-5-5 --effort low` runs and the
run reports `claude-haiku-5-5` as the model used (the alias `haiku` resolves to the same model),
while an unknown id such as `claude-haiku-9-9` is rejected (`unrecognized_model`) and surfaces as
`NOTES_103`. `claude --help` lists `--effort` levels `low`, `medium`, `high`, `xhigh`, `max`, and
`low` ran with Haiku 5.5 without error. The CLI also accepted `--effort bogus` without complaint,
so for the `claude-cli` runtime noesis rejects any other value with
`CORE_001_INVALID_CONFIGURATION` when a briefing is about to run (`--no-synthesis` and the other
`notes` commands are unaffected). I did not verify that effort changes Haiku 5.5's behaviour; noesis
only passes it on. The model the CLI reports is shown as `briefing.model`.

## Flags and output

`--limit` (1..20, default 5), `--budget-tokens` (default 1000, `0` none), `--repo`/`--area`,
`--synthesis/--no-synthesis`, `--json`.

`--json` result:

| Field | Meaning |
|---|---|
| `synthesis` | `briefing`, `no_evidence` (nothing found, no agent ran) or `digest` (`--no-synthesis`) |
| `briefing` | `summary`, `constraints`, `decisions`, `gotchas`, `context`, `open_questions`, `inferences`, `unsupported` (each `{text, sources}`), `not_covered`, `model`, `markdown`; null unless `synthesis` is `briefing` |
| `entries` | `kind`, `title`, `path`, `date`, `snippet`: the notes read (briefing) or the notes worth reading (digest), best first |
| `considered`, `omitted` | notes the search returned and ranking saw; how many are not in `entries` |
| `backend` | the backend that answered (`filesystem` after a fallback) |
| `warnings` | notes unreadable, text cut, secrets masked, statements set aside |
| `notice` | only after a fallback |

`--no-synthesis` keeps the earlier digest: ranked pointers and snippets, trimmed to
`--budget-tokens`, and no model, no cost, no `claude` needed.

| Situation | Result |
|---|---|
| no note found | exit 0, `synthesis: no_evidence`, `entries` empty, text `no relevant notes`; no agent call |
| no keywords left in the task | `NOTES_204_NO_RECALL_TERMS`, exit 1 |
| blank task, `--limit` or `--budget-tokens` out of range | usage error, exit 2 |
| vault not configured | `CORE_002_VAULT_NOT_CONFIGURED`, exit 1 |
| Obsidian unreachable, vault set | files searched and read, exit 0, `Obsidian MCP unreachable, searched files instead` as `notice` |
| Obsidian unreachable, no vault | `INTEGRATION_102_OBSIDIAN_MCP_FAILED`, exit 1 (never `no_evidence`) |
| agent missing, failed, timed out, wrong model or effort, or unusable answer | `NOTES_103_RECALL_AGENT_FAILED`, exit 1, `metadata.candidates` lists the notes that would have been read, next step `--no-synthesis` |
| notes found but none readable | `NOTES_102_NOTE_STORAGE_FAILED`, exit 1 |
| some notes unreadable | exit 0, a `warnings` entry per note |

A failed briefing is never reported as success and never silently degraded to a digest.

## Limits

- The agent cannot search on its own: it sees the top `--limit` notes noesis chose. If the right
  note ranks lower, raise `--limit` (a higher limit reads more notes and costs more).
- Citations are checked to name a note that was read, not that the note supports the claim.
- Obsidian's score sign and order were not verified; noesis keeps the engine's order.
- There is no recall check in `noesis doctor` yet.

Back to [workflows](README.md).
