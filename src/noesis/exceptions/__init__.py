"""Application-wide exception hierarchy and exit codes."""

from .base import (
    AppException,
    ApplicationException,
    CoreException,
    DomainException,
    InfrastructureException,
    InterfaceException,
)
from .capture_errors import (
    CaptureNotEnabledError,
    CaptureSessionNotFoundError,
    CaptureStateError,
    InvalidSessionIdError,
    SessionIdentityMissingError,
)
from .core_errors import (
    ConfigFileExistsError,
    ConfigTemplateMissingError,
    CuratorPromptUnreadableError,
    InvalidConfigurationError,
    VaultNotConfiguredError,
)
from .exit_code_enum import ExitCodeEnum
from .integration_errors import (
    AgentSettingsInvalidError,
    ObsidianMcpError,
    ObsidianMcpToolError,
    SkillGuideNotFoundError,
)
from .interface_errors import (
    BlankSessionIdError,
    EmptyRecallTaskError,
    InvalidWorkBriefError,
    NotInGitRepositoryError,
    SelfParentSessionError,
)
from .notes_errors import (
    ApplyFailedError,
    CurationFailedError,
    CuratorFailedError,
    InvalidNoteAreaError,
    InvalidNoteLocationError,
    InvalidNoteSlugError,
    ManualNoteProtectedError,
    NoRecallTermsError,
    NoteStorageError,
    ParkedCurationNotFoundError,
    RecallAgentFailedError,
)

__all__ = [
    "AgentSettingsInvalidError",
    "ApplyFailedError",
    "AppException",
    "ApplicationException",
    "BlankSessionIdError",
    "CaptureNotEnabledError",
    "CaptureSessionNotFoundError",
    "CaptureStateError",
    "ConfigFileExistsError",
    "ConfigTemplateMissingError",
    "CoreException",
    "CurationFailedError",
    "CuratorFailedError",
    "CuratorPromptUnreadableError",
    "DomainException",
    "EmptyRecallTaskError",
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
    "NoRecallTermsError",
    "NoteStorageError",
    "NotInGitRepositoryError",
    "ObsidianMcpError",
    "ObsidianMcpToolError",
    "ParkedCurationNotFoundError",
    "RecallAgentFailedError",
    "SelfParentSessionError",
    "SessionIdentityMissingError",
    "SkillGuideNotFoundError",
    "VaultNotConfiguredError",
]
