"""Settings loading: file, environment precedence, defaults, and validation errors."""

from pathlib import Path

import pytest

from noesis.core import (
    CuratorRelatedLookupEnum,
    Environment,
    env_example_text,
    load_environment,
)
from noesis.core.configurations import (
    LogLevelEnum,
)
from noesis.exceptions import (
    InvalidConfigurationError,
)

pytestmark = pytest.mark.unit


def test_defaults_apply_when_no_file_and_no_variables(isolated_environment: Path) -> None:
    environment: Environment = load_environment()

    assert environment.env_file == isolated_environment / ".config/noesis/.env"
    assert environment.runtime.state_dir == isolated_environment / ".local/state/noesis"
    assert environment.vault_import.vault_dir is None
    assert (environment.capture.min_files, environment.capture.min_lines) == (2, 20)
    assert environment.curator.claude_bin == "claude"


def test_values_come_from_the_env_file_and_expand_the_home_folder(tmp_path: Path) -> None:
    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text("NOESIS_VAULT_DIR=~/brain\nNOESIS_CAPTURE_MIN_LINES=5\n", encoding="utf-8")

    environment: Environment = load_environment(env_file)

    assert environment.vault_import.vault_dir == Path.home() / "brain"
    assert environment.capture.min_lines == 5


def test_environment_variables_override_the_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text(
        "NOESIS_LOG_LEVEL=DEBUG\nNOESIS_CURATOR_MAX_BUDGET_USD=0.2\n", encoding="utf-8"
    )
    monkeypatch.setenv("NOESIS_LOG_LEVEL", "ERROR")

    environment: Environment = load_environment(env_file)

    assert environment.runtime.log_level is LogLevelEnum.ERROR
    assert environment.curator.max_budget_usd == 0.2


def test_invalid_values_are_reported_by_variable_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOESIS_CAPTURE_MIN_FILES", "-1")
    monkeypatch.setenv("NOESIS_LOG_LEVEL", "LOUD")

    with pytest.raises(InvalidConfigurationError) as raised:
        load_environment()

    problems: object = raised.value.metadata["problems"]
    assert isinstance(problems, list)
    assert any(str(problem).startswith("NOESIS_CAPTURE_MIN_FILES:") for problem in problems)
    assert any(str(problem).startswith("NOESIS_LOG_LEVEL:") for problem in problems)


def test_the_env_example_template_documents_every_setting() -> None:
    template: str = env_example_text()

    for variable in (
        "NOESIS_VAULT_DIR",
        "NOESIS_STATE_DIR",
        "NOESIS_LOG_LEVEL",
        "NOESIS_CAPTURE_MIN_FILES",
        "NOESIS_CAPTURE_TRACE",
        "NOESIS_CURATOR_MODEL",
        "NOESIS_CURATOR_RETRY_SECONDS",
        "NOESIS_CURATOR_SYSTEM_PROMPT_FILE",
    ):
        assert variable in template


def test_the_related_lookup_defaults_to_required_and_can_be_turned_off(tmp_path: Path) -> None:
    assert load_environment().curator.related_lookup is CuratorRelatedLookupEnum.REQUIRED

    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text("NOESIS_CURATOR_RELATED_LOOKUP=off\n", encoding="utf-8")

    assert load_environment(env_file).curator.related_lookup is CuratorRelatedLookupEnum.OFF


def test_a_bogus_related_lookup_is_a_settings_error_naming_the_variable(tmp_path: Path) -> None:
    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text("NOESIS_CURATOR_RELATED_LOOKUP=sometimes\n", encoding="utf-8")

    with pytest.raises(InvalidConfigurationError) as raised:
        load_environment(env_file)

    problems: object = raised.value.metadata["problems"]
    assert isinstance(problems, list)
    assert any(str(p).startswith("NOESIS_CURATOR_RELATED_LOOKUP:") for p in problems)


def test_the_related_lookup_is_documented_in_the_env_example() -> None:
    assert "NOESIS_CURATOR_RELATED_LOOKUP" in env_example_text()


@pytest.mark.parametrize(
    ("suffix", "value"),
    [
        ("SEARCH_BACKEND", "obsidian-mcp"),
        ("WRITER_BACKEND", "mcp"),
        ("RECALL_RUNTIME", "carrier-pigeon"),
        ("VECTRA_COLLECTION", "stale"),
    ],
)
def test_variables_of_the_retired_notes_context_are_ignored(
    suffix: str, value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text(f"NOESIS_{suffix}={value}\n", encoding="utf-8")
    monkeypatch.setenv(f"NOESIS_{suffix}", value)

    environment: Environment = load_environment(env_file)

    assert not hasattr(environment, "notes")
    assert not hasattr(environment, "recall")


def test_ambient_session_ids_are_read_from_the_process_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NOESIS_SESSION_ID", "mine")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.setenv("CODEX_SESSION_ID", "")

    identity = load_environment(tmp_path / "missing.env").identity

    assert (identity.noesis_session_id, identity.codex_thread_id, identity.codex_session_id) == (
        "mine",
        "thread-1",
        None,
    )
