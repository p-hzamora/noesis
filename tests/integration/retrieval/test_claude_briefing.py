"""Exercise the synthesis process boundary with a fake executable only."""

import json
from pathlib import Path

import pytest
from tests.support.fake_claude import briefing_envelope, write_fake_claude

from noesis.bounded_context.retrieval.infrastructure.outbound.briefing.claude_cli_briefing_adapter import (
    ClaudeCliBriefingAdapter,
)
from noesis.exceptions.retrieval_errors import BriefingRunFailedError

pytestmark = pytest.mark.integration


async def test_synthesis_ignores_extra_metadata_and_isolates_environment(tmp_path: Path) -> None:
    claude = write_fake_claude(
        tmp_path,
        envelope=briefing_envelope(
            {
                "constraints": [],
                "decisions": [],
                "context": [],
                "unconfirmed": [],
                "tools": ["invented"],
            }
        ),
    )
    adapter = ClaudeCliBriefingAdapter(
        claude_bin=str(claude),
        environment={
            "PATH": "/usr/bin:/bin",
            "NOESIS_NEO4J_PASSWORD": "private",
            "CLAUDECODE": "1",
            "NOESIS_VAULT_DIR": "private",
        },
    )
    result = await adapter.synthesize("task", [])
    assert result.model_dump() == {
        "constraints": (),
        "decisions": (),
        "context": (),
        "unconfirmed": (),
    }
    environment = json.loads((tmp_path / "env.json").read_text())
    assert environment["NOESIS_HOOK"] == "1"
    assert not any(key.startswith("NOESIS_NEO4J") for key in environment)
    assert "CLAUDECODE" not in environment and "NOESIS_VAULT_DIR" not in environment
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--max-budget-usd") + 1] == "0.5"


@pytest.mark.parametrize("failure", ["missing", "timeout", "exit", "json", "shape", "envelope"])
async def test_model_failure_is_typed_and_suggests_digest(tmp_path: Path, failure: str) -> None:
    claude = tmp_path / "missing"
    if failure != "missing":
        claude = write_fake_claude(
            tmp_path,
            raw="garbage" if failure == "json" else None,
            exit_code=3 if failure == "exit" else 0,
            sleep_seconds=1 if failure == "timeout" else 0,
            envelope=briefing_envelope({}) if failure == "shape" else {},
        )
    adapter = ClaudeCliBriefingAdapter(
        claude_bin=str(claude), timeout_seconds=0.05, environment={"PATH": "/usr/bin:/bin"}
    )
    with pytest.raises(BriefingRunFailedError) as caught:
        await adapter.synthesize("task", [])
    assert "--no-synthesis" in str(caught.value.next_steps)
