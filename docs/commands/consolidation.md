# Consolidation

`noesis consolidation` proposes one new Knowledge record (the successor) that covers two to
ten overlapping accepted Knowledge records (the originals), and links it to each original with
a proposed `supersedes` assertion. Nothing is merged, deleted or rewritten: originals, their
revisions, Sources, assertions, LinkSets and LINKS_TO/EMBEDS edges stay exactly as they were.
Acceptance goes through the normal review rules; proposing never accepts anything.

```sh
noesis consolidation scan --project demo --json
noesis consolidation propose --member 01A... --member 01B... \
  --title "Retry policy" --body "..." --rationale "Both describe the same retry rule" \
  --idempotency-key retry-merge-1
noesis consolidation show 01C...
noesis consolidation list --project demo --state materialised
noesis consolidation accept 01C... --yes --idempotency-key retry-merge-1-accept
noesis consolidation reject 01C... --reason-kind distinct --reason "Different scopes" \
  --yes --idempotency-key retry-merge-1-reject
```

| Command | Options | Result |
| --- | --- | --- |
| `scan` | exactly one of `--record ID`, `--project KEY`, `--global`; `--limit` (hits per anchor, default 5, max 50), `--anchors` (default 20, max 100), `--cursor`, `--include-dismissed` | candidate groups per anchor with `rank`/`found_by`, open conflicts, `semantic_state`, `suppressed_count`, `excluded_unaccepted_migrated`, `next_cursor` |
| `propose` | `--member ID` (2–10), `--title`, `--body` (or stdin), `--rationale`; `--tag`, `--source` repeatable; `--reconsider ID`; `--dry-run`; `--idempotency-key` | consolidation id, member revisions, successor and assertion ids with status, `requires`, `decidable_by_caller`, `link_policy` |
| `show ID` | – | the consolidation, current progress, produced records, dismissal, `link_policy`, who may decide |
| `list` | exactly one of `--project KEY`, `--global`; `--state`, `--limit` (default 20, max 100), `--cursor` | `items`, `next_cursor` |
| `accept ID` | `--reason`, `--yes`, `--idempotency-key` | preview, or `steps` per target with outcome and error code, `progress` |
| `reject ID` | `--reason-kind distinct\|poor_draft\|other`, `--reason` (required); `--yes`, `--idempotency-key` | preview, or `effects` per target, `progress` |

## Members and scanning

Members are accepted Knowledge, not effectively superseded or retracted, all in one space with
the same subtype and the same project (or all space-wide). Experiences, assertions, Sources and
catalog entries cannot be members. A proposed `origin:migrated` record must be reviewed first:
the error and the scan's `excluded_unaccepted_migrated` count point to
`noesis review accept --tag origin:migrated --all --yes`, which consolidation never runs.

`scan` is read-only. It ranks neighbours from lexical search and the shared graph (shared
Sources and links); semantic search is optional and reported in `semantic_state`
(`ready`, `lagging`, `absent` or `unavailable`). A missing semantic index is a normal result.
Ranks order candidates; they do not measure semantic equivalence, and no similarity score is
claimed. Pairs dismissed as `distinct` at the same revisions are hidden unless
`--include-dismissed` is passed.

## Propose

The caller writes the successor's title, body and rationale; there is no drafter. Stored text
is redacted. The successor carries the union of the originals' Sources plus any `--source`, and
each `supersedes` assertion cites evidence independent of both endpoints (the original's Sources
and live supporting records). Structural links are never turned into evidence. An agent cannot
accept an assertion without independent evidence; a user can still review it.

Each member can belong to one open consolidation. A pair dismissed as `distinct` is refused
until either record gets a new revision, or `--reconsider <dismissed-id>` names that dismissal.

## Accept and reject

Without `--yes` both commands preview their steps and write nothing. With `--yes` they need an
idempotency key, apply the review authority rules (project consolidations: agent or user;
space-wide: user only, at an interactive terminal), then call the normal review handlers:
accept the successor, then each assertion; or retract the proposals. Accepting makes the
originals superseded through the existing review effects; recall then cites the successor
separately and keeps the originals' links and provenance. Recommendations and supports are not
transferred to the successor.

Once acceptance starts, the members stay reserved, even if the successor is later retracted.
Rejecting releases them; `distinct` remembers the judged pairs, `poor_draft` and `other` do not.

## Partial failures and retries

Each step is its own transaction, so a failure can leave earlier steps committed. The command
then exits 1 with `KNOWLEDGE_295_CONSOLIDATION_PARTIALLY_APPLIED` (or the step's own error),
listing each step as completed (`done`, `accepted`, `rejected`, `already_accepted`, `already_retracted`, `left_accepted`), `failed` or `not_run`, the consolidation id and the retry command.
A store outage stops the run at once (later steps `not_run`, `progress: unknown`).
Nothing is rolled back. Running the same command with the same idempotency key resumes the
frozen plan and converges on the same records; a different payload under the same key is
refused. Members that changed since the plan was frozen stop the resume for manual review.

Consolidation bookkeeping writes no change-feed event and no link changes; the record and
review effects append their usual `created` and `status_changed` events.
