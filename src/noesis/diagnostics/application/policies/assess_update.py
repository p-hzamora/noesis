"""Decides how a checkout compares with its origin."""

from noesis.diagnostics.application.enums import UpdateVerdictEnum
from noesis.diagnostics.application.ports.updates import CheckoutSnapshot

from .update_assessment import UpdateAssessment


def _unknown(reason: str) -> UpdateAssessment:
    return UpdateAssessment(verdict=UpdateVerdictEnum.UNKNOWN, reason=reason)


def assess_update(snapshot: CheckoutSnapshot) -> UpdateAssessment:
    """The verdict for `snapshot`; any missing fact makes it `unknown` with a named reason."""
    if snapshot.checkout is None:
        return _unknown("noesis was not installed from a git checkout (not a git checkout)")
    if snapshot.remote_url is None:
        return _unknown("the checkout has no `origin` remote")
    if snapshot.local_sha is None:
        return _unknown("could not read the local commit")
    if snapshot.remote_sha is None:
        return _unknown("could not read origin's latest commit (unreachable or timed out)")
    if snapshot.remote_sha == snapshot.local_sha:
        return UpdateAssessment(
            verdict=UpdateVerdictEnum.UP_TO_DATE, reason="the checkout matches origin"
        )
    if snapshot.remote_contains_local is None or snapshot.local_contains_remote is None:
        return _unknown("cannot compare histories (origin's commit could not be fetched)")
    if snapshot.local_contains_remote:
        return UpdateAssessment(
            verdict=UpdateVerdictEnum.AHEAD, reason="the checkout has commits origin does not"
        )
    if snapshot.remote_contains_local:
        return UpdateAssessment(
            verdict=UpdateVerdictEnum.BEHIND, reason="origin has commits the checkout lacks"
        )
    return UpdateAssessment(
        verdict=UpdateVerdictEnum.DIVERGED,
        reason="the checkout and origin each have commits the other lacks",
    )
