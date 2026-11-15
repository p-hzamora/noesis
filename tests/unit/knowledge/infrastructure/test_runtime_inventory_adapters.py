"""Runtime inventory adapters and the PATH probe, against tmp_path folders (FR-006, FR-010, NFR-002).

Never reads a real home folder: every adapter is given folders under `tmp_path`.
"""

import hashlib
import os
import subprocess
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import pytest
from tests.support.knowledge_support import NOW, MutableClock
from tests.support.runtime_folders_support import (
    add_claude_plugin,
    add_codex_plugin,
    empty_registry,
    touch,
    write_registry,
)

from noesis.bounded_context.knowledge.application.dtos import (
    InstalledArtifactDto,
    RuntimeEnum,
    RuntimeInventoryDto,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.runtime import (
    ClaudeCodeRuntimeInventoryAdapter,
    CodexRuntimeInventoryAdapter,
    PathHostToolProbeAdapter,
)

pytestmark = pytest.mark.unit

HOST: str = "host-1"
MCP_NOT_PROBED: tuple[str, str] = ("mcp_server", "kind_not_probed")


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "fixtures" / "claude"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (path := tmp_path / "fixtures" / "project").mkdir(parents=True)
    return path


@pytest.fixture
def codex_home(tmp_path: Path) -> Path:
    return tmp_path / "fixtures" / "codex"


def claude_adapter(config: Path, project_root: Path) -> ClaudeCodeRuntimeInventoryAdapter:
    return ClaudeCodeRuntimeInventoryAdapter(
        config_dir=config, project_root=project_root, clock=MutableClock(), host=HOST
    )


def codex_adapter(home: Path) -> CodexRuntimeInventoryAdapter:
    return CodexRuntimeInventoryAdapter(codex_home=home, clock=MutableClock(), host=HOST)


def artifacts(inventory: RuntimeInventoryDto) -> dict[tuple[str, str], str | None]:
    return {(str(a.kind), a.name): a.observed_version for a in inventory.artifacts}


def unreadable_kinds(inventory: RuntimeInventoryDto) -> set[tuple[str, str]]:
    return {(str(u.kind), str(u.reason)) for u in inventory.unreadable_kinds}


# --- Claude Code ------------------------------------------------------------------------------


async def test_claude_inventory_names_runtime_host_and_the_clock_time(
    config_dir: Path, project: Path
) -> None:
    empty_registry(config_dir)
    adapter = claude_adapter(config_dir, project)

    inventory = await adapter.inventory()

    assert adapter.runtime == RuntimeEnum("claude-code")
    assert inventory.runtime == RuntimeEnum("claude-code")
    assert inventory.host == HOST
    assert datetime.fromisoformat(inventory.observed_at) == NOW
    assert inventory.artifacts == ()


async def test_claude_lists_user_and_project_skills_without_a_version(
    config_dir: Path, project: Path
) -> None:
    empty_registry(config_dir)
    touch(config_dir / "skills" / "local" / "SKILL.md")
    touch(project / ".claude" / "skills" / "proj" / "SKILL.md")

    inventory = await claude_adapter(config_dir, project).inventory()

    assert artifacts(inventory) == {("skill", "local"): None, ("skill", "proj"): None}


async def test_claude_lists_plugin_skills_and_agents_qualified_with_the_registry_version(
    config_dir: Path, project: Path
) -> None:
    add_claude_plugin(
        config_dir,
        "python-suite",
        "claude-flow",
        "2.0.0",
        skills=("ddd-hexagonal-python",),
        agents=("ddd-architect",),
    )
    add_claude_plugin(config_dir, "other", "market", "0.3.1", skills=("helper",))

    inventory = await claude_adapter(config_dir, project).inventory()

    assert artifacts(inventory) == {
        ("skill", "python-suite:ddd-hexagonal-python"): "2.0.0",
        ("agent", "python-suite:ddd-architect"): "2.0.0",
        ("skill", "other:helper"): "0.3.1",
    }


async def test_claude_lists_project_agents_without_a_version(
    config_dir: Path, project: Path
) -> None:
    empty_registry(config_dir)
    touch(project / ".claude" / "agents" / "reviewer.md")

    inventory = await claude_adapter(config_dir, project).inventory()

    assert artifacts(inventory) == {("agent", "reviewer"): None}


async def test_claude_ignores_a_skill_folder_without_skill_md(
    config_dir: Path, project: Path
) -> None:
    add_claude_plugin(
        config_dir, "p", "m", "1.0", skills=("real",), skill_dirs_without_file=("empty",)
    )
    (config_dir / "skills" / "empty-user").mkdir(parents=True)
    (project / ".claude" / "skills" / "empty-proj").mkdir(parents=True)

    inventory = await claude_adapter(config_dir, project).inventory()

    assert artifacts(inventory) == {("skill", "p:real"): "1.0"}


async def test_claude_never_probes_mcp_servers(config_dir: Path, project: Path) -> None:
    empty_registry(config_dir)

    inventory = await claude_adapter(config_dir, project).inventory()

    assert unreadable_kinds(inventory) == {MCP_NOT_PROBED}


async def test_claude_missing_config_folder_reports_skill_and_agent_as_probe_failed(
    config_dir: Path, project: Path
) -> None:
    assert not config_dir.exists()

    inventory = await claude_adapter(config_dir, project).inventory()

    assert unreadable_kinds(inventory) == {
        ("skill", "probe_failed"),
        ("agent", "probe_failed"),
        MCP_NOT_PROBED,
    }
    assert not any(name.count(":") for _, name in artifacts(inventory))


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("{not json", id="not-json"),
        pytest.param("[]", id="not-an-object"),
        pytest.param('{"version": 2, "plugins": "none"}', id="plugins-not-an-object"),
    ],
)
async def test_ac004_unreadable_registry_gives_probe_failed(
    config_dir: Path, project: Path, content: str
) -> None:
    """AC-004 (adapter half): returns without raising and reports the same two items."""
    write_registry(config_dir, content)

    inventory = await claude_adapter(config_dir, project).inventory()

    assert unreadable_kinds(inventory) == {
        ("skill", "probe_failed"),
        ("agent", "probe_failed"),
        MCP_NOT_PROBED,
    }


