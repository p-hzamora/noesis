# `doctor`, `config`, `skills`

These have no bounded-context handler (except `doctor`'s host-level one) and never write
notes.

```mermaid
flowchart LR
    doctor["doctor"] --> rd["bootstrap.run_diagnostics"]
    rd -->|installed hook events as plain values| hs[GetAgentHooksStatusHandler]
    rd --> dh[RunDiagnosticsHandler]
    dh --> probe[SystemEnvironmentProbeAdapter]
    dh -.->|"only when search is obsidian-mcp or writer is mcp"| mp[ObsidianMcpProbeAdapter]
    mp -->|"vault_list root; write and delete noesis-doctor-probe.md"| obs[("Obsidian MCP")]
    probe --> checks["env file, vault dir, state dir,<br/>curator binary, Claude Code hooks,<br/>writer, search backend"]
    dh --> upd["CheckForUpdateHandler → ICheckoutInspector (git)"]
    upd --> checks
    checks --> dr["DoctorResponse, exit 1 if any check fails"]

    show["config show"] --> env[load_environment] --> cs[ConfigShowResponse]
    init["config init [--vault-dir D] [--force]"] --> tpl["packaged env.example"] --> envfile[("~/.config/noesis/.env")]

    sl["skills list"] --> guides[("files:<br/>skill_guides/*.md (repo root)")]
    sg["skills get NAME"] --> guides
```

The `writer` check (between `claude_code_hooks` and `search_backend`) is ok with no MCP call
on the default `filesystem` writer; with `NOESIS_WRITER_BACKEND=mcp` it writes and deletes
`noesis-doctor-probe.md` at the vault root and fails (exit 1) when the server is unreachable or
refuses the write or the delete. The `vault` check fails on an unset vault only when a vault is required (writer or
search on `filesystem`).

The `search_backend` check makes no MCP call on the default `filesystem` backend. With
`obsidian-mcp` it lists the root of the vault Obsidian serves and compares the non-hidden
entry names with `NOESIS_VAULT_DIR`: unreachable server or a different vault fails the check
(exit 1) with a next step. Obsidian does not report which folder it serves, so equal root
listings are the evidence of "same vault".

The last check, `update`, compares the noesis checkout's git HEAD with origin's default
branch (the same query as `noesis update check`, with a 3 s budget). It never fails the
run: every verdict except `up_to_date` (`behind`, `ahead`, `diverged`, `unknown`) shows as a
`warn` line, with the fix command as the next step for `behind` and `diverged`. It may fetch
git objects into the checkout's `.git`, and moves no ref or file.

`skills get noesis` is what the installed agent skill stub runs, so the guide always
matches the installed version.

Back to [workflows](README.md).
