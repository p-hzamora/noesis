"""Settings loading: file, environment precedence, defaults, and validation errors."""

from pathlib import Path

import pytest

from noesis.core import (
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
    assert environment.notes.vault_dir is None
    assert (environment.capture.min_files, environment.capture.min_lines) == (2, 20)
    assert environment.curator.claude_bin == "claude"


def test_values_come_from_the_env_file_and_expand_the_home_folder(tmp_path: Path) -> None:
    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text("NOESIS_VAULT_DIR=~/brain\nNOESIS_CAPTURE_MIN_LINES=5\n", encoding="utf-8")

    environment: Environment = load_environment(env_file)

    assert environment.notes.vault_dir == Path.home() / "brain"
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
        "NOESIS_WRITER_BACKEND",
        "NOESIS_STATE_DIR",
        "NOESIS_LOG_LEVEL",
        "NOESIS_CAPTURE_MIN_FILES",
        "NOESIS_CAPTURE_TRACE",
        "NOESIS_CURATOR_MODEL",
        "NOESIS_CURATOR_RETRY_SECONDS",
        "NOESIS_CURATOR_SYSTEM_PROMPT_FILE",
        "NOESIS_RECALL_RUNTIME",
        "NOESIS_RECALL_MODEL=claude-haiku-5-5",
        "NOESIS_RECALL_EFFORT=low",
        "NOESIS_RECALL_MAX_INPUT_CHARS",
    ):
        assert variable in template


def test_search_backend_defaults_to_the_filesystem_and_hides_the_token(
    tmp_path: Path, isolated_environment: Path
) -> None:
    default = load_environment(tmp_path / "missing.env").notes
    assert default.search_backend.value == "filesystem"
    assert default.obsidian_mcp_url == "http://127.0.0.1:27123/mcp/"
    assert default.obsidian_mcp_token is None

    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text(
        "NOESIS_SEARCH_BACKEND=obsidian-mcp\nNOESIS_OBSIDIAN_MCP_TOKEN=abc123\n", encoding="utf-8"
    )
    configured = load_environment(env_file).notes
    assert configured.search_backend.value == "obsidian-mcp"
    assert configured.obsidian_mcp_token is not None
    assert configured.obsidian_mcp_token.get_secret_value() == "abc123"
    assert "abc123" not in repr(configured)


def test_an_unknown_search_backend_is_rejected(tmp_path: Path) -> None:
    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text("NOESIS_SEARCH_BACKEND=elasticsearch\n", encoding="utf-8")

    with pytest.raises(InvalidConfigurationError) as raised:
        load_environment(env_file)

    assert "NOESIS_SEARCH_BACKEND" in str(raised.value.metadata["problems"])


def test_writer_backend_defaults_to_the_filesystem_and_accepts_mcp(tmp_path: Path) -> None:
    assert load_environment(tmp_path / "missing.env").notes.writer_backend.value == "filesystem"

    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text("NOESIS_WRITER_BACKEND=mcp\n", encoding="utf-8")

    assert load_environment(env_file).notes.writer_backend.value == "mcp"


def test_an_unknown_writer_backend_is_rejected(tmp_path: Path) -> None:
    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text("NOESIS_WRITER_BACKEND=bogus\n", encoding="utf-8")

    with pytest.raises(InvalidConfigurationError) as raised:
        load_environment(env_file)

    assert "NOESIS_WRITER_BACKEND" in str(raised.value.metadata["problems"])


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


def test_recall_settings_default_to_the_runtime_defaults_and_read_the_model_and_effort(
    tmp_path: Path,
) -> None:
    default = load_environment(tmp_path / "missing.env").recall
    assert (default.runtime.value, default.model, default.effort) == ("claude-cli", "", "")

    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text(
        "NOESIS_RECALL_MODEL=claude-haiku-5-5\nNOESIS_RECALL_EFFORT=low\n", encoding="utf-8"
    )
    configured = load_environment(env_file).recall
    assert (configured.model, configured.effort) == ("claude-haiku-5-5", "low")


def test_an_unknown_recall_runtime_is_rejected(tmp_path: Path) -> None:
    env_file: Path = tmp_path / "noesis.env"
    env_file.write_text("NOESIS_RECALL_RUNTIME=carrier-pigeon\n", encoding="utf-8")

    with pytest.raises(InvalidConfigurationError) as raised:
        load_environment(env_file)

    assert "NOESIS_RECALL_RUNTIME" in str(raised.value.metadata["problems"])
