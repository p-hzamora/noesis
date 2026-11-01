"""Errors raised while loading configuration."""

from .base import CoreException


class InvalidConfigurationError(CoreException):
    """A setting in the environment or the `.env` file has an invalid value."""

    __error_code__ = "CORE_001_INVALID_CONFIGURATION"


class VaultNotConfiguredError(CoreException):
    """No vault folder is configured, so notes have nowhere to go."""

    __error_code__ = "CORE_002_VAULT_NOT_CONFIGURED"


class ConfigFileExistsError(CoreException):
    """`config init` would overwrite an existing configuration file."""

    __error_code__ = "CORE_003_CONFIG_FILE_EXISTS"


class ConfigTemplateMissingError(CoreException):
    """The packaged `.env.example` template cannot be found."""

    __error_code__ = "CORE_004_CONFIG_TEMPLATE_MISSING"
