"""Application-wide exception hierarchy and exit codes."""

from .base import (
    AppException,
    ApplicationException,
    CoreException,
    DomainException,
    InfrastructureException,
    InterfaceException,
)
from .capture_errors import CaptureNotEnabledError, CaptureStateError, InvalidSessionIdError
from .core_errors import (
    ConfigFileExistsError,
    ConfigTemplateMissingError,
    CuratorPromptUnreadableError,
    InvalidConfigurationError,
    VaultNotConfiguredError,
)
from .exit_code_enum import ExitCodeEnum
from .integration_errors import AgentSettingsInvalidError, SkillGuideNotFoundError
from .interface_errors import InvalidWorkBriefError
from .knowledge_errors import (
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
    "CuratorPromptUnreadableError",
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
