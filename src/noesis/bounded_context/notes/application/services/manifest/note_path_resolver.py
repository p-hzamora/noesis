"""Chooses where a NEW note's file goes, from the manifest layout."""

from collections.abc import Iterator, Mapping
from itertools import count
from typing import Any

from noesis.bounded_context.notes.domain.value_objects import (
    NoteKind,
    NotePath,
    NoteScope,
    NoteScopeTypeEnum,
    NoteSlug,
)

from .group_spec import GroupSpec
from .kind_catalog import KindCatalog
from .layout_spec import LayoutSpec


class NotePathResolver:
    """Expands the layout template of a scope type.

    The caller walks the candidates and takes the first one nothing occupies: `<slug>.md`,
    then `<slug>-2.md`, `<slug>-3.md`... so a write never overwrites. The resolver does no I/O.
    """

    def __init__(
        self,
        layout: LayoutSpec,
        catalog: KindCatalog,
        groups: Mapping[str, GroupSpec] | None = None,
    ) -> None:
        self._layout: LayoutSpec = layout
        self._catalog: KindCatalog = catalog
        self._groups: Mapping[str, GroupSpec] = groups or {}

    def candidates(
        self, scope: NoteScope, kind: NoteKind, slug: NoteSlug, remote: str | None = None
    ) -> Iterator[NotePath]:
        """Endless paths for the note, the preferred one first.

        A repository note goes under its group's root when the repository (by name or by the
        canonical `remote`) belongs to a group; the first matching group wins.

        Raises:
            UnknownNoteKindError: The kind is not in the catalog.
        """
        folder: str = self._catalog.require(kind).folder
        template: str = self._layout.template_for(scope.type)
        fields: dict[str, Any] = {}
        group: GroupSpec | None = self._group_of(scope, remote)
        if group is not None:
            template, fields = self._layout.grouped_repo, {"root": group.root}
        for attempt in count(1):
            suffix: str = "" if attempt == 1 else f"-{attempt}"
            yield NotePath(
                value=template.format(
                    name=scope.name,
                    kind_folder=folder,
                    slug=f"{slug.value}{suffix}",
                    **fields,
                )
            )

    def _group_of(self, scope: NoteScope, remote: str | None) -> GroupSpec | None:
        if scope.type is not NoteScopeTypeEnum.REPO:
            return None
        return next((g for g in self._groups.values() if g.matches(scope.name, remote)), None)
