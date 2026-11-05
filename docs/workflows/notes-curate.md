# `notes curate --brief-file F`

```mermaid
sequenceDiagram
    autonumber
    participant Cmd as notes curate
    participant Boot as build_notes
    participant H as CurateWorkBriefHandler
    participant A as ApplyCurationHandler
    participant Map as WorkBriefMapper
    participant Read as INoteReadRepository<br/>(filesystem keyword search, or Obsidian MCP<br/>with filesystem fallback)
    participant Cur as ICurator<br/>(ClaudeCliCuratorAdapter)
    participant Pol as AutoCurationPolicy (domain)
    participant UoW as INotesUnitOfWork<br/>(files, or Obsidian MCP: NOESIS_WRITER_BACKEND)
    participant Q as IParkedCurationQueue

    Cmd->>Cmd: load F as WorkBriefContract (else INVALID_WORK_BRIEF)
    Cmd->>Boot: vault required only where files are used, system prompt resolved
    Cmd->>H: CurateWorkBriefCommand(brief, max_attempts=2, park=true, dry_run=false)
    H->>Map: to_domain(contract)
    Map-->>H: WorkBrief (area, search_text, provenance)
    H->>Read: search(brief.search_text(), area, limit=8)
    Read-->>H: related NoteSummaryDto[]<br/>(never fails: MCP errors fall back to files)
    loop up to max_attempts
        H->>Cur: judge(brief, related)
        Cur-->>H: CurationDecision[] or CuratorFailedError
    end
    alt every attempt failed
        H->>Q: park(contract, error) -> ticket
        H-->>Cmd: CurationFailedError (next step: notes retry ticket)
    else decisions
        H->>A: ApplyCurationCommand(area, decisions, commits, session, dry_run)
        loop each decision
            A->>UoW: get existing auto note and manual note (from the writer's backend)
            A->>Pol: apply(decision, existing, commits, session)
            Pol-->>A: created / updated / skipped (manual note wins)
            A->>UoW: notes.save(note)
        end
        A->>UoW: commit (MCP: validate all, send one by one, not atomic)
        alt NoteStorageError (lookup or commit)
            A-->>H: NoteStorageError (curate's apply has no failure log)
            H->>Q: park(contract, error) -> ticket
            H-->>Cmd: CurationFailedError NOTES_201 (written / not_written, notes retry ticket)
        else stored
            H-->>Cmd: CurationResultDto -> CurationResponse
        end
    end
```

With `--dry-run` the curator still runs, but `ApplyCurationHandler` skips `save` and `commit`,
nothing is parked on any failure (no ticket), and the output carries `"dry_run": true`.
Storing is shared with [`notes apply`](notes-apply.md); the only difference is who wrote the
decisions.

Back to [workflows](README.md).
