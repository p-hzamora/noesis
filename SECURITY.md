# Security policy

## Supported versions

Only the latest release on `main` receives fixes while the project is in early development.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting:
**Security tab -> Report a vulnerability**.

Include what you found, how to reproduce it, and the impact you see. You can expect an
acknowledgement within a few days. Please give us reasonable time to fix the problem
before disclosing it.

## Scope notes

noesis edits Claude Code's `settings.json` (always with a backup and a preview), reads
session transcripts, runs `git`, and launches the `claude` CLI as a curator. Reports about
unexpected file writes, command injection through transcripts or commit messages, or
leaking private note content are especially welcome.
