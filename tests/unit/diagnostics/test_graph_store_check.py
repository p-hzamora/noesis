"""The doctor's graph store check, against a scripted probe (FR-015, AC-012, D-027)."""

from pathlib import Path

import pytest

from noesis.diagnostics.application.enums import GraphStoreStatusEnum
from noesis.diagnostics.application.handlers.queries import (
    RunDiagnosticsHandler,
    RunDiagnosticsQuery,
)
from noesis.diagnostics.application.ports.graph_store import GraphStoreSnapshot, IGraphStoreProbe
from noesis.diagnostics.application.ports.probes import IEnvironmentProbe

pytestmark = pytest.mark.unit

URI = "bolt://127.0.0.1:7687"


class _Environment(IEnvironmentProbe):
    def exists(self, path: Path) -> bool:
        return True

    def is_file(self, path: Path) -> bool:
        return True

    def is_writable_folder(self, folder: Path) -> bool:
        return True

    def find_executable(self, command: str) -> str | None:
        return f"/bin/{command}"


class _Store(IGraphStoreProbe):
    def __init__(self, snapshot: GraphStoreSnapshot) -> None:
        self.snapshot: GraphStoreSnapshot = snapshot
        self.calls: int = 0

    async def inspect(self) -> GraphStoreSnapshot:
        self.calls += 1
        return self.snapshot


def _query(**changes: object) -> RunDiagnosticsQuery:
    values: dict[str, object] = {
        "env_file": Path("/cfg/.env"),
        "vault_dir": Path("/vault"),
        "state_dir": Path("/state"),
        "curator_binary": "claude",
        "hooks_settings_file": Path("/s.json"),
        "installed_hook_events": (),
        "graph_store_steps": ("core", "later"),
    } | changes
    return RunDiagnosticsQuery.model_validate(values)


async def _check(store: _Store | None, **changes: object):
    report = await RunDiagnosticsHandler(probe=_Environment(), graph_store=store).handle(
        _query(**changes)
    )
    return report, [check for check in report.checks if check.name == "graph_store"]


async def test_reachable_with_every_step_applied_passes() -> None:
    store = _Store(
        GraphStoreSnapshot(
            status=GraphStoreStatusEnum.REACHABLE,
            uri=URI,
            applied_steps=frozenset({"core", "later"}),
        )
    )

    report, checks = await _check(store)

    assert report.ok and checks[0].ok
    assert checks[0].detail == f"reachable at {URI}; schema steps applied: core, later"
    assert checks[0].next_step is None


async def test_missing_steps_fail_and_name_them_with_store_init_as_the_next_step() -> None:
    store = _Store(
        GraphStoreSnapshot(
            status=GraphStoreStatusEnum.REACHABLE, uri=URI, applied_steps=frozenset({"core"})
        )
    )

    report, checks = await _check(store)

    assert not report.ok
    assert "applied: core" in checks[0].detail and "missing: later" in checks[0].detail
    assert checks[0].next_step == "Run `noesis store init`."


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (GraphStoreStatusEnum.UNREACHABLE, f"unreachable at {URI}"),
        (
            GraphStoreStatusEnum.AUTHENTICATION_FAILED,
            f"reachable at {URI}, credentials rejected",
        ),
        (GraphStoreStatusEnum.ERROR, f"reachable at {URI}, but inspecting it failed: boom"),
    ],
)
async def test_an_outage_a_rejection_or_an_error_fails_the_run(
    status: GraphStoreStatusEnum, expected: str
) -> None:
    store = _Store(GraphStoreSnapshot(status=status, uri=URI, message="boom"))

    report, checks = await _check(store)

    assert not report.ok and not checks[0].ok
    assert checks[0].detail == expected
    assert checks[0].next_step


async def test_an_unset_password_is_a_warning_and_the_store_is_not_probed() -> None:
    store = _Store(GraphStoreSnapshot(status=GraphStoreStatusEnum.UNREACHABLE, uri=URI))

    report, checks = await _check(store, graph_store_configured=False)

    assert report.ok
    assert checks[0].ok and checks[0].warning
    assert store.calls == 0


async def test_no_store_probe_means_no_check() -> None:
    _, checks = await _check(None)

    assert checks == []