async def test_claude_missing_registry_with_the_folder_present_means_no_plugins(
    config_dir: Path, project: Path
) -> None:
    """Q-007 default."""
    touch(config_dir / "skills" / "local" / "SKILL.md")
    assert not (config_dir / "plugins").exists()

    inventory = await claude_adapter(config_dir, project).inventory()

    assert artifacts(inventory) == {("skill", "local"): None}
    assert unreadable_kinds(inventory) == {MCP_NOT_PROBED}


# --- Codex ------------------------------------------------------------------------------------


async def test_codex_lists_plugin_skills_from_config_table_names_and_the_cache_path(
    codex_home: Path,
) -> None:
    add_codex_plugin(codex_home, "demo-plugin", "demo-market", "1.0.0", skills=("demo-skill",))

    adapter = codex_adapter(codex_home)
    inventory = await adapter.inventory()

    assert adapter.runtime == RuntimeEnum("codex")
    assert inventory.runtime == RuntimeEnum("codex")
    assert inventory.host == HOST
    assert datetime.fromisoformat(inventory.observed_at) == NOW
    assert artifacts(inventory) == {("skill", "demo-plugin:demo-skill"): "1.0.0"}
    assert unreadable_kinds(inventory) == {("agent", "kind_not_probed"), MCP_NOT_PROBED}


async def test_codex_lists_only_plugins_named_in_the_config(codex_home: Path) -> None:
    add_codex_plugin(codex_home, "listed", "market", "1.0.0", skills=("a",))
    touch(
        codex_home
        / "plugins"
        / "cache"
        / "market"
        / "cached-only"
        / "2.0.0"
        / "skills"
        / "b"
        / "SKILL.md"
    )

    inventory = await codex_adapter(codex_home).inventory()

    assert set(artifacts(inventory)) == {("skill", "listed:a")}


