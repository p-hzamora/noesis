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

**Repository id**:
`<main folder name>-<8 hex>`, derived from the repository's common git directory. Every
worktree of a repository shares it, and so do its notes (`repos/<main folder name>/`).

**Child session**:
A capture session started with `capture on --parent`, for a sub-agent. It has its own pending
commits and cursor, inherits the parent's mode, and is merged into the parent's runs with
`capture runs --children`.

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
One Markdown document whose `noesis:` frontmatter block (id, scope, kind, origin, sources,
updated) is its identity; the folder it sits in means nothing. Kinds come from the manifest
(`noesis.yaml`; defaults: decision, gotcha, howto, concept, run, glossary).

**Auto note**:
A note written by noesis without a person in the loop. Carries `origin: auto`, is updated in
place (same id) when the topic recurs, and never edits a manual note.

**Recall**:
Preparing for a task from the notes: search by keyword, read the best notes in full, and have the
recall agent write a briefing. Read-only.

**Recall agent**:
The LLM that writes the briefing from notes noesis hands it (`IRecallAgent.brief`). It has no
tools and no access to the vault. Its runtime (`NOESIS_RECALL_RUNTIME`, the program that runs it)
and its model (`NOESIS_RECALL_MODEL`) are separate.

**Briefing**:
What recall returns: a summary plus constraints, decisions, gotchas, context, open questions,
inferences and gaps, each statement citing the notes it rests on. Not the same as the agent's
instructions (`recall_system.md`) and not a work brief.

**Vault**:
The folder that stores notes (`NOESIS_VAULT_DIR`). An Obsidian vault is one kind of vault.

_Avoid_: "brain" as a structural term; "writer" for the curator (it does not write).
