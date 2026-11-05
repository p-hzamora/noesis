"""`noesis update check` and the `update` line of `noesis doctor`, against a local origin."""

import json
from pathlib import Path

import pytest
from tests.support.git_support import GitWorld, commit, git, isolate_git

from noesis.interfaces.cli import run

pytestmark = pytest.mark.integration

BUILDER = "noesis.interfaces.cli.bootstrap.diagnostics_handlers_builder.installed_package_dir"


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_git(monkeypatch)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GitWorld:
    world = GitWorld(tmp_path / "w")
    monkeypatch.setattr(BUILDER, lambda: world.package_dir)
    return world


def _result(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is True
    return envelope["result"]  # type: ignore[no-any-return]


def test_up_to_date_prints_text_and_exits_zero(
    world: GitWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["update", "check"]) == 0

    out: str = capsys.readouterr().out
    assert out.startswith("up_to_date")
    assert world.base[:7] in out


def test_behind_exits_zero_and_lists_the_next_steps(
    world: GitWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    remote_sha: str = world.publish("new.txt")

    assert run(["update", "check", "--json"]) == 0

    result = _result(capsys)
    assert result["verdict"] == "behind"
    assert result["local_sha"] == world.base[:7] and result["remote_sha"] == remote_sha[:7]
    assert result["checkout"] == str(world.checkout.resolve())
    assert result["next_steps"] == [
        f"git -C {world.checkout.resolve()} pull",
        f"uv tool install --reinstall {world.checkout.resolve()}",
    ]


def test_behind_text_shows_the_steps(world: GitWorld, capsys: pytest.CaptureFixture[str]) -> None:
    world.publish("new.txt")

    assert run(["update", "check"]) == 0

    out: str = capsys.readouterr().out
    assert out.startswith("behind") and "uv tool install --reinstall" in out


@pytest.mark.parametrize("scenario", ["ahead", "diverged"])
def test_ahead_and_diverged_exit_zero(
    world: GitWorld, capsys: pytest.CaptureFixture[str], scenario: str
) -> None:
    if scenario == "diverged":
        world.publish("theirs.txt")
    commit(world.checkout, "mine.txt")

    assert run(["update", "check", "--json"]) == 0

    assert _result(capsys)["verdict"] == scenario


def test_unreachable_origin_exits_zero_as_unknown(
    world: GitWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git(world.checkout, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))

    assert run(["update", "check", "--json"]) == 0

    result = _result(capsys)
    assert result["verdict"] == "unknown" and result["next_steps"] == []


def test_not_a_checkout_exits_zero_as_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(BUILDER, lambda: tmp_path)

    assert run(["update", "check", "--json"]) == 0

    assert _result(capsys)["verdict"] == "unknown"


def _doctor_update(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    checks = _result(capsys)["checks"]
    assert isinstance(checks, list)
    return next(check for check in checks if check["name"] == "update")


def test_doctor_warns_when_behind_without_changing_the_exit_code(
    world: GitWorld,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(tmp_path))
    world.publish("new.txt")

    run(["doctor"])

    text: str = capsys.readouterr().out
    update_line: str = next(line for line in text.splitlines() if " update:" in line)
    assert update_line.startswith("warn")
    assert "next: git -C" in text


def test_doctor_json_marks_the_update_check_as_a_warning_and_keeps_ok(
    world: GitWorld,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(tmp_path))
    world.publish("new.txt")

    run(["doctor", "--json"])

    result = _result(capsys)
    checks = result["checks"]
    assert isinstance(checks, list)
    update = next(check for check in checks if check["name"] == "update")
    assert update["ok"] is True and update["warning"] is True
    assert result["ok"] is all(check["ok"] for check in checks if check["name"] != "update")
    assert "uv tool install --reinstall" in str(update["next_step"])


def test_doctor_up_to_date_is_a_plain_ok(
    world: GitWorld,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(tmp_path))

    run(["doctor", "--json"])

    update = _doctor_update(capsys)
    assert update["ok"] is True and update["warning"] is False


def test_the_installed_package_dir_is_the_running_package() -> None:
    import noesis
    from noesis.interfaces.cli.bootstrap import installed_package_dir

    assert installed_package_dir() == Path(noesis.__file__).resolve().parent


def test_doctor_warns_when_ahead(
    world: GitWorld,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(tmp_path))
    commit(world.checkout, "mine.txt")

    run(["doctor", "--json"])

    update = _doctor_update(capsys)
    assert update["ok"] is True and update["warning"] is True
    assert update["next_step"] is None and "origin does not" in str(update["detail"])


def test_doctor_warns_when_unknown_and_keeps_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOESIS_VAULT_DIR", str(tmp_path))

    run(["doctor"])

    line: str = next(line for line in capsys.readouterr().out.splitlines() if " update:" in line)
    assert line.startswith("warn") and "not a git checkout" in line