async def test_codex_configured_plugin_with_no_cached_skills_lists_nothing(
    codex_home: Path,
) -> None:
    add_codex_plugin(codex_home, "demo", "market", "1.0.0")

    inventory = await codex_adapter(codex_home).inventory()

    assert artifacts(inventory) == {}
    assert ("skill", "probe_failed") not in unreadable_kinds(inventory)


async def test_codex_invalid_toml_reports_skill_as_probe_failed_without_raising(
    codex_home: Path,
) -> None:
    touch(codex_home / "config.toml", "[plugins\n")

    inventory = await codex_adapter(codex_home).inventory()

    assert unreadable_kinds(inventory) == {
        ("skill", "probe_failed"),
        ("agent", "kind_not_probed"),
        MCP_NOT_PROBED,
    }
    assert artifacts(inventory) == {}


async def test_codex_missing_home_reports_skill_as_probe_failed(codex_home: Path) -> None:
    assert not codex_home.exists()

    inventory = await codex_adapter(codex_home).inventory()

    assert ("skill", "probe_failed") in unreadable_kinds(inventory)


async def test_codex_missing_config_with_the_home_present_means_no_plugins(
    codex_home: Path,
) -> None:
    """Q-007 default."""
    codex_home.mkdir(parents=True)

    inventory = await codex_adapter(codex_home).inventory()

    assert artifacts(inventory) == {}
    assert unreadable_kinds(inventory) == {("agent", "kind_not_probed"), MCP_NOT_PROBED}


async def test_codex_config_values_not_read(codex_home: Path) -> None:
    """NFR-002: a secret-looking value in a plugin table never reaches the inventory."""
    add_codex_plugin(
        codex_home,
        "demo",
        "market",
        "1.0.0",
        skills=("s",),
        extra_lines=('token = "SENTINEL-123"', 'url = "https://SENTINEL-123.invalid"'),
    )

    inventory = await codex_adapter(codex_home).inventory()

    assert artifacts(inventory) == {("skill", "demo:s"): "1.0.0"}
    assert "SENTINEL-123" not in inventory.model_dump_json()


# --- PATH -------------------------------------------------------------------------------------


def make_tool(directory: Path, name: str, *, executable: bool = True, body: str = "") -> Path:
    path: Path = touch(directory / name, f"#!/bin/sh\n{body}\n")
    path.chmod(0o755 if executable else 0o644)
    return path


def test_path_probe_returns_only_the_names_found_as_cli_tools_without_a_version(
    tmp_path: Path,
) -> None:
    bin_dir: Path = tmp_path / "bin"
    make_tool(bin_dir, "gh")
    make_tool(bin_dir, "git")

    found: tuple[InstalledArtifactDto, ...] = PathHostToolProbeAdapter(path=str(bin_dir)).find(
        ("gh", "missing", "git")
    )

    assert [(str(a.kind), a.name, a.observed_version) for a in found] == [
        ("cli_tool", "gh", None),
        ("cli_tool", "git", None),
    ]


def test_path_probe_ignores_files_that_are_not_executable(tmp_path: Path) -> None:
    bin_dir: Path = tmp_path / "bin"
    make_tool(bin_dir, "plain", executable=False)

    assert PathHostToolProbeAdapter(path=str(bin_dir)).find(("plain",)) == ()


@pytest.mark.parametrize("names", [(), ("gh",)])
def test_path_probe_over_an_empty_or_missing_path_finds_nothing(
    tmp_path: Path, names: tuple[str, ...]
) -> None:
    assert PathHostToolProbeAdapter(path=str(tmp_path / "does-not-exist")).find(names) == ()
    assert PathHostToolProbeAdapter(path="").find(names) == ()


def test_path_probe_without_a_path_argument_uses_the_process_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir: Path = tmp_path / "bin"
    make_tool(bin_dir, "gh")
    monkeypatch.setenv("PATH", str(bin_dir))

    found = PathHostToolProbeAdapter().find(("gh",))

    assert [a.name for a in found] == ["gh"]


# --- NFR-002: read-only and executes nothing --------------------------------------------------


