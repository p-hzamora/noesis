# noesis

The vocabulary of the project. Use these terms in code, docs, and conversation.

## Language

**Capture** (bounded context):
Detecting units of finished work inside an agent session and deciding when they are ready
to hand over. Knows sessions, commits, and transcripts; knows nothing about notes.

**Knowledge** (bounded context):
Deciding what is worth keeping and storing it. Knows notes, curation, and storage; knows
nothing about agent sessions.

**Capture session**:
One agent session that the user switched on for capture. Holds the commits waiting to be
handed over and how far the transcript has been read.

**Work brief**:
The compact, versioned description of finished work that Capture hands to Knowledge:
repository, commits, diff stat, session goal, and an excerpt of the conversation. Never a diff.

**Hand-over**:
Capture publishing a work brief for the pending commits. In live mode it starts the
curator as a detached process; in dry-run mode it only stores the brief.

**Journal**:
The append-only per-session record of what Capture did (`noesis capture runs`).

**Curator**:
The LLM that judges a work brief against the admission rule and drafts note decisions.
It never writes storage itself.

**Admission rule**:
Keep decisions with rationale, non-obvious gotchas, run outcomes, and glossary terms;
reject anything the repository already records.

**Note**:
One Markdown document with frontmatter, of a kind (decision, gotcha, run, glossary) and an
origin (manual or auto).

**Auto note**:
A note written by noesis without a person in the loop. Lives only under
`<area>/auto/`, carries `origin: auto`, and never edits a manual note.

**Vault**:
The folder that stores notes (`NOESIS_VAULT_DIR`). An Obsidian vault is one kind of vault.

_Avoid_: "brain" as a structural term; "writer" for the curator (it does not write).
