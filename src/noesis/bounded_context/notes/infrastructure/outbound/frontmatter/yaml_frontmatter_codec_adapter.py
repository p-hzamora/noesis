"""`IFrontmatterCodec` over YAML: the `noesis:` block at the top of a Markdown file."""

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import yaml

from noesis.bounded_context.notes.application.dtos import ParsedDocumentDto
from noesis.bounded_context.notes.application.ports.frontmatter import IFrontmatterCodec
from noesis.bounded_context.notes.domain.value_objects import (
    NoteFrontmatter,
    NoteId,
    NoteKind,
    NoteOriginEnum,
    NoteScope,
    NoteSourceRef,
)
from noesis.exceptions import DomainException
from noesis.shared_kernel.domain import JsonValue

HEADER_PATTERN: re.Pattern[str] = re.compile(
    r"\A---\n(?P<yaml>.*?)\n---[ \t]*(?:\n|\Z)(?P<body>.*)\Z", re.DOTALL
)
BLOCK_KEY: str = "noesis"
DATE_PATTERN: re.Pattern[str] = re.compile(r"\d{4}-\d{2}-\d{2}")
DATETIME_PATTERN: re.Pattern[str] = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?")


def _yamlable(value: JsonValue) -> Any:
    """Inverse of `_jsonable` for dates, so a kept key is written as it was read."""
    if isinstance(value, str):
        try:
            if DATE_PATTERN.fullmatch(value):
                return date.fromisoformat(value)
            if DATETIME_PATTERN.fullmatch(value):
                return datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, dict):
        return {key: _yamlable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_yamlable(item) for item in value]
    return value


def _jsonable(value: object) -> JsonValue:
    """A YAML value as JSON-compatible data (dates become ISO text)."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


class YamlFrontmatterCodecAdapter(IFrontmatterCodec):
    """Parses leniently (hand-written notes are messy) and renders deterministically."""

    def parse(self, text: str) -> ParsedDocumentDto:
        """Split `text`; see `IFrontmatterCodec.parse`."""
        match: re.Match[str] | None = HEADER_PATTERN.match(text)
        if match is None:
            return ParsedDocumentDto(
                frontmatter=None, header={}, body=text, malformed_header=text.startswith("---")
            )
        malformed: bool = False
        try:
            loaded: object = yaml.safe_load(match.group("yaml"))
        except yaml.YAMLError:
            loaded, malformed = None, True
        if loaded is not None and not isinstance(loaded, dict):
            malformed = True
        raw: dict[str, Any] = loaded if isinstance(loaded, dict) else {}
        header: dict[str, JsonValue] = {str(key): _jsonable(value) for key, value in raw.items()}
        return ParsedDocumentDto(
            frontmatter=self._frontmatter(raw.get(BLOCK_KEY)),
            header=header,
            body=match.group("body"),
            malformed_header=malformed,
        )

    @staticmethod
    def _frontmatter(block: object) -> NoteFrontmatter | None:
        """The block as a value object, or None when anything about it is missing or invalid."""
        if not isinstance(block, dict):
            return None
        try:
            sources: object = block.get("sources") or []
            return NoteFrontmatter(
                id=NoteId(value=str(block["id"])),
                scope=NoteScope.parse(str(block["scope"])),
                kind=NoteKind(value=str(block["kind"])),
                origin=NoteOriginEnum(str(block["origin"])),
                sources=tuple(
                    NoteSourceRef(value=str(ref))
                    for ref in (sources if isinstance(sources, list) else [])
                ),
                updated=date.fromisoformat(str(block["updated"])[:10]),
            )
        except KeyError, ValueError, TypeError, DomainException:
            return None

    def render(
        self, frontmatter: NoteFrontmatter, body: str, extra: Mapping[str, JsonValue] | None = None
    ) -> str:
        """The header (`extra` keys, then the `noesis:` block) followed by `body` unchanged."""
        block: dict[str, Any] = {
            "id": frontmatter.id.value,
            "scope": frontmatter.scope.value,
            "kind": frontmatter.kind.value,
            "origin": frontmatter.origin.value,
            "sources": [ref.value for ref in frontmatter.sources],
            "updated": frontmatter.updated,
        }
        kept: dict[str, Any] = {
            key: _yamlable(value) for key, value in (extra or {}).items() if key != BLOCK_KEY
        }
        header: str = yaml.safe_dump(
            {**kept, BLOCK_KEY: block}, sort_keys=False, allow_unicode=True
        ).strip()
        return f"---\n{header}\n---\n{body}"
