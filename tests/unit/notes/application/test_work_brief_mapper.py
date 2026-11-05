"""Translating the published work-brief contract into Notes's model."""

import pytest
from tests.support.notes_support import a_brief

from noesis.bounded_context.notes.application.mappers import WorkBriefMapper
from noesis.bounded_context.notes.domain.value_objects import CommitRef, WorkBrief
from noesis.shared_kernel.contracts import WorkBriefContract

pytestmark = pytest.mark.unit


def test_every_contract_field_is_carried_into_the_domain_brief() -> None:
    contract: WorkBriefContract = a_brief()

    brief: WorkBrief = WorkBriefMapper.to_domain(contract)

    assert brief == WorkBrief(
        session_id=contract.session_id,
        repository=contract.repository,
        repository_path=contract.repository_path,
        branch=contract.branch,
        head=contract.head,
        commits=(CommitRef(sha="8e6d3b5fe598c6bf", subject="feat: add TTL cache"),),
        diff_stat=contract.diff_stat,
        goal=contract.goal,
        session_excerpt=contract.session_excerpt,
    )


def test_the_domain_brief_carries_every_field_except_the_contract_version() -> None:
    contract_fields: set[str] = set(WorkBriefContract.model_fields) - {"contract_version"}

    assert set(WorkBrief.model_fields) == contract_fields
