"""Who may take which review decision (cooperative, not access control)."""

from collections.abc import Sequence

from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    Applicability,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewRequirementEnum,
)
from noesis.exceptions import EvidenceRequiredError, ReviewNotAuthorisedError


class ReviewAuthorityPolicy:
    """A user may take every transition; an agent only inside one named project."""

    @staticmethod
    def may_decide(actor: Actor, governing: Sequence[Applicability]) -> bool:
        """Whether `actor` may take a transition governed by these applicabilities."""
        if actor.kind is ActorKindEnum.USER:
            return True
        projects = {a.project_id for a in governing}
        return len(projects) == 1 and None not in projects

    @staticmethod
    def check(actor: Actor, governing: Sequence[Applicability]) -> None:
        """Refuse unless the actor may decide.

        Raises:
            ReviewNotAuthorisedError: An agent on space-wide or cross-project scope.
        """
        if not ReviewAuthorityPolicy.may_decide(actor, governing):
            raise ReviewNotAuthorisedError(
                "An agent may decide only records of one named project; ask the user.",
                {"reason": "scope_requires_user"},
                next_steps=["Ask the user to run the command in their terminal."],
            )

    @staticmethod
    def check_evidence(actor: Actor, evidence_count: int) -> None:
        """Refuse an agent accepting an assertion without evidence.

        Raises:
            EvidenceRequiredError: An agent and no evidence.
        """
        if actor.kind is ActorKindEnum.AGENT and evidence_count == 0:
            raise EvidenceRequiredError(
                "An agent cannot accept an assertion that has no evidence.",
                next_steps=["Propose the assertion with evidence."],
            )

    @staticmethod
    def requires(governing: Sequence[Applicability]) -> ReviewRequirementEnum:
        """Who must decide an item governed by these applicabilities."""
        agent_ok: bool = (
            len({a.project_id for a in governing}) == 1
            and next(iter(governing)).project_id is not None
        )
        return ReviewRequirementEnum.AGENT_OR_USER if agent_ok else ReviewRequirementEnum.USER

    @staticmethod
    def may_bulk_accept(actor: Actor) -> bool:
        """Only the user applies the bulk accept."""
        return actor.kind is ActorKindEnum.USER

    @staticmethod
    def basis_for(actor: Actor) -> DecisionBasisEnum:
        """`user` for a user, `agent_project` for an agent."""
        if actor.kind is ActorKindEnum.USER:
            return DecisionBasisEnum.USER
        return DecisionBasisEnum.AGENT_PROJECT
