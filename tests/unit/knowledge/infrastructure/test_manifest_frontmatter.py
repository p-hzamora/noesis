"""Manifest facts the runtime probes read: frontmatter only, whole-file digest (WP-05, A-002)."""

import hashlib
from pathlib import Path

import pytest
from tests.support.knowledge_support import MutableClock
from tests.support.runtime_folders_support import (
    add_claude_plugin,
    add_codex_plugin,
    empty_registry,
    skill_manifest,
    touch,
)

from noesis.bounded_context.knowledge.application.dtos import InstalledArtifactDto
from noesis.bounded_context.knowledge.infrastructure.outbound.runtime import (
    ClaudeCodeRuntimeInventoryAdapter,
    CodexRuntimeInventoryAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.runtime.inventory_support import (
    MAX_FRONTMATTER_BYTES,
    read_manifest,
)

pytestmark = pytest.mark.unit


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _read(tmp_path: Path, text: str):
    return read_manifest(touch(tmp_path / "SKILL.md", text))


def test_valid_frontmatter_gives_description_digest_and_requires(tmp_path: Path) -> None:
    text: str = skill_manifest("Builds things", requires=("cli_tool:uv", "skill:plug:base"))

    facts = _read(tmp_path, text)

    assert facts.description == "Builds things"
    assert facts.digest == _digest(text)
    assert facts.requires == ("cli_tool:uv", "skill:plug:base")


def test_multiline_description_is_collapsed_to_one_line(tmp_path: Path) -> None:
    text: str = "---\ndescription: >\n  first part\n  second part\n---\nbody\n"

    assert _read(tmp_path, text).description == "first part second part"


@pytest.mark.parametrize(
    "text",
    [
        "# no frontmatter\n",
        "---\ndescription: [unclosed\n---\nbody\n",
        "---\njust a string\n---\n",
        "---\ndescription: 42\n---\n",
        "---\nname: x\n---\n",
        "---\ndescription: never closed\n",
        "",
    ],
)
def test_missing_or_malformed_frontmatter_gives_no_description_but_the_digest(
    tmp_path: Path, text: str
) -> None:
    facts = _read(tmp_path, text)

    assert facts.description is None
    assert facts.digest == _digest(text)
    assert facts.requires == ()


def test_requires_ignores_values_that_are_not_text_lists(tmp_path: Path) -> None:
    text: str = "---\ndescription: d\nmetadata:\n  noesis:\n    requires: cli_tool:uv\n---\n"

    assert _read(tmp_path, text).requires == ()


def test_oversize_manifest_hashes_the_whole_file_but_reads_frontmatter_from_the_first_16_kib(
    tmp_path: Path,
) -> None:
    body: str = "x" * (3 * MAX_FRONTMATTER_BYTES)
    closed: str = f"---\ndescription: early\n---\n{body}"
    unclosed: str = (
        "---\ndescription: late\n" + "# " + "y" * (2 * MAX_FRONTMATTER_BYTES) + "\n---\n"
    )

    first = _read(tmp_path, closed)
    second = _read(tmp_path / "other", unclosed)

    assert (first.description, first.digest) == ("early", _digest(closed))
    assert (second.description, second.digest) == (None, _digest(unclosed))


def test_unreadable_file_gives_no_facts(tmp_path: Path) -> None:
    facts = read_manifest(tmp_path / "missing.md")

    assert (facts.description, facts.digest, facts.requires) == (None, None, ())


def _by_name(artifacts: tuple[InstalledArtifactDto, ...]) -> dict[str, InstalledArtifactDto]:
    return {artifact.name: artifact for artifact in artifacts}


async def test_claude_adapter_carries_the_facts_of_user_plugin_and_project_manifests(
    tmp_path: Path,
) -> None:
    config, project = tmp_path / "claude", tmp_path / "project"
    project.mkdir()
    empty_registry(config)
    user_text: str = skill_manifest("User skill")
    agent_text: str = "---\ndescription: Plugin agent\n---\n# agent\n"
    touch(config / "skills" / "mine" / "SKILL.md", user_text)
    touch(project / ".claude" / "agents" / "local.md", "---\ndescription: Local\n---\n")
    add_claude_plugin(
        config,
        "plug",
        "market",
        "1.0",
        skills=("helper", "plain"),
        agents=("scout",),
        skill_manifests={"helper": skill_manifest("Plugin skill", requires=("cli_tool:uv",))},
        agent_manifests={"scout": agent_text},
    )
    adapter = ClaudeCodeRuntimeInventoryAdapter(
        config_dir=config, project_root=project, clock=MutableClock(), host="h"
    )

    artifacts = _by_name((await adapter.inventory()).artifacts)

    assert artifacts["mine"].description == "User skill"
    assert artifacts["mine"].manifest_digest == _digest(user_text)
    assert artifacts["plug:helper"].declared_requires == ("cli_tool:uv",)
    assert artifacts["plug:scout"].description == "Plugin agent"
    assert artifacts["plug:scout"].manifest_digest == _digest(agent_text)
    assert artifacts["local"].description == "Local"
    assert artifacts["plug:plain"].description is None
    assert artifacts["plug:plain"].manifest_digest == _digest("# skill")


async def test_codex_adapter_carries_the_facts_of_its_skill_manifests(tmp_path: Path) -> None:
    codex = tmp_path / "codex"
    text: str = skill_manifest("Codex skill")
    add_codex_plugin(
        codex, "plug", "market", "2.0", skills=("helper",), skill_manifests={"helper": text}
    )
    adapter = CodexRuntimeInventoryAdapter(codex_home=codex, clock=MutableClock(), host="h")

    artifacts = _by_name((await adapter.inventory()).artifacts)

    assert artifacts["plug:helper"].description == "Codex skill"
    assert artifacts["plug:helper"].manifest_digest == _digest(text)
