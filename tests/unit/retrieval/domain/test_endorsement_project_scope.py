"""AC-007: a project endorsement never leaks to another project or to no project."""

import pytest

from noesis.bounded_context.retrieval.domain.enums import DecisionBasisEnum, EndorsementEnum
from noesis.bounded_context.retrieval.domain.policies.endorsement_policy import EndorsementPolicy
from noesis.bounded_context.retrieval.domain.value_objects.endorsement_fact import EndorsementFact

pytestmark = pytest.mark.unit
policy = EndorsementPolicy()


def accepted(project: str | None, basis: DecisionBasisEnum) -> EndorsementFact:
    return EndorsementFact(status="accepted", basis=basis, project_key=project)


@pytest.mark.parametrize("basis", list(DecisionBasisEnum))
def test_project_endorsement_applies_on_its_project(basis: DecisionBasisEnum) -> None:
    assert policy.endorsement([accepted("noesis", basis)], project_key="noesis") is (
        EndorsementEnum.PROJECT
    )


@pytest.mark.parametrize("current", ["other", None])
def test_project_endorsement_does_not_leak(current: str | None) -> None:
    facts = [accepted("noesis", DecisionBasisEnum.USER)]
    assert policy.endorsement(facts, project_key=current) is EndorsementEnum.NONE


def test_foreign_proposal_does_not_leak_either() -> None:
    fact = EndorsementFact(status="proposed", basis=DecisionBasisEnum.AGENT, project_key="x")
    assert policy.endorsement([fact], project_key="noesis") is EndorsementEnum.NONE


def test_user_endorsement_outranks_project() -> None:
    facts = [accepted("noesis", DecisionBasisEnum.AGENT), accepted(None, DecisionBasisEnum.USER)]
    assert policy.endorsement(facts, project_key="noesis") is EndorsementEnum.USER
