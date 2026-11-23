# `noesis search`

Unified search over the record store and the resource catalog: one call returns matching records,
the skills, agents, CLI tools and MCP servers that cover the task, and an ordered list of next
actions. With `--briefing` it also returns the task briefing.

```text
noesis search <query> [--project <key> | --target-root <path> | --all-projects] [--tag <t>]...
              [--type knowledge|experience]... [--status <s>]... [--limit 1..50] [--include-stale]
              [--require-semantic] [--semantic]
              [--need <facet>]... [--runtime claude-code|codex]... [--resource-limit 0..20]
              [--no-resources] [--briefing none|digest|synthesis] [--budget-chars <n>] [--json]
```

## Options added for resources

| Option | Meaning |
| --- | --- |
| `--need <facet>` | A capability the task must cover (repeatable, 1..64 characters). Default: the query words. |
| `--runtime` | Runtimes whose availability is reported (default: the current session). |
| `--resource-limit` | Maximum selected resources, 0..20 (default 8; 0 selects none). |
| `--no-resources` | Records only. The JSON keeps exactly the record-search keys. |
| `--briefing` | `none` (default), `digest` (model-free) or `synthesis`. |
| `--budget-chars` | Evidence budget for the briefing. |

## Result

- `requirements[]`: `id`, `source` (`need` or `query`), `coverage` (`covered`, `partial`, `missing`),
  `supported_by`. A missing facet is reported as a gap; no resource is invented for it.
- `resources[]`: in load order, prerequisites first. Fields: `ref`, `name`, `kind`, `load_order`,
  `requires`, `why.channels` (`catalog_text`, `catalog_semantic`, `recommends`, `prerequisite`),
  `cataloged`, `discovered`, `available` (runtime to `available` or `unavailable`),
  `endorsement` (`user`, `project`, `proposed`, `none`), `recommended_by`, `refined_by`.
- `next_actions[]`: `{order, action, ref}` with `action` in `load_skill`, `use_agent`,
  `use_cli_tool`, `use_mcp_server`, `read_record`. Refs are `catalog:<kind>:<name>` or
  `record:<id>@<revision>`; never shell text from stored content.
- `index.catalog`: whether the catalog is synced and how many installed resources are not in it.
- `briefing`: present only with `--briefing digest|synthesis`. Without it no record bodies are returned.
- `warnings`: semantic search absent or unavailable (resources still return), unsynced installed
  resources (`noesis catalog sync`), prerequisites not found, prerequisite cycles.

When the semantic index is `ready` or `lagging`, cataloged resources are also found by meaning
(`catalog_semantic`) and merged with the text hits by rank fusion, one entry per catalog id. Only
cataloged entries are embedded; installed skills not yet in the catalog stay text-only. Without
semantic the output is unchanged.

`--no-resources` without a briefing returns the record-search JSON unchanged.
