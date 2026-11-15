# noesis

The vocabulary of the project. Use these terms in code, docs, and conversation.

## Language

**Capture** (bounded context):
Detecting units of finished work inside an agent session and deciding when they are ready
to hand over. Knows sessions, commits, and transcripts; knows nothing about notes.

**Notes** (bounded context):
Owns a note from its creation through validation to storing it or not. Knows notes,
curation, and storage; knows nothing about agent sessions.

**Knowledge** (bounded context):
Owns records and their history: spaces, projects, sources, immutable revisions, and the Neo4j
store that holds them. Knows records and ids; knows nothing about files, notes or agent sessions.
Distinct from the **Knowledge** record type below.

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
(`noesis.yaml`; defaults: decision, gotcha, howto, concept, run, glossary, drift, dependency).

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

**Migration plan**:
A JSON file of entries `{old, new, action, scope?, kind?}` that `noesis vault migrate` applies:
`note` adds or refreshes the `noesis:` block and moves the file, `move` relocates it byte for
byte, `keep` leaves it. noesis knows nothing about the old layout; a one-off generator writes
the plan.

**Group**:
A manifest entry (`groups:` in the vault's `noesis.yaml`) giving some repositories their own root,
e.g. a gitignored `company/<org>`; scope stays `repo:<name>`, only the folder changes. Membership
is decided by a remote glob (recommended: glob only, the file is pushed with the vault) or a
`repos` list. `vault doctor` has no remotes, so it infers membership from the group root a
repository's notes sit under (`{root}/repos/<name>/`).

**Record**:
Anything the knowledge store keeps under a ULID that is unique across all record types: a
knowledge item, an experience, an assertion, a source, a project or a catalog entry. A record
belongs to exactly one knowledge space, fixed at creation.

**Knowledge space**:
The top-level container of records, a node in the one database (`NOESIS_KNOWLEDGE_SPACE`, default
`personal`). Its key is unique; every record, project and idempotency key lives in one. An id from
another space is "not found". Separate trust domains are separate Neo4j instances.

**Project**:
A named anchor inside a space (key unique within the space), created on capture from the git root
name. It scopes applicability; it does not own records.

**Revision**:
One immutable, numbered version of a knowledge item, 1..n without gaps, each with an actor and at
least one source. Only the head revision number is stored on the record and doubles as the
optimistic-concurrency token: `record revise` must name the expected head.

**Source**:
Write-once evidence a record cites, kept before the records that use it: a `file_version`,
`commit`, `agent_session`, `url` or `work_brief`, with a locator and an optional digest. Its
natural key (space, kind, locator, digest) is unique.

**Ownership** (file-owned / graph-owned):
Who holds the text of a knowledge item, fixed at creation. A file-owned item keeps its text in a
file and its revisions record only the content hash, the file-version source id and the title as
read. A graph-owned item keeps title and body in its revisions, after secret redaction.

**Knowledge** (record type):
A statement of guidance with a subtype, an applicability (optional project plus tags), a status
(`proposed`, `accepted`, `superseded`, `retracted`) and numbered revisions. Starts `proposed`; it may
be revised only while `proposed`.

**Experience**:
A write-once record of something that happened (`observation`, `outcome`, `failure`) with at least
one source. It has no status and no revisions.

**Assertion**:
An immutable claim between two records (`supports`, `contradicts`, `supersedes`, `recommends`) with
evidence and a rationale; only its status changes. Modelled in the domain, stored by a later chunk.

**Catalog entry**:
A record of a tool agents may use (`skill`, `agent`, `cli_tool`, `mcp_server`), unique by kind and
name in a space, with append-only revisions of purpose, declared version, prerequisites and
location. It holds only values a caller supplied, never an install path, and availability is never
a property of it. Registered and revised with `noesis catalog`.

**Runtime**:
An agent harness whose installed capabilities noesis can list: `claude-code` or `codex`. A
catalog check names the runtime and the host it observed.

**Observation**:
What `catalog check` finds when it compares an entry with what a runtime has installed now:
`available`, `unavailable` or `unknown`, with a reason. It is computed per invocation and never
stored; only `available` means usable.

**Idempotency key**:
The caller's required token on every mutating `record` command. The same key and request returns the
original result without writing; the same key with a different request is rejected. Kept
indefinitely in the ledger.

**Schema step**:
A named, additive, idempotent change to the store's schema (`core` is the first). `noesis store
init` applies every registered step once and records it; a command may require a step by name.
There is no numeric schema version.
