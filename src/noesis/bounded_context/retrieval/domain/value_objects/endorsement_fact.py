"""A `recommends` assertion as the endorsement policy reads it."""

from noesis.shared_kernel.domain.value_objects import ValueObject

from ..enums import DecisionBasisEnum


class EndorsementFact(ValueObject):
    """One recommendation.

    Attributes:
        status: Stored assertion status (`accepted`, `proposed`, ...).
        basis: Who decided the status.
        project_key: The project the assertion applies to, or None when unscoped.
    """

    status: str
    basis: DecisionBasisEnum
    project_key: str | None = None
