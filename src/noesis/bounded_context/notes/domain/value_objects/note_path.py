"""Where a note's file sits in its source: a relative Markdown path that never escapes it."""

from pathlib import PurePosixPath

from pydantic import field_validator

from noesis.exceptions import InvalidNotePathError
from noesis.shared_kernel.domain.value_objects import ValueObject

NOTE_SUFFIX: str = ".md"


class NotePath(ValueObject):
    """A `/`-separated relative path ending in `.md`, without `..` or hidden segments.

    The path carries no meaning: identity, scope and kind live in the frontmatter.

    Attributes:
        value: The path.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _safe(cls, value: str) -> str:
        parts: tuple[str, ...] = PurePosixPath(value).parts
        if (
            not value
            or value.startswith("/")
            or not value.endswith(NOTE_SUFFIX)
            or any(part in {"", ".", ".."} or part.startswith(".") for part in value.split("/"))
        ):
            raise InvalidNotePathError(
                f"Invalid note path {value!r}.",
                {"path": value, "parts": list(parts)},
                next_steps=[
                    "Use a relative `/`-separated `.md` path without `..` or hidden folders."
                ],
            )
        return value

    @property
    def stem(self) -> str:
        """File name without `.md`."""
        return PurePosixPath(self.value).stem