@pytest.fixture
def populated(tmp_path: Path, config_dir: Path, project: Path, codex_home: Path) -> dict[str, Path]:
    """Every probe fixture at once, plus an executable that would leave `ran` if it ever ran."""
    add_claude_plugin(
        config_dir, "python-suite", "claude-flow", "2.0.0", skills=("s",), agents=("a",)
    )
    touch(config_dir / "skills" / "local" / "SKILL.md")
    touch(project / ".claude" / "skills" / "proj" / "SKILL.md")
    touch(project / ".claude" / "agents" / "reviewer.md")
    add_codex_plugin(
        codex_home,
        "demo",
        "market",
        "1.0.0",
        skills=("s",),
        extra_lines=('token = "SENTINEL-123"',),
    )
    ran: Path = tmp_path / "ran"
    bin_dir: Path = tmp_path / "bin"
    make_tool(bin_dir, "demo-tool", body=f"touch {ran}")
    return {
        "claude": config_dir,
        "project": project,
        "codex": codex_home,
        "bin": bin_dir,
        "ran": ran,
    }


def snapshot(*roots: Path) -> dict[str, tuple[str, int]]:
    state: dict[str, tuple[str, int]] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            digest: str = (
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "directory"
            )
            state[str(path)] = (digest, path.stat().st_mtime_ns)
    return state


async def run_every_probe(folders: dict[str, Path]) -> None:
    await claude_adapter(folders["claude"], folders["project"]).inventory()
    await codex_adapter(folders["codex"]).inventory()
    PathHostToolProbeAdapter(path=str(folders["bin"])).find(("demo-tool", "absent"))


async def test_probes_are_read_only(populated: dict[str, Path]) -> None:
    roots = (populated["claude"], populated["project"], populated["codex"], populated["bin"])
    before = snapshot(*roots)

    await run_every_probe(populated)

    assert snapshot(*roots) == before


async def test_probes_execute_nothing(
    populated: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a probe tried to execute something")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    for name in (
        "system",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "posix_spawn",
        "posix_spawnp",
    ):
        monkeypatch.setattr(os, name, forbidden)

    await run_every_probe(populated)

    assert not populated["ran"].exists()


# --- D-006: an unreadable folder is probe_failed, never an exception ---------------------------


@pytest.fixture
def unreadable_folder() -> Iterator[Callable[[Path], None]]:
    """`lock(path)` makes a folder unreadable; every lock is undone afterwards."""
    locked: list[Path] = []

    def lock(path: Path) -> None:
        path.chmod(0o000)
        locked.append(path)

    yield lock
    for path in locked:
        path.chmod(0o755)


async def test_claude_unreadable_plugin_install_folder_is_probe_failed_without_raising(
    config_dir: Path, project: Path, unreadable_folder: Callable[[Path], None]
) -> None:
    install = add_claude_plugin(config_dir, "p", "m", "1.0", skills=("s",))
    unreadable_folder(install / "skills")

    inventory = await claude_adapter(config_dir, project).inventory()

    assert {("skill", "probe_failed"), ("agent", "probe_failed")} <= unreadable_kinds(inventory)


async def test_claude_unreadable_project_folder_is_probe_failed_without_raising(
    config_dir: Path, project: Path, unreadable_folder: Callable[[Path], None]
) -> None:
    empty_registry(config_dir)
    touch(project / ".claude" / "skills" / "proj" / "SKILL.md")
    unreadable_folder(project / ".claude" / "skills")

    inventory = await claude_adapter(config_dir, project).inventory()

    assert ("skill", "probe_failed") in unreadable_kinds(inventory)


async def test_codex_unreadable_cache_folder_is_probe_failed_without_raising(
    codex_home: Path, unreadable_folder: Callable[[Path], None]
) -> None:
    add_codex_plugin(codex_home, "demo", "market", "1.0.0", skills=("s",))
    unreadable_folder(codex_home / "plugins" / "cache" / "market" / "demo")

    inventory = await codex_adapter(codex_home).inventory()

    assert ("skill", "probe_failed") in unreadable_kinds(inventory)
