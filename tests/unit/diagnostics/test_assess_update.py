"""The update verdict, from what was observed about the checkout."""

from pathlib import Path

import pytest

from noesis.diagnostics.application.enums import UpdateVerdictEnum
from noesis.diagnostics.application.policies import UpdateAssessment, assess_update
from noesis.diagnostics.application.ports.updates import CheckoutSnapshot

pytestmark = pytest.mark.unit

LOCAL = "a" * 40
REMOTE = "b" * 40


def _snapshot(**changes: object) -> CheckoutSnapshot:
    values: dict[str, object] = {
        "checkout": Path("/src/noesis"),
        "branch": "main",
        "remote_url": "git@example.com:o/noesis.git",
        "local_sha": LOCAL,
        "remote_branch": "main",
        "remote_sha": REMOTE,
        "remote_contains_local": True,
        "local_contains_remote": False,
    } | changes
    return CheckoutSnapshot.model_validate(values)


@pytest.mark.parametrize(
    ("changes", "verdict"),
    [
        ({"remote_sha": LOCAL, "remote_contains_local": None, "local_contains_remote": None},
         UpdateVerdictEnum.UP_TO_DATE),
        ({"remote_contains_local": True, "local_contains_remote": False}, UpdateVerdictEnum.BEHIND),
        ({"remote_contains_local": False, "local_contains_remote": True}, UpdateVerdictEnum.AHEAD),
        ({"remote_contains_local": False, "local_contains_remote": False},
         UpdateVerdictEnum.DIVERGED),
    ],
)  # fmt: skip
def test_histories_decide_the_verdict(
    changes: dict[str, object], verdict: UpdateVerdictEnum
) -> None:
    assert assess_update(_snapshot(**changes)).verdict is verdict


@pytest.mark.parametrize(
    ("changes", "reason_part"),
    [
        ({"checkout": None}, "not a git checkout"),
        ({"remote_url": None}, "no `origin` remote"),
        ({"remote_sha": None}, "could not read"),
        ({"local_sha": None}, "local commit"),
        ({"remote_contains_local": None}, "cannot compare histories"),
        ({"local_contains_remote": None}, "cannot compare histories"),
    ],
)
def test_missing_facts_are_unknown_with_a_named_reason(
    changes: dict[str, object], reason_part: str
) -> None:
    assessment: UpdateAssessment = assess_update(_snapshot(**changes))

    assert assessment.verdict is UpdateVerdictEnum.UNKNOWN
    assert reason_part in assessment.reason


def test_a_dirty_tree_does_not_change_the_verdict() -> None:
    assert assess_update(_snapshot(dirty=True)).verdict is UpdateVerdictEnum.BEHIND
