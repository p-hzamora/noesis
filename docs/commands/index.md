# noesis index

Keep search projections up to date. This release registers no projection: every command reports
`projections: []`, `head_sequence` and a warning, writes nothing and exits 0.

```text
noesis index sync    [--wait-seconds <n>] [--json]
noesis index rebuild [--projection <name>] --yes [--json]
noesis index status  [--verify] [--json]
```

- `sync` applies the changes since each projection's cursor. `rebuild` clears and refills; it needs
  `--yes` (exit 2 without it) and an unregistered `--projection` exits 2.
- `status` reports `kind`, `cursor`, `lag`, `profile` per projection, and with `--verify` the
  `divergences[]` found by comparing records with the projections.
- Errors: `RETRIEVAL_201_INDEX_NOT_INITIALISED`, `RETRIEVAL_202_INDEX_REBUILD_REQUIRED`,
  `RETRIEVAL_203_INDEX_SYNC_IN_PROGRESS`.
