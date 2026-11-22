# ADR-0005: discover installed skills from runtime manifests

Status: accepted, 2026-11-22.

## Context

The catalog (Knowledge BC) held only entries a caller registered; the live store had none.
`catalog scan` listed installed Claude Code and Codex artifacts by name but registered nothing,
and no full-text index covered catalog entries, so `search` could not find a skill that was never
registered, used or endorsed.

## Decision

- Runtime inventory adapters read each manifest's frontmatter (`description`, optional
  `metadata.noesis.requires`) and a sha256 digest of the file. Only the frontmatter block is
  parsed; nothing is executed and the body is never stored.
- `noesis catalog sync` registers new artifacts (`origin: discovered`, source kind `manifest`) and
  revises entries whose digest, description or version changed. It never deletes: an artifact
  that disappeared is reported `not_installed` and its history and assertions remain. A repeated
  sync with unchanged runtimes writes nothing.
- A `catalog_fulltext` index covers head catalog revisions (name, purpose, capabilities).
- Search also reads installed artifacts that are not yet synced, in memory and read-only, and
  reports them with `cataloged: false` plus a warning to run `catalog sync`.
- Dependencies use the existing `prerequisites` (one edge for "extends" and "requires").

## Consequences

Cold-start discovery works without writes and without a semantic index. Each search pays a
filesystem probe for the overlay (budget: NFR-004). Skill text stays authoritative in its files;
the graph holds metadata, digest and relations only.
