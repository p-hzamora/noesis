# `doctor`, `config`, `skills`, `update`

Setup and housekeeping. Flow: [setup](../workflows/setup.md). Installing the command and
the skill: [install](../install.md).

| Command | Does | Options |
|---|---|---|
| `doctor` | Check configuration, folders and required executables (state dir, git, curator CLI, hooks, graph store, update). Exit 1 if anything fails. The `graph_store` check reports Neo4j reachable with its applied schema steps; unreachable, rejected credentials or a missing step fail it (`noesis store init` is the fix for a missing step); an unset `NOESIS_NEO4J_PASSWORD` is only a warning. | |
| `config show` | Print the effective settings and the file they were read from. | |
| `config init` | Write a commented configuration file to `~/.config/noesis/.env` (or `--env-file`). | `--vault-dir <path>` writes `NOESIS_VAULT_DIR` (the vault `import run` reads); `--force` overwrites an existing file |
| `skills list` | List the guides this noesis version ships. | |
| `skills get <name>` | Print a guide, what an agent reads before using noesis (e.g. `noesis`). | |
| `update check` | Compare the checkout noesis runs from with its origin. Exit 0 for every verdict. | |
