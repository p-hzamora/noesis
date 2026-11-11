# Installing noesis

noesis comes in two parts that you install separately:

1. **The `noesis` command**, a Python 3.14+ package.
2. **The agent skill** (`skills/noesis/SKILL.md`), which tells coding agents how to use the
   command.

## 1. The command

### One-line installer

```bash
curl -LsSf https://raw.githubusercontent.com/p-hzamora/noesis/main/install.sh | sh
```

`install.sh` uses the first installer it finds:

| Installer | When | Where `noesis` goes |
|---|---|---|
| `uv tool install` | `uv` is on your `PATH` | uv's tool bin dir (usually `~/.local/bin`). uv downloads Python 3.14 if you don't have it. |
| `pipx install` | no `uv`, but `pipx` and Python 3.14+ are | pipx's bin dir (usually `~/.local/bin`) |
| a private venv | neither, but Python 3.14+ is | venv in `~/.local/share/noesis/venv`, launcher symlinked into `~/.local/bin` |

If none of these work, the script stops and says what is missing. Git is needed to install
from the repository.

Run from a checkout (`./install.sh`), it installs that checkout instead of the repository.

Settings (environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `NOESIS_SOURCE` | this checkout, else `https://github.com/p-hzamora/noesis` | git URL or local path to install |
| `NOESIS_REF` | `main` | branch, tag or commit, for a git source |
| `NOESIS_INSTALLER` | auto | force `uv`, `pipx` or `venv` |
| `NOESIS_HOME` | `~/.local/share/noesis` | venv installer only: where the venv goes |
| `NOESIS_BIN_DIR` | `~/.local/bin` | venv installer only: where the launcher goes |

Example: to install a given commit with pipx:

```bash
curl -LsSf https://raw.githubusercontent.com/p-hzamora/noesis/main/install.sh \
  | NOESIS_REF=<commit-or-tag> NOESIS_INSTALLER=pipx sh
```

To upgrade, run the installer again; it replaces the existing install. To uninstall:

```bash
curl -LsSf https://raw.githubusercontent.com/p-hzamora/noesis/main/install.sh | sh -s -- --uninstall
```

Uninstalling removes the command only. Your config (`~/.config/noesis/`) and your notes are
kept.

### Manual install

You can also install with any of these:

```bash
uv tool install git+https://github.com/p-hzamora/noesis
pipx install --python python3.14 git+https://github.com/p-hzamora/noesis
python3.14 -m pip install --user git+https://github.com/p-hzamora/noesis
```

For development, `make install` does an editable `uv tool install` of your checkout, so
source edits apply at once.

### Configure and check

```bash
noesis config init --vault-dir ~/notes   # writes ~/.config/noesis/.env
noesis doctor                            # checks folders, git, the curator CLI, hooks
```

## 2. The agent skill

The skill is a small stub. It finds the `noesis` command and loads the guide that matches
the installed version (`noesis skills get noesis`), so it does not go out of date when you
upgrade the command. Install it with the [`skills`](https://github.com/vercel-labs/skills)
CLI (needs Node.js):

```bash
npx skills add p-hzamora/noesis --skill noesis -g     # every project, for your user
npx skills add p-hzamora/noesis --skill noesis        # this project only
npx skills add ./path/to/noesis --skill noesis -g     # from a local checkout
```

`-g` installs it for your user rather than for the current project. The CLI asks which
agents to install it for (Claude Code, Codex, Cursor and others).

Without Node.js, copy the folder yourself:

```bash
mkdir -p ~/.claude/skills && cp -R skills/noesis ~/.claude/skills/   # Claude Code, from a checkout
```

## 3. Claude Code hooks (optional)

To capture work automatically, add noesis's hooks to Claude Code:

```bash
noesis integrate claude-code install          # preview the change to ~/.claude/settings.json
noesis integrate claude-code install --yes    # write it (a timestamped backup is kept)
```

`noesis integrate claude-code uninstall --yes` removes them. See
[agent integration](commands/agent-integration.md).
