"""Chooses where a NEW note's file goes, from the manifest layout."""

from collections.abc import Iterator
from itertools import count

from noesis.bounded_context.notes.domain.value_objects import (
    NoteKind,
    NotePath,
    NoteScope,
    NoteSlug,
)

from .kind_catalog import KindCatalog
from .layout_spec import LayoutSpec


class NotePathResolver:
    """Expands the layout template of a scope type.

    The caller walks the candidates and takes the first one nothing occupies: `<slug>.md`,
    then `<slug>-2.md`, `<slug>-3.md`... so a write never overwrites. The resolver does no I/O.
    """

    def __init__(self, layout: LayoutSpec, catalog: KindCatalog) -> None:
        self._layout: LayoutSpec = layout
        self._catalog: KindCatalog = catalog

    def candidates(self, scope: NoteScope, kind: NoteKind, slug: NoteSlug) -> Iterator[NotePath]:
        """Endless paths for the note, the preferred one first.

        Raises:
            UnknownNoteKindError: The kind is not in the catalog.
        """
        folder: str = self._catalog.require(kind).folder
        template: str = self._layout.template_for(scope.type)
        for attempt in count(1):
            suffix: str = "" if attempt == 1 else f"-{attempt}"
            yield NotePath(
                value=template.format(
                    name=scope.name, kind_folder=folder, slug=f"{slug.value}{suffix}"
                )
            )
