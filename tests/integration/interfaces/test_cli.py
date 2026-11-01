"""The CLI end to end, in-process: help, version, config, doctor, errors, exit codes."""

import json
import os
from pathlib import Path

import pytest

from noesis import __version__
from noesis.interfaces.cli import (
    run,
)

pytestmark = pytest.mark.integration


def _json(captured: str) -> dict[str, object]:
    envelope: object = json.loads(captured)
    assert isinstance(envelope, dict)
    return envelope


def test_version_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"noesis {__version__}"
    assert run(["--help"]) == 0
    out: str = capsys.readouterr().out
    for expected in ("config", "doctor", "Exit codes"):
        assert expected in out


def test_unknown_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["bogus"]) == 2
    assert "No such command" in capsys.readouterr().err


def test_config_init_writes_the_template_with_the_vault_and_refuses_to_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file: Path = tmp_path / "noesis.env"
    vault: Path = tmp_path / "vault"

    assert (
        run(["--env-file", str(env_file), "config", "init", "--vault-dir", str(vault), "--json"])
        == 0
    )
    assert _json(capsys.readouterr().out)["ok"] is True
    assert f"NOESIS_VAULT_DIR={vault}" in env_file.read_text(encoding="utf-8")

    assert run(["--env-file", str(env_file), "config", "init", "--json"]) == 1
    error: object = _json(capsys.readouterr().out)["error"]
    assert isinstance(error, dict)
    assert error["code"] == "CORE_003_CONFIG_FILE_EXISTS"
    assert error["next_steps"]


def test_config_show_reports_effective_settings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text(f"NOESIS_VAULT_DIR={tmp_path}\n", encoding="utf-8")

    assert run(["--env-file", str(env_file), "config", "show", "--json"]) == 0

    result: object = _json(capsys.readouterr().out)["result"]
    assert isinstance(result, dict)
    assert result["env_file_exists"] is True
    assert result["settings"]["knowledge"]["vault_dir"] == str(tmp_path)  # type: ignore[index]


def test_invalid_configuration_prints_problems_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_CAPTURE_MIN_LINES", "-5")

    assert run(["config", "show"]) == 1

    err: str = capsys.readouterr().err
    assert "CORE_001_INVALID_CONFIGURATION" in err
    assert "NOESIS_CAPTURE_MIN_LINES" in err


def test_doctor_fails_without_a_vault_and_passes_with_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_bin: Path = tmp_path / "bin"
    fake_bin.mkdir()
    curator: Path = fake_bin / "claude"
    curator.write_text("#!/bin/sh\n", encoding="utf-8")
    curator.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")

    assert run(["doctor", "--json"]) == 1
    checks: object = _json(capsys.readouterr().out)["result"]["checks"]  # type: ignore[index]
    assert isinstance(checks, list)
    assert {check["name"]: check["ok"] for check in checks}["vault"] is False

    monkeypatch.setenv("NOESIS_VAULT_DIR", str(tmp_path))
    assert run(["doctor"]) == 0
    assert "ok  vault" in capsys.readouterr().out
