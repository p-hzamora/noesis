"""One thing the task needs, named by the agent or taken from the query."""

from noesis.shared_kernel.domain.value_objects import ValueObject

from ..enums import RequirementSourceEnum


class RequirementFacet(ValueObject):
    """A requirement facet.

    Attributes:
        id: Lower-cased facet text.
        source: `need` when supplied explicitly, `query` when taken from the query terms.
    """

    id: str
    source: RequirementSourceEnum
