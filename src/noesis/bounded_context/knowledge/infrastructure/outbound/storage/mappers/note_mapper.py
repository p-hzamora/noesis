"""`Note` <-> Markdown with YAML frontmatter.

Layout of a file::

    ---
    type: decision
    id: auto-decision-use-ttl-cache
    ...
    ---

    # Title

    ## Decision

    Body.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import yaml

from noesis.bounded_context.knowledge.domain.entities import Note
from noesis.bounded_context.knowledge.domain.value_objects import (
    NoteLocation,
    NoteOriginEnum,
    NoteSection,
)

FRONTMATTER_PATTERN: re.Pattern[str] = re.compile(
    r"\A---\n(?P<yaml>.*?)\n---\n?(?P<body>.*)\Z", re.DOTALL
)
SNIPPET_LENGTH: int = 200


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedMarkdown:
    """A Markdown note split into its parts.

    Attributes:
        frontmatter: Decoded YAML frontmatter (empty when absent or invalid).
        title: The `#` heading, or the frontmatter `title`, or None.
        sections: `##` sections in order.
    """

    frontmatter: dict[str, Any]
    title: str | None
    sections: tuple[NoteSection, ...]


def _as_datetime(value: object) -> datetime | None:
    """Frontmatter dates (YAML `date` or ISO text) as UTC datetimes."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        try:
            return _as_datetime(date.fromisoformat(value[:10]))
        except ValueError:
            return None
    return None


def _strings(value: object) -> tuple[str, ...]:
    """A YAML list (or a single scalar) as a tuple of strings."""
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),) if value not in (None, "") else ()


class NoteMapper:
    """Maps the Note aggregate to Markdown (`to_markdown`) and back (`to_entity`)."""

    def parse(self, text: str) -> ParsedMarkdown:
        """Split Markdown into frontmatter, title and sections, tolerating hand-written notes."""
        frontmatter: dict[str, Any] = {}
        body: str = text
        match: re.Match[str] | None = FRONTMATTER_PATTERN.match(text)
        if match:
            try:
                loaded: object = yaml.safe_load(match.group("yaml"))
            except yaml.YAMLError:
                loaded = None
            frontmatter = loaded if isinstance(loaded, dict) else {}
            body = match.group("body")
        title: str | None = None
        sections: list[NoteSection] = []
        heading: str | None = None
        lines: list[str] = []
        for line in body.splitlines():
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
        fallback_title: object = frontmatter.get("title")
        return ParsedMarkdown(
            frontmatter=frontmatter,
            title=title or (str(fallback_title) if fallback_title else None),
            sections=tuple(sections),
        )

    def to_entity(self, text: str, location: NoteLocation) -> Note:
        """Rebuild a stored note (no creation rules apply: hand-written notes may be partial).

        Args:
            text: File content.
            location: Where the file was found.

        Returns:
            The reconstituted note.
        """
        parsed: ParsedMarkdown = self.parse(text)
        created: datetime | None = _as_datetime(parsed.frontmatter.get("date"))
        updated: datetime | None = _as_datetime(parsed.frontmatter.get("updated")) or created
        session: object = parsed.frontmatter.get("session")
        note: Note = Note(
            location=location,
            title=parsed.title or location.slug.value,
            sections=parsed.sections,
            tags=_strings(parsed.frontmatter.get("tags")),
            commits=_strings(parsed.frontmatter.get("commits")),
            session=str(session) if session else None,
        )
        if created:
            note.created_at = created
        if updated:
            note.updated_at = updated
        return note

    def to_markdown(self, note: Note) -> str:
        """Render a note as Markdown with frontmatter."""
        frontmatter: dict[str, Any] = {"type": note.location.kind.value, "id": note.id}
        if note.location.area.repository:
            frontmatter["repo"] = note.location.area.repository
        frontmatter["area"] = note.location.area.value
        if note.location.origin is NoteOriginEnum.AUTO:
            frontmatter["origin"] = NoteOriginEnum.AUTO.value
        frontmatter["title"] = note.title
        frontmatter["date"] = note.created_at.date()
        frontmatter["updated"] = note.updated_at.date()
        if note.session:
            frontmatter["session"] = note.session
        if note.commits:
            frontmatter["commits"] = list(note.commits)
        frontmatter["tags"] = list(note.tags)
        header: str = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
        blocks: list[str] = [f"---\n{header}\n---", f"# {note.title}"]
        blocks += [f"## {section.heading}\n\n{section.body.strip()}" for section in note.sections]
        return "\n\n".join(blocks) + "\n"

    def snippet(self, parsed: ParsedMarkdown) -> str:
        """Start of the first non-empty section, collapsed to one line."""
        body: str = next((section.body for section in parsed.sections if section.body), "")
        return " ".join(body.split())[:SNIPPET_LENGTH]
