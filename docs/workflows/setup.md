# `doctor`, `config`, `skills`

These have no bounded-context handler (except `doctor`'s host-level one) and never write
notes.

```mermaid
flowchart LR
    doctor["doctor"] --> rd["bootstrap.run_diagnostics"]
    rd -->|installed hook events as plain values| hs[GetAgentHooksStatusHandler]
    rd --> dh[RunDiagnosticsHandler]
    dh --> probe[SystemEnvironmentProbeAdapter]
    dh -.->|"only when NOESIS_SEARCH_BACKEND=obsidian-mcp"| mp[ObsidianMcpProbeAdapter]
    mp -->|"vault_list root"| obs[("Obsidian MCP")]
    probe --> checks["env file, vault dir, state dir,<br/>curator binary, Claude Code hooks,<br/>search backend"]
    checks --> dr["DoctorResponse, exit 1 if any check fails"]

    show["config show"] --> env[load_environment] --> cs[ConfigShowResponse]
    init["config init [--vault-dir D] [--force]"] --> tpl["packaged env.example"] --> envfile[("~/.config/noesis/.env")]

    sl["skills list"] --> guides[("package data:<br/>interfaces/cli/skill_guides/*.md")]
    sg["skills get NAME"] --> guides
```

The `search_backend` check makes no MCP call on the default `filesystem` backend. With
`obsidian-mcp` it lists the root of the vault Obsidian serves and compares the non-hidden
entry names with `NOESIS_VAULT_DIR`: unreachable server or a different vault fails the check
(exit 1) with a next step. Obsidian does not report which folder it serves, so equal root
listings are the evidence of "same vault".

`skills get noesis` is what the installed agent skill stub runs, so the guide always
matches the installed version.

Back to [workflows](README.md).
