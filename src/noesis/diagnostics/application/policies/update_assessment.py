"""The outcome of comparing a checkout with its origin."""

from noesis.diagnostics.application.enums import UpdateVerdictEnum
from noesis.utils import FrozenObject


class UpdateAssessment(FrozenObject):
    """Verdict and the reason behind it.

    Attributes:
        verdict: How the checkout compares with its origin.
        reason: One sentence saying why.
    """

    verdict: UpdateVerdictEnum
    reason: str
