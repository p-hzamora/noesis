# Running the knowledge store (Neo4j)

The `knowledge` context keeps records in a local Neo4j Community database
([ADR-0003](../adr/0003-knowledge-context-and-neo4j-record-store.md)). `noesis store init`,
`noesis record ...`, `noesis curate brief`, `noesis curate apply` and the Neo4j check of
`noesis doctor` need it; the Capture hooks do not.

## Start it

`compose.yaml` at the repository root pins the image (`neo4j:5.26.33-community`), binds the HTTP
(7474) and Bolt (7687) ports to 127.0.0.1 and keeps data in the `neo4j-data` volume. The password
is never committed; Compose reads it from the environment and refuses to start without it.

```bash
export NOESIS_NEO4J_PASSWORD='<8 or more characters>'
docker compose up -d
```

The password only takes effect while the volume is empty. To change it later, use
`ALTER CURRENT USER SET PASSWORD` in `cypher-shell`.

## Configure noesis

Put the same password in your **user-side** profile (`~/.config/noesis/.env`, or
`~/.config/noesis/profiles/<repo>/<name>.env`) or in the environment, never in a file inside a
repository (ADR-0001, Amendment 3):

```text
NOESIS_NEO4J_PASSWORD=<the password>
# defaults, change only when needed:
# NOESIS_NEO4J_URI=bolt://127.0.0.1:7687
# NOESIS_NEO4J_USER=neo4j
# NOESIS_NEO4J_DATABASE=neo4j
# NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS=5
# NOESIS_KNOWLEDGE_SPACE=personal
```

`noesis config show` masks the password.

## Initialise

```bash
noesis store init
```

It applies the named schema steps (single-property uniqueness constraints only) and creates the
configured space. It is safe to repeat: a step already applied is skipped. Other commands on a store
that was not initialised fail with a typed error that points here.

If Neo4j is stopped or unreachable, store commands fail closed with
`INTEGRATION_103_GRAPH_STORE_UNAVAILABLE` (exit 1) within the connect timeout and change nothing.

## Back up (offline)

Neo4j Community has no online backup. Stop the database, dump it, start it again:

```bash
docker compose stop neo4j
docker compose run --rm --no-deps -v "$PWD/backups:/backups" neo4j \
  neo4j-admin database dump neo4j --to-path=/backups
docker compose start neo4j
```

The dump is `backups/neo4j.dump`. To restore, stop the container and run
`neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true` the same way.

Back to [workflows](README.md).
