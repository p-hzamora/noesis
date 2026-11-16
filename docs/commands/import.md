# noesis import

Bring an existing notes vault, or a single file, into the record store as `proposed`,
graph-owned Knowledge records. Prepare the store first: [store workflow](../workflows/store.md).
Files are only read, never written, renamed or deleted. `--help` and usage errors need no
configuration and never connect.

## import run

```text
noesis import run [--yes] [--update] [--strict] [--verbose] [--json]
```

- Reads every `.md` file under `NOESIS_VAULT_DIR` (no symbolic links, no hidden folders such as
  `.obsidian`), in path order. Without `--yes` it is a preview: Knowledge assesses each note and
  nothing is written.
- Each note becomes a record tagged `origin:migrated` with a `file_version` Source
  `vault://<vault_key>/<relative path>`; `NOESIS_IMPORT_VAULT_KEY` sets the key (default: the vault
  folder name). Wiki links turn into their text, sections holding only links are removed, code
  blocks are untouched. A note left with no text is `skipped_empty`.
- A rerun is safe: unchanged notes are `unchanged`. A changed note is `changed_in_vault`; with
  `--update` a `proposed` record gets a new revision (`revised`) and an accepted one gets a new
  `proposed` successor and a proposed `supersedes` assertion from it to the accepted record
  (`successor_proposed`, with `target_record_id` and `assertion_id`).
- `--strict` refuses the run with `IMPORT_201_BLOCKING_FINDINGS` when any note is blocked, before
  writing anything. `--verbose` lists every note in `result.notes`.
- Result: `applied`, `update`, `vault_key`, `totals`, `blocked_reasons`, `warnings`,
  `sources_skipped`, `complete` (no note blocked), `notes` (verbose only), `next_steps`. The exit
  code is 0 whenever the run finishes, blocked notes included.
- Block reasons: `not_text`, `invalid_header`, `invalid_id`, `duplicate_id`, `invalid_scope`,
  `id_conflict`, `target_closed`, `revision_conflict`, `idempotency_key_reused`, `invalid_metadata`.

## import file

```text
noesis import file <path> [--title <text>] [--subtype <slug>] [--project <key>] [--tag <tag>]...
                   [--dry-run] [--json]
```

Registers one file, anywhere on disk, tagged `origin:imported`; its Source is the resolved path.
A header `id` is ignored. `--dry-run` reports the outcome without writing. Running it again on the
same file is `unchanged`; after an edit it is `revised` (still `proposed`) or a successor.

## Errors

| Code | When | Exit |
| --- | --- | --- |
| `IMPORT_101_VAULT_READ_FAILED` | vault folder missing or a note unreadable | 1 |
| `IMPORT_102_FILE_READ_FAILED` | `import file`: path missing, not a file, unreadable | 1 |
| `IMPORT_201_BLOCKING_FINDINGS` | `import run --strict` and a blocked note | 1 |
| `IMPORT_203_FILE_NOT_IMPORTABLE` | `import file`: blocked, `not_text`, `invalid_header`, `empty_body` | 1 |
| `CORE_002_VAULT_NOT_CONFIGURED` | `import run` without `NOESIS_VAULT_DIR` | 1 |
| `CORE_001_INVALID_CONFIGURATION` | invalid `NOESIS_IMPORT_VAULT_KEY`, or a derived key that is invalid | 1 |
| `KNOWLEDGE_204_STORE_NOT_INITIALISED`, `KNOWLEDGE_208_SPACE_NOT_FOUND`, `INTEGRATION_103..107` | store problems | 1 |
| usage error | missing `<path>`, `--update` or `--strict` on `import file`, `--dry-run` on `import run` | 2 |

## Links

`import run` reads wiki links (`[[note]]`), embeds (`![[note]]`) and relative Markdown
note links before normalising the body. Links in removed links-only sections still count;
fenced and inline code, header properties and external URLs do not. Resolution uses scanned
note paths, case-insensitive Unicode NFC matching, partial paths and same-folder preference
for duplicated base names. Header aliases are not lookup keys. Relative paths cannot escape
the vault.

After the record pass, `--yes` stores resolved links as `LINKS_TO` or `EMBEDS` relationships,
with origin `migrated`, occurrence counts and sorted distinct anchors (including `^` block
anchors). Dangling, ambiguous, non-note, self and not-imported targets are counted without
creating stub records. JSON adds `links` occurrence totals and `link_sets` outcomes; previews
report `planned`, applies report `created`/`replaced`, and both include `unchanged`, `deferred`,
`no_record` and `blocked`. Verbose rows include link counts, the link-set outcome and ambiguous
targets with sorted candidate paths. Notes with no outgoing links and no stored set contribute
no set outcome. Links-only skipped notes with outgoing links contribute `no_record`; their
occurrences are shown on the row, excluded from the totals for imported source notes.

Unchanged reruns backfill missing link sets, then write nothing. Updating a note replaces its
whole set, removing old edges. Without `--update`, changed notes defer their outgoing sets but
remain valid targets. A successor receives new outgoing links; incoming links keep pointing to
the accepted record. Retracted and superseded records retain their edges. Link classifications
never affect `--strict`; a refused link set is counted as `blocked` without changing `complete`.
`import file` does not import links.

Run `noesis store init` after upgrading to apply the `links` schema step. An apply checks for
this step before writing records; a preview needs no link schema. Each source's link set is
atomic, but the whole vault is not. A store failure stops the run. On `GraphStoreBusyError`
(lock timeout or deadlock), rerun `noesis import run --yes` with the same options: the run
converges. Link changes do not add change-feed entries or trigger text re-indexing.
