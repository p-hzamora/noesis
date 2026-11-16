# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Recall resolves, merges and cites notes by stable ID, preserving different records with
  identical relative paths across sources and rejecting mismatched content. JSON adds
  `entries[].id` and verified `source_ids` alongside existing paths. Ambiguous legacy path
  citations are set aside; renamed local notes can resolve by their unchanged ID.
- Make configuration validation narrow optional settings for strict type checking; isolate
  capture tests from ambient Codex session identifiers.

### Added

- Rebuild `noesis recall` over Knowledge and Retrieval with revision citations, authority
  labels, redacted model-free digests, isolated synthesis and observed catalog availability.
- Discover live imported links and accepted supersession paths without transferring
  endorsement; tolerate unknown change-feed kinds while preserving contiguous cursors.

- Import vault wiki links, embeds and relative Markdown note links as versioned graph edge
  sets, with preview counts, ambiguous-target diagnostics and unchanged-record backfill.
  Run `noesis store init` to install the additive `links` schema step.

- `noesis vault doctor` and `noesis vault migrate --plan <file> [--apply]`: restructure a vault
  to the manifest layout from a plan, crash-safe and idempotent, with wikilinks kept pointing at
  moved files.
- Manifest `groups`: repositories matched by remote glob or name keep their notes under a group
  root (e.g. a gitignored `company/<org>/repos/`); `vault doctor` reports misplaced notes.
- Default kinds `drift` (folder `drift`) and `dependency` (folder `dependencies`).

## [0.1.1] - 2026-11-09

### Fixed

- Make `notes recall` search task sentences keyword by keyword when using the
  Obsidian MCP backend, so repository-scoped notes are discoverable.

### Tests

- Add an integration regression test covering recall through Obsidian MCP
  within an explicit repository area.
