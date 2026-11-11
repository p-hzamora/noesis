# `doctor`, `config`, `skills`, `update`

Setup and housekeeping. Flow: [setup](../workflows/setup.md). Installing the command and
the skill: [install](../install.md).

| Command | Does | Options |
|---|---|---|
| `doctor` | Check configuration, folders and required executables (vault, state dir, git, curator CLI, hooks, writer, search backend, update). Exit 1 if anything fails. | |
| `config show` | Print the effective settings and the file they were read from. | |
| `config init` | Write a commented configuration file to `~/.config/noesis/.env` (or `--env-file`). | `--vault-dir <path>` writes `NOESIS_VAULT_DIR`; `--force` overwrites an existing file |
| `skills list` | List the guides this noesis version ships. | |
| `skills get <name>` | Print a guide, what an agent reads before using noesis (e.g. `noesis`). | |
| `update check` | Compare the checkout noesis runs from with its origin. Exit 0 for every verdict. | |
