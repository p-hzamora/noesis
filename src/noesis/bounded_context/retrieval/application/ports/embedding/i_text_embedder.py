"""Turns text into vectors with one fixed embedding profile."""

import abc
from collections.abc import Sequence

from noesis.utils import FrozenObject

from ....domain.value_objects import EmbeddingProfile

MAX_PASSAGES_PER_REQUEST: int = 32
MAX_QUERY_CHARACTERS: int = 32_000


class EmbedderUnavailableError(Exception):
    """The embedder cannot answer (no prepared model, no runtime, overload, bad reply)."""


class EmbeddedChunkDto(FrozenObject):
    """One window of a passage and its vector.

    Attributes:
        index: Position of the window in the passage, from 0.
        token_start: First content token of the window.
        token_end: One past its last content token.
        vector: Unit-length vector of the profile's dimensions.
    """

    index: int
    token_start: int
    token_end: int
    vector: tuple[float, ...]


class EmbeddedPassageDto(FrozenObject):
    """Every window of one passage, in order; none for an empty text.

    Attributes:
        token_count: Content tokens of the whole passage.
        chunks: The windows, which together cover every token.
    """

    token_count: int
    chunks: tuple[EmbeddedChunkDto, ...]


class ITextEmbedder(abc.ABC):
    """Embeds passages (no instruction) and queries (the profile's instruction exactly once)."""

    @abc.abstractmethod
    def profile(self) -> EmbeddingProfile:
        """The configured profile; reading it loads no model and starts nothing."""
        ...

    @abc.abstractmethod
    async def embed_passages(self, texts: Sequence[str]) -> list[EmbeddedPassageDto]:
        """Window and embed up to `MAX_PASSAGES_PER_REQUEST` passages, one result per text.

        Raises:
            EmbedderUnavailableError: The embedder cannot answer.
        """
        ...

    @abc.abstractmethod
    async def embed_query(self, text: str) -> tuple[float, ...]:
        """One unit vector for a query of at most `MAX_QUERY_CHARACTERS` characters.

        Raises:
            EmbedderUnavailableError: The embedder cannot answer or the query is too long.
        """
        ...
