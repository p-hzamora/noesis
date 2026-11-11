"""Reads and writes the `noesis:` frontmatter block of a Markdown file."""

import abc
from collections.abc import Mapping

from noesis.bounded_context.notes.application.dtos import ParsedDocumentDto
from noesis.bounded_context.notes.domain.value_objects import NoteFrontmatter
from noesis.shared_kernel.domain import JsonValue


class IFrontmatterCodec(abc.ABC):
    """Splits a file into frontmatter and body, and joins them back."""

    @abc.abstractmethod
    def parse(self, text: str) -> ParsedDocumentDto:
        """Split `text`. A missing or invalid `noesis:` block gives `frontmatter=None`; never raises."""
        ...

    @abc.abstractmethod
    def render(
        self, frontmatter: NoteFrontmatter, body: str, extra: Mapping[str, JsonValue] | None = None
    ) -> str:
        """The file text: a header, then `body` unchanged.

        The header holds the `extra` keys (a note's own keys, kept as they were; a `noesis` key
        in `extra` is ignored) followed by the `noesis:` block.
        """
        ...
