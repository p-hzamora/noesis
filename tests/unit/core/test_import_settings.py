"""ImportSettings: vault folder, vault key default, and lazy key validation (review finding 18)."""

from pathlib import Path

import pytest

from noesis.core.configurations import ImportSettings
from noesis.exceptions import InvalidConfigurationError

pytestmark = pytest.mark.unit


def test_the_vault_key_defaults_to_the_vault_folder_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOESIS_VAULT_DIR", "/x/my-vault")

    settings: ImportSettings = ImportSettings()

    assert settings.vault_dir == Path("/x/my-vault")
    assert settings.resolve_vault_key() == "my-vault"


def test_a_given_vault_key_wins_over_the_folder_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOESIS_VAULT_DIR", "/x/my-vault")
    monkeypatch.setenv("NOESIS_IMPORT_VAULT_KEY", "team.vault_1")

    assert ImportSettings().resolve_vault_key() == "team.vault_1"


def test_nothing_is_set_by_default() -> None:
    settings: ImportSettings = ImportSettings()

    assert settings.vault_dir is None
    assert settings.import_vault_key is None


def test_an_invalid_key_does_not_fail_construction_so_other_commands_keep_working(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOESIS_VAULT_DIR", "/x/vault")
    monkeypatch.setenv("NOESIS_IMPORT_VAULT_KEY", "a b")

    settings: ImportSettings = ImportSettings()

    assert settings.import_vault_key == "a b"


def test_an_invalid_key_raises_when_it_is_resolved_and_names_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOESIS_VAULT_DIR", "/x/vault")
    monkeypatch.setenv("NOESIS_IMPORT_VAULT_KEY", "a b")

    with pytest.raises(InvalidConfigurationError) as raised:
        ImportSettings().resolve_vault_key()

    assert "NOESIS_IMPORT_VAULT_KEY" in raised.value.message


def test_a_derived_default_that_is_not_a_key_also_names_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOESIS_VAULT_DIR", "/x/my vault")

    with pytest.raises(InvalidConfigurationError) as raised:
        ImportSettings().resolve_vault_key()

    assert "NOESIS_IMPORT_VAULT_KEY" in raised.value.message
