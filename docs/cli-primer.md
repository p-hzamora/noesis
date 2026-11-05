# How command-line programs work (and how noesis follows the rules)

A short guide to the ideas behind every CLI, with noesis as the running example. Read it
top to bottom once; afterwards use the checklist at the end when you design a command.

## 1. What happens when you type a command

```text
$ noesis notes search "ttl cache" --repo demo --json
  └─┬──┘ └───┬───┘ └─┬──┘ └────┬────┘ └────┬────┘ └─┬─┘
 program  command  sub-  argument      option     flag
          group   command (positional) (key value) (on/off)
```

1. The **shell** splits the line into words (`argv`), honouring quotes: `"ttl cache"` is
 one word. It finds `noesis` on your `PATH` and starts it with those words.
2. The program **parses** `argv`: which command, which arguments, which options. noesis uses
 Typer, which turns typed Python functions into this parser (see
 `src/noesis/interfaces/cli/commands/`).
3. The command runs, writes results to **stdout**, problems to **stderr**, and ends with an
 **exit code**.

`noesis` is on your `PATH` because `pyproject.toml` declares it:

```toml
[project.scripts]
noesis = "noesis.interfaces.cli.app:main"
```

`uv tool install` (or `make install`) creates a small `noesis` launcher in `~/.local/bin`
that imports and calls `main()`. During development, `uv run noesis …` (or `make run ARGS="…"`) does the same from the source tree without installing anything.

## 2. Arguments, options, flags


| Kind                | Example                    | Use it for                                                  |
| ------------------- | -------------------------- | ----------------------------------------------------------- |
| Positional argument | `search "ttl cache"`       | The one thing the command acts on. Required, order matters. |
| Option              | `--repo demo`, `--limit 5` | Named, usually optional settings. Order does not matter.    |
| Flag                | `--json`, `--force`        | Booleans. `--park/--no-park` is a flag pair.                |


Rules of thumb: at most one or two positionals; everything else is a named option;
destructive behaviour needs an explicit flag (`config init --force`).

## 3. Commands and sub-commands

Big tools group verbs under nouns, like `git remote add`. noesis does the same:

```text
noesis capture   on | off | status | runs        (Capture context)
noesis notes curate | apply | retry | parked | search | list  (Notes context)
noesis hook      claude-code                     (machine entry point for agent hooks)
noesis config    show | init
noesis doctor
```

Each group is a module in `interfaces/cli/commands/`, and each command is one function.
The function only translates the command line into a *command* or *query* object and calls
its handler; it contains no business rules (those live in the bounded contexts).

## 4. Where values come from (precedence)

A setting can come from several places. The usual order, highest wins:

```text
command-line option  >  environment variable  >  config file  >  built-in default
```

noesis: `--env-file` / `--session` on the command line, then `NOESIS_*` variables, then
`~/.config/noesis/.env`, then defaults in `core/configurations/*_settings.py`.
`noesis config show` prints the effective values, so you never have to guess.

## 5. The three streams


| Stream | For                             | noesis                                                 |
| ------ | ------------------------------- | ------------------------------------------------------ |
| stdin  | Input data                      | `noesis hook claude-code` reads the hook JSON from it. |
| stdout | The result, and only the result | Text or the `--json` envelope.                         |
| stderr | Errors, warnings, progress      | Error messages with `next:` hints.                     |


Keeping results on stdout and everything else on stderr is what makes piping work:
`noesis notes list --json | jq '.result.notes[].path'` stays clean even when warnings
are printed.

## 6. Exit codes

The exit code is how a script, CI job, or agent learns whether a command worked without
reading its output.


| Code | Meaning in noesis                                                 |
| ---- | ----------------------------------------------------------------- |
| 0    | Success.                                                          |
| 1    | The operation failed (curator down, vault missing, …).            |
| 2    | You called it wrong (unknown command, bad option, invalid input). |


Check one in your shell with `echo $?` right after a command. Hooks are the exception:
`noesis hook …` always exits 0, because a failing hook would disturb the agent session;
it logs problems to `$NOESIS_STATE_DIR/capture/hook-errors.log` instead.

## 7. Output for people and for machines

People want short text; programs want a stable structure. Offer both:

```bash
noesis capture status --session s1          # text
noesis capture status --session s1 --json   # {"ok": true, "result": {...}}
```

Every noesis command returns the same envelope with `--json`:

```json
{"ok": false, "error": {"code": "CORE_002_VAULT_NOT_CONFIGURED", "message": "...",
                        "next_steps": ["Run `noesis config init --vault-dir <folder>`..."]}}
```

The `code` never changes once published, so callers (including AI agents) can branch on
it; the `message` is free to improve. `next_steps` tells the caller how to recover.
All of this lives in one place: `interfaces/cli/output.py`.

## 8. Help is the user interface

`--help` exists at every level (`noesis --help`, `noesis capture --help`,
`noesis capture on --help`). Typer builds it from the function's docstring and the
option `help=` texts, so writing good docstrings *is* writing the help.

## 9. Testing a CLI

Do not start a process for every test. noesis exposes `run(argv) -> exit code`
(`interfaces/cli/app.py`), so tests call it in-process and read stdout/stderr with
pytest's `capsys`:

```python
assert run(["notes", "list", "--json"]) == 1
assert json.loads(capsys.readouterr().out)["error"]["code"] == "CORE_002_VAULT_NOT_CONFIGURED"
```

Only one test (`tests/architecture`) launches a real process. For the hook flow, the
sandbox does it end to end (section 11).

## 10. When another program calls your CLI

Agents call CLIs too. Claude Code runs `noesis hook claude-code` and writes a JSON payload
to its stdin on certain events. A command meant for programs should:

- read structured input (stdin JSON) and validate it, ignoring fields it does not know;
- never prompt, never print noise, never fail the caller (exit 0, log elsewhere);
- return fast: noesis starts slow work (the curator) as a detached process.

## 11. Try it

```bash
make run ARGS="--help"             # explore the commands
make run ARGS="doctor --json"      # check your setup
make sandbox-hook                  # simulate a Claude Code session (dry run, free)
make sandbox-hook MODE=live        # same, with the real curator (haiku, a few cents at most)
eval "$(make -s sandbox-env)"      # point `uv run noesis …` at the sandbox in this shell
uv run noesis capture runs --session <id printed by sandbox-hook>
make sandbox-clean
```

## 12. Checklist for a new command

- [ ] It is a verb under the right noun group, with one clear job.
- [ ] One positional at most; everything else is a named option with `help=`.
- [ ] Docstring explains what it does in one line (it becomes `--help`).
- [ ] Results to stdout, errors to stderr; `--json` returns the envelope.
- [ ] Failures raise an `AppException` subclass with a stable code and `next_steps`.
- [ ] Exit code 0 / 1 / 2 is right for every path.
- [ ] Destructive or costly actions need an explicit flag or show a dry run first.
- [ ] It calls a handler; no business rule lives in the command function.
- [ ] A test calls `run([...])` for the happy path and each error path.