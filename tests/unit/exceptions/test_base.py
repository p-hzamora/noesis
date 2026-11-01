"""Exception metadata used by every interface."""

import pytest

from noesis.exceptions import (
    ExitCodeEnum,
    InterfaceException,
    VaultNotConfiguredError,
)

pytestmark = pytest.mark.unit


def test_errors_carry_code_title_exit_code_metadata_and_next_steps() -> None:
    error: VaultNotConfiguredError = VaultNotConfiguredError(
        "No vault.", {"setting": "NOESIS_VAULT_DIR"}, next_steps=["Run `noesis config init`."]
    )

    assert error.error_code == "CORE_002_VAULT_NOT_CONFIGURED"
    assert error.error_title() == "Vault not configured"
    assert error.exit_code is ExitCodeEnum.FAILURE
    assert error.metadata == {"setting": "NOESIS_VAULT_DIR"}
    assert error.next_steps == ("Run `noesis config init`.",)
    assert str(error) == "No vault."


def test_interface_errors_exit_with_the_usage_code() -> None:
    assert InterfaceException("bad input").exit_code is ExitCodeEnum.USAGE
