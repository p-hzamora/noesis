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
from noesis.diagnostics.application.ports.probes import IEnvironmentProbe, IObsidianMcpProbe
from noesis.exceptions import ObsidianMcpError
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
        entries: dict[Path, tuple[str, ...]] | None = None,
    ) -> None:
        self.entries: dict[Path, tuple[str, ...]] = entries or {}
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

    def list_entries(self, folder: Path) -> tuple[str, ...]:
        return self.entries.get(folder, ())


VAULT = Path("/vault")
STATE = Path("/home/u/.local/state/noesis")


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
        "writer", "search_backend",
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


class _Obsidian(IObsidianMcpProbe):
    def __init__(self, root: tuple[str, ...] | None, *, accepts_writes: bool = True) -> None:
        self.root: tuple[str, ...] | None = root
        self.accepts_writes: bool = accepts_writes
        self.calls: int = 0
        self.writes: int = 0

    async def write_probe(self) -> None:
        self.writes += 1
        if not self.accepts_writes:
            raise ObsidianMcpError("Obsidian MCP tool `vault_write` failed: read-only vault.")

    async def list_root(self) -> tuple[str, ...]:
        self.calls += 1
        if self.root is None:
            raise ObsidianMcpError("Obsidian MCP at http://x/mcp/ is unreachable (refused).")
        return self.root


MCP_URL: str = "http://127.0.0.1:27123/mcp/"


async def _search_check(obsidian: _Obsidian | None, **changes: object) -> tuple[bool, str]:
    probe: _Probe = _healthy()
    probe.entries[VAULT] = (".obsidian", "repos", "learning")
    report = await RunDiagnosticsHandler(probe=probe, obsidian=obsidian).handle(_query(**changes))
    check = report.checks[-1]
    assert check.name == "search_backend"
    return check.ok, check.detail


async def test_the_filesystem_backend_makes_no_mcp_call() -> None:
    obsidian: _Obsidian = _Obsidian(("repos",))

    ok, detail = await _search_check(obsidian)

    assert ok
    assert "filesystem" in detail
    assert obsidian.calls == 0


async def test_obsidian_serving_the_same_vault_passes_ignoring_hidden_entries() -> None:
    ok, detail = await _search_check(
        _Obsidian((".obsidian", "learning", "repos")), obsidian_mcp_url=MCP_URL
    )

    assert ok
    assert detail == f"obsidian-mcp reachable at {MCP_URL}, serving {VAULT}"


async def test_obsidian_serving_another_vault_is_flagged() -> None:
    ok, detail = await _search_check(_Obsidian(("projects", "repos")), obsidian_mcp_url=MCP_URL)

    assert not ok
    assert "different vault" in detail
    assert "learning" in detail
    assert "projects" in detail


async def test_an_unreachable_obsidian_is_flagged_with_the_fallback_hint() -> None:
    ok, detail = await _search_check(_Obsidian(None), obsidian_mcp_url=MCP_URL)

    assert not ok
    assert "unreachable" in detail


async def test_without_a_vault_folder_the_comparison_is_skipped() -> None:
    ok, detail = await _search_check(
        _Obsidian(("repos",)), obsidian_mcp_url=MCP_URL, vault_dir=None
    )

    assert ok
    assert "not compared" in detail


async def _writer_check(
    obsidian: _Obsidian | None, **changes: object
) -> tuple[bool, str, str | None]:
    report = await RunDiagnosticsHandler(probe=_healthy(), obsidian=obsidian).handle(
        _query(**changes)
    )
    check = next(check for check in report.checks if check.name == "writer")
    return check.ok, check.detail, check.next_step


async def test_writer_check_on_the_filesystem_makes_no_mcp_call() -> None:
    obsidian: _Obsidian = _Obsidian(("repos",))

    ok, detail, _ = await _writer_check(obsidian)

    assert ok
    assert detail == f"filesystem (files under {VAULT}; see the vault check)"
    assert (obsidian.calls, obsidian.writes) == (0, 0)


async def test_writer_check_on_mcp_passes_when_the_server_accepts_a_write() -> None:
    obsidian: _Obsidian = _Obsidian(("repos",))

    ok, detail, _ = await _writer_check(obsidian, writer_mcp_url=MCP_URL)

    assert ok
    assert detail == f"obsidian-mcp at {MCP_URL} accepted a write"
    assert obsidian.writes == 1


async def test_writer_check_on_mcp_fails_when_the_write_is_refused() -> None:
    obsidian: _Obsidian = _Obsidian(("repos",), accepts_writes=False)
    probe: _Probe = _healthy()

    report = await RunDiagnosticsHandler(probe=probe, obsidian=obsidian).handle(
        _query(writer_mcp_url=MCP_URL)
    )

    check = next(check for check in report.checks if check.name == "writer")
    assert not check.ok
    assert "read-only vault" in check.detail
    assert check.next_step is not None
    assert "write permission" in check.next_step
    assert not report.ok


async def test_writer_check_on_the_filesystem_names_an_unset_vault() -> None:
    ok, detail, _ = await _writer_check(None, vault_dir=None)

    assert ok
    assert "None" not in detail
    assert "NOESIS_VAULT_DIR is not set" in detail


async def test_writer_check_on_mcp_fails_when_no_probe_is_wired() -> None:
    ok, detail, next_step = await _writer_check(None, writer_mcp_url=MCP_URL)

    assert not ok
    assert "no probe wired" in detail
    assert next_step is not None


async def test_an_unset_vault_does_not_fail_the_vault_check_when_no_vault_is_required() -> None:
    report = await RunDiagnosticsHandler(probe=_healthy()).handle(
        _query(vault_dir=None, vault_required=False)
    )

    vault = next(check for check in report.checks if check.name == "vault")
    assert vault.ok
    assert report.ok


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
