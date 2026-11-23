"""Refs are canonical and safe: stored text never becomes something to run (AC-019)."""

import pytest

from noesis.bounded_context.retrieval.domain.enums import NextActionEnum
from noesis.bounded_context.retrieval.domain.policies.resource_ref_policy import ResourceRefPolicy

pytestmark = pytest.mark.unit
policy = ResourceRefPolicy()
ULID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.mark.parametrize(
    ("kind", "name", "expected"),
    [
        ("skill", "python-suite:ddd-interface-cli", "catalog:skill:python-suite:ddd-interface-cli"),
        ("cli_tool", "uv", "catalog:cli_tool:uv"),
        ("skill", "x; rm -rf ~", None),
        ("skill", "$(id)", None),
        ("skill", "a b", None),
        ("skill", "", None),
        ("widget", "x", None),
    ],
)
def test_resource_ref(kind: str, name: str, expected: str | None) -> None:
    assert policy.resource_ref(kind, name) == expected


def test_prerequisite_ref_and_lookup_key_round_trip() -> None:
    ref = policy.prerequisite_ref("skill:python-suite:ddd-hexagonal-python")

    assert ref == "catalog:skill:python-suite:ddd-hexagonal-python"
    assert ref is not None
    assert policy.lookup_key(ref) == "skill:python-suite:ddd-hexagonal-python"
    assert policy.prerequisite_ref("no-kind") is None


@pytest.mark.parametrize(
    ("kind", "action"),
    [
        ("skill", NextActionEnum.LOAD_SKILL),
        ("agent", NextActionEnum.USE_AGENT),
        ("cli_tool", NextActionEnum.USE_CLI_TOOL),
        ("mcp_server", NextActionEnum.USE_MCP_SERVER),
        ("other", None),
    ],
)
def test_action_for(kind: str, action: NextActionEnum | None) -> None:
    assert policy.action_for(kind) == action


def test_record_ref_needs_a_ulid_and_a_revision() -> None:
    assert policy.record_ref(ULID, 3) == f"record:{ULID}@3"
    assert policy.record_ref(ULID, None) is None
    assert policy.record_ref("rm -rf /", 1) is None
