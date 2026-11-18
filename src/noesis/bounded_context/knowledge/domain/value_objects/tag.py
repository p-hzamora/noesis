"""A normalised label on a record, optionally scoped by a facet (`area:billing`)."""

import re

from pydantic import field_validator

from noesis.bounded_context.knowledge.domain.value_objects.slug import MAX_SLUG_LENGTH
from noesis.exceptions import InvalidSlugError
from noesis.shared_kernel.domain.value_objects import ValueObject

FACET_SEPARATOR: str = ":"
TAG_PART_PATTERN: re.Pattern[str] = re.compile(r"^\.?[a-z0-9]+(?:[-_][a-z0-9]+)*$")


def check_tag_part(value: str) -> str:
    """`value` when it is a valid tag part: a slug that may also use `_` and start with `.`.

    Raises:
        InvalidSlugError: The value is empty, too long, or not lowercase words joined by `-` or `_`.
    """
    if len(value) > MAX_SLUG_LENGTH or not TAG_PART_PATTERN.fullmatch(value):
        raise InvalidSlugError(
            f"Invalid tag part {value!r}.",
            {"slug": value},
            next_steps=[
                "Use lowercase letters and digits joined by single hyphens or underscores, "
                f"optionally after one leading dot, up to {MAX_SLUG_LENGTH} characters."
            ],
        )
    return value


class Tag(ValueObject):
    """`name` or `facet:name`, each part a tag part. Input is trimmed and lowercased.

    Attributes:
        value: The normalised tag.
    """

    value: str

    @field_validator("value")
    @classmethod
    def _normalise(cls, value: str) -> str:
        normalised: str = value.strip().lower()
        facet, separator, name = normalised.partition(FACET_SEPARATOR)
        if separator:
            check_tag_part(facet)
            check_tag_part(name)
        else:
            check_tag_part(normalised)
        return normalised

    @property
    def facet(self) -> str | None:
        """The part before `:`, when there is one."""
        facet, separator, _ = self.value.partition(FACET_SEPARATOR)
        return facet if separator else None
