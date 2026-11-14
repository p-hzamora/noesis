"""A normalised label on a record, optionally scoped by a facet (`area:billing`)."""

from pydantic import field_validator

from noesis.bounded_context.knowledge.domain.value_objects.slug import check_slug
from noesis.shared_kernel.domain.value_objects import ValueObject

FACET_SEPARATOR: str = ":"


class Tag(ValueObject):
    """`name` or `facet:name`, each part a slug. Input is trimmed and lowercased.

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
            check_slug(facet)
            check_slug(name)
        else:
            check_slug(normalised)
        return normalised

    @property
    def facet(self) -> str | None:
        """The part before `:`, when there is one."""
        facet, separator, _ = self.value.partition(FACET_SEPARATOR)
        return facet if separator else None
