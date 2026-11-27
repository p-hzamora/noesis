# noesis

Capture finished agent work, curate what is worth keeping, and store it as knowledge records.

noesis watches coding-agent sessions (Claude Code today) for units of finished work such as
git commits. It asks an LLM curator which decisions, gotchas, and outcomes are worth
remembering, and stores them as proposed records in a Neo4j knowledge store, with the commits
and the session as sources. Capture never accepts a record; a person reviews them.

> Status: early development. See `docs/architecture.md` for the design and
> `CONTEXT.md` for the vocabulary.

## Install

```bash
curl -LsSf https://raw.githubusercontent.com/p-hzamora/noesis/main/install.sh | sh
noesis config init                       # writes ~/.config/noesis/.env
noesis doctor                           # checks folders, git, the curator CLI, and whether this checkout is behind origin
```

The installer uses `uv` if you have it, otherwise `pipx`, otherwise a private virtual
environment built with Python 3.14+. From a checkout, `./install.sh` installs that checkout;
`make install` does an editable install for development. Options, manual installs and
uninstalling: [docs/install.md](docs/install.md).

## Use it from Claude Code

```bash
npx skills add p-hzamora/noesis --skill noesis -g   # teach agents the CLI (or copy skills/noesis/)
noesis integrate claude-code install          # preview the hooks diff for ~/.claude/settings.json
noesis integrate claude-code install --yes    # write it (a timestamped backup is kept)
noesis doctor
```

Then, in a Claude Code session: "turn noesis capture on". The skill stub loads the
version-matched guide (`noesis skills get noesis`) and runs
`noesis capture on --session <this session>`. Commits and turn ends are captured by the
hooks from then on; `noesis capture runs --session <id>` shows what happened.

`noesis integrate claude-code uninstall --yes` removes every noesis hook and nothing else.

## Configuration

Settings come from a repository profile when the repo has a `.noesis-config`
(`profile = <name>`, file in `~/.config/noesis/profiles/<repo>/<name>.env`), otherwise from
`~/.config/noesis/.env`. `--env-file` overrides both. `NOESIS_*` environment variables win over
the file.
`noesis config show` prints the effective values; the generated file documents every key.

## Command line

```text
noesis --help | --version
noesis config show|init [--json]
noesis doctor [--json]
noesis update check [--json]                # is this checkout behind its origin? (exit 0 always)
noesis curate brief --brief-file FILE [--dry-run]   # the curator judges a work brief, then stores proposed records ([details](docs/commands/curate.md))
noesis curate apply --decisions-file FILE|- [--dry-run] # store candidates you wrote, no curator
noesis curate parked | retry TICKET|--all [--yes]  # failed curations
noesis search TEXT [--project P]            # find records and resources; --briefing digest|synthesis for a briefing
noesis remember --as knowledge|experience ...   # capture a record on purpose ([details](docs/commands/remember.md))
noesis record revise|get ...                # revise and read records of the knowledge store
noesis import run | file ...                # import a notes vault as proposed records (reads NOESIS_VAULT_DIR)
noesis capture on|off|status|runs [--session ID] [--mode live|dry-run] [--parent ID] [--children]
noesis hook claude-code                     # stdin: Claude Code hook JSON (always exits 0)
noesis integrate claude-code install|uninstall|status [--settings F] [--yes]
noesis skills list | get NAME               # guides for agent skills
```

Every command accepts `--json` (a `{"ok": ..., "result" | "error": ...}` envelope) and
`--help`. Exit codes: `0` ok, `1` the operation failed, `2` invalid command line.

New to command-line tools? Read [`docs/cli-primer.md`](docs/cli-primer.md).

For the Neo4j architecture, configuration reference and an end-to-end checklist, read the
[refactor walkthrough](docs/guides/refactor-walkthrough.md).

## Playground

```bash
make sandbox-hook              # simulate a Claude Code session in sandbox/ (dry run)
make sandbox-hook MODE=live    # the same, with the real curator (haiku)
make run ARGS="capture --help"
```

## Development

```bash
make init     # uv sync
make check    # ruff, format check, mypy --strict, import-linter, pytest with coverage
make help     # every target
```

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first; it covers
setup, `make check`, the architecture rules and the commit style. Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Security reports: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
