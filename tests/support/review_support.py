"""Support for the C4 container, CLI and subprocess tests (assertions and review lifecycle).

Environment helpers (`env_agent`, `env_user`), a whole-graph digest to prove "nothing written",
raw reads of decisions, the real handlers wired over a Neo4j container with seeding helpers
("seed accepted X" means capture then accept by the user, in-process, 90-verification), and a
unit-of-work factory that raises on the Nth commit. The C4 modules imported here do not exist
until C4 is built.
"""

import asyncio
import hashlib
import io
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

import pytest
from tests.support.knowledge_commands import COMMIT, experience_command, revise_command
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, make_neo4j_env, query
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY
from tests.support.review_commands import (
    USER,
    accept_assertion_command,
    accept_knowledge_command,
    propose_command,
    retract_knowledge_command,
)

from noesis.bounded_context.knowledge.application.handlers.commands.accept_assertion_handler import (
    AcceptAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.accept_knowledge_handler import (
    AcceptKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.apply_supersession_handler import (
    ApplySupersessionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.bulk_accept_knowledge_by_tag_handler import (
    BulkAcceptKnowledgeByTagHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.repair_supersession_effects_handler import (
    RepairSupersessionEffectsHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retract_assertion_handler import (
    RetractAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retract_knowledge_handler import (
    RetractKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_review_states_handler import (
    GetReviewStatesHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_assertions_by_subjects_handler import (
    ListAssertionsBySubjectsHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_review_queue_handler import (
    ListReviewQueueHandler,
)
from noesis.bounded_context.knowledge.application.services.inputs import ProjectRef
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    AssertionPredicateEnum,
    Key,
    RecordId,
    Slug,
    Tag,
)
from noesis.exceptions import GraphStoreUnavailableError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

SPACE: Final[str] = "default"
AGENT_SESSION: Final[str] = "test-agent-1"
MIGRATED: Final[str] = "origin:migrated"
HARNESS_MARKERS: Final[tuple[str, ...]] = (
    "NOESIS_SESSION_ID",
    "CODEX_THREAD_ID",
    "CODEX_SESSION_ID",
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "AI_AGENT",
)
requires_pty = pytest.mark.skipif(
    sys.platform not in {"linux", "darwin"},
    reason="the pseudo-terminal helper (pty.openpty) runs on Linux and macOS only",
)


# --- environments -----------------------------------------------------------------------------


def env_agent(env: dict[str, str]) -> dict[str, str]:
    """`env` with exactly one harness marker, `NOESIS_SESSION_ID=test-agent-1`."""
    clean: dict[str, str] = {k: v for k, v in env.items() if k not in HARNESS_MARKERS}
    return {**clean, "NOESIS_SESSION_ID": AGENT_SESSION}


def env_user(env: dict[str, str]) -> dict[str, str]:
    """`env` with no harness marker at all."""
    return {k: v for k, v in env.items() if k not in HARNESS_MARKERS}


class _Stdin(io.StringIO):
    """A stand-in for `sys.stdin` whose terminal-ness the test decides."""

    def __init__(self, *, tty: bool) -> None:
        super().__init__("")
        self._tty: bool = tty

    def isatty(self) -> bool:
        """Whether the test says this is an interactive terminal."""
        return self._tty


def attach_terminal(monkeypatch: pytest.MonkeyPatch, *, tty: bool = True) -> None:
    """In-process: make `sys.stdin.isatty()` answer `tty` (the CLI must ask it at call time)."""
    monkeypatch.setattr("sys.stdin", _Stdin(tty=tty))


# --- the graph as raw data --------------------------------------------------------------------


def graph_digest(settings: Neo4jConnectionSettings) -> str:
    """A hash over every node (labels and properties) and every relationship (type, ends, properties).

    Nothing is ignored, so equality before and after a command proves it wrote nothing.
    """
    nodes: list[dict[str, Any]] = query(
        settings,
        "MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props",
    )
    relationships: list[dict[str, Any]] = query(
        settings,
        "MATCH (a)-[r]->(b) RETURN elementId(a) AS start, type(r) AS type, "
        "elementId(b) AS end, properties(r) AS props",
    )
    canonical: str = json.dumps(
        {
            "nodes": sorted(
                json.dumps({**node, "labels": sorted(node["labels"])}, sort_keys=True, default=repr)
                for node in nodes
            ),
            "relationships": sorted(
                json.dumps(rel, sort_keys=True, default=repr) for rel in relationships
            ),
        }
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def decisions_of(settings: Neo4jConnectionSettings, record_id: str) -> list[dict[str, Any]]:
    """The `:Decision` nodes of a record, ordered by `seq`, as raw property maps."""
    rows: list[dict[str, Any]] = query(
        settings,
        "MATCH (d:Decision)-[:DECIDES]->(r:Record {id: $id}) RETURN properties(d) AS d ORDER BY d.seq",
        id=record_id,
    )
    return [row["d"] for row in rows]


def record_snapshot(settings: Neo4jConnectionSettings, record_id: str) -> dict[str, Any]:
    """A record's labels, properties and decisions, to compare before and after a command."""
    rows: list[dict[str, Any]] = query(
        settings,
        "MATCH (r:Record {id: $id}) RETURN labels(r) AS labels, properties(r) AS props",
        id=record_id,
    )
    assert len(rows) == 1, f"record {record_id} not found"
    return {
        "labels": sorted(rows[0]["labels"]),
        "props": rows[0]["props"],
        "decisions": decisions_of(settings, record_id),
    }


def stored_status(settings: Neo4jConnectionSettings, record_id: str) -> str | None:
    """The stored `status` property of a record."""
    rows = query(settings, "MATCH (r:Record {id: $id}) RETURN r.status AS status", id=record_id)
    return rows[0]["status"]


def count_nodes(settings: Neo4jConnectionSettings, label: str) -> int:
    """How many nodes carry `label` (a plain identifier)."""
    assert label.isidentifier()
    rows = query(settings, f"MATCH (n:{label}) RETURN count(n) AS total")  # type: ignore[arg-type]
    return int(rows[0]["total"])


# --- handlers over the real store ---------------------------------------------------------------


class FailingCommitUow:
    """Delegates to a real unit of work; the Nth commit of the factory raises instead of committing."""

    def __init__(self, inner: Any, should_fail: Callable[[], bool]) -> None:
        self._inner: Any = inner
        self._should_fail: Callable[[], bool] = should_fail

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def __aenter__(self) -> FailingCommitUow:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._inner.__aexit__(*exc)

    async def commit(self) -> None:
        """Raise `INTEGRATION_103` when it is this unit of work's turn; the rollback follows."""
        if self._should_fail():
            raise GraphStoreUnavailableError(
                "Connection lost before commit (test fault).", {"phase": "commit"}
            )
        await self._inner.commit()


class CommitFailingFactory:
    """A unit-of-work factory whose `fail_on`-th committing unit of work raises (1-based)."""

    def __init__(self, inner: Callable[[], Any], *, fail_on: int) -> None:
        self._inner: Callable[[], Any] = inner
        self.fail_on: int = fail_on
        self.commits: int = 0

    def __call__(self) -> FailingCommitUow:
        return FailingCommitUow(self._inner(), self._next_is_failure)

    def _next_is_failure(self) -> bool:
        self.commits += 1
        return self.commits == self.fail_on


@dataclass(frozen=True, slots=True)
class BulkFixture:
    """The bulk fixture of AC-025..AC-027 (ids ascend with the number, `k1 < k2 < k3 < k5`).

    Attributes:
        k1: Tagged, in `acme`, revised once while proposed (head 2); titled "Bulk one".
        k2: Tagged, space-wide, head 1; titled "Bulk two".
        k3: Tagged and accepted by the user.
        k5: In `acme`, not tagged, proposed.
    """

    k1: RecordId
    k2: RecordId
    k3: RecordId
    k5: RecordId


@dataclass(frozen=True, slots=True)
class SelectionWorld:
    """The AC-030 world: one record the bulk accept may change and six it must leave alone.

    Attributes:
        k1: Tagged, proposed, space `default`: the only record that changes.
        untouched: Untagged proposed knowledge, a tagged assertion, tagged knowledge in space B,
            knowledge with tag `origin:migrated-old`, tagged knowledge superseded by an accepted
            `supersedes`, and tagged knowledge that was accepted and then retracted.
    """

    k1: RecordId
    untouched: tuple[RecordId, ...]


@dataclass(slots=True)
class ReviewNeo4jEnv:
    """C2's Neo4j environment plus the C4 handlers, read repositories and seeding helpers."""

    base: Neo4jKnowledgeEnv
    settings: Neo4jConnectionSettings

    @property
    def client(self) -> Any:
        """The shared Neo4j client (close it when done)."""
        return self.base.client

    def uow(self) -> Any:
        """A fresh unit of work (one transaction)."""
        return self.base.uow()

    def _deps(self, uow_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
        deps: dict[str, Any] = self.base._deps()
        return {**deps, "uow_factory": uow_factory or deps["uow_factory"]}

    def propose_assertion(self, uow_factory: Any = None) -> ProposeAssertionHandler:
        """`assertion propose` over the real store."""
        return ProposeAssertionHandler(**self._deps(uow_factory))

    def accept_knowledge(self, uow_factory: Any = None) -> AcceptKnowledgeHandler:
        """`review accept <knowledge>` over the real store."""
        return AcceptKnowledgeHandler(**self._deps(uow_factory))

    def accept_assertion(self, uow_factory: Any = None) -> AcceptAssertionHandler:
        """`review accept <assertion>` over the real store."""
        return AcceptAssertionHandler(**self._deps(uow_factory))

    def retract_knowledge(self, uow_factory: Any = None) -> RetractKnowledgeHandler:
        """`review retract <knowledge>` over the real store."""
        return RetractKnowledgeHandler(**self._deps(uow_factory))

    def retract_assertion(self, uow_factory: Any = None) -> RetractAssertionHandler:
        """`review retract <assertion>` over the real store."""
        return RetractAssertionHandler(**self._deps(uow_factory))

    def apply_supersession(self, uow_factory: Any = None) -> ApplySupersessionHandler:
        """The supersession effect over the real store."""
        return ApplySupersessionHandler(**self._deps(uow_factory))

    def repair(self, uow_factory: Any = None) -> RepairSupersessionEffectsHandler:
        """`review repair` over the real store."""
        return RepairSupersessionEffectsHandler(
            **self._deps(uow_factory),
            state_reader=self.base.persistence.review_state_read_repository,
        )

    def bulk_accept(self, uow_factory: Any = None) -> BulkAcceptKnowledgeByTagHandler:
        """The bulk accept by tag over the real store."""
        return BulkAcceptKnowledgeByTagHandler(
            **self._deps(uow_factory),
            queue_reader=self.base.persistence.review_queue_read_repository,
        )

    @property
    def get_review_states(self) -> GetReviewStatesHandler:
        """`GetReviewStatesHandler` over the real store."""
        persistence = self.base.persistence
        return GetReviewStatesHandler(
            read_repository=persistence.review_state_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        )

    @property
    def list_assertions_by_subjects(self) -> ListAssertionsBySubjectsHandler:
        """`ListAssertionsBySubjectsHandler` over the real store."""
        persistence = self.base.persistence
        return ListAssertionsBySubjectsHandler(
            read_repository=persistence.assertion_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        )

    @property
    def list_review_queue(self) -> ListReviewQueueHandler:
        """`ListReviewQueueHandler` over the real store."""
        persistence = self.base.persistence
        return ListReviewQueueHandler(
            read_repository=persistence.review_queue_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        )

    # --- seeding ----------------------------------------------------------------------------

    async def initialise(self) -> None:
        """`store init` with the registered steps (core and review) and the default space."""
        await self.base.initialise_store.handle(
            InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
        )

    async def space_id(self) -> str:
        """Id of the default space."""
        rows = query(self.settings, "MATCH (s:Space {key: $key}) RETURN s.id AS id", key=SPACE)
        return str(rows[0]["id"])

    async def capture(
        self,
        key: str,
        *,
        project: str | None = None,
        tags: Sequence[str] = (),
        title: str = "Retry policy",
        body: str = "Use retries.",
        actor: Actor = AGENT,
        space_key: Key = DEFAULT_SPACE_KEY,
    ) -> RecordId:
        """Capture proposed graph-owned knowledge through C2's handler.

        The fake clock moves one second first, so ids (ULIDs) ascend in creation order.
        """
        self.base.clock.advance()
        result = await self.base.capture_knowledge.handle(
            CaptureKnowledgeCommand(
                idempotency_key=key,
                space_key=space_key,
                title=title,
                body=body,
                subtype=Slug(value="decision"),
                actor=actor,
                project=ProjectRef(key=Key(value=project)) if project else None,
                tags=tuple(Tag(value=tag) for tag in tags),
                sources=(COMMIT,),
            )
        )
        return RecordId(value=result.record_id)

    async def capture_experience(self, key: str = "exp-1") -> RecordId:
        """Capture an experience through C2's handler (ids ascend, see `capture`)."""
        self.base.clock.advance()
        result = await self.base.capture_experience.handle(experience_command(key))
        return RecordId(value=result.record_id)

    async def seed_accepted(
        self,
        key: str,
        *,
        project: str | None = None,
        tags: Sequence[str] = (),
        title: str = "Retry policy",
    ) -> RecordId:
        """Seed accepted knowledge: capture, then accept at revision 1 by the user."""
        record_id = await self.capture(key, project=project, tags=tags, title=title)
        await self.accept_knowledge().handle(
            accept_knowledge_command(record_id, f"seed-{key}", actor=USER)
        )
        return record_id

    async def seed_bulk_fixture(self) -> BulkFixture:
        """K1 (acme, revised to head 2), K2 (space-wide), K3 (accepted), all `origin:migrated`; K5 untagged."""
        k1 = await self.capture("bulk-k1", project="acme", tags=(MIGRATED,), title="Bulk one")
        await self.base.revise_knowledge.handle(revise_command(k1, "bulk-k1-rev", expected=1))
        k2 = await self.capture("bulk-k2", tags=(MIGRATED,), title="Bulk two")
        k3 = await self.seed_accepted("bulk-k3", tags=(MIGRATED,), title="Bulk three")
        k5 = await self.capture("bulk-k5", project="acme", title="Bulk five")
        return BulkFixture(k1=k1, k2=k2, k3=k3, k5=k5)

    async def seed_selection_world(self) -> SelectionWorld:
        """K1 and the records of AC-030 that a tag-based bulk accept must not touch."""
        await self.base.initialise_store.handle(  # creates space B; the steps stay applied
            InitialiseStoreCommand(default_space_key=Key(value="space-b"))
        )
        k1 = await self.capture("sel-k1", tags=(MIGRATED,))
        untagged = await self.capture("sel-u")
        experience = await self.capture_experience("sel-exp")
        tagged_assertion = await self.propose(
            AssertionPredicateEnum.SUPPORTS, experience, k1, "sel-a", tags=(MIGRATED,)
        )
        in_space_b = await self.capture("sel-kb", tags=(MIGRATED,), space_key=Key(value="space-b"))
        similar_tag = await self.capture("sel-ko", tags=("origin:migrated-old",))
        superseded = await self.seed_accepted("sel-ks", tags=(MIGRATED,))
        successor = await self.seed_accepted("sel-n")
        await self.seed_accepted_assertion(
            AssertionPredicateEnum.SUPERSEDES, successor, superseded, "sel-sup"
        )
        retracted = await self.seed_accepted("sel-kr", tags=(MIGRATED,))
        await self.retract_knowledge().handle(
            retract_knowledge_command(retracted, "sel-kr-ret", reason="obsolete")
        )
        return SelectionWorld(
            k1=k1,
            untouched=(untagged, tagged_assertion, in_space_b, similar_tag, superseded, retracted),
        )

    async def seed_catalog_entry(self) -> RecordId:
        """A bare `:Record:CatalogEntry {id, space_id}` node: all C6 owes the review side."""
        self.base.clock.advance()
        record_id: RecordId = self.base.persistence.ids.new_record_id()
        query(
            self.settings,
            "CREATE (:Record:CatalogEntry {id: $id, space_id: $space_id})",
            id=record_id.value,
            space_id=await self.space_id(),
        )
        return record_id

    async def propose(
        self,
        predicate: AssertionPredicateEnum,
        subject: RecordId,
        object_: RecordId,
        key: str,
        *,
        evidence: tuple[RecordId, ...] = (),
        project: str | None = None,
        tags: tuple[str, ...] = (),
        actor: Actor = AGENT,
    ) -> RecordId:
        """Propose an assertion through the handler; returns its id (ids ascend, see `capture`)."""
        self.base.clock.advance()
        result = await self.propose_assertion().handle(
            propose_command(
                predicate,
                subject,
                object_,
                key,
                evidence=evidence,
                project=project,
                tags=tags,
                actor=actor,
            )
        )
        return RecordId(value=result.id)

    async def seed_accepted_assertion(
        self,
        predicate: AssertionPredicateEnum,
        subject: RecordId,
        object_: RecordId,
        key: str,
        *,
        evidence: tuple[RecordId, ...] = (),
        project: str | None = None,
    ) -> RecordId:
        """Propose an assertion, then accept it by the user."""
        assertion_id = await self.propose(
            predicate, subject, object_, key, evidence=evidence, project=project
        )
        await self.accept_assertion().handle(
            accept_assertion_command(assertion_id, f"seed-{key}", actor=USER)
        )
        return assertion_id


def make_review_neo4j_env(settings: Neo4jConnectionSettings) -> ReviewNeo4jEnv:
    """A client and handlers whose schema registry holds `core` and `review`; close `.client`."""
    from noesis.bounded_context.knowledge.infrastructure.outbound.persistence.neo4j_store_schema_adapter import (
        REVIEW_SCHEMA_STEP,  # infrastructure is imported lazily, so the CLI-only tests collect without it
    )

    return ReviewNeo4jEnv(make_neo4j_env(settings, extra_steps=(REVIEW_SCHEMA_STEP,)), settings)


def run_with_handlers[T](
    settings: Neo4jConnectionSettings, use: Callable[[ReviewNeo4jEnv], Awaitable[T]]
) -> T:
    """Run `use` over fresh handlers in its own event loop (for the synchronous CLI/e2e tests)."""

    async def go() -> T:
        env: ReviewNeo4jEnv = make_review_neo4j_env(settings)
        try:
            return await use(env)
        finally:
            await env.client.close()

    return asyncio.run(go())
