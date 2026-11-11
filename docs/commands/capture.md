# `noesis capture`

Switch capture on or off for an agent session and inspect what it did. Flow:
[capture](../workflows/capture.md), [pipeline](../workflows/capture-pipeline.md).

All four commands take `--session <id>`: the agent session id (in Claude Code skills
`${CLAUDE_SESSION_ID}`). Omit it when the harness exposes its own (`NOESIS_SESSION_ID`, Codex);
`capture on` then prints the id to pass back.

| Command | Does | Options |
|---|---|---|
| `capture on` | Switch capture on. A repeat call keeps pending work and changes nothing. | `--parent <session>` (sub-agent: own state, inherits the parent's mode, shown by `runs --children`); `--mode live\|dry-run` (live curates into the vault, dry-run only stores briefs; default keeps the session's mode, live for a new one) |
| `capture off` | Switch capture off. Pending work is kept. | |
| `capture status` | Show whether capture is on and what is pending. | |
| `capture runs` | Show the session journal: marks, hand-overs, skips and curation results. | `--limit <1-1000>` most recent entries (default 50); `--children` also the sub-agent sessions |
