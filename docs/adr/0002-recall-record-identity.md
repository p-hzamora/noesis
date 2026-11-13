# ADR-0002: preserve record identity through recall

Status: implemented, 2026-11-13. Storage ownership remains open.

## Context

Multi-source search deduplicates notes by ULID, but recall previously merged, ranked and
read them by source-relative path. Two sources can contain different `decision.md` records.
An integration regression reproduced the resulting loss of one candidate. Path citations
also could not distinguish those records.

## Decision

Carry stable IDs through recall candidate fusion and ranking. Resolve full content through
`read_by_id`, validating the identity and requested scope of the returned record. Existing
document adapters use ID lookup plus a checked path hint for vault-less MCP compatibility.
Multi-source reads try sources in primary-first order, accepting only a matching ID.

Add `id` to recall entries and verified `source_ids` to briefing items. Preserve existing
path fields for display and compatibility. Ask the recall agent to cite IDs; accept legacy
path citations only when unambiguous among the records actually read. Do not trust IDs
supplied in the draft's `source_ids` field: derive them from resolved citations.

## Consequences

Different records sharing a relative path remain distinct. A renamed local record can be
resolved by its unchanged ID; a replacement at its former path is rejected. Existing
filesystem, MCP and Vectra workflows retain their storage and fallback behavior.

This is a compatibility step, not the final port design. The mixed read/search repository
still needs separation. File lookups may scan repeatedly, divergent copies of one ID are
not reconciled, and reads do not pin revisions. Citation membership is not semantic claim
verification. No stored data or index schema changes; rollback needs only a code revert.

See [the architecture assessment](../design/knowledge-memory-direction.md) for the product
capability map and unchosen Neo4j/Vectra ownership alternatives.
