"""Test doubles for `remember`: a similar-record lookup with fixed answers and a flaky proposer."""

from collections.abc import Sequence

from noesis.bounded_context.knowledge.application.dtos import ProposeAssertionResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionCommand,
    ProposeAssertionHandler,
)
from noesis.exceptions import GraphStoreUnavailableError
from noesis.shared_kernel.contracts.retrieval import RecordSearchHitContract, RecordSearchHitItem


class FakeFinder:
    """Answers every lookup with fixed hits, or fails like an unavailable index."""

    def __init__(self, hits: Sequence[str] = (), *, fail: bool = False) -> None:
        self.hits: list[str] = list(hits)
        self.fail: bool = fail
        self.calls: int = 0

    async def find(
        self, text: str, *, space_id: str, project_key: str | None, limit: int
    ) -> RecordSearchHitContract:
        self.calls += 1
        if self.fail:
            raise GraphStoreUnavailableError("index down", {})
        return RecordSearchHitContract(
            hits=tuple(
                RecordSearchHitItem(
                    record_id=record_id,
                    record_type="knowledge",
                    title="Retry policy",
                    authority="authoritative",
                    sources=("lexical",),
                    revised_at="2026-11-14T12:00:00Z",
                    rank=rank,
                )
                for rank, record_id in enumerate(self.hits, start=1)
            ),
            pending_changes=0,
            semantic_state="absent",
        )


class FlakyPropose(ProposeAssertionHandler):
    """Fails its first call like a store that dropped the connection, then behaves."""

    failures_left: int = 1

    async def handle(self, action: ProposeAssertionCommand) -> ProposeAssertionResultDto:
        if self.failures_left > 0:
            self.failures_left -= 1
            raise GraphStoreUnavailableError("connection lost", {})
        return await super().handle(action)
