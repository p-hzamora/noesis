# noesis

Capture finished agent work, curate what is worth keeping, and store it as notes.

noesis watches coding-agent sessions (Claude Code today) for units of finished work such as
git commits. It asks an LLM curator which decisions, gotchas, and outcomes are worth
remembering, and writes them as Markdown notes into a folder you choose: an Obsidian
vault, a plain directory, or an NFS mount. Storage is an adapter, so the same flow works
with any of them.

> Status: early development. See `docs/architecture.md` for the design and
> `CONTEXT.md` for the vocabulary.

## Install

```bash
uv tool install ~/Desktop/noesis        # or: uv tool install -e . from a checkout
noesis config init --vault-dir ~/brain  # writes ~/.config/noesis/.env
noesis doctor                           # checks folders, git, and the curator CLI
```

## Use it from Claude Code

```bash
make install                                  # or: uv tool install ~/Desktop/noesis
noesis config init --vault-dir ~/brain        # where notes go
noesis integrate claude-code install          # preview the hooks diff for ~/.claude/settings.json
noesis integrate claude-code install --yes    # write it (a timestamped backup is kept)
npx skills add ~/Desktop/noesis --skill noesis -g   # teach agents the CLI (or copy skills/noesis/)
noesis doctor
```

Then, in a Claude Code session: "turn noesis capture on". The skill stub loads the
version-matched guide (`noesis skills get noesis`) and runs
`noesis capture on --session <this session>`. Commits and turn ends are captured by the
hooks from then on; `noesis capture runs --session <id>` shows what happened.

`noesis integrate claude-code uninstall --yes` removes every noesis hook and nothing else.

## Configuration

Settings come from `~/.config/noesis/.env` (override with `--env-file` or
`NOESIS_ENV_FILE`) and from `NOESIS_*` environment variables, which win over the file.
`noesis config show` prints the effective values; the generated file documents every key.

## Command line

```text
noesis --help | --version
noesis config show|init [--json]
noesis doctor [--json]
noesis knowledge curate --brief-file FILE   # judge a work brief, store auto notes
noesis knowledge parked | retry TICKET      # failed curations
noesis knowledge search TEXT [--repo R]     # find notes
noesis knowledge list [--repo R] [--origin manual|auto]
noesis capture on|off|status|runs --session ID [--mode live|dry-run]
noesis hook claude-code                     # stdin: Claude Code hook JSON (always exits 0)
noesis integrate claude-code install|uninstall|status [--settings F] [--yes]
noesis skills list | get NAME               # guides for agent skills
```

Every command accepts `--json` (a `{"ok": ..., "result" | "error": ...}` envelope) and
`--help`. Exit codes: `0` ok, `1` the operation failed, `2` invalid command line.

New to command-line tools? Read [`docs/cli-primer.md`](docs/cli-primer.md).

## Playground

```bash
make sandbox-hook              # simulate a Claude Code session in .sandbox/ (dry run)
make sandbox-hook MODE=live    # the same, with the real curator (haiku)
make run ARGS="capture --help"
```

## Development

```bash
make init     # uv sync
make check    # ruff, format check, mypy --strict, import-linter, pytest with coverage
make help     # every target
```
