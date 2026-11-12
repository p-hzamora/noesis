"""Gives a Markdown file the `noesis:` frontmatter block, keeping everything else of it."""

from datetime import date
from typing import Final

from noesis.bounded_context.notes.application.dtos import ParsedDocumentDto
from noesis.bounded_context.notes.application.ports.frontmatter import IFrontmatterCodec
from noesis.bounded_context.notes.application.ports.ids import INoteIdGenerator
from noesis.bounded_context.notes.domain.value_objects import (
    NoteFrontmatter,
    NoteKind,
    NoteOriginEnum,
    NoteScope,
    NoteSourceRef,
)
from noesis.exceptions import DomainException
from noesis.shared_kernel.domain import JsonValue

BLOCK_KEY: Final[str] = "noesis"
LEGACY_KEYS: Final[frozenset[str]] = frozenset(
    {"type", "id", "repo", "area", "origin", "session", "commits"}
)  # keys of the earlier noesis note format; the `noesis:` block replaces them


def _as_list(value: JsonValue | None) -> list[JsonValue]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


class NoteDocumentMigrator:
    """Builds the migrated text of a note and judges whether a file already is one.

    Args:
        codec: Reads and writes the frontmatter block.
        ids: Ids for notes that have none yet.
        today: Date used for `updated` when the file records none.
    """

    def __init__(self, codec: IFrontmatterCodec, ids: INoteIdGenerator, today: date) -> None:
        self._codec: IFrontmatterCodec = codec
        self._ids: INoteIdGenerator = ids
        self._today: date = today

    def parse(self, text: str) -> ParsedDocumentDto:
        """The file split into header and body."""
        return self._codec.parse(text)

    def is_current(self, document: ParsedDocumentDto, scope: NoteScope, kind: NoteKind) -> bool:
        """Whether the file already carries a valid block for exactly this scope and kind."""
        found: NoteFrontmatter | None = document.frontmatter
        return found is not None and found.scope == scope and found.kind == kind

    def build(self, document: ParsedDocumentDto, scope: NoteScope, kind: NoteKind) -> str:
        """The file with a `noesis:` block for `scope` and `kind`, body untouched.

        An existing valid block keeps its id, origin, sources and date; a file without one gets
        a new id and what the legacy keys recorded. Header keys outside `LEGACY_KEYS` all stay.
        """
        found: NoteFrontmatter | None = document.frontmatter
        header: dict[str, JsonValue] = document.header
        frontmatter: NoteFrontmatter = NoteFrontmatter(
            id=found.id if found else self._ids.new_id(),
            scope=scope,
            kind=kind,
            origin=found.origin if found else self._legacy_origin(header),
            sources=found.sources if found else self._legacy_sources(header),
            updated=found.updated if found else self._updated(header),
        )
        kept: dict[str, JsonValue] = {
            key: value for key, value in header.items() if key not in LEGACY_KEYS | {BLOCK_KEY}
        }
        return self._codec.render(frontmatter, document.body, kept)

    def keeps_header(self, old: ParsedDocumentDto, new: ParsedDocumentDto) -> bool:
        """Whether every key of `old` outside the legacy ones survived in `new` unchanged."""
        return all(
            new.header.get(key) == value
            for key, value in old.header.items()
            if key not in LEGACY_KEYS | {BLOCK_KEY}
        )

    @staticmethod
    def _legacy_origin(header: dict[str, JsonValue]) -> NoteOriginEnum:
        value: JsonValue | None = header.get("origin")
        return NoteOriginEnum.AUTO if value == NoteOriginEnum.AUTO.value else NoteOriginEnum.MANUAL

    @staticmethod
    def _legacy_sources(header: dict[str, JsonValue]) -> tuple[NoteSourceRef, ...]:
        refs: list[str] = [
            ref if ":" in ref else f"{kind}:{ref}"
            for kind, key in (("commit", "commits"), ("session", "session"))
            for item in _as_list(header.get(key))
            if (ref := str(item).strip())
        ]
        valid: list[NoteSourceRef] = []
        for ref in refs:
            try:
                valid.append(NoteSourceRef(value=ref))
            except DomainException:  # one malformed ref must not stop a migration
                continue
        return tuple(valid)

    def _updated(self, header: dict[str, JsonValue]) -> date:
        for key in ("updated", "date"):
            value: JsonValue | None = header.get(key)
            if isinstance(value, str):
                try:
                    return date.fromisoformat(value[:10])
                except ValueError:
                    continue
        return self._today
