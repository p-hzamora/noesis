# ADR-0003: a `knowledge` context and a Neo4j record store

## Status

Accepted (2026-11-14), chunk C2 (`c2-core-model-neo4j-store`). Decision ids below are C2's
(D-001..D-029 in its overview spec); only the ones that shape the architecture are recorded here.
The storage-ownership question left open by [ADR-0002](0002-recall-record-identity.md) and the
[knowledge and memory direction](../design/knowledge-memory-direction.md) is settled for records:
Neo4j holds them. Notes and Vectra keep their roles until later chunks move behaviour across.

## Context

Noesis modelled Markdown documents (paths, manifest kinds, frontmatter), not knowledge. It had no
place for records, immutable revisions or relationships independent of files, and no store that
could keep them. Later chunks (import of files, review, retrieval, work-brief capture, recall,
consolidation) all need that model and store, and are built in parallel.

## Decision

- **D-001 A new `knowledge` bounded context** beside `notes` and `capture`, with domain,
  application and infrastructure layers. C2 is additive (strangler): Notes and Capture are
  unchanged except for the removal of the Obsidian MCP backends (Amendment 6 of ADR-0001).
- **D-002 Responsibilities are not each a context.** Retrieval and indexing are one later
  context, import/export another; review, catalog and curation are modules of Knowledge.
- **D-003 Cross-context integration** goes only through JSON-native contracts in
  `shared_kernel/contracts/<publisher>/` that carry `contract_version`, a consumer-owned port typed
  with them, satisfied by an inbound adapter of the providing context and wired in the composition
  root. No context imports another and import-linter has no exception for it. Naming a kernel
  package after its publisher is a deliberate, recorded exception to a small kernel. The rule is in
  [architecture-rules.md](../architecture-rules.md).
- **D-004 Seven aggregates**, each its own root, repository and transaction, referencing each other
  by id: KnowledgeSpace, Project, Source, Knowledge, Experience, Assertion, CatalogEntry. C2
  persists the first five; Assertion and CatalogEntry are domain types with reserved storage (D-020).
- **D-013 One database, spaces as nodes, only single-property uniqueness constraints.** They are
  available in Neo4j Community and are the concurrency guard (revision key, idempotency key,
  natural keys). Required properties and types are enforced by the domain and mappers. Separate
  trust domains are separate Neo4j instances, not separate databases.
- **D-014 Fail closed, system-wide.** An unreachable store raises
  `INTEGRATION_103_GRAPH_STORE_UNAVAILABLE` (exit 1, next steps) from the shared Neo4j client,
  detected lazily at first access within the connect timeout (default 5 s), before any side effect.
  There is no fallback, partial result or cached answer; retrieval will raise the same code.
- **D-015 and D-027 Explicit `store init` with named schema steps.** The schema changes only
  through `noesis store init`, which applies an ordered list of named, idempotent, additive steps
  registered by any module or context and records them in `:StoreMeta`. A command may require a
  step by name. There is no numeric schema version, because four later chunks add constraints and
  indexes in parallel.
- **D-023 Pinned `neo4j:5.26.33-community`, offline dump backups.** The tag (the latest released
  LTS on 2026-11-14) is written only in `compose.yaml`; tests read it from there. Revisit when the
  announced 2026 LTS ships. Community has no online backup: stop the container and run
  `neo4j-admin database dump`.
- **Rules for the code.** `neo4j` is imported only by infrastructure and the shared client
  (`shared_kernel/infrastructure/outbound/neo4j/`); `knowledge` is in the layers, independence,
  framework-free and I/O-free import-linter contracts. Settings are `KnowledgeSettings`
  (`NOESIS_NEO4J_*`, `NOESIS_KNOWLEDGE_SPACE`), and the password is a secret read only from a
  user-side profile or the environment (ADR-0001, Amendment 3).

## Consequences

- Users who want records run a local Neo4j (`docker compose up -d`) and `noesis store init`; the
  rest of noesis works without it. The Community licence is GPLv3 for the server.
- A store outage fails every `record` and `store` command closed; agents see one stable code.
- Extension points (unit-of-work members, labels, edges, error blocks, ledger shape) are reserved
  in [architecture.md](../architecture.md), so later chunks add without changing C2.
- Neo4j and Vectra ownership of retrieval, and the move of notes and recall onto records, stay for
  later chunks. Until then two stores exist: files for notes, Neo4j for records.
- Constraints Community cannot express (composite, existence, node key) are not available; moving to
  Enterprise would be a new decision.
