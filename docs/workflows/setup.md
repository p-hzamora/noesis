# `doctor`, `config`, `skills`

These have no bounded-context handler (except `doctor`'s host-level one) and never write
records.

```mermaid
flowchart LR
    doctor["doctor"] --> rd["bootstrap.run_diagnostics"]
    rd -->|installed hook events as plain values| hs[GetAgentHooksStatusHandler]
    rd --> dh[RunDiagnosticsHandler]
    dh --> probe[SystemEnvironmentProbeAdapter]
    probe --> checks["env file, state dir,<br/>git, curator binary, Claude Code hooks,<br/>graph store"]
    dh --> upd["CheckForUpdateHandler → ICheckoutInspector (git)"]
    upd --> checks
    checks --> dr["DoctorResponse, exit 1 if any check fails"]

    show["config show"] --> env[load_environment] --> cs[ConfigShowResponse]
    init["config init [--vault-dir D] [--force]"] --> tpl["packaged env.example"] --> envfile[("~/.config/noesis/.env")]

    sl["skills list"] --> guides[("files:<br/>skill_guides/*.md (repo root)")]
    sg["skills get NAME"] --> guides
```

`doctor` makes no write. The checks are the env file, state dir, `git`, the curator binary,
the Claude Code hooks, the graph store (a warning when `NOESIS_NEO4J_PASSWORD` is unset) and
`update`. A leftover variable of the removed Notes backends (writer, search, vectra, recall) in an old
`.env` is ignored.

The last check, `update`, compares the noesis checkout's git HEAD with origin's default
branch (the same query as `noesis update check`, with a 3 s budget). It never fails the
run: every verdict except `up_to_date` (`behind`, `ahead`, `diverged`, `unknown`) shows as a
`warn` line, with the fix command as the next step for `behind` and `diverged`. It may fetch
git objects into the checkout's `.git`, and moves no ref or file.

`skills get noesis` is what the installed agent skill stub runs, so the guide always
matches the installed version.

Back to [workflows](README.md).
