"""A semantic `ICandidateSource` whose hits, profile and failure a test sets."""

from collections.abc import Sequence
from typing import NamedTuple

from noesis.bounded_context.retrieval.application.ports.candidates.i_candidate_source import (
    CandidateSourceUnavailableError,
    ICandidateSource,
    RankedCandidatesDto,
)
from noesis.bounded_context.retrieval.domain.enums import CandidateKindEnum
from noesis.bounded_context.retrieval.domain.value_objects.projection_key import ProjectionKey
from noesis.shared_kernel.domain import JsonValue


class SemanticCall(NamedTuple):
    """One `find` call."""

    text: str
    space_id: str
    limit: int


class FakeSemanticSource(ICandidateSource):
    """Kind `semantic`. Its cursor lives in the cursor store under projection `semantic`.

    Hits are keyed by space and returned best first, cut to the requested limit.
    """

    def __init__(self, profile: dict[str, JsonValue] | None = None) -> None:
        self._profile: dict[str, JsonValue] = profile or {"name": "fake-semantic", "version": 1}
        self._hits: dict[str, tuple[ProjectionKey, ...]] = {}
        self.failure: Exception | None = None
        self.calls: list[SemanticCall] = []

    @property
    def kind(self) -> CandidateKindEnum:
        """Always `semantic`."""
        return CandidateKindEnum.SEMANTIC

    def set_hits(self, space_id: str, keys: Sequence[ProjectionKey]) -> None:
        """The keys `find` answers for `space_id`, best first."""
        self._hits[space_id] = tuple(keys)

    def set_profile(self, profile: dict[str, JsonValue]) -> None:
        """Change what `profile()` reports."""
        self._profile = profile

    def go_down(self) -> None:
        """Make `find` raise `CandidateSourceUnavailableError`."""
        self.failure = CandidateSourceUnavailableError("fake semantic source is down")

    @property
    def limits(self) -> list[int]:
        """The limit of every `find` call, in order."""
        return [call.limit for call in self.calls]

    async def find(self, text: str, *, space_id: str, limit: int) -> RankedCandidatesDto:
        """The seeded hits, or the failure."""
        self.calls.append(SemanticCall(text, space_id, limit))
        if self.failure is not None:
            raise self.failure
        return RankedCandidatesDto(hits=self._hits.get(space_id, ())[:limit])

    def profile(self) -> dict[str, JsonValue]:
        """The settable profile."""
        return dict(self._profile)
