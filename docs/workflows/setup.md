# `doctor`, `config`, `skills`

These have no bounded-context handler (except `doctor`'s host-level one) and never write
notes.

```mermaid
flowchart LR
    doctor["doctor"] --> rd["bootstrap.run_diagnostics"]
    rd -->|installed hook events as plain values| hs[GetAgentHooksStatusHandler]
    rd --> dh[RunDiagnosticsHandler]
    dh --> probe[SystemEnvironmentProbeAdapter]
    probe --> checks["env file, vault dir, state dir,<br/>curator binary, Claude Code hooks"]
    checks --> dr["DoctorResponse, exit 1 if any check fails"]

    show["config show"] --> env[load_environment] --> cs[ConfigShowResponse]
    init["config init [--vault-dir D] [--force]"] --> tpl["packaged env.example"] --> envfile[("~/.config/noesis/.env")]

    sl["skills list"] --> guides[("package data:<br/>interfaces/cli/skill_guides/*.md")]
    sg["skills get NAME"] --> guides
```

`skills get noesis` is what the installed agent skill stub runs, so the guide always
matches the installed version.

Back to [workflows](README.md).
