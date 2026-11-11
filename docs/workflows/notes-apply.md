# `notes apply --decisions-file F|-`

Stores note drafts that a person or an agent wrote, with no curator. It is the second half of
[`notes curate`](notes-curate.md) run alone.

```mermaid
sequenceDiagram
    autonumber
    participant Cmd as notes apply
    participant Git as find_git_root(cwd)
    participant Par as parse_decisions_strict
    participant Boot as build_apply
    participant H as ApplyCurationHandler
    participant Pol as AutoCurationPolicy (domain)
    participant UoW as INotesUnitOfWork<br/>(files, or Obsidian MCP: NOESIS_WRITER_BACKEND)
    participant Log as IApplyFailureLog<br/>(JsonFileApplyFailureLogAdapter)

    Cmd->>Git: repository root of the working directory
    Git-->>Cmd: scope repo:<repo> (else INTERFACE_002, exit 2, nothing read)
    Cmd->>Cmd: read F or stdin (unreadable: one rejected entry)
    Cmd->>Par: raw text
    Par-->>Cmd: decisions + rejected entries (index, reason)
    Cmd->>Boot: vault only where files are used; no curator, no queue
    Cmd->>H: ApplyCurationCommand(scope, decisions, rejected, raw_payload, commits, session, dry_run)
    alt any rejected entry
        H->>Log: record(raw payload, errors)  (not in --dry-run)
        H-->>Cmd: ApplyFailedError NOTES_203 (rejected, ticket, record_path, payload_path)
    else all entries valid
        loop each decision
            H->>UoW: get existing auto note and manual note
            H->>Pol: apply(decision, existing, commits, session)
            Pol-->>H: created / updated / skipped (manual note wins)
            H->>UoW: notes.save(note)  (not in --dry-run)
        end
        H->>UoW: commit  (not in --dry-run)
        alt NoteStorageError
            H->>Log: record(raw payload, errors)
            H-->>Cmd: ApplyFailedError NOTES_203 (written / not_written, ticket, payload_path)
        else stored (or previewed)
            H-->>Cmd: CurationResultDto -> CurationResponse (CurationPreviewResponse with --dry-run)
        end
    end
```

Rules worth knowing:

- The path is never chosen by the caller: the manifest layout (default `repos/<repo folder>/<kind folder>/<slug>.md`).
- One malformed entry fails the whole call before anything is written; nothing is partly applied.
- A failed call keeps the payload under `<state>/notes/apply-failed/`; if that cannot be written
  the payload is returned in `error.metadata.raw_payload`. Re-applying the kept payload is the
  retry: `apply` is an upsert, so repeating it never duplicates a note.
- `notes apply` never parks a brief and never touches `notes retry` or capture state.

Back to [workflows](README.md).
