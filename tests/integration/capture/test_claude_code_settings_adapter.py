"""The Claude Code settings adapter against real files."""

import json
from pathlib import Path

import pytest

from noesis.bounded_context.capture.infrastructure.outbound.agent_hooks import (
    ClaudeCodeSettingsAdapter,
)
from noesis.exceptions import (
    AgentSettingsInvalidError,
)

pytestmark = pytest.mark.integration

COMMAND: str = "/opt/noesis hook claude-code"


async def test_plan_apply_status_and_removal_round_trip(tmp_path: Path) -> None:
    path: Path = tmp_path / "settings.json"
    path.write_text('{"model": "opus"}', encoding="utf-8")
    registry = ClaudeCodeSettingsAdapter(path)

    plan = await registry.plan(COMMAND)
    assert plan.changed
    assert path.read_text() == '{"model": "opus"}'  # planning never writes
    assert "(now)" in plan.diff
    assert plan.installed_before == {}
    assert set(plan.installed_after) == {"PostToolUse", "Stop", "SessionEnd"}

    backup: str | None = await registry.apply(plan)
    assert backup is not None
    assert Path(backup).read_text() == '{"model": "opus"}'
    assert Path(backup).name.startswith("settings.json.noesis-backup-")
    assert json.loads(path.read_text())["model"] == "opus"
    assert (await registry.status()).missing_events == []
    assert not (await registry.plan(COMMAND)).changed

    await registry.apply(await registry.plan(None))
    assert json.loads(path.read_text()) == {"model": "opus"}
    assert (await registry.status()).missing_events == ["PostToolUse", "Stop", "SessionEnd"]


async def test_a_missing_file_is_created_without_a_backup(tmp_path: Path) -> None:
    path: Path = tmp_path / "new" / "settings.json"
    registry = ClaudeCodeSettingsAdapter(path)

    backup: str | None = await registry.apply(await registry.plan(COMMAND))

    assert backup is None
    assert path.is_file()


@pytest.mark.parametrize("content", ["{not json", "[1, 2]"])
async def test_an_invalid_file_is_reported_and_left_alone(tmp_path: Path, content: str) -> None:
    path: Path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(AgentSettingsInvalidError):
        await ClaudeCodeSettingsAdapter(path).plan(COMMAND)

    assert path.read_text() == content


async def test_a_blank_file_reads_as_empty(tmp_path: Path) -> None:
    path: Path = tmp_path / "settings.json"
    path.write_text("  \n", encoding="utf-8")

    assert (await ClaudeCodeSettingsAdapter(path).status()).installed == {}
