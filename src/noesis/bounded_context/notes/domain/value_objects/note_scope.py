"""The group of notes a note belongs to: `repo:<name>` or `topic:<name>`."""

from typing import Self

from pydantic import model_validator

from noesis.exceptions import InvalidNoteScopeError
from noesis.shared_kernel.domain.value_objects import ValueObject

from .note_scope_type_enum import NoteScopeTypeEnum


class NoteScope(ValueObject):
    """A scope type and a safe name (one path segment, so a layout can place it in a folder).

    Attributes:
        type: Repository or topic.
        name: Repository directory name or topic name.
    """

    type: NoteScopeTypeEnum
    name: str

    @model_validator(mode="after")
    def _safe_name(self) -> Self:
        if (
            not self.name
            or "/" in self.name
            or "\\" in self.name
            or self.name.startswith(".")
            or self.name != self.name.strip()
        ):
            raise InvalidNoteScopeError(
                f"Invalid note scope name {self.name!r}.",
                {"scope": f"{self.type.value}:{self.name}"},
                next_steps=["Use a single folder-safe name: no `/`, no leading `.`."],
            )
        return self

    @property
    def value(self) -> str:
        """The scope as written in frontmatter, e.g. `repo:noesis`."""
        return f"{self.type.value}:{self.name}"

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read `repo:<name>` or `topic:<name>`.

        Raises:
            InvalidNoteScopeError: The text is anything else (`personal` is not a scope).
        """
        kind, separator, name = text.partition(":")
        known: dict[str, NoteScopeTypeEnum] = {t.value: t for t in NoteScopeTypeEnum}
        if not separator or kind not in known:
            raise InvalidNoteScopeError(
                f"Invalid note scope {text!r}.",
                {"scope": text},
                next_steps=["Use `repo:<name>` or `topic:<name>`."],
            )
        return cls(type=known[kind], name=name)

    @classmethod
    def for_repository(cls, repository: str) -> Self:
        """The scope of one repository."""
        return cls(type=NoteScopeTypeEnum.REPO, name=repository)
