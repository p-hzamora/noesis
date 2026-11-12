# noesis vault

Check a vault's notes and restructure it to the manifest layout from a plan. Both commands work
on the files of `NOESIS_VAULT_DIR` and ignore the writer and search backends.

## vault doctor

```text
noesis vault doctor [--root <folder>]... [--verbose] [--json]
```

Counts the visible Markdown files with a valid `noesis:` block, without one, and with an
invalid header or block. A project name that exists under two roots is listed: the roots are the
manifest's repository folder (`repos/`) and every `--root` (a folder whose subfolders are
projects, e.g. `--root company/stidea/projects`). `--verbose` also lists the files behind the
counts. Read-only.

## vault migrate

```text
noesis vault migrate --plan <file> [--apply] [--verbose] [--json]
```

A dry run unless `--apply`. Prints counts (plan entries per action, files to write, already in
place, old files to delete, wikilinks to rewrite, unresolved wikilinks before and after, empty
folders to remove); `--verbose` adds one line per file with work left.

Plan entries: `{"old", "new", "action", "scope", "kind"}` in a JSON list or in `{"entries": [...]}`.

| action | does |
|---|---|
| `note` | adds or refreshes the `noesis:` block (an existing block keeps its id, origin, sources and date), keeps every other header key except the legacy `type, id, repo, area, origin, session, commits`, leaves the body as it is, and moves the file |
| `move` | relocates the file byte for byte |
| `keep` | leaves the file where it is and as it is (wikilinks in it are still kept pointing at moved files) |

`note` needs a `scope` (`repo:<name>` or `topic:<name>`) and a `kind` from the manifest. A plan
that breaks a rule, names a file the vault does not have (and no target for it), or holds a
file with a YAML header that cannot be read fails with `NOTES_207_INVALID_MIGRATION_PLAN`.

Order of an apply, so a run that stopped anywhere is finished by running it again:

1. write every target (atomically) and verify each one against its source (non-Markdown files
   byte for byte; notes: same body, every foreign header key kept);
2. rewrite the wikilinks (`[[x]]`, `[[x|alias]]`, `[[x#heading]]`, embeds) of every visible
   Markdown file that pointed at a moved file; only changed files are written; hidden folders
   are skipped;
3. only then delete the old files;
4. remove empty folders with `rmdir` (never recursively).

A target that already exists with different content stops everything before any write:
`NOTES_208_MIGRATION_CONFLICT`, listing each pair. A target with the same content counts as
already done. A failed verification (`NOTES_104_MIGRATION_VERIFICATION_FAILED`) deletes nothing.
