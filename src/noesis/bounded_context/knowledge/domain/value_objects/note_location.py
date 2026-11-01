"""Where a note lives in the vault, derived from its area, origin, kind and slug."""

from pathlib import PurePosixPath
from typing import Self

from noesis.exceptions import (
    InvalidNoteLocationError,
)
from noesis.shared_kernel.domain.value_objects import ValueObject

from .note_area import AUTO_FOLDER, NoteArea
from .note_kind_enum import NoteKindEnum
from .note_origin_enum import NoteOriginEnum
from .note_slug import NoteSlug

NOTE_SUFFIX: str = ".md"


class NoteLocation(ValueObject):
    """Auto notes live in `<area>/auto/<kind folder>/<slug>.md`, manual ones in `<area>/<kind folder>/<slug>.md`.

    Attributes:
        area: Vault folder of the group of notes.
        origin: Who wrote the note.
        kind: What the note records.
        slug: File name without `.md`.
    """

    area: NoteArea
    origin: NoteOriginEnum
    kind: NoteKindEnum
    slug: NoteSlug

    @property
    def relative_path(self) -> str:
        """Path inside the vault, `/`-separated."""
        auto: tuple[str, ...] = (AUTO_FOLDER,) if self.origin is NoteOriginEnum.AUTO else ()
        return str(
            PurePosixPath(
                self.area.value, *auto, self.kind.folder, f"{self.slug.value}{NOTE_SUFFIX}"
            )
        )

    def with_origin(self, origin: NoteOriginEnum) -> Self:
        """The same note identity under the other origin's folder."""
        return self.model_copy(update={"origin": origin})

    @classmethod
    def parse(cls, relative_path: str) -> Self:
        """Read a location back from a vault-relative path.

        Args:
            relative_path: `/`-separated path inside the vault.

        Returns:
            The location.

        Raises:
            InvalidNoteLocationError: The path does not follow the note layout.
        """
        path = PurePosixPath(relative_path)
        parts: tuple[str, ...] = path.parts
        kind: NoteKindEnum | None = NoteKindEnum.from_folder(parts[-2]) if len(parts) >= 3 else None
        if path.suffix != NOTE_SUFFIX or kind is None:
            raise InvalidNoteLocationError(
                f"{relative_path!r} is not a note path.", {"path": relative_path}
            )
        is_auto: bool = len(parts) >= 4 and parts[-3] == AUTO_FOLDER
        area_parts: tuple[str, ...] = parts[: -3 if is_auto else -2]
        if not area_parts:
            raise InvalidNoteLocationError(
                f"{relative_path!r} has no area folder.", {"path": relative_path}
            )
        return cls(
            area=NoteArea(value="/".join(area_parts)),
            origin=NoteOriginEnum.AUTO if is_auto else NoteOriginEnum.MANUAL,
            kind=kind,
            slug=NoteSlug(value=path.stem),
        )
