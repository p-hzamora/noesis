"""The vault folder a group of notes belongs to, such as `repos/<repo>`."""

from pathlib import PurePosixPath
from typing import Self

from pydantic import field_validator

from noesis.exceptions import (
    InvalidNoteAreaError,
)
from noesis.shared_kernel.domain.value_objects import ValueObject

REPOSITORIES_ROOT: str = "repos"
AUTO_FOLDER: str = "auto"


class NoteArea(ValueObject):
    """A relative, `/`-separated folder inside the vault, never escaping it.

    Attributes:
        value: The folder, e.g. `repos/noesis`.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise InvalidNoteAreaError(
                f"Invalid note area {value!r}.",
                {"area": value},
                next_steps=["Use a relative folder such as `repos/<repo>`, without `..`."],
            )
        if AUTO_FOLDER in path.parts:
            raise InvalidNoteAreaError(
                f"Note area {value!r} contains the reserved folder `{AUTO_FOLDER}`.",
                {"area": value},
            )
        return value

    @classmethod
    def for_repository(cls, repository: str) -> Self:
        """The area of one repository: `repos/<repository>`."""
        return cls(value=f"{REPOSITORIES_ROOT}/{repository}")

    @property
    def repository(self) -> str | None:
        """The repository name when this is a `repos/<repo>` area."""
        parts: tuple[str, ...] = PurePosixPath(self.value).parts
        return parts[1] if len(parts) == 2 and parts[0] == REPOSITORIES_ROOT else None
