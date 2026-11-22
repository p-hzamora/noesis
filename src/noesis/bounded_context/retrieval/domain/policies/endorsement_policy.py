"""Who stands behind a resource, from `recommends` assertions only."""

from collections.abc import Iterable

from ..enums import DecisionBasisEnum, EndorsementEnum
from ..value_objects.endorsement_fact import EndorsementFact


class EndorsementPolicy:
    """Endorsement is never implied by availability, installation or sync.

    - `user`: accepted on the user's decision and not tied to a project.
    - `project`: accepted and tied to the current project; it never applies elsewhere.
    - `proposed`: a live proposal, or an acceptance not decided by the user without a project.
    - `none`: no applicable assertion.

    The strongest applicable level wins: user, project, proposed, none.
    """

    def endorsement(
        self, facts: Iterable[EndorsementFact], *, project_key: str | None
    ) -> EndorsementEnum:
        """The endorsement a resource has for the current project."""
        result = EndorsementEnum.NONE
        for fact in facts:
            if fact.project_key is not None and fact.project_key != project_key:
                continue
            level = self._level(fact)
            if self._strength(level) > self._strength(result):
                result = level
        return result

    @staticmethod
    def _level(fact: EndorsementFact) -> EndorsementEnum:
        if fact.status == "accepted":
            if fact.project_key is not None:
                return EndorsementEnum.PROJECT
            if fact.basis is DecisionBasisEnum.USER:
                return EndorsementEnum.USER
            return EndorsementEnum.PROPOSED
        if fact.status == "proposed":
            return EndorsementEnum.PROPOSED
        return EndorsementEnum.NONE

    @staticmethod
    def _strength(level: EndorsementEnum) -> int:
        return (
            EndorsementEnum.NONE,
            EndorsementEnum.PROPOSED,
            EndorsementEnum.PROJECT,
            EndorsementEnum.USER,
        ).index(level)
