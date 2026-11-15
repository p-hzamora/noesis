"""ReviewAuthorityPolicy: every row of the authority table (FR-005..FR-007, FR-016; AC-002, AC-005,
AC-013, AC-027; Q-003, Q-004)."""

import pytest
from tests.support.knowledge_support import AGENT

from noesis.bounded_context.knowledge.domain.services.review_authority_policy import (
    ReviewAuthorityPolicy,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    Applicability,
    RecordId,
)
from noesis.bounded_context.knowledge.domain.value_objects.enums import (
    DecisionBasisEnum,
    ReviewRequirementEnum,
)
from noesis.exceptions import EvidenceRequiredError, ReviewNotAuthorisedError

pytestmark = pytest.mark.unit

USER: Actor = Actor(kind=ActorKindEnum.USER, name="pablo")
ACME: Applicability = Applicability(project_id=RecordId(value="0" * 25 + "7"))
OTHER: Applicability = Applicability(project_id=RecordId(value="0" * 25 + "8"))
GLOBAL: Applicability = Applicability()

PROJECT_ONLY = [ACME]
GLOBAL_ONLY = [GLOBAL]
SAME_PROJECT_SUPERSEDES = [ACME, ACME]
CROSS_PROJECT_SUPERSEDES = [ACME, OTHER]
PROJECT_OVER_GLOBAL_SUPERSEDES = [ACME, GLOBAL]
GLOBAL_SUPERSEDES = [GLOBAL, GLOBAL]


@pytest.mark.parametrize(
    "governing",
    [
        PROJECT_ONLY,
        GLOBAL_ONLY,
        SAME_PROJECT_SUPERSEDES,
        CROSS_PROJECT_SUPERSEDES,
        GLOBAL_SUPERSEDES,
    ],
)
def test_user_may_take_every_transition_whatever_the_scope(governing: list[Applicability]) -> None:
    ReviewAuthorityPolicy.check(USER, governing)

    assert ReviewAuthorityPolicy.may_decide(USER, governing) is True


@pytest.mark.parametrize(
    "governing", [PROJECT_ONLY, SAME_PROJECT_SUPERSEDES], ids=["project", "same-project-supersedes"]
)
def test_agent_may_decide_when_every_governing_applicability_names_the_same_project(
    governing: list[Applicability],
) -> None:
    ReviewAuthorityPolicy.check(AGENT, governing)

    assert ReviewAuthorityPolicy.may_decide(AGENT, governing) is True


@pytest.mark.parametrize(
    "governing",
    [GLOBAL_ONLY, PROJECT_OVER_GLOBAL_SUPERSEDES, GLOBAL_SUPERSEDES, CROSS_PROJECT_SUPERSEDES],
    ids=["global", "project-supersedes-global", "global-supersedes", "cross-project-supersedes"],
)
def test_agent_is_refused_on_global_or_cross_project_scope(
    governing: list[Applicability],
) -> None:
    """Includes Q-004: an agent may not reject a space-wide proposal either, same check."""
    with pytest.raises(ReviewNotAuthorisedError) as raised:
        ReviewAuthorityPolicy.check(AGENT, governing)

    assert raised.value.error_code == "KNOWLEDGE_022_REVIEW_NOT_AUTHORISED"
    assert ReviewAuthorityPolicy.may_decide(AGENT, governing) is False


@pytest.mark.parametrize(
    ("governing", "required"),
    [
        (PROJECT_ONLY, ReviewRequirementEnum.AGENT_OR_USER),
        (SAME_PROJECT_SUPERSEDES, ReviewRequirementEnum.AGENT_OR_USER),
        (GLOBAL_ONLY, ReviewRequirementEnum.USER),
        (PROJECT_OVER_GLOBAL_SUPERSEDES, ReviewRequirementEnum.USER),
    ],
)
def test_requires_follows_whether_an_agent_may_decide(
    governing: list[Applicability], required: ReviewRequirementEnum
) -> None:
    assert ReviewAuthorityPolicy.requires(governing) is required


def test_agent_accept_of_an_assertion_needs_evidence_but_a_user_does_not() -> None:
    ReviewAuthorityPolicy.check_evidence(AGENT, 1)
    ReviewAuthorityPolicy.check_evidence(USER, 0)

    with pytest.raises(EvidenceRequiredError) as raised:
        ReviewAuthorityPolicy.check_evidence(AGENT, 0)

    assert raised.value.error_code == "KNOWLEDGE_023_EVIDENCE_REQUIRED"


def test_only_the_user_may_apply_the_bulk_accept() -> None:
    assert ReviewAuthorityPolicy.may_bulk_accept(USER) is True
    assert ReviewAuthorityPolicy.may_bulk_accept(AGENT) is False


def test_basis_is_user_for_a_user_and_agent_project_for_an_agent() -> None:
    assert ReviewAuthorityPolicy.basis_for(USER) is DecisionBasisEnum.USER
    assert ReviewAuthorityPolicy.basis_for(AGENT) is DecisionBasisEnum.AGENT_PROJECT
