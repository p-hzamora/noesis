"""C9's handlers over the pinned Neo4j container, a stub similarity lookup and seeding helpers.

"Seed accepted" means capture through C2's handler with a source of its own, then accept by the
user, in-process, so the originals have independent evidence the way 90-verification AC-01 asks.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from tests.support.knowledge_neo4j_support import make_neo4j_env, query
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY
from tests.support.review_commands import USER, accept_knowledge_command
from tests.support.review_support import ReviewNeo4jEnv

from noesis.bounded_context.knowledge.application.dtos import ConsolidationProposalDto
from noesis.bounded_context.knowledge.application.handlers.commands.accept_consolidation_handler import (
    AcceptConsolidationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_consolidation_handler import (
    ProposeConsolidationCommand,
    ProposeConsolidationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.reject_consolidation_handler import (
    RejectConsolidationCommand,
    RejectConsolidationHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.scan_consolidation_candidates_handler import (
    ScanConsolidationCandidatesHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.show_consolidation_handler import (
    ListConsolidationsHandler,
    ShowConsolidationHandler,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    NewSourceInput,
    ProjectRef,
    SourceInput,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ConsolidationId,
    DismissalReasonKindEnum,
    Key,
    RecordId,
    Slug,
    SourceKindEnum,
    Tag,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence import (
    CONSOLIDATION_SCHEMA_STEP,
    REVIEW_SCHEMA_STEP,
)
from noesis.shared_kernel.contracts.retrieval import SimilarRecordHitItem, SimilarRecordsContract
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

MIGRATED = "origin:migrated"


@dataclass(slots=True)
class StubSimilarFinder:
    """`ISimilarRecordFinder` that answers from a table, or fails on demand."""

    hits: dict[str, list[tuple[str, tuple[str, ...]]]] = field(default_factory=dict)
    semantic_state: str = "absent"
    error: Exception | None = None
    calls: list[tuple[str, int]] = field(default_factory=list)

    async def find_similar(
        self, record_id: str, *, space_id: str, limit: int
    ) -> SimilarRecordsContract:
        """The configured hits for the anchor, capped at `limit`."""
        self.calls.append((record_id, limit))
        if self.error is not None:
            raise self.error
        rows = self.hits.get(record_id, [])[:limit]
        return SimilarRecordsContract(
            anchor_id=record_id,
            hits=tuple(
                SimilarRecordHitItem(record_id=hit, revision=1, rank=rank, found_by=found_by)
                for rank, (hit, found_by) in enumerate(rows, start=1)
            ),
            semantic_state=self.semantic_state,
        )


@dataclass(slots=True)
class ConsolidationEnv:
    """The review environment plus the consolidation handlers and seeding helpers."""

    review: ReviewNeo4jEnv
    finder: StubSimilarFinder
    seeded: int = 0

    @property
    def settings(self) -> Neo4jConnectionSettings:
        """The container's connection settings."""
        return self.review.settings

    @property
    def client(self) -> Any:
        """The shared Neo4j client."""
        return self.review.client

    def uow(self) -> Any:
        """A fresh unit of work."""
        return self.review.uow()

    def _deps(self, uow_factory: Callable[[], Any] | None) -> dict[str, Any]:
        persistence = self.review.base.persistence
        return {
            "uow_factory": uow_factory or persistence.uow_factory,
            "clock": self.review.base.clock,
            "ids": persistence.ids,
            "schema": persistence.schema,
            "states": persistence.review_state_read_repository,
            "read_repository": persistence.consolidation_read_repository,
        }

    def propose(self, uow_factory: Any = None) -> ProposeConsolidationHandler:
        """`consolidation propose` over the real store."""
        return ProposeConsolidationHandler(**self._deps(uow_factory))

    def accept(self, uow_factory: Any = None) -> AcceptConsolidationHandler:
        """`consolidation accept` over the real store."""
        return AcceptConsolidationHandler(**self._deps(uow_factory))

    def reject(self, uow_factory: Any = None) -> RejectConsolidationHandler:
        """`consolidation reject` over the real store."""
        return RejectConsolidationHandler(**self._deps(uow_factory))

    @property
    def scan(self) -> ScanConsolidationCandidatesHandler:
        """`consolidation scan` over the real store and the stub finder."""
        persistence = self.review.base.persistence
        return ScanConsolidationCandidatesHandler(
            read_repository=persistence.consolidation_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
            finder=self.finder,
        )

    @property
    def show(self) -> ShowConsolidationHandler:
        """`consolidation show` over the real store."""
        persistence = self.review.base.persistence
        return ShowConsolidationHandler(
            read_repository=persistence.consolidation_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
            states=persistence.review_state_read_repository,
        )

    @property
    def listing(self) -> ListConsolidationsHandler:
        """`consolidation list` over the real store."""
        persistence = self.review.base.persistence
        return ListConsolidationsHandler(
            read_repository=persistence.consolidation_read_repository,
            records=persistence.read_repository,
            schema=persistence.schema,
        )

    async def seed(
        self,
        key: str,
        *,
        project: str | None = "acme",
        subtype: str = "decision",
        title: str | None = None,
        tags: Sequence[str] = (),
        accept: bool = True,
        sources: Sequence[SourceInput] | None = None,
    ) -> RecordId:
        """Capture Knowledge with a source of its own, and accept it by the user unless told not to."""
        self.seeded += 1
        self.review.base.clock.advance()
        locator: str = f"{self.seeded:040x}"
        result = await self.review.base.capture_knowledge.handle(
            CaptureKnowledgeCommand(
                idempotency_key=f"seed-{key}",
                space_key=DEFAULT_SPACE_KEY,
                title=title or f"Retry policy {key}",
                body=f"Use retries ({key}).",
                subtype=Slug(value=subtype),
                actor=AGENT,
                project=ProjectRef(key=Key(value=project)) if project else None,
                tags=tuple(Tag(value=tag) for tag in tags),
                sources=tuple(sources)
                if sources is not None
                else (NewSourceInput(kind=SourceKindEnum.COMMIT, locator=locator),),
            )
        )
        record_id = RecordId(value=result.record_id)
        if accept:
            await self.review.accept_knowledge().handle(
                accept_knowledge_command(record_id, f"accept-{key}", actor=USER)
            )
        return record_id

    def command(
        self,
        members: Sequence[RecordId],
        key: str | None = "p1",
        *,
        actor: Actor = AGENT,
        apply: bool = True,
        **overrides: Any,
    ) -> ProposeConsolidationCommand:
        """A valid propose command; override what a test cares about."""
        fields: dict[str, Any] = {
            "space_key": DEFAULT_SPACE_KEY,
            "actor": actor,
            "apply": apply,
            "idempotency_key": key,
            "member_ids": tuple(members),
            "title": "Retry policy, merged",
            "body": "Retry transient failures with backoff.",
            "rationale": "Both describe the same retry rule.",
        }
        return ProposeConsolidationCommand(**{**fields, **overrides})

    async def propose_pair(
        self, key: str = "p1", *, project: str | None = "acme"
    ) -> tuple[RecordId, RecordId, ConsolidationProposalDto]:
        """Seed two accepted records and propose their consolidation as the agent."""
        first = await self.seed(f"{key}-a", project=project)
        second = await self.seed(f"{key}-b", project=project)
        result = await self.propose().handle(self.command([first, second], key))
        return first, second, result

    def reject_command(
        self,
        consolidation_id: str,
        key: str | None = "r1",
        *,
        kind: DismissalReasonKindEnum = DismissalReasonKindEnum.DISTINCT,
        actor: Actor = USER,
        apply: bool = True,
    ) -> RejectConsolidationCommand:
        """A valid reject command."""
        return RejectConsolidationCommand(
            space_key=DEFAULT_SPACE_KEY,
            actor=actor,
            apply=apply,
            idempotency_key=key,
            consolidation_id=ConsolidationId(value=consolidation_id),
            reason_kind=kind,
            reason="They are different rules.",
        )


