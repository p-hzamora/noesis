"""assess_availability: the pure policy, as a table of cases (FR-004..FR-008; AC-001, AC-005, AC-007)."""

import pytest
from tests.support.catalog_support import (
    CLAUDE,
    CODEX,
    OBSERVED_AT,
    artifact,
    entry_dto,
    inventory_of,
    unreadable,
)

from noesis.bounded_context.knowledge.application.dtos import (
    AvailabilityObservationDto,
    AvailabilityReasonEnum,
    AvailabilityStatusEnum,
    RuntimeInventoryDto,
)
from noesis.bounded_context.knowledge.application.policies.catalog import assess_availability

pytestmark = pytest.mark.unit

AVAILABLE = AvailabilityStatusEnum.AVAILABLE
UNAVAILABLE = AvailabilityStatusEnum.UNAVAILABLE
UNKNOWN = AvailabilityStatusEnum.UNKNOWN
NONE = AvailabilityReasonEnum.NONE
NOT_INSTALLED = AvailabilityReasonEnum.NOT_INSTALLED
PREREQ_MISSING = AvailabilityReasonEnum.PREREQUISITE_MISSING
PROBE_FAILED = AvailabilityReasonEnum.PROBE_FAILED
NOT_PROBED = AvailabilityReasonEnum.KIND_NOT_PROBED


def assess(inventory: RuntimeInventoryDto, **entry: object) -> AvailabilityObservationDto:
    return assess_availability(entry_dto(**entry), inventory)  # type: ignore[arg-type]


def outcome(observation: AvailabilityObservationDto) -> tuple[object, object]:
    return observation.status, observation.reason


def test_observation_carries_entry_identity_and_the_inventorys_runtime_host_and_time() -> None:
    inventory = inventory_of(CODEX, artifact("skill", "demo"), host="box", observed_at=OBSERVED_AT)

    observation = assess(inventory, kind="skill", name="demo", entry_id="0" * 25 + "9")

    assert observation.entry_id == "0" * 25 + "9"
    assert (observation.kind, observation.name) == ("skill", "demo")
    assert observation.runtime == CODEX
    assert (observation.host, observation.observed_at) == ("box", OBSERVED_AT)


def test_rule2_uninstalled_entry_is_unavailable_not_installed() -> None:
    """AC-001 (unit)."""
    observation = assess(
        inventory_of(CLAUDE, artifact("skill", "python-suite:ddd-hexagonal-python", "2.0.0")),
        kind="skill",
        name="python-suite:ddd-interface-cli",
        version="2.0.0",
    )

    assert outcome(observation) == (UNAVAILABLE, NOT_INSTALLED)
    assert observation.version_drift is None
    assert observation.observed_version is None
    assert list(observation.missing_prerequisites) == []


def test_rule5_installed_entry_is_available_with_no_reason() -> None:
    observation = assess(inventory_of(CLAUDE, artifact("skill", "demo", "1.0.0")), name="demo")

    assert outcome(observation) == (AVAILABLE, NONE)
    assert observation.observed_version == "1.0.0"
    assert list(observation.missing_prerequisites) == []


@pytest.mark.parametrize(
    ("entry_name", "installed_name", "expected"),
    [
        ("demo-skill", "demo-plugin:demo-skill", NOT_INSTALLED),
        ("other-plugin:demo-skill", "demo-plugin:demo-skill", NOT_INSTALLED),
        ("demo-plugin:demo-skill", "demo-plugin:demo-skill", NONE),
        ("demo-plugin:demo-skill", "demo-skill", NOT_INSTALLED),
        ("demo-skill", "demo-skill", NONE),
        ("Gh", "gh", NOT_INSTALLED),
    ],
)
def test_rule6_matching_is_exact_on_name(
    entry_name: str, installed_name: str, expected: AvailabilityReasonEnum
) -> None:
    observation = assess(
        inventory_of(CLAUDE, artifact("skill", installed_name)), kind="skill", name=entry_name
    )

    assert observation.reason == expected


def test_rule6_matching_is_exact_on_kind() -> None:
    observation = assess(inventory_of(CLAUDE, artifact("agent", "demo")), kind="skill", name="demo")

    assert outcome(observation) == (UNAVAILABLE, NOT_INSTALLED)


@pytest.mark.parametrize("reason", [PROBE_FAILED, NOT_PROBED])
def test_rule1_unreadable_kind_is_unknown_with_that_reason(
    reason: AvailabilityReasonEnum,
) -> None:
    observation = assess(
        inventory_of(unreadable_kinds=(unreadable("mcp_server", reason.value),)),
        kind="mcp_server",
        name="docs",
    )

    assert outcome(observation) == (UNKNOWN, reason)
    assert observation.version_drift is None


def test_rule1_unreadable_kind_is_never_assumed_available_even_when_listed() -> None:
    observation = assess(
        inventory_of(
            CLAUDE,
            artifact("skill", "local"),
            unreadable_kinds=(unreadable("skill", "probe_failed"),),
        ),
        kind="skill",
        name="local",
    )

    assert outcome(observation) == (UNKNOWN, PROBE_FAILED)


def test_rule1_applies_only_to_the_entrys_own_kind() -> None:
    observation = assess(
        inventory_of(
            CLAUDE,
            artifact("skill", "demo"),
            unreadable_kinds=(unreadable("mcp_server", "kind_not_probed"),),
        ),
        kind="skill",
        name="demo",
    )

    assert outcome(observation) == (AVAILABLE, NONE)


def test_codex_agent_entry_is_unknown_kind_not_probed() -> None:
    observation = assess(
        inventory_of(CODEX, unreadable_kinds=(unreadable("agent", "kind_not_probed"),)),
        kind="agent",
        name="demo-plugin:reviewer",
    )

    assert outcome(observation) == (UNKNOWN, NOT_PROBED)


