# noesis

The vocabulary of the project. Use these terms in code, docs, and conversation.

## Language

**Capture** (bounded context):
Detecting units of finished work inside an agent session and deciding when they are ready
to hand over. Knows sessions, commits, and transcripts; knows nothing about notes.

**Notes** (bounded context):
Owns a note from its creation through validation to storing it or not. Knows notes,
curation, and storage; knows nothing about agent sessions.

**Capture session**:
One agent session that the user switched on for capture. Holds the commits waiting to be
handed over and how far the transcript has been read.

**Work brief**:
The compact, versioned description of finished work that Capture hands to Notes:
repository, commits, diff stat, session goal, and an excerpt of the conversation. Never a diff.

**Hand-over**:
Capture publishing a work brief for the pending commits. In live mode it starts the
curator as a detached process; in dry-run mode it only stores the brief.

**Journal**:
The append-only per-session record of what Capture did (`noesis capture runs`).

**Curator**:
The LLM that judges a work brief against the admission rule and drafts note decisions
(`ICurator.judge`). It never writes storage itself.

**Curate**:
The whole flow behind `noesis notes curate`: the curator judges, then apply stores what it
admitted.

**Apply**:
Storing decisions as auto notes through the auto-curation policy, with no curator. It is the
second half of curate, and `noesis notes apply` runs it alone for drafts a person or an agent
wrote. A failed apply keeps its payload in the failure log.

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