def make_consolidation_env(settings: Neo4jConnectionSettings) -> ConsolidationEnv:
    """A client and handlers whose registry holds `core`, `review` and `consolidation`."""
    base = make_neo4j_env(settings, extra_steps=(REVIEW_SCHEMA_STEP, CONSOLIDATION_SCHEMA_STEP))
    return ConsolidationEnv(review=ReviewNeo4jEnv(base, settings), finder=StubSimilarFinder())


def raw_consolidations(settings: Neo4jConnectionSettings) -> list[dict[str, Any]]:
    """Every `:Consolidation` node's properties, ascending id."""
    rows = query(settings, "MATCH (c:Consolidation) RETURN properties(c) AS c ORDER BY c.id")
    return [row["c"] for row in rows]


def open_keys(settings: Neo4jConnectionSettings) -> list[str]:
    """Record ids an open consolidation currently holds."""
    rows = query(
        settings,
        "MATCH (m:ConsolidationMembership) WHERE m.open_key IS NOT NULL "
        "RETURN m.open_key AS k ORDER BY k",
    )
    return [row["k"] for row in rows]


def change_kinds(settings: Neo4jConnectionSettings) -> list[str]:
    """The change kinds of the feed, in sequence order."""
    rows = query(settings, "MATCH (c:Change) RETURN c.change_kind AS kind ORDER BY c.sequence")
    return [row["kind"] for row in rows]


def run_with_consolidation[T](
    settings: Neo4jConnectionSettings, use: Callable[[ConsolidationEnv], Awaitable[T]]
) -> T:
    """Run `use` over fresh handlers in its own event loop (for the synchronous CLI tests)."""

    async def go() -> T:
        env: ConsolidationEnv = make_consolidation_env(settings)
        try:
            return await use(env)
        finally:
            await env.client.close()

    return asyncio.run(go())