def test_rule3_missing_prerequisites_are_listed_in_declared_order() -> None:
    observation = assess(
        inventory_of(CLAUDE, artifact("skill", "demo"), artifact("cli_tool", "present")),
        name="demo",
        prerequisites=("cli_tool:b", "cli_tool:present", "cli_tool:a"),
    )

    assert outcome(observation) == (UNAVAILABLE, PREREQ_MISSING)
    assert list(observation.missing_prerequisites) == ["cli_tool:b", "cli_tool:a"]


def test_rule3_prerequisite_of_another_kind_does_not_satisfy_it() -> None:
    observation = assess(
        inventory_of(CLAUDE, artifact("skill", "demo"), artifact("skill", "gh")),
        name="demo",
        prerequisites=("cli_tool:gh",),
    )

    assert outcome(observation) == (UNAVAILABLE, PREREQ_MISSING)


def test_rule3_qualified_prerequisite_matches_only_the_same_plugins_artifact() -> None:
    observation = assess(
        inventory_of(CLAUDE, artifact("skill", "demo"), artifact("skill", "plug-a:helper")),
        name="demo",
        prerequisites=("skill:plug-b:helper",),
    )

    assert list(observation.missing_prerequisites) == ["skill:plug-b:helper"]


def test_rule3_keeps_observed_version_and_no_drift_when_a_prerequisite_is_missing() -> None:
    observation = assess(
        inventory_of(CLAUDE, artifact("skill", "demo", "2.0.1")),
        name="demo",
        version="2.0.0",
        prerequisites=("cli_tool:x",),
    )

    assert outcome(observation) == (UNAVAILABLE, PREREQ_MISSING)
    assert observation.observed_version == "2.0.1"
    assert observation.version_drift is None


def test_rule_order_not_installed_wins_over_a_missing_prerequisite() -> None:
    observation = assess(inventory_of(), name="demo", prerequisites=("cli_tool:absent",))

    assert outcome(observation) == (UNAVAILABLE, NOT_INSTALLED)
    assert list(observation.missing_prerequisites) == []


def test_only_the_entrys_own_prerequisites_are_checked() -> None:
    """One level deep: B's own prerequisite is invisible to the policy, so A is available."""
    observation = assess(
        inventory_of(CLAUDE, artifact("skill", "demo"), artifact("skill", "b")),
        name="demo",
        prerequisites=("skill:b",),
    )

    assert outcome(observation) == (AVAILABLE, NONE)


def test_rule4_prerequisite_of_a_not_probed_kind_makes_the_entry_unknown_not_missing() -> None:
    """Q-011 default."""
    observation = assess(
        inventory_of(
            CLAUDE,
            artifact("skill", "demo"),
            unreadable_kinds=(unreadable("mcp_server", "kind_not_probed"),),
        ),
        name="demo",
        prerequisites=("mcp_server:docs",),
    )

    assert outcome(observation) == (UNKNOWN, NOT_PROBED)
    assert list(observation.missing_prerequisites) == []
    assert observation.version_drift is None


def test_rule3_wins_over_rule4_when_another_prerequisite_is_really_missing() -> None:
    """Q-011 default."""
    observation = assess(
        inventory_of(
            CLAUDE,
            artifact("skill", "demo"),
            unreadable_kinds=(unreadable("mcp_server", "kind_not_probed"),),
        ),
        name="demo",
        prerequisites=("mcp_server:docs", "cli_tool:x"),
    )

    assert outcome(observation) == (UNAVAILABLE, PREREQ_MISSING)
    assert list(observation.missing_prerequisites) == ["cli_tool:x"]


@pytest.mark.parametrize(
    ("prerequisites", "expected"),
    [
        (("agent:a", "mcp_server:m"), PROBE_FAILED),
        (("mcp_server:m", "agent:a"), NOT_PROBED),
    ],
)
def test_rule4_the_first_unreadable_prerequisite_in_declared_order_decides_the_reason(
    prerequisites: tuple[str, ...], expected: AvailabilityReasonEnum
) -> None:
    observation = assess(
        inventory_of(
            CLAUDE,
            artifact("skill", "demo"),
            unreadable_kinds=(
                unreadable("mcp_server", "kind_not_probed"),
                unreadable("agent", "probe_failed"),
            ),
        ),
        name="demo",
        prerequisites=prerequisites,
    )

    assert outcome(observation) == (UNKNOWN, expected)


@pytest.mark.parametrize(
    ("declared", "observed", "drift"),
    [
        ("2.0.0", "2.0.1", True),
        ("2.0.1", "2.0.1", False),
        (None, "2.0.1", None),
        ("2.0.0", None, None),
        (None, None, None),
    ],
)
def test_version_drift_is_set_only_when_both_versions_exist_and_never_blocks_availability(
    declared: str | None, observed: str | None, drift: bool | None
) -> None:
    """AC-007 (unit)."""
    observation = assess(
        inventory_of(CLAUDE, artifact("skill", "demo", observed)), name="demo", version=declared
    )

    assert outcome(observation) == (AVAILABLE, NONE)
    assert observation.observed_version == observed
    assert observation.version_drift is drift


@pytest.mark.parametrize("variant", ["not_installed", "unknown"])
def test_version_drift_is_null_for_every_status_but_available(variant: str) -> None:
    unreadable_kinds = (unreadable("skill", "probe_failed"),) if variant == "unknown" else ()
    observation = assess(
        inventory_of(unreadable_kinds=unreadable_kinds), name="demo", version="2.0.0"
    )

    assert observation.status is not AVAILABLE
    assert observation.version_drift is None
