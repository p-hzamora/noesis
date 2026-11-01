"""How big a change is."""

from typing import Self

from pydantic import Field

from noesis.shared_kernel.domain.value_objects import ValueObject


class DiffSize(ValueObject):
    """Files touched and lines added plus removed.

    Attributes:
        files: Number of files.
        lines: Changed lines.
    """

    files: int = Field(default=0, ge=0)
    lines: int = Field(default=0, ge=0)

    def __add__(self, other: Self) -> Self:
        return self.model_copy(
            update={"files": self.files + other.files, "lines": self.lines + other.lines}
        )
