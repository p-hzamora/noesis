# `noesis notes`

Curate work into notes, retry failed curations, search and list. Flows:
[curate](../workflows/notes-curate.md), [apply](../workflows/notes-apply.md),
[retry, parked, search, list](../workflows/notes.md), [recall](../workflows/notes-recall.md).

| Command | Does | Arguments and options |
|---|---|---|
| `notes curate` | Ask the curator what in a work brief is worth keeping, then store it as auto notes. An existing auto note is updated in place; a manual note is never touched. | `--brief-file <file>` (required, work-brief JSON, see [example](../examples/work-brief.json)); `--max-attempts <n>` curator runs before giving up (default 2); `--park / --no-park` park the brief when every attempt fails (default park); `--dry-run` show paths and outcomes without writing |
| `notes apply` | Store note drafts you wrote as auto notes, without calling the curator. | `--decisions-file <file\|->` (required, JSON `{"decisions": [...]}`; `-` reads stdin); `--session <id>` recorded on the notes; `--commit <sha>` repeatable; `--dry-run` |
| `notes retry <ticket>` | Retry a parked curation once, in the foreground. | `ticket` from `notes parked` |
| `notes parked` | List work briefs whose curation failed and wait for `retry`. | |
| `notes search <text>` | Find notes by free text, best match first. | `--scope`, `--repo`, `--limit <1-100>` (default 10) |
| `notes recall <task>` | Brief a task from the notes: search, read the best ones, write what matters with sources. | `--scope`, `--repo`, `--limit <1-20>` (default 5); `--budget-tokens <n>` rough briefing size, 0 is unlimited (default 1000); `--synthesis / --no-synthesis` (`--no-synthesis` lists the best notes and calls no model) |
| `notes list` | List notes, optionally of one scope and one origin. | `--scope`, `--repo`, `--origin manual\|auto` |

New notes never go in an `auto/` folder and never overwrite: a taken path gets `-2`, `-3`.
