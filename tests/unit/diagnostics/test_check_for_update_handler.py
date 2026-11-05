"""`CheckForUpdateHandler` against a scripted inspector."""

from pathlib import Path

import pytest

from noesis.diagnostics.application.enums import UpdateVerdictEnum
from noesis.diagnostics.application.handlers.queries import (
    CheckForUpdateHandler,
    CheckForUpdateQuery,
)
from noesis.diagnostics.application.ports.updates import CheckoutSnapshot, ICheckoutInspector

pytestmark = pytest.mark.unit

CHECKOUT = Path("/src/noesis")


class _Inspector(ICheckoutInspector):
    def __init__(self, snapshot: CheckoutSnapshot) -> None:
        self.snapshot: CheckoutSnapshot = snapshot
        self.inspected: list[Path] = []

    async def inspect(self, package_dir: Path) -> CheckoutSnapshot:
        self.inspected.append(package_dir)
        return self.snapshot


def _snapshot(**changes: object) -> CheckoutSnapshot:
    values: dict[str, object] = {
        "checkout": CHECKOUT,
        "branch": "main",
        "remote_url": "origin-url",
        "local_sha": "a" * 40,
        "remote_branch": "main",
        "remote_sha": "b" * 40,
        "remote_contains_local": True,
        "local_contains_remote": False,
        "dirty": True,
    } | changes
    return CheckoutSnapshot.model_validate(values)


async def test_behind_reports_short_shas_and_the_update_steps() -> None:
    inspector = _Inspector(_snapshot())

    dto = await CheckForUpdateHandler(inspector=inspector).handle(
        CheckForUpdateQuery(package_dir=CHECKOUT / "src/noesis")
    )

    assert inspector.inspected == [CHECKOUT / "src/noesis"]
    assert dto.verdict is UpdateVerdictEnum.BEHIND
    assert (dto.local_sha, dto.remote_sha) == ("aaaaaaa", "bbbbbbb")
    assert (dto.checkout, dto.branch, dto.remote_branch) == (str(CHECKOUT), "main", "main")
    assert dto.remote_url == "origin-url"
    assert dto.dirty is True
    assert dto.next_steps == (
        f"git -C {CHECKOUT} pull",
        f"uv tool install --reinstall {CHECKOUT}",
    )


async def test_diverged_gets_the_same_steps_and_ahead_gets_none() -> None:
    diverged = await CheckForUpdateHandler(
        inspector=_Inspector(_snapshot(remote_contains_local=False))
    ).handle(CheckForUpdateQuery(package_dir=CHECKOUT))
    ahead = await CheckForUpdateHandler(
        inspector=_Inspector(_snapshot(remote_contains_local=False, local_contains_remote=True))
    ).handle(CheckForUpdateQuery(package_dir=CHECKOUT))

    assert diverged.verdict is UpdateVerdictEnum.DIVERGED and len(diverged.next_steps) == 2
    assert ahead.verdict is UpdateVerdictEnum.AHEAD and ahead.next_steps == ()


async def test_an_empty_snapshot_is_unknown_without_steps() -> None:
    dto = await CheckForUpdateHandler(inspector=_Inspector(CheckoutSnapshot())).handle(
        CheckForUpdateQuery(package_dir=Path("/site-packages/noesis"))
    )

    assert dto.verdict is UpdateVerdictEnum.UNKNOWN
    assert dto.reason
    assert dto.next_steps == ()
    assert dto.local_sha is None and dto.checkout is None
