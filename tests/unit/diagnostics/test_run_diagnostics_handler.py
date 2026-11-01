"""Diagnostics rules, against a scripted probe."""

from pathlib import Path

import pytest

from noesis.diagnostics.application.handlers.queries import (
    RunDiagnosticsHandler,
    RunDiagnosticsQuery,
)
from noesis.diagnostics.application.ports.probes import IEnvironmentProbe

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


VAULT: Path = Path("/vault")
STATE: Path = Path("/home/u/.local/state/noesis")


def _query(**changes: object) -> RunDiagnosticsQuery:
    values: dict[str, object] = {
        "env_file": Path("/cfg/.env"),
        "vault_dir": VAULT,
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
        writable={VAULT, Path("/home/u")},
        executables={"git": "/usr/bin/git", "claude": "/bin/claude"},
    )


async def test_a_healthy_machine_passes_every_check() -> None:
    report = await RunDiagnosticsHandler(probe=_healthy()).handle(_query())

    assert report.ok
    assert [check.name for check in report.checks] == [
        "config_file", "vault", "state_dir", "git", "curator", "claude_code_hooks",
    ]  # fmt: skip
    assert report.checks[0].detail == "/cfg/.env (found)"
    assert report.checks[2].detail == str(
        STATE
    )  # a missing state folder is fine: its parent is writable
    assert report.checks[5].next_step is not None  # hooks missing is informational, not a failure


async def test_missing_pieces_fail_with_a_next_step() -> None:
    report = await RunDiagnosticsHandler(probe=_Probe()).handle(
        _query(vault_dir=None, installed_hook_events=None)
    )

    failed = {check.name: check for check in report.checks if not check.ok}
    assert not report.ok
    assert set(failed) == {"vault", "state_dir", "git", "curator", "claude_code_hooks"}
    assert all(check.next_step for check in failed.values())
    assert failed["vault"].detail == "NOESIS_VAULT_DIR is not set"
    assert report.checks[0].detail == "/cfg/.env (not created, defaults in use)"
    assert failed["claude_code_hooks"].detail.endswith("is not valid JSON")


async def test_an_unwritable_vault_is_reported() -> None:
    probe: _Probe = _healthy()
    probe.writable.discard(VAULT)

    report = await RunDiagnosticsHandler(probe=probe).handle(_query())

    vault = report.checks[1]
    assert (vault.ok, vault.detail) == (False, "/vault is missing or not writable")


async def test_installed_events_are_listed_sorted() -> None:
    report = await RunDiagnosticsHandler(probe=_healthy()).handle(
        _query(installed_hook_events=("Stop", "PostToolUse"))
    )

    assert report.checks[5].detail == "installed: PostToolUse, Stop"
    assert report.checks[5].next_step is None
