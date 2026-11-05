# Workflows per command

What happens, layer by layer, when each `noesis` command runs. Read
[architecture.md](../architecture.md) first for the folder layout; these pages follow the calls.

Legend used in every diagram:

| Layer | Lives in |
|---|---|
| CLI | `src/noesis/interfaces/cli/` (commands, `bootstrap/`, `responses/`, `output.py`) |
| Handler | `bounded_context/<context>/application/handlers/` or `diagnostics/application/` |
| Domain | `bounded_context/<context>/domain/` (aggregates, value objects, specifications, policies) |
| Adapter | `bounded_context/<context>/infrastructure/` (files, git, `claude`, settings JSON) |

1. [Every command: the common path](common-path.md)
2. [The whole pipeline: from a commit to a note](capture-pipeline.md)
3. [`capture on | off | status | runs`](capture.md)
4. [`hook claude-code` (run by Claude Code, never by hand)](hook-claude-code.md)
5. [`notes curate --brief-file F`](notes-curate.md)
6. [`notes retry | parked | search | list`](notes.md)
7. [`integrate claude-code install | uninstall | status`](integrate-claude-code.md)
8. [`doctor`, `config`, `skills`](setup.md)
