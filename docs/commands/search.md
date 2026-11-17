# noesis search

Find knowledge and experience records of the active space. Needs `NOESIS_NEO4J_PASSWORD` and an
initialised store (`noesis store init`); `--help` and usage errors never connect.

```text
noesis search <query> [--project <key> | --all-projects] [--tag <tag>]...
              [--type knowledge|experience]... [--status <status>]... [--limit 1..50]
              [--include-stale] [--require-semantic] [--semantic] [--json]
```

- The default project is the git repository of the working directory (the name `record capture`
  uses). Outside a repository, or for a project the space does not have, only space-wide records are
  searched and `result.warnings` says so. Search never creates a project.
- `result.hits[]`: `id`, `type`, `subtype`, `title`, `revision`, `status`, `authority`, `project`,
  `sources`, `revised_at`, `rank`. `result.scope`: `space`, `project`, `project_source`
  (`option`, `git_root`, `all_projects`, `none`), `space_wide_only`. `result.index`:
  `pending_changes`, `stale_hits`, `semantic.state`, `filter_shortfall`.
- Semantic (optional, English only; see [index](index.md#semantic-search-setup-english-only)):
  in `resident` mode a running `noesis index embedder serve` adds `semantic` candidates
  automatically; `--semantic` opts into loading the model in this process in `per-call` mode (a
  usage error, exit 2, in `off` mode). Queries that look like identifiers (backticks, `--flags`,
  paths, dotted names, snake_case, camelCase, UUIDs, `KEY-123`) keep the lexical+graph order and
  only append semantic-only records (authority tiers order the lexical+graph hits, then the
  appended ones, so an exact match is never pushed out by a semantic neighbour); other queries
  fuse lexical, graph and semantic with equal RRF weight, then order by authority tier. Semantic-only failures never fail a search;
  store failures do.
- Errors: `RETRIEVAL_101_SEMANTIC_INDEX_UNAVAILABLE`, `RETRIEVAL_202_INDEX_REBUILD_REQUIRED`,
  `INTEGRATION_103_GRAPH_STORE_UNAVAILABLE`. An empty query, `--limit` outside 1..50 and `--project`
  with `--all-projects` exit 2.
