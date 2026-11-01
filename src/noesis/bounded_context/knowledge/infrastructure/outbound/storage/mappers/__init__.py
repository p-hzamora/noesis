"""Translation between the Note aggregate and Markdown files."""

from noesis.bounded_context.knowledge.infrastructure.outbound.storage.mappers.note_mapper import (
    NoteMapper,
    ParsedMarkdown,
)

__all__ = ["NoteMapper", "ParsedMarkdown"]
