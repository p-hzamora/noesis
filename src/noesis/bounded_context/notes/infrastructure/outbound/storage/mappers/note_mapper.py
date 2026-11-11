"""`Note` <-> Markdown with a `noesis:` frontmatter block.

Layout of a file::

    ---
    noesis:
      id: 01ARZ3NDEKTSV4RRFFQ69G5FAV
      scope: repo:demo
      kind: decision
      origin: auto
      sources: [commit:8e6d3b5f]
      updated: 2026-11-11
    ---

    # Title

    ## Decision

    Body.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from noesis.bounded_context.notes.application.dtos import (
    NoteContentDto,
    NoteSummaryDto,
    ParsedDocumentDto,
)
from noesis.bounded_context.notes.application.ports.frontmatter import IFrontmatterCodec
from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.value_objects import (
    NoteFrontmatter,
    NotePath,
    NoteSection,
)
from noesis.shared_kernel.domain import JsonValue

SNIPPET_LENGTH: int = 200


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedMarkdown:
    """A Markdown note split into its parts.

    Attributes:
        frontmatter: The `noesis:` block; None for a file that is not a noesis note.
        title: The `#` heading, or None.
        sections: `##` sections in order.
    """

    frontmatter: NoteFrontmatter | None
    title: str | None
    sections: tuple[NoteSection, ...]


class NoteMapper:
    """Maps the Note aggregate to Markdown (`to_markdown`) and back (`to_entity`), and files to DTOs."""

    def __init__(self, codec: IFrontmatterCodec) -> None:
        self._codec: IFrontmatterCodec = codec

    def parse(self, text: str) -> ParsedMarkdown:
        """Split Markdown into frontmatter, title and sections, tolerating hand-written notes."""
        document: ParsedDocumentDto = self._codec.parse(text)
        title: str | None = None
        sections: list[NoteSection] = []
        heading: str | None = None
        lines: list[str] = []
        for line in document.body.splitlines():
            if line.startswith("# ") and title is None and heading is None:
                title = line[2:].strip()
            elif line.startswith("## "):
                if heading is not None:
                    sections.append(NoteSection(heading=heading, body="\n".join(lines).strip()))
                heading, lines = line[3:].strip(), []
            else:
                lines.append(line)
        if heading is not None:
            sections.append(NoteSection(heading=heading, body="\n".join(lines).strip()))
        return ParsedMarkdown(
            frontmatter=document.frontmatter, title=title, sections=tuple(sections)
        )

    def to_entity(self, text: str, path: NotePath) -> Note | None:
        """Rebuild a stored note (no creation rules apply: hand-written notes may be partial).

        Args:
            text: File content.
            path: Where the file was found.

        Returns:
            The reconstituted note, or None when the file has no valid `noesis:` block.
        """
        parsed: ParsedMarkdown = self.parse(text)
        frontmatter: NoteFrontmatter | None = parsed.frontmatter
        if frontmatter is None:
            return None
        updated: datetime = datetime(
            frontmatter.updated.year, frontmatter.updated.month, frontmatter.updated.day, tzinfo=UTC
        )
        return Note(
            id=frontmatter.id,
            scope=frontmatter.scope,
            kind=frontmatter.kind,
            origin=frontmatter.origin,
            path=path,
            title=parsed.title or path.stem,
            sections=parsed.sections,
            sources=frontmatter.sources,
            created_at=updated,
            updated_at=updated,
        )

    def to_markdown(self, note: Note, existing: str | None = None) -> str:
        """Render a note as Markdown with frontmatter.

        Args:
            note: The note to render.
            existing: The file's current text when it is being updated; its keys other than
                `noesis` are kept in the new header.
        """
        kept: dict[str, JsonValue] = {} if existing is None else self._codec.parse(existing).header
        blocks: list[str] = [f"# {note.title}"]
        blocks += [f"## {section.heading}\n\n{section.body.strip()}" for section in note.sections]
        return self._codec.render(note.frontmatter, "\n" + "\n\n".join(blocks) + "\n", kept)

    def snippet(self, parsed: ParsedMarkdown) -> str:
        """Start of the first non-empty section, collapsed to one line."""
        body: str = next((section.body for section in parsed.sections if section.body), "")
        return " ".join(body.split())[:SNIPPET_LENGTH]

    def to_summary(self, path: str, text: str) -> NoteSummaryDto | None:
        """The listing entry of a file, or None when it is not a noesis note."""
        parsed: ParsedMarkdown = self.parse(text)
        frontmatter: NoteFrontmatter | None = parsed.frontmatter
        if frontmatter is None:
            return None
        return NoteSummaryDto(
            id=frontmatter.id.value,
            scope=frontmatter.scope.value,
            path=path,
            title=parsed.title or path.rsplit("/", 1)[-1].removesuffix(".md"),
            kind=frontmatter.kind.value,
            origin=frontmatter.origin.value,
            updated=frontmatter.updated.isoformat(),
            snippet=self.snippet(parsed),
        )

    def to_content(self, path: str, text: str) -> NoteContentDto | None:
        """The full note of a file, or None when it is not a noesis note."""
        summary: NoteSummaryDto | None = self.to_summary(path, text)
        if summary is None:
            return None
        return NoteContentDto(
            id=summary.id,
            scope=summary.scope,
            path=path,
            title=summary.title,
            kind=summary.kind,
            origin=summary.origin,
            updated=summary.updated,
            content=text,
        )
