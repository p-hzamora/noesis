"""Where a record applies: one project, or the whole space."""

from noesis.bounded_context.knowledge.domain.value_objects.record_id import RecordId
from noesis.bounded_context.knowledge.domain.value_objects.tag import Tag
from noesis.shared_kernel.domain.value_objects import ValueObject


class Applicability(ValueObject):
    """An optional project and a set of tags. No project means space-wide.

    Attributes:
        project_id: The project the record applies to; None for the whole space.
        tags: Labels narrowing the scope.
    """

    project_id: RecordId | None = None
    tags: frozenset[Tag] = frozenset()

    @property
    def sorted_tags(self) -> tuple[Tag, ...]:
        """The tags in a stable order."""
        return tuple(sorted(self.tags, key=lambda tag: tag.value))
