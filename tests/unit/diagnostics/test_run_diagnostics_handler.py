"""Diagnostics rules, against a scripted probe."""

from pathlib import Path

import pytest

from noesis.diagnostics.application.dtos import UpdateCheckDto
from noesis.diagnostics.application.enums import UpdateVerdictEnum
from noesis.diagnostics.application.handlers.queries import (
    CheckForUpdateQuery,
    RunDiagnosticsHandler,
    RunDiagnosticsQuery,
)
from noesis.diagnostics.application.ports.probes import IEnvironmentProbe
from noesis.shared_kernel.application.handlers import IHandler

pytestmark = pytest.mark.unit


class _Probe(IEnvironmentProbe):
    def __init__(
        self,
        *,
        files: set[Path] | None = None,
        folders: set[Path] | None = None,
        writable: set[Path] | None = None,
        executables: dict[str, str] | None = None,
    ) -> None:
        self.files: set[Path] = files or set()
        self.folders: set[Path] = folders or set()
        self.writable: set[Path] = writable or set()
        self.executables: dict[str, str] = executables or {}

    def exists(self, path: Path) -> bool:
        return path in self.folders or path in self.files

    def is_file(self, path: Path) -> bool:
        return path in self.files

    def is_writable_folder(self, folder: Path) -> bool:
        return folder in self.writable

    def find_executable(self, command: str) -> str | None:
        return self.executables.get(command)


STATE = Path("/home/u/.local/state/noesis")


def _query(**changes: object) -> RunDiagnosticsQuery:
    values: dict[str, object] = {
        "env_file": Path("/cfg/.env"),
        "state_dir": STATE,
        "curator_binary": "claude",
        "hooks_settings_file": Path("/home/u/.claude/settings.json"),
        "installed_hook_events": (),
    } | changes
    return RunDiagnosticsQuery.model_validate(values)


def _healthy() -> _Probe:
    return _Probe(
        files={Path("/cfg/.env")},
        folders={Path("/home/u")},
        writable={Path("/home/u")},
        executables={"git": "/usr/bin/git", "claude": "/bin/claude"},
    )


async def test_a_healthy_machine_passes_every_check() -> None:
    report = await RunDiagnosticsHandler(probe=_healthy()).handle(_query())

    assert report.ok
    assert [check.name for check in report.checks] == [
        "config_file", "state_dir", "git", "curator", "claude_code_hooks",
    ]  # fmt: skip
    assert report.checks[0].detail == "/cfg/.env (found)"
    assert report.checks[1].detail == str(
        STATE
    )  # a missing state folder is fine: its parent is writable
    assert report.checks[4].next_step is not None  # hooks missing is informational, not a failure


async def test_missing_pieces_fail_with_a_next_step() -> None:
    report = await RunDiagnosticsHandler(probe=_Probe()).handle(_query(installed_hook_events=None))

    failed = {check.name: check for check in report.checks if not check.ok}
    assert not report.ok
    assert set(failed) == {"state_dir", "git", "curator", "claude_code_hooks"}
    assert all(check.next_step for check in failed.values())
    assert report.checks[0].detail == "/cfg/.env (not created, defaults in use)"
    assert failed["claude_code_hooks"].detail.endswith("is not valid JSON")


async def test_installed_events_are_listed_sorted() -> None:
    report = await RunDiagnosticsHandler(probe=_healthy()).handle(
        _query(installed_hook_events=("Stop", "PostToolUse"))
    )

    assert report.checks[4].detail == "installed: PostToolUse, Stop"
    assert report.checks[4].next_step is None


async def test_no_check_mentions_obsidian_or_mcp() -> None:
    report = await RunDiagnosticsHandler(probe=_healthy()).handle(_query())

    text: str = " ".join(
        f"{check.name} {check.detail} {check.next_step}" for check in report.checks
    )
    assert "obsidian" not in text.lower()
    assert "mcp" not in text.lower()


class _Updates(IHandler[CheckForUpdateQuery, UpdateCheckDto]):
    def __init__(self, verdict: UpdateVerdictEnum, *, next_steps: tuple[str, ...] = ()) -> None:
        self.verdict: UpdateVerdictEnum = verdict
        self.next_steps: tuple[str, ...] = next_steps
        self.queries: list[CheckForUpdateQuery] = []

    async def handle(self, action: CheckForUpdateQuery) -> UpdateCheckDto:
        self.queries.append(action)
        return UpdateCheckDto(
            verdict=self.verdict, reason=f"reason {self.verdict}", next_steps=self.next_steps
        )


async def test_no_update_check_without_a_handler_or_a_package_dir() -> None:
    names = lambda report: [check.name for check in report.checks]  # noqa: E731
    updates = _Updates(UpdateVerdictEnum.BEHIND)

    without_handler = await RunDiagnosticsHandler(probe=_healthy()).handle(
        _query(update_package_dir=Path("/p"))
    )
    without_dir = await RunDiagnosticsHandler(probe=_healthy(), updates=updates).handle(_query())

    assert "update" not in names(without_handler) and "update" not in names(without_dir)
    assert updates.queries == []


@pytest.mark.parametrize(
    ("verdict", "warning"),
    [
        (UpdateVerdictEnum.BEHIND, True),
        (UpdateVerdictEnum.DIVERGED, True),
        (UpdateVerdictEnum.AHEAD, True),
        (UpdateVerdictEnum.UNKNOWN, True),
        (UpdateVerdictEnum.UP_TO_DATE, False),
    ],
)
async def test_the_update_check_never_fails_the_report(
    verdict: UpdateVerdictEnum, warning: bool
) -> None:
    updates = _Updates(verdict, next_steps=("git -C /c pull", "uv tool install --reinstall /c"))

    report = await RunDiagnosticsHandler(probe=_healthy(), updates=updates).handle(
        _query(update_package_dir=Path("/c/src/noesis"))
    )

    check = report.checks[-1]
    assert report.ok and check.ok
    assert check.name == "update"
    assert check.warning is warning
    assert check.detail == f"reason {verdict}"
    assert updates.queries == [CheckForUpdateQuery(package_dir=Path("/c/src/noesis"))]
    assert check.next_step == "git -C /c pull; uv tool install --reinstall /c"


async def test_ordinary_checks_are_not_warnings() -> None:
    report = await RunDiagnosticsHandler(probe=_healthy()).handle(_query())

    assert not any(check.warning for check in report.checks)
