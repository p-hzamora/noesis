"""A source of ranked candidates backed by a projection (semantic search)."""

import abc

from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

from ....domain.enums import CandidateKindEnum
from ....domain.value_objects import ProjectionKey


class CandidateSourceUnavailableError(Exception):
    """The source cannot answer right now; the search continues without it."""


class RankedCandidatesDto(FrozenObject):
    """Candidates of one source.

    Attributes:
        hits: Keys of the records found, best first.
    """

    hits: tuple[ProjectionKey, ...]


class ICandidateSource(abc.ABC):
    """Answers a text query from a projection. Its cursor is the writer's of the same `kind`."""

    @property
    @abc.abstractmethod
    def kind(self) -> CandidateKindEnum:
        """The candidate kind it reports (`semantic`)."""
        ...

    @abc.abstractmethod
    async def find(self, text: str, *, space_id: str, limit: int) -> RankedCandidatesDto:
        """Up to `limit` candidates, best first.

        Raises:
            CandidateSourceUnavailableError: The source cannot answer.
        """
        ...

    @abc.abstractmethod
    def profile(self) -> dict[str, JsonValue]:
        """What the index was built with (model, dimensions, ...)."""
        ...
