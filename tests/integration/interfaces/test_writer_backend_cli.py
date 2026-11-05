"""`NOESIS_WRITER_BACKEND=mcp` end to end: the issue's acceptance criteria."""

import json
from pathlib import Path

import pytest
from tests.support.fake_claude import TTL_DECISION, success_envelope, write_fake_claude
from tests.support.fake_obsidian_mcp import fake_obsidian_mcp, free_port
from tests.support.notes_support import a_brief

from noesis.interfaces.cli import run
from noesis.shared_kernel.domain import JsonObject

pytestmark = pytest.mark.integration

TTL_PATH: str = "repos/demo/auto/decisions/use-ttl-cache.md"
LRU_PATH: str = "repos/demo/auto/decisions/use-lru-cache.md"
LRU_DECISION: JsonObject = {**TTL_DECISION, "slug": "use-lru-cache", "title": "Use an LRU cache"}
RELATED_NOTE: str = """---
type: decision
id: auto-decision-use-ttl-cache
title: Use a TTL cache
updated: 2026-10-02
---

# Use a TTL cache

## Decision

Cache lookups for sixty seconds.
"""
MANUAL_NOTE: str = "---\ntype: decision\ntitle: Use a TTL cache\n---\n\n# Use a TTL cache\n\n## Decision\n\nMine.\n"
TOKEN: str = "s3cret-token"
PROBE_PATH: str = "noesis-doctor-probe.md"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The local vault (`NOESIS_VAULT_DIR`): where the filesystem writer and file search look."""
    folder: Path = tmp_path / "vault"
    folder.mkdir()
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(folder))
    monkeypatch.setenv("NOESIS_CURATOR_RETRY_SECONDS", "0")
    return folder


@pytest.fixture
def served(tmp_path: Path) -> Path:
    """The folder the fake MCP server serves (a different place than the local vault)."""
    folder: Path = tmp_path / "served"
    folder.mkdir()
    return folder


def _json(capsys: pytest.CaptureFixture[str]) -> JsonObject:
    envelope: object = json.loads(capsys.readouterr().out)
    assert isinstance(envelope, dict)
    return envelope


def _error(envelope: JsonObject) -> JsonObject:
    return envelope["error"]  # type: ignore[return-value]


def _closed_url() -> str:
    return f"http://127.0.0.1:{free_port()}/mcp/"


def _use_mcp_writer(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("NOESIS_WRITER_BACKEND", "mcp")
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_URL", url)
    monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_TIMEOUT_SECONDS", "2")


def _use_curator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *decisions: JsonObject) -> Path:
    """Install the fake `claude` answering `decisions`; returns the brief file to curate."""
    folder: Path = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    monkeypatch.setenv(
        "NOESIS_CURATOR_CLAUDE_BIN",
        str(write_fake_claude(folder, envelope=success_envelope(list(decisions)))),
    )
    brief: Path = tmp_path / "brief.json"
    brief.write_text(a_brief().model_dump_json(), encoding="utf-8")
    return brief


def _curate(brief: Path, *extra: str) -> int:
    return run(["notes", "curate", "--brief-file", str(brief), "--json", *extra])


def _output(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def _writes(server: object) -> dict[str, str]:
    return {args["path"]: args["content"] for tool, args in server.calls if tool == "vault_write"}  # type: ignore[attr-defined]


def test_default_writer_writes_files_and_never_calls_the_mcp(
    vault: Path,
    tmp_path: Path,
    served: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)

    with fake_obsidian_mcp(served) as server:
        monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_URL", server.url)  # configured, not selected
        assert _curate(brief) == 0

    assert _json(capsys)["result"]["created"] == [TTL_PATH]  # type: ignore[index]
    assert (vault / TTL_PATH).is_file()
    assert server.calls == []
    assert server.authorizations == []


def test_mcp_writer_matches_the_filesystem_writer(
    vault: Path,
    tmp_path: Path,
    served: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION, LRU_DECISION)
    assert _curate(brief) == 0
    filesystem: JsonObject = _json(capsys)

    with fake_obsidian_mcp(served) as server:
        _use_mcp_writer(monkeypatch, server.url)
        assert _curate(brief) == 0
        via_mcp: JsonObject = _json(capsys)

    assert via_mcp == filesystem
    assert filesystem["result"]["created"] == [TTL_PATH, LRU_PATH]  # type: ignore[index]
    sent: dict[str, str] = _writes(server)
    assert list(sent) == [TTL_PATH, LRU_PATH]
    for path, content in sent.items():
        assert content == (vault / path).read_text(encoding="utf-8")
        assert (served / path).read_bytes() == (vault / path).read_bytes()


def test_manual_note_wins_on_the_mcp_writer(
    vault: Path,
    tmp_path: Path,
    served: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manual: str = "repos/demo/decisions/use-ttl-cache.md"
    (served / manual).parent.mkdir(parents=True)
    (served / manual).write_text(MANUAL_NOTE, encoding="utf-8")
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)

    with fake_obsidian_mcp(served) as server:
        _use_mcp_writer(monkeypatch, server.url)
        assert _curate(brief) == 0

    result: JsonObject = _json(capsys)["result"]  # type: ignore[assignment]
    assert result["created"] == result["updated"] == [] or (
        result["created"],
        result["updated"],
    ) == ([], [])
    assert [skip["reason"] for skip in result["skipped"]] == [f"covered by {manual}"]  # type: ignore[union-attr]
    assert _writes(server) == {}
    assert ("vault_read", {"path": manual}) in server.calls
    assert (served / manual).read_text(encoding="utf-8") == MANUAL_NOTE


def test_unreachable_mcp_writer_parks_and_retry_succeeds_after_recovery(
    vault: Path,
    tmp_path: Path,
    served: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)
    port: int = free_port()
    url: str = f"http://127.0.0.1:{port}/mcp/"
    _use_mcp_writer(monkeypatch, url)

    assert _curate(brief) == 1
    error: JsonObject = _error(_json(capsys))
    ticket: str = error["metadata"]["ticket"]  # type: ignore[index]
    assert error["code"] == "NOTES_201_CURATION_FAILED"
    assert ticket
    assert f"Fix the cause, then run `noesis notes retry {ticket}`." in error["next_steps"]  # type: ignore[operator]

    with fake_obsidian_mcp(served, port=port) as server:  # the server is back on the same URL
        assert run(["notes", "retry", ticket, "--json"]) == 0
        assert _json(capsys)["result"]["created"] == [TTL_PATH]  # type: ignore[index]

    assert (served / TTL_PATH).is_file()
    assert _writes(server) == {TTL_PATH: (served / TTL_PATH).read_text(encoding="utf-8")}
    assert run(["notes", "parked", "--json"]) == 0
    assert _json(capsys)["result"]["parked"] == []  # type: ignore[index]


def test_partial_write_parks_and_retry_completes(
    vault: Path,
    tmp_path: Path,
    served: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION, LRU_DECISION)

    with fake_obsidian_mcp(served, fail_write_after=1) as server:
        _use_mcp_writer(monkeypatch, server.url)
        assert _curate(brief) == 1
        error: JsonObject = _error(_json(capsys))
        assert error["code"] == "NOTES_201_CURATION_FAILED"
        assert error["metadata"]["written"] == [TTL_PATH]  # type: ignore[index]
        assert error["metadata"]["not_written"] == [LRU_PATH]  # type: ignore[index]
        ticket: str = error["metadata"]["ticket"]  # type: ignore[index]
        assert (served / TTL_PATH).is_file()
        assert not (served / LRU_PATH).exists()

        server.fail_write_after = None  # the server recovers
        assert run(["notes", "retry", ticket, "--json"]) == 0
        retried: JsonObject = _json(capsys)
        # TTL was written by the partial run, so the retry finds it and overwrites it (FR-008).
        assert retried["result"]["created"] == [LRU_PATH]  # type: ignore[index]
        assert retried["result"]["updated"] == [TTL_PATH]  # type: ignore[index]

    assert (served / LRU_PATH).is_file()
    assert run(["notes", "parked", "--json"]) == 0
    assert _json(capsys)["result"]["parked"] == []  # type: ignore[index]


@pytest.mark.parametrize(
    ("writer", "search", "needs_vault"),
    [
        ("filesystem", "filesystem", True),
        ("filesystem", "obsidian-mcp", True),
        ("mcp", "filesystem", True),
        ("mcp", "obsidian-mcp", False),
    ],
)
def test_vault_is_required_only_where_files_are_used(
    writer: str,
    search: str,
    needs_vault: bool,
    tmp_path: Path,
    served: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NOESIS_CURATOR_RETRY_SECONDS", "0")  # no NOESIS_VAULT_DIR at all
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)

    with fake_obsidian_mcp(served) as server:
        monkeypatch.setenv("NOESIS_WRITER_BACKEND", writer)
        monkeypatch.setenv("NOESIS_SEARCH_BACKEND", search)
        monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_URL", server.url)
        monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_TIMEOUT_SECONDS", "2")

        if needs_vault:
            assert _curate(brief) == 1
            assert _error(_json(capsys))["code"] == "CORE_002_VAULT_NOT_CONFIGURED"
            assert not (tmp_path / "bin/stdin.txt").exists()  # failed before the curator ran
            return

        assert _curate(brief) == 0
        assert _json(capsys)["result"]["created"] == [TTL_PATH]  # type: ignore[index]
        assert run(["notes", "search", "ttl cache", "--json"]) == 0
        assert _json(capsys)["ok"] is True
        assert run(["notes", "parked", "--json"]) == 0
        assert _json(capsys)["ok"] is True
    assert (served / TTL_PATH).is_file()


def test_vault_less_list_and_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_mcp_writer(monkeypatch, _closed_url())
    monkeypatch.setenv("NOESIS_SEARCH_BACKEND", "obsidian-mcp")

    assert run(["notes", "list", "--json"]) == 1
    assert _error(_json(capsys))["code"] == "CORE_002_VAULT_NOT_CONFIGURED"

    assert run(["notes", "search", "ttl", "--json"]) == 1
    envelope: JsonObject = _json(capsys)
    assert _error(envelope)["code"] == "INTEGRATION_102_OBSIDIAN_MCP_FAILED"
    assert "searched files instead" not in json.dumps(envelope)  # no fallback without a vault


def test_mcp_writer_with_filesystem_search(
    vault: Path,
    tmp_path: Path,
    served: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (vault / TTL_PATH).parent.mkdir(parents=True)
    (vault / TTL_PATH).write_text(RELATED_NOTE, encoding="utf-8")
    brief: Path = _use_curator(tmp_path, monkeypatch, LRU_DECISION)

    with fake_obsidian_mcp(served) as server:
        _use_mcp_writer(monkeypatch, server.url)
        assert _curate(brief) == 0

    assert _json(capsys)["result"]["created"] == [LRU_PATH]  # type: ignore[index]
    assert TTL_PATH in (tmp_path / "bin/stdin.txt").read_text(
        encoding="utf-8"
    )  # related, from files
    assert "search_simple" not in [call[0] for call in server.calls]
    assert list(_writes(server)) == [LRU_PATH]
    assert not (vault / LRU_PATH).exists()


def test_writer_token_is_sent_and_never_printed(
    vault: Path,
    tmp_path: Path,
    served: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)

    with fake_obsidian_mcp(served, token=TOKEN) as server:
        _use_mcp_writer(monkeypatch, server.url)
        monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_TOKEN", TOKEN)
        assert _curate(brief) == 0
        assert run(["config", "show", "--json"]) == 0
        printed: str = _output(capsys)

        monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_TOKEN", "wrong-s3cret")  # rejected by the server
        assert _curate(brief) == 1
        rejected: str = _output(capsys)
        assert run(["notes", "curate", "--brief-file", str(brief)]) == 1
        rejected += _output(capsys)

    assert set(server.authorizations) >= {f"Bearer {TOKEN}"}
    assert (served / TTL_PATH).is_file()
    assert TOKEN not in printed
    assert "obsidian_mcp_token" in printed  # shown, but masked
    assert "NOTES_201_CURATION_FAILED" in rejected
    assert "wrong-s3cret" not in rejected


def test_a_storage_failure_on_the_default_backend_parks_the_brief(
    vault: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (vault / "repos").write_text("a file where the notes folder should be", encoding="utf-8")
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)

    assert _curate(brief) == 1
    error: JsonObject = _error(_json(capsys))
    assert error["code"] == "NOTES_201_CURATION_FAILED"
    ticket: str = error["metadata"]["ticket"]  # type: ignore[index]
    assert f"Fix the cause, then run `noesis notes retry {ticket}`." in error["next_steps"]  # type: ignore[operator]

    (vault / "repos").unlink()  # storage is fixed
    assert run(["notes", "retry", ticket, "--json"]) == 0
    assert _json(capsys)["result"]["created"] == [TTL_PATH]  # type: ignore[index]
    assert (vault / TTL_PATH).is_file()


def test_a_storage_failure_without_parking_keeps_the_storage_error_code(
    vault: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (vault / "repos").write_text("a file where the notes folder should be", encoding="utf-8")
    brief: Path = _use_curator(tmp_path, monkeypatch, TTL_DECISION)

    assert _curate(brief, "--no-park") == 1
    assert _error(_json(capsys))["code"] == "NOTES_102_NOTE_STORAGE_FAILED"
    assert run(["notes", "parked", "--json"]) == 0
    assert _json(capsys)["result"]["parked"] == []  # type: ignore[index]


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
def test_doctor_probes_the_mcp_writer_and_deletes_the_probe_file(
    vault: Path, served: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with fake_obsidian_mcp(served) as server:
        _use_mcp_writer(monkeypatch, server.url)
        run(["doctor", "--json"])
        check: JsonObject = _checks(capsys)["writer"]

    assert check["ok"] is True
    assert "accepted a write" in check["detail"]  # type: ignore[operator]
    assert list(_writes(server)) == [PROBE_PATH]
    assert [tool for tool, _ in server.calls if tool == "vault_delete"] == ["vault_delete"]
    assert not (served / PROBE_PATH).exists()


@pytest.mark.usefixtures("curator_on_path")
def test_doctor_flags_an_unreachable_mcp_writer(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_mcp_writer(monkeypatch, _closed_url())

    assert run(["doctor", "--json"]) == 1
    check: JsonObject = _checks(capsys)["writer"]

    assert check["ok"] is False
    assert "NOESIS_OBSIDIAN_MCP_URL" in check["next_step"]  # type: ignore[operator]


@pytest.mark.usefixtures("curator_on_path")
def test_doctor_flags_an_mcp_writer_that_rejects_writes(
    vault: Path, served: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with fake_obsidian_mcp(served, reject_writes=True) as server:
        _use_mcp_writer(monkeypatch, server.url)
        assert run(["doctor", "--json"]) == 1
        check: JsonObject = _checks(capsys)["writer"]

    assert check["ok"] is False


@pytest.mark.usefixtures("curator_on_path")
def test_doctor_on_the_default_writer_makes_no_mcp_call_and_needs_no_vault_for_mcp(
    vault: Path, served: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with fake_obsidian_mcp(served) as server:
        monkeypatch.setenv("NOESIS_OBSIDIAN_MCP_URL", server.url)  # configured, not selected
        run(["doctor", "--json"])
        default: dict[str, JsonObject] = _checks(capsys)
        assert server.calls == []

        monkeypatch.delenv("NOESIS_VAULT_DIR")
        _use_mcp_writer(monkeypatch, server.url)
        monkeypatch.setenv("NOESIS_SEARCH_BACKEND", "obsidian-mcp")
        run(["doctor", "--json"])
        vault_less: dict[str, JsonObject] = _checks(capsys)

    assert default["writer"]["ok"] is True
    assert str(vault) in default["writer"]["detail"]  # type: ignore[operator]
    assert vault_less["vault"]["ok"] is True  # nothing local is used, so nothing is missing
    assert vault_less["writer"]["ok"] is True
