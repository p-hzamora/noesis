# `knowledge curate --brief-file F`

```mermaid
sequenceDiagram
    autonumber
    participant Cmd as knowledge curate
    participant Boot as build_knowledge
    participant H as CurateWorkBriefHandler
    participant Map as WorkBriefMapper
    participant Read as INoteReadRepository<br/>(filesystem keyword search)
    participant Cur as ICurator<br/>(ClaudeCliCuratorAdapter)
    participant Pol as AutoCurationPolicy (domain)
    participant UoW as IKnowledgeUnitOfWork
    participant Q as IParkedCurationQueue

    Cmd->>Cmd: load F as WorkBriefContract (else INVALID_WORK_BRIEF)
    Cmd->>Boot: vault required, system prompt resolved
    Cmd->>H: CurateWorkBriefCommand(brief, max_attempts=2, park=true)
    H->>Map: to_domain(contract)
    Map-->>H: WorkBrief (area, search_text, provenance)
    H->>Read: search(brief.search_text(), area, limit=8)
    Read-->>H: related NoteSummaryDto[]
    loop up to max_attempts
        H->>Cur: curate(brief, related)
        Cur-->>H: CurationDecision[] or CuratorFailedError
    end
    alt every attempt failed
        H->>Q: park(contract, error) -> ticket
        H-->>Cmd: CurationFailedError (next step: knowledge retry ticket)
    else decisions
        loop each decision
            H->>UoW: get existing auto note and manual note
            H->>Pol: apply(decision, existing, commits, session)
            Pol-->>H: created / updated / skipped (manual note wins)
            H->>UoW: notes.save(note)
        end
        H->>UoW: commit (all notes or none)
        H-->>Cmd: CurationResultDto -> CurationResponse
    end
```

Back to [workflows](README.md).
