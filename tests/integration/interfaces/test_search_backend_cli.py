"""`NOESIS_SEARCH_BACKEND=obsidian-mcp` end to end: the issue's acceptance criteria."""

import json
from pathlib import Path

import pytest
from tests.support.fake_claude import TTL_DECISION, success_envelope, write_fake_claude
from tests.support.fake_obsidian_mcp import fake_obsidian_mcp, free_port
from tests.support.notes_support import a_brief

from noesis.interfaces.cli import run
from noesis.shared_kernel.domain import JsonObject

pytestmark = pytest.mark.integration

NOTE: str = """---
type: decision
id: auto-decision-use-ttl-cache
title: Use a TTL cache
updated: 2026-10-02
---

# Use a TTL cache

## Decision

Cache lookups for sixty seconds.
"""
FALLBACK_NOTICE: str = "Obsidian MCP unreachable, searched files instead"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder: Path = tmp_path / "vault"
    for relative in (
        "repos/demo/auto/decisions/use-ttl-cache.md",
        "repos/other/decisions/use-ttl-cache.md",
    ):
        (folder / relative).parent.mkdir(parents=True)
        (folder / relative).write_text(NOTE, encoding="utf-8")
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(folder))
    monkeypatch.setenv("NOESIS_CURATOR_RETRY_SECONDS", "0")
    return folder


def _json(capsys: pytest.CaptureFixture[str]) -> JsonObject:
    envelope: object = json.loads(capsys.readouterr().out)
    assert isinstance(envelope, dict)
    return envelope


def _paths(envelope: JsonObject) -> list[str]:
    return [note["path"] for note in envelope["result"]["notes"]]  # type: ignore[index]


def _use_mcp(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("NOESIS_SEARCH_BACKEND", "obsidian-mcp")
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_URL", url)
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_TIMEOUT_SECONDS", "2")


def _closed_url() -> str:
    return f"http://127.0.0.1:{free_port()}/mcp/"


def test_search_goes_through_the_mcp_in_the_same_envelope_and_shape(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "search", "ttl cache", "--json"]) == 0
    filesystem: JsonObject = _json(capsys)

    # Obsidian ranks a note by its own index: the canned hit has none of the query's words.
    with fake_obsidian_mcp(
        vault, canned=[("repos/demo/auto/decisions/use-ttl-cache.md", 9)]
    ) as server:
        _use_mcp(monkeypatch, server.url)
        assert run(["notes", "search", "anything at all", "--json"]) == 0
        via_mcp: JsonObject = _json(capsys)

    assert [call[0] for call in server.calls] == ["search_simple", "vault_read"]
    assert server.calls[0][1] == {"query": "anything at all"}
    assert via_mcp["ok"] is True
    assert set(via_mcp) == set(filesystem) == {"ok", "result"}  # no notice key
    assert set(via_mcp["result"]) == set(filesystem["result"]) == {"notes", "backend"}  # type: ignore[arg-type]
    assert filesystem["result"]["backend"] == "filesystem"  # type: ignore[index]
    assert via_mcp["result"]["backend"] == "obsidian-mcp"  # type: ignore[index]
    assert via_mcp["result"]["notes"][0] == next(  # type: ignore[index]
        note
        for note in filesystem["result"]["notes"]  # type: ignore[index]
        if note["path"] == "repos/demo/auto/decisions/use-ttl-cache.md"
    )
    assert _paths(via_mcp) == ["repos/demo/auto/decisions/use-ttl-cache.md"]


def test_repo_restricts_results_to_repos_r_on_both_backends(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["notes", "search", "ttl", "--repo", "other", "--json"]) == 0
    assert _paths(_json(capsys)) == ["repos/other/decisions/use-ttl-cache.md"]

    with fake_obsidian_mcp(vault) as server:
        _use_mcp(monkeypatch, server.url)
        assert run(["notes", "search", "ttl", "--repo", "other", "--json"]) == 0
        assert _paths(_json(capsys)) == ["repos/other/decisions/use-ttl-cache.md"]
        assert server.calls[0][0] == "search_simple"


