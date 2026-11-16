# Command reference

What each `noesis` command takes and prints. For what happens inside a command, layer by
layer, see [workflows](../workflows/README.md); for the ideas behind the CLI, see the
[CLI primer](../cli-primer.md).

| Group | Page |
|---|---|
| `capture on \| off \| status \| runs` | [capture.md](capture.md) |
| `curate brief \| apply \| retry \| parked` | [curate.md](curate.md) |
| `record capture \| revise \| get`, `store init` | [record.md](record.md) |
| `search` | [search.md](search.md) |
| `index sync \| rebuild \| status` | [index.md](index.md) |
| `catalog register \| revise \| list \| show \| check \| scan` | [catalog.md](catalog.md) |
| `hook claude-code`, `integrate claude-code install \| uninstall \| status` | [agent-integration.md](agent-integration.md) |
| `doctor`, `config show \| init`, `skills list \| get`, `update check` | [setup.md](setup.md) |

## Every command

- `--json` prints one envelope instead of text: `{"ok": true, "result": {...}}` on success,
  `{"ok": false, "error": {"code", "title", "message", "metadata", "next_steps"}}` on failure.
- `--help` describes the command.
- Top-level `noesis --env-file <file>` overrides the configuration file (default: the
  repository's `.noesis-config` profile, else `~/.config/noesis/.env`). `--version` prints the version.
- Exit codes: `0` ok, `1` the operation failed, `2` invalid command line.
