"""One piece of evidence that backs a requirement facet."""

from noesis.shared_kernel.domain.value_objects import ValueObject

from ..enums import AuthorityTierEnum, SupportKindEnum


class FacetSupport(ValueObject):
    """A selected resource or a record hit that matches a facet.

    Attributes:
        kind: `resource` or `record`.
        available: For a resource, whether it is usable; None when not checked.
        authority: For a record, its authority tier.
    """

    kind: SupportKindEnum
    available: bool | None = None
    authority: AuthorityTierEnum | None = None
