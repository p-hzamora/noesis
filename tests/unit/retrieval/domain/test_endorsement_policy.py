"""AC-006: endorsement matrix; availability never implies endorsement."""

import pytest

from noesis.bounded_context.retrieval.domain.enums import DecisionBasisEnum, EndorsementEnum
from noesis.bounded_context.retrieval.domain.policies.endorsement_policy import EndorsementPolicy
from noesis.bounded_context.retrieval.domain.value_objects.endorsement_fact import EndorsementFact

pytestmark = pytest.mark.unit
policy = EndorsementPolicy()
USER, AGENT = DecisionBasisEnum.USER, DecisionBasisEnum.AGENT


def fact(status: str, basis: DecisionBasisEnum, project: str | None = None) -> EndorsementFact:
    return EndorsementFact(status=status, basis=basis, project_key=project)


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ([], EndorsementEnum.NONE),
        ([fact("accepted", USER)], EndorsementEnum.USER),
        ([fact("accepted", AGENT)], EndorsementEnum.PROPOSED),
        ([fact("proposed", USER)], EndorsementEnum.PROPOSED),
        ([fact("proposed", AGENT)], EndorsementEnum.PROPOSED),
        ([fact("retracted", USER)], EndorsementEnum.NONE),
        ([fact("superseded", USER), fact("rejected", AGENT)], EndorsementEnum.NONE),
        ([fact("proposed", AGENT), fact("accepted", USER)], EndorsementEnum.USER),
    ],
)
def test_matrix(facts: list[EndorsementFact], expected: EndorsementEnum) -> None:
    assert policy.endorsement(facts, project_key=None) is expected


def test_availability_alone_is_not_endorsement() -> None:
    assert policy.endorsement([], project_key="noesis") is EndorsementEnum.NONE
