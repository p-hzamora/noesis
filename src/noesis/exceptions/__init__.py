"""Application-wide exception hierarchy and exit codes."""

from noesis.exceptions.base import (
    AppException,
    ApplicationException,
    CoreException,
    DomainException,
    InfrastructureException,
    InterfaceException,
)
from noesis.exceptions.capture_errors import (
    CaptureNotEnabledError,
    CaptureStateError,
    InvalidSessionIdError,
)
from noesis.exceptions.core_errors import (
    ConfigFileExistsError,
    ConfigTemplateMissingError,
    InvalidConfigurationError,
    VaultNotConfiguredError,
)
from noesis.exceptions.exit_code_enum import ExitCodeEnum
from noesis.exceptions.integration_errors import (
    AgentSettingsInvalidError,
    SkillGuideNotFoundError,
)
from noesis.exceptions.interface_errors import (
    InvalidWorkBriefError,
)
from noesis.exceptions.knowledge_errors import (
    CurationFailedError,
    CuratorFailedError,
    InvalidNoteAreaError,
    InvalidNoteLocationError,
    InvalidNoteSlugError,
    ManualNoteProtectedError,
    NoteStorageError,
    ParkedCurationNotFoundError,
)

__all__ = [
    "AgentSettingsInvalidError",
    "AppException",
    "ApplicationException",
    "CaptureNotEnabledError",
    "CaptureStateError",
    "ConfigFileExistsError",
    "ConfigTemplateMissingError",
    "CoreException",
    "CurationFailedError",
    "CuratorFailedError",
    "DomainException",
    "ExitCodeEnum",
    "InfrastructureException",
    "InterfaceException",
    "InvalidConfigurationError",
    "InvalidNoteAreaError",
    "InvalidNoteLocationError",
    "InvalidNoteSlugError",
    "InvalidSessionIdError",
    "InvalidWorkBriefError",
    "ManualNoteProtectedError",
    "NoteStorageError",
    "ParkedCurationNotFoundError",
    "SkillGuideNotFoundError",
    "VaultNotConfiguredError",
]
