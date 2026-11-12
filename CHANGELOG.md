# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `noesis vault doctor` and `noesis vault migrate --plan <file> [--apply]`: restructure a vault
  to the manifest layout from a plan, crash-safe and idempotent, with wikilinks kept pointing at
  moved files.
- Default kinds `drift` (folder `drift`) and `dependency` (folder `dependencies`).

## [0.1.1] - 2026-11-09

### Fixed

- Make `notes recall` search task sentences keyword by keyword when using the
  Obsidian MCP backend, so repository-scoped notes are discoverable.

### Tests

- Add an integration regression test covering recall through Obsidian MCP
  within an explicit repository area.
