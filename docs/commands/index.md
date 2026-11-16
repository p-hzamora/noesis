# noesis index

Keep search projections up to date. The only production projection is `semantic` (optional, C5b):
it is registered when `NOESIS_RETRIEVAL_SEMANTIC_MODE` is `resident` (default) or `per-call` **and**
the optional `noesis[semantic]` extra is installed. Otherwise nothing is registered and every
command reports `projections: []`, `head_sequence` and a warning, writes nothing and exits 0.

```text
noesis index sync    [--wait-seconds <n>] [--json]
noesis index rebuild [--projection <name>] --yes [--json]
noesis index status  [--verify] [--json]
noesis index model prepare [--json]
noesis index embedder serve [--json]
```

- `sync` applies the changes since each projection's cursor. `rebuild` clears and refills; it needs
  `--yes` (exit 2 without it) and an unregistered `--projection` exits 2.
- `status` reports `kind`, `cursor`, `lag`, `profile` (the persisted *built* profile),
  `configured_profile`, `profile_matches` and `build_state` per projection, with `--verify` the
  `divergences[]` found by comparing records with the projections (a broken chunk set reports
  `found_revision: -1`), and a `semantic` block: mode, whether the extra is installed, whether the
  model is prepared, whether the resident runtime answers, the vector index state and a next
  step. Status never loads the model, starts a runtime or downloads anything.
- Errors: `RETRIEVAL_101_SEMANTIC_INDEX_UNAVAILABLE` (embedder or model unavailable; the cursor does
  not move), `RETRIEVAL_201_INDEX_NOT_INITIALISED`, `RETRIEVAL_202_INDEX_REBUILD_REQUIRED`,
  `RETRIEVAL_203_INDEX_SYNC_IN_PROGRESS` (another holder, a lost lease, or a record that kept
  changing while it was embedded).

## Semantic search setup (English only)

```text
uv tool install --force 'noesis[semantic]'   # numpy, onnxruntime (CPU), tokenizers; no torch
noesis store init                            # adds the `retrieval_semantic` schema step
noesis index model prepare                   # the only download: ~133 MB, verified, cached
noesis index embedder serve                  # foreground; supervise it yourself
noesis index rebuild --yes                   # embeds every Knowledge head and Experience
```

- **Model.** `BAAI/bge-small-en-v1.5` (MIT), official fp32 ONNX export pinned to upstream commit
  `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` with fixed SHA-256 digests; 384-dimension cosine
  vectors in a Neo4j 5.26 Community native vector index (`retrieval_semantic_vector`). Retrieval
  quality is measured for **English only**; other languages are indexed (never rejected or
  dropped) but carry no quality promise.
- **Offline cache.** `$XDG_CACHE_HOME/noesis/models/` (or `NOESIS_RETRIEVAL_MODEL_CACHE_DIR`).
  `prepare` downloads into a temporary directory, verifies sizes and digests and moves it into place
  atomically. Every other command reads the cache offline; a missing or corrupt cache makes semantic
  unavailable with a `prepare` next step, never a download or another model.
- **Runtime.** `resident` mode uses the process started by `index embedder serve`: it loads the
  model once and answers on a private Unix socket under `$XDG_RUNTIME_DIR/noesis/` (mode 0700/0600;
  no network listener, no store access, no text logging). Nothing ever starts it automatically.
  When it is not running, search silently continues lexical+graph (`semantic.state: unavailable`)
  and `--require-semantic` fails with `RETRIEVAL_101`. `per-call` mode loads the model inside the
  invoking process only for `search --semantic` (or `--require-semantic`) and for `index
  sync/rebuild`; that costs seconds per call and is outside the 3 s semantic target. `off` never
  uses semantic.
- **Chunks.** Text is the title, a newline and the body (an Experience's body alone), split into
  windows of 448 tokens overlapping by 64: every token is embedded, nothing is truncated. A record
  ranks by its best chunk, once. Queries carry bge's instruction once; long queries are windowed and
  averaged; over 32,000 characters semantic is unavailable.
- **Freshness.** A capture starts a detached `index sync`; search never syncs. `lagging` results
  are still served. A rebuild marks the space unavailable from before the clear until it publishes
  its built profile; a failed rebuild must be rerun (ordinary `sync` refuses it). Changing the
  model or chunking profile requires `index rebuild --yes` in each space.
- **Leases.** Sync and rebuild hold a fenced 300 s lease (`NOESIS_INDEX_LOCK_TTL_SECONDS`) renewed
  every ≤30 s; a holder that lost it can write no chunk, cursor or manifest.
