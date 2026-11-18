"""Maps a parsed note header to the record fields of a note (current and older layouts)."""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from noesis.bounded_context.interop.domain.services.header_source_rule import (
    HeaderSourceResult,
    HeaderSourceRule,
)
from noesis.bounded_context.interop.domain.services.tag_rule import TagRule
from noesis.bounded_context.interop.domain.value_objects import (
    NoteBlockReasonEnum,
    NoteMapping,
    NoteWarningEnum,
)

ULID_PATTERN: re.Pattern[str] = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
BLOCK_KEY: str = "noesis"
DEFAULT_SUBTYPE: str = "note"
REPO_PREFIX: str = "repo:"
TOPIC_PREFIX: str = "topic:"
CURRENT_READ_KEYS: frozenset[str] = frozenset({BLOCK_KEY, "title", "tags"})
LEGACY_READ_KEYS: frozenset[str] = frozenset(
    {"title", "tags", "type", "project", "repo", "topic", "area"}
)
type Header = Mapping[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class _Scope:
    """A `noesis.scope` value read as a project key and/or a tag; `valid` is false otherwise."""

    valid: bool
    project_key: str | None = None
    tag: str | None = None


def _text(value: object) -> str | None:
    """A scalar header value as trimmed text; None for absent, blank or structured values."""
    if value is None or isinstance(value, Mapping | list | tuple | set):
        return None
    text: str = str(value).strip()
    return text or None


def _declared(value: object) -> str | None:
    """A declared subtype: null is absent; any other value, a blank string included, is kept."""
    if value is None or isinstance(value, Mapping | list | tuple | set):
        return None
    return str(value).strip()


class NoteMapper:
    """Header to `NoteMapping`, or the reason the note cannot be mapped.

    The title is resolved by `TitleRule` and passed in; nothing here reads the body.
    """

    def __init__(self) -> None:
        self._tags: TagRule = TagRule()
        self._sources: HeaderSourceRule = HeaderSourceRule()

    def map_vault_note(
        self, header: Header | None, *, title: str
    ) -> NoteMapping | NoteBlockReasonEnum:
        """Map a note of `import run`; None means the note has no header."""
        current: Header | None = None
        warnings: list[str] = []
        if header is not None and BLOCK_KEY in header:
            block: object = header[BLOCK_KEY]
            if not isinstance(block, Mapping):
                return NoteBlockReasonEnum.INVALID_HEADER
            current = {str(key): value for key, value in block.items()}
        elif header is not None:
            warnings.append(NoteWarningEnum.LEGACY_HEADER.value)
        source: Header = header or {}
        warnings.extend(self._ignored_fields(source, current is not None))
        record_id: str | None = None
        project_key: str | None
        extra_tags: list[str] = []
        if current is not None:
            raw_id: object = current.get("id")
            if raw_id is not None:
                if not isinstance(raw_id, str) or not ULID_PATTERN.fullmatch(raw_id):
                    return NoteBlockReasonEnum.INVALID_ID
                record_id = raw_id
            declared: str | None = _declared(current.get("kind"))
            subtype: str = DEFAULT_SUBTYPE if declared is None else declared
            scope: _Scope = self._scope(current.get("scope"))
            if not scope.valid:
                return NoteBlockReasonEnum.INVALID_SCOPE
            project_key = scope.project_key
            if scope.tag is not None:
                extra_tags.append(scope.tag)
            sources: HeaderSourceResult = self._sources.map(current.get("sources"))
        else:
            declared = _declared(source.get("type"))
            subtype = DEFAULT_SUBTYPE if declared is None else declared
            project_key = _text(source.get("project")) or _text(source.get("repo"))
            extra_tags.extend(self._facet_tags(source, warnings))
            sources = HeaderSourceResult(sources=(), skipped=0)
        tags: set[str] = self._header_tags(source, warnings)
        tags.update(extra_tags)
        return NoteMapping(
            record_id=record_id,
            title=title,
            subtype=subtype,
            project_key=project_key,
            tags=tuple(sorted(tags)),
            header_sources=sources.sources,
            sources_skipped=sources.skipped,
            warnings=tuple(warnings),
        )

    def map_file(
        self,
        header: Header | None,
        *,
        title: str,
        subtype: str | None,
        project_key: str | None,
        tags: tuple[str, ...],
    ) -> NoteMapping | NoteBlockReasonEnum:
        """Map a file of `import file`: options win over the header, nothing is blocked but a bad block.

        Option values are passed through untouched; Knowledge validates them.
        """
        current: Header | None = None
        warnings: list[str] = []
        if header is not None and BLOCK_KEY in header:
            block: object = header[BLOCK_KEY]
            if not isinstance(block, Mapping):
                return NoteBlockReasonEnum.INVALID_HEADER
            current = {str(key): value for key, value in block.items()}
        source: Header = header or {}
        warnings.extend(self._ignored_fields(source, current is not None))
        header_subtype: str | None
        header_project: str | None
        collected: set[str] = self._header_tags(source, warnings)
        if current is not None:
            header_subtype = _declared(current.get("kind"))
            scope: _Scope = self._scope(current.get("scope"))
            if scope.valid:
                header_project = scope.project_key
                if scope.tag is not None:
                    collected.add(scope.tag)
            else:
                header_project = None
                warnings.append(NoteWarningEnum.IGNORED_SCOPE.value)
        else:
            header_subtype = _declared(source.get("type"))
            header_project = _text(source.get("project")) or _text(source.get("repo"))
            collected.update(self._facet_tags(source, warnings))
        collected.update(tags)
        return NoteMapping(
            title=title,
            subtype=subtype or (DEFAULT_SUBTYPE if header_subtype is None else header_subtype),
            project_key=project_key or header_project,
            tags=tuple(sorted(collected)),
            warnings=tuple(warnings),
        )

    def _scope(self, value: object) -> _Scope:
        if value is None:
            return _Scope(valid=True)
        if not isinstance(value, str):
            return _Scope(valid=False)
        text: str = value.strip()
        if text.startswith(REPO_PREFIX):
            name: str = text.removeprefix(REPO_PREFIX).strip()
            return _Scope(valid=bool(name), project_key=name or None)
        if text.startswith(TOPIC_PREFIX):
            tag: str = self._tags.normalise(text)
            return _Scope(valid=self._tags.is_valid(tag), tag=tag)
        return _Scope(valid=False)

    @staticmethod
    def _ignored_fields(header: Header, has_block: bool) -> list[str]:
        """`ignored_field:<key>` for each top-level header key the mapping never reads."""
        read: frozenset[str] = CURRENT_READ_KEYS if has_block else LEGACY_READ_KEYS
        return [
            f"{NoteWarningEnum.IGNORED_FIELD.value}:{key}"
            for key in sorted(str(key) for key in header)
            if key not in read
        ]

    def _header_tags(self, header: Header, warnings: list[str]) -> set[str]:
        """Valid tags of `H.tags`; the others are dropped with a warning."""
        raw: object = header.get("tags")
        values: list[object] = raw if isinstance(raw, list) else [] if raw is None else [raw]
        return self._valid_tags([str(value) for value in values], warnings)

    def _facet_tags(self, header: Header, warnings: list[str]) -> set[str]:
        """`topic:<v>` and `area:<v>` of an older-layout header."""
        built: list[str] = []
        for facet in ("topic", "area"):
            value: str | None = _text(header.get(facet))
            if value is not None:
                built.append(f"{facet}:{value}")
        return self._valid_tags(built, warnings)

    def _valid_tags(self, candidates: list[str], warnings: list[str]) -> set[str]:
        valid: set[str] = set()
        for candidate in candidates:
            tag: str = self._tags.normalise(candidate)
            if self._tags.is_valid(tag):
                valid.add(tag)
            else:
                warnings.append(f"{NoteWarningEnum.DROPPED_TAG.value}:{tag}")
        return valid