def test_with_obsidian_closed_search_falls_back_to_files_and_exits_zero(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_mcp(monkeypatch, _closed_url())

    assert run(["notes", "search", "ttl cache", "--repo", "demo", "--json"]) == 0
    envelope: JsonObject = _json(capsys)
    assert _paths(envelope) == ["repos/demo/auto/decisions/use-ttl-cache.md"]
    assert envelope["result"]["notice"] == FALLBACK_NOTICE  # type: ignore[index]
    assert envelope["result"]["backend"] == "filesystem"  # files answered, not the MCP  # type: ignore[index]

    assert run(["notes", "search", "ttl cache", "--repo", "demo"]) == 0
    text: str = capsys.readouterr().out
    assert "repos/demo/auto/decisions/use-ttl-cache.md" in text
    assert text.count(FALLBACK_NOTICE) == 1
    assert "backend: filesystem" in text


def test_default_settings_never_call_the_mcp(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with fake_obsidian_mcp(vault) as server:
        monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_URL", server.url)  # configured, but not selected
        assert run(["notes", "search", "ttl", "--json"]) == 0
        assert run(["notes", "list", "--json"]) == 0
        assert run(["doctor", "--json"]) in (0, 1)

    assert server.calls == []
    assert server.authorizations == []
    assert "notice" not in capsys.readouterr().out


def test_list_never_uses_the_mcp(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with fake_obsidian_mcp(vault) as server:
        _use_mcp(monkeypatch, server.url)
        assert run(["notes", "list", "--json"]) == 0

    assert server.calls == []
    assert len(_paths(_json(capsys))) == 2


def _curate_fixtures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir: Path = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv(
        "NOESIS_CURATOR_CLAUDE_BIN",
        str(write_fake_claude(bin_dir, envelope=success_envelope([TTL_DECISION]))),
    )
    brief: Path = tmp_path / "brief.json"
    brief.write_text(a_brief().model_dump_json(), encoding="utf-8")
    return brief


def test_curate_uses_the_mcp_search_for_related_notes(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    brief: Path = _curate_fixtures(tmp_path, monkeypatch)
    with fake_obsidian_mcp(vault) as server:
        _use_mcp(monkeypatch, server.url)
        assert run(["notes", "curate", "--brief-file", str(brief), "--json"]) == 0

    assert server.calls[0][0] == "search_simple"
    result: JsonObject = _json(capsys)["result"]  # type: ignore[assignment]
    assert result["created"] + result["updated"] == ["repos/demo/auto/decisions/use-ttl-cache.md"]  # type: ignore[operator]
    assert (vault / "repos/demo/auto/decisions/use-ttl-cache.md").is_file()  # written to files


def test_curate_still_succeeds_when_obsidian_is_closed(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    brief: Path = _curate_fixtures(tmp_path, monkeypatch)
    _use_mcp(monkeypatch, _closed_url())

    assert run(["notes", "curate", "--brief-file", str(brief), "--json"]) == 0

    captured = capsys.readouterr()
    result: JsonObject = json.loads(captured.out)["result"]  # stdout stays pure JSON
    assert result["created"] + result["updated"] == ["repos/demo/auto/decisions/use-ttl-cache.md"]  # type: ignore[operator]
    assert FALLBACK_NOTICE in captured.err


def _checks(capsys: pytest.CaptureFixture[str]) -> dict[str, JsonObject]:
    envelope: JsonObject = _json(capsys)
    return {check["name"]: check for check in envelope["result"]["checks"]}  # type: ignore[index]


@pytest.fixture
def curator_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder: Path = tmp_path / "doctor-bin"
    folder.mkdir()
    for name in ("claude", "git"):
        (folder / name).write_text("#!/bin/sh\n", encoding="utf-8")
        (folder / name).chmod(0o755)
    monkeypatch.setenv("PATH", str(folder))


@pytest.mark.usefixtures("curator_on_path")
def test_doctor_probes_the_mcp_and_accepts_the_same_vault(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with fake_obsidian_mcp(vault) as server:
        _use_mcp(monkeypatch, server.url)
        code: int = run(["doctor", "--json"])
        check: JsonObject = _checks(capsys)["search_backend"]

    assert check["ok"] is True
    assert "reachable" in check["detail"]  # type: ignore[operator]
    assert code in (0, 1)  # other checks (hooks etc.) are not under test
    assert server.calls == [("vault_list", {"path": ""})]


@pytest.mark.usefixtures("curator_on_path")
def test_doctor_flags_a_vault_mismatch(
    vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    other: Path = tmp_path / "other-vault"
    (other / "projects").mkdir(parents=True)
    with fake_obsidian_mcp(other) as server:
        _use_mcp(monkeypatch, server.url)
        assert run(["doctor", "--json"]) == 1
        check: JsonObject = _checks(capsys)["search_backend"]

    assert check["ok"] is False
    assert "different vault" in check["detail"]  # type: ignore[operator]


@pytest.mark.usefixtures("curator_on_path")
def test_doctor_flags_an_unreachable_mcp(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_mcp(monkeypatch, _closed_url())

    assert run(["doctor", "--json"]) == 1
    check: JsonObject = _checks(capsys)["search_backend"]

    assert check["ok"] is False
    assert "unreachable" in check["detail"]  # type: ignore[operator]


def test_config_show_masks_the_token(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_TOKEN", "s3cret-token")

    assert run(["config", "show", "--json"]) == 0
    output: str = capsys.readouterr().out

    assert "s3cret-token" not in output
    assert "obsidian_mcp_url" in output


def test_the_skill_guide_explains_the_backend_and_the_fallback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["skills", "get", "noesis"]) == 0

    guide: str = capsys.readouterr().out
    assert "NOESIS_SEARCH_BACKEND=obsidian-mcp" in guide
    assert FALLBACK_NOTICE in guide
